import unittest
from unittest.mock import patch
import httpx
from backend.app.main import app
from backend.app import database
from backend.app.database import Base
from backend.tests.conftest import build_tiny_mp4_bytes


class TestApiEndpoints(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        async with database.engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        self.client = httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://testserver",
        )

    async def asyncTearDown(self):
        await self.client.aclose()

    async def test_health_check(self):
        resp = await self.client.get("/api/health")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertTrue(data["online"])
        self.assertIn("python_version", data)
        self.assertIn("ffmpeg", data)
        self.assertIn("gpu_encoder", data)

    async def test_upload_video_invalid_format(self):
        files = {"file": ("test.txt", b"plain text content", "text/plain")}
        resp = await self.client.post("/api/videos/upload", files=files)
        self.assertEqual(resp.status_code, 400)
        self.assertIn("Unsupported file type", resp.json()["detail"])

    @patch("backend.app.api.videos.job_runner.start_pipeline")
    async def test_upload_video_valid(self, _mock_start):
        mp4_bytes = build_tiny_mp4_bytes()
        files = {"file": ("sample_gameplay.mp4", mp4_bytes, "video/mp4")}
        resp = await self.client.post("/api/videos/upload", files=files)
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertIn("id", data)
        self.assertIn("job_id", data)
        self.assertEqual(data["title"], "sample_gameplay.mp4")
        self.assertGreater(data["duration"], 0)

    async def test_import_url_invalid(self):
        resp = await self.client.post("/api/videos/import-url", json={"url": "ftp://bad-url.com"})
        self.assertEqual(resp.status_code, 400)

        resp2 = await self.client.post("/api/videos/import-url", json={"url": "https://unsupported-site.com/video"})
        self.assertEqual(resp2.status_code, 400)

    @patch("backend.app.api.videos.job_runner.start_url_import")
    @patch("backend.app.video_import.ytdlp_available", return_value=True)
    async def test_import_url_youtube_valid(self, _mock_ytdlp, mock_start_import):
        resp = await self.client.post(
            "/api/videos/import-url",
            json={"url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ"},
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertIn("id", data)
        self.assertIn("job_id", data)
        self.assertIn("YouTube", data["title"])
        mock_start_import.assert_called_once()

    async def test_languages_endpoint(self):
        resp = await self.client.get("/api/languages")
        self.assertEqual(resp.status_code, 200)
        langs = resp.json()
        self.assertIn("ml", langs)
        self.assertIn("hi", langs)
        self.assertIn("ta", langs)
        self.assertIn("en", langs)
        self.assertIn("auto", langs)
        self.assertIn("Malayalam", langs["ml"])
        self.assertIn("Hindi", langs["hi"])

    async def test_clip_translate_endpoint(self):
        from backend.app.models import Video, Job, Clip, TranscriptSegment

        async with database.async_session_maker() as session:
            v = Video(id="v_ml_test", filename="speech.mp4", file_path="x", duration=30.0)
            j = Job(id="j_ml_test", video_id="v_ml_test", status="ready", detected_language="en")
            c = Clip(
                id="c_ml_test",
                job_id="j_ml_test",
                start_time=2.0,
                end_time=8.0,
                duration=6.0,
                status="selected",
                subtitle_style={"preset": "bold_creator"},
            )
            t = TranscriptSegment(
                id="seg_ml_test",
                video_id="v_ml_test",
                start_time=2.0,
                end_time=7.5,
                text="hello welcome to the stream",
                words=[
                    {"word": "hello", "start": 2.0, "end": 2.8},
                    {"word": "welcome", "start": 3.0, "end": 4.0},
                    {"word": "to", "start": 4.1, "end": 4.5},
                    {"word": "the", "start": 4.6, "end": 5.0},
                    {"word": "stream", "start": 5.1, "end": 6.5},
                ],
            )
            session.add_all([v, j, c, t])
            await session.commit()

        # Translate to Malayalam
        resp = await self.client.post("/api/clips/c_ml_test/translate", json={"target_language": "ml"})
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["clip_id"], "c_ml_test")
        self.assertEqual(data["target_language"], "ml")
        self.assertGreater(len(data["translated_words"]), 0)
        self.assertEqual(data["subtitle_style"]["subtitle_language"], "ml")

        # Reset back to original
        resp_reset = await self.client.post("/api/clips/c_ml_test/translate", json={"target_language": "original"})
        self.assertEqual(resp_reset.status_code, 200)
        data_reset = resp_reset.json()
        self.assertEqual(data_reset["target_language"], "original")
        self.assertEqual(data_reset["translated_words"], [])

    @patch("backend.app.api.videos.job_runner.start_pipeline")
    async def test_jobs_workflow(self, _mock_start):
        # 1. Upload video
        mp4_bytes = build_tiny_mp4_bytes()
        files = {"file": ("test_clip.mp4", mp4_bytes, "video/mp4")}
        upload_resp = await self.client.post("/api/videos/upload", files=files)
        self.assertEqual(upload_resp.status_code, 200)
        job_id = upload_resp.json()["job_id"]

        # 2. List jobs
        list_resp = await self.client.get("/api/jobs")
        self.assertEqual(list_resp.status_code, 200)
        jobs = list_resp.json()
        self.assertTrue(any(j["id"] == job_id for j in jobs))

        # 3. Get job details
        detail_resp = await self.client.get(f"/api/jobs/{job_id}")
        self.assertEqual(detail_resp.status_code, 200)
        details = detail_resp.json()
        self.assertEqual(details["id"], job_id)

        # 4. Cancel job
        cancel_resp = await self.client.post(f"/api/jobs/{job_id}/cancel")
        self.assertEqual(cancel_resp.status_code, 200)
        self.assertEqual(cancel_resp.json()["status"], "cancelled")

        # 5. Delete job
        del_resp = await self.client.delete(f"/api/jobs/{job_id}")
        self.assertEqual(del_resp.status_code, 200)


if __name__ == "__main__":
    unittest.main()
