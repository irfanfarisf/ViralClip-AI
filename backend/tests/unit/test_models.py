import unittest
from backend.app.schemas.video import VideoResponse, VideoImportUrlRequest
from backend.app.schemas.job import JobCreate, JobResponse
from backend.app.schemas.clip import ClipExportRequest
from backend.app.models.video import Video
from backend.app.models.job import Job
from backend.app.models.clip import Clip

class TestModelsAndSchemas(unittest.TestCase):
    def test_video_model_defaults(self):
        video = Video(
            id="vid_test_123",
            filename="my_stream.mp4",
            source_type="local",
            file_path="/storage/test.mp4",
            duration=120.5,
            fps=60.0,
        )
        self.assertEqual(video.id, "vid_test_123")
        self.assertEqual(video.source_type, "local")
        self.assertEqual(video.duration, 120.5)
        self.assertEqual(video.fps, 60.0)

    def test_job_model_initial_state(self):
        job = Job(
            id="job_test_456",
            video_id="vid_test_123",
            status="queued",
            progress=0,
            current_stage="Queued",
        )
        self.assertEqual(job.status, "queued")
        self.assertEqual(job.progress, 0)

    def test_clip_model_creation(self):
        clip = Clip(
            id="clip_test_789",
            job_id="job_test_456",
            start_time=10.0,
            end_time=30.0,
            duration=20.0,
            score=95,
            suggested_title="Epic Moment",
            layout="facecam_gameplay",
        )
        self.assertEqual(clip.duration, 20.0)
        self.assertEqual(clip.score, 95)
        self.assertEqual(clip.layout, "facecam_gameplay")

    def test_import_url_schema_validation(self):
        req = VideoImportUrlRequest(url="https://www.youtube.com/watch?v=dQw4w9WgXcQ")
        self.assertTrue(req.url.startswith("https://"))

    def test_clip_export_request_schema(self):
        req = ClipExportRequest(
            title="Custom Clip Title",
            layout="facecam_gameplay",
            resolution="1080x1920 (9:16)",
            facecam_crop={"heightPercent": 35, "zoom": 1.0, "offsetY": 0},
            gameplay_crop={"heightPercent": 65, "zoom": 1.0, "offsetY": 0},
        )
        self.assertEqual(req.title, "Custom Clip Title")
        self.assertEqual(req.layout, "facecam_gameplay")

if __name__ == "__main__":
    unittest.main()
