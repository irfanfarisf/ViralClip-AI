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
        from sqlalchemy import select
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

        # 1. Translate to Malayalam (mocked provider for deterministic offline CI)
        with patch(
            "backend.app.translation._translate_batch_with_providers",
            return_value=(["നമസ്കാരം സ്ട്രീമിലേക്ക് സ്വാഗതം"], "google_translate"),
        ):
            resp = await self.client.post("/api/clips/c_ml_test/translate", json={"target_language": "ml"})
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["clip_id"], "c_ml_test")
        self.assertEqual(data["target_language"], "ml")
        self.assertEqual(data["provider"], "google_translate")
        self.assertFalse(data["partial"])
        self.assertGreater(len(data["translated_words"]), 0)
        self.assertEqual(data["translated_segments"][0]["text"], "നമസ്കാരം സ്ട്രീമിലേക്ക് സ്വാഗതം")
        self.assertEqual(data["translated_segments"][0]["original_text"], "hello welcome to the stream")
        self.assertEqual(data["subtitle_style"]["subtitle_language"], "ml")
        self.assertEqual(data["subtitle_style"]["font"], "Nirmala UI")

        # Verify original TranscriptSegment in DB was NEVER overwritten & translated data persisted separately
        async with database.async_session_maker() as session:
            orig_seg = await session.get(TranscriptSegment, "seg_ml_test")
            self.assertEqual(orig_seg.text, "hello welcome to the stream")
            clip_row = await session.get(Clip, "c_ml_test")
            self.assertEqual(clip_row.subtitle_style["subtitle_language"], "ml")
            self.assertEqual(len(clip_row.subtitle_style["translated_segments"]), 1)

        # 2. Unsupported language returns 422
        resp_bad = await self.client.post("/api/clips/c_ml_test/translate", json={"target_language": "klingon"})
        self.assertEqual(resp_bad.status_code, 422)

        # 3. Provider failure returns 503 (never silently returns original text)
        with patch("backend.app.translation._translate_batch_with_providers", return_value=(None, None)):
            resp_fail = await self.client.post("/api/clips/c_ml_test/translate", json={"target_language": "ar"})
        self.assertEqual(resp_fail.status_code, 503)

        # 4. Reset back to original clears translated_words but preserves TranscriptSegment
        resp_reset = await self.client.post("/api/clips/c_ml_test/translate", json={"target_language": "original"})
        self.assertEqual(resp_reset.status_code, 200)
        data_reset = resp_reset.json()
        self.assertEqual(data_reset["target_language"], "original")
        self.assertEqual(data_reset["translated_words"], [])
        self.assertFalse(data_reset["subtitle_style"]["is_translated"])

        # 5. Empty clip transcript returns 422
        async with database.async_session_maker() as session:
            c_empty = Clip(
                id="c_empty_test",
                job_id="j_ml_test",
                start_time=20.0,
                end_time=25.0,
                duration=5.0,
                status="selected",
                subtitle_style={},
            )
            session.add(c_empty)
            await session.commit()
        resp_empty = await self.client.post("/api/clips/c_empty_test/translate", json={"target_language": "hi"})
        self.assertEqual(resp_empty.status_code, 422)

        # 6. Duplicate concurrent request returns 409
        from backend.app.api import pipeline as pipeline_api
        pipeline_api._active_clip_translations.add("c_ml_test")
        try:
            resp_dup = await self.client.post("/api/clips/c_ml_test/translate", json={"target_language": "ta"})
            self.assertEqual(resp_dup.status_code, 409)
        finally:
            pipeline_api._active_clip_translations.discard("c_ml_test")

    @patch("backend.app.api.videos.job_runner.start_pipeline")
    async def test_chunked_upload_preserves_manual_language(self, mock_start):
        from backend.app.models import Job

        mp4_bytes = build_tiny_mp4_bytes()
        init_resp = await self.client.post(
            "/api/videos/upload/init",
            json={
                "filename": "malayalam_sample.mp4",
                "total_bytes": len(mp4_bytes),
                "chunk_size": 1024 * 1024,
                "language": "ml",
                "whisper_model": "small",
                "auto_analyze": True,
            },
        )
        self.assertEqual(init_resp.status_code, 201)
        sess = init_resp.json()
        job_id = sess["job_id"]
        upload_id = sess["upload_id"]

        async with database.async_session_maker() as session:
            job_row = await session.get(Job, job_id)
            self.assertIsNotNone(job_row)
            self.assertEqual(job_row.settings.get("language"), "ml")
            self.assertEqual(job_row.settings.get("whisper_model"), "small")

        chunk_resp = await self.client.put(
            f"/api/videos/upload/{upload_id}/chunk?chunk_index=0&offset=0",
            content=mp4_bytes,
            headers={"Content-Type": "application/octet-stream"},
        )
        self.assertEqual(chunk_resp.status_code, 200)

        comp_resp = await self.client.post(f"/api/videos/upload/{upload_id}/complete", json={"auto_analyze": True})
        self.assertEqual(comp_resp.status_code, 200)
        mock_start.assert_called_once()

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

    async def test_export_clip_forwards_burn_subtitles_off_and_preserves_data(self):
        from backend.app.models import Video, Job, Clip, TranscriptSegment

        async with database.async_session_maker() as session:
            v = Video(id="v_sub_off", filename="clip.mp4", file_path="x", duration=20.0)
            j = Job(id="j_sub_off", video_id="v_sub_off", status="ready", detected_language="en")
            c = Clip(
                id="c_sub_off",
                job_id="j_sub_off",
                start_time=1.0,
                end_time=6.0,
                duration=5.0,
                status="selected",
                subtitle_style={
                    "enabled": False,
                    "subtitle_language": "ml",
                    "translated_words": [{"word": "നമസ്കാരം", "start": 1.0, "end": 3.0}],
                },
            )
            t = TranscriptSegment(
                id="seg_sub_off",
                video_id="v_sub_off",
                start_time=1.0,
                end_time=5.0,
                text="hello everyone",
                words=[{"word": "hello", "start": 1.0, "end": 2.5}],
            )
            session.add_all([v, j, c, t])
            await session.commit()

        captured_opts = {}

        async def fake_run_export(clip_id, opts):
            captured_opts.update(opts)
            return {
                "export_url": f"/api/exports/{clip_id}/download",
                "duration": 5.0,
                "resolution": "1080x1920",
                "codec": "h264",
                "audio_codec": "aac",
                "gpu_accelerated": False,
                "size_mb": 1.2,
                "sync_report": {"encoder": "CPU (libx264)", "passed": True, "subtitle_words": 0},
            }

        with patch("backend.app.api.jobs.job_runner.run_export", side_effect=fake_run_export):
            resp = await self.client.post(
                "/api/jobs/j_sub_off/clips/c_sub_off/export",
                json={
                    "layout": "center_crop",
                    "burn_subtitles": False,
                    "subtitle_style": {
                        "enabled": False,
                        "subtitle_language": "ml",
                        "translated_words": [{"word": "നമസ്കാരം", "start": 1.0, "end": 3.0}],
                    },
                },
            )
        self.assertEqual(resp.status_code, 200)
        self.assertIs(captured_opts.get("burn_subtitles"), False)
        self.assertIs(captured_opts.get("subtitle_style", {}).get("enabled"), False)

        # Verify original TranscriptSegment and translated_words are preserved in DB
        async with database.async_session_maker() as session:
            seg = await session.get(TranscriptSegment, "seg_sub_off")
            clip_row = await session.get(Clip, "c_sub_off")
            self.assertEqual(seg.text, "hello everyone")
            self.assertEqual(clip_row.subtitle_style["translated_words"][0]["word"], "നമസ്കാരം")

    async def test_url_dedup_retry_cancel_and_health_profiles(self):
        from backend.app.models import Video, Job

        # 1. Health reports transcription profiles and hardware details
        h_resp = await self.client.get("/api/health")
        self.assertEqual(h_resp.status_code, 200)
        h_data = h_resp.json()
        self.assertIn("transcription_profiles", h_data)
        self.assertIn("speed", h_data["transcription_profiles"])
        self.assertIn("balanced", h_data["transcription_profiles"])
        self.assertIn("accuracy", h_data["transcription_profiles"])
        self.assertIn("whisper_hardware", h_data)

        # 2. Canonical URL deduplication (watch?v=X vs youtu.be/X)
        async with database.async_session_maker() as session:
            v = Video(id="v_dup_test", filename="YT Import", source_type="youtube", file_path="x", status="downloading")
            j = Job(id="j_dup_test", video_id="v_dup_test", status="downloading", progress=25, current_stage="DOWNLOADING")
            session.add_all([v, j])
            await session.commit()

        from backend.app import job_runner
        job_runner.running.add("j_dup_test")
        job_runner.active_url_imports["youtube:dQw4w9WgXcQ"] = "j_dup_test"
        try:
            with patch("backend.app.video_import.ytdlp_available", return_value=True):
                dup_resp = await self.client.post(
                    "/api/videos/import-url",
                    json={"url": "https://youtu.be/dQw4w9WgXcQ?t=10", "transcription_profile": "speed"},
                )
            self.assertEqual(dup_resp.status_code, 200)
            dup_data = dup_resp.json()
            self.assertTrue(dup_data.get("duplicate_prevented"))
            self.assertEqual(dup_data.get("job_id"), "j_dup_test")
        finally:
            job_runner.running.discard("j_dup_test")
            job_runner.active_url_imports.pop("youtube:dQw4w9WgXcQ", None)

        # 3. Retry sets lowercase 'queued' and can be cancelled immediately
        async with database.async_session_maker() as session:
            j_row = await session.get(Job, "j_dup_test")
            j_row.status = "failed"
            await session.commit()

        with patch("backend.app.api.jobs.job_runner.start_url_import", return_value=True):
            async with database.async_session_maker() as session:
                j_row = await session.get(Job, "j_dup_test")
                j_row.settings = {"source_url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ"}
                await session.commit()
            retry_resp = await self.client.post("/api/jobs/j_dup_test/retry")
            self.assertEqual(retry_resp.status_code, 200)
            self.assertEqual(retry_resp.json()["status"], "queued")

        cancel_resp = await self.client.post("/api/jobs/j_dup_test/cancel")
        self.assertEqual(cancel_resp.status_code, 200)
        self.assertEqual(cancel_resp.json()["status"], "cancelled")


if __name__ == "__main__":
    unittest.main()
