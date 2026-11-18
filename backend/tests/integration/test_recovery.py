"""Restart recovery: jobs/exports interrupted mid-flight are marked failed (never left 'running' forever).

Run in its own process (it points the app at a throwaway database):
    .venv\\Scripts\\python.exe -m unittest backend.tests.integration.test_recovery
"""
import os
import tempfile

_tmp = tempfile.mkdtemp(prefix="vc_recovery_")
os.environ["DB_PATH"] = os.path.join(_tmp, "t.db")
os.environ["TEMP_DIR"] = os.path.join(_tmp, "temp")
os.environ["OUTPUT_DIR"] = os.path.join(_tmp, "out")
os.environ["STORAGE_DIR"] = _tmp

import unittest  # noqa: E402

from backend.app import database, job_runner  # noqa: E402
from backend.app.database import Base  # noqa: E402
from backend.app.models import Clip, Job, Video  # noqa: E402


class TestRecovery(unittest.IsolatedAsyncioTestCase):
    async def test_interrupted_work_marked_failed(self):
        async with database.engine.begin() as c:
            await c.run_sync(Base.metadata.create_all)
        await job_runner.migrate_schema()
        async with database.async_session_maker() as s:
            s.add(Video(id="v1", filename="a.mp4", file_path="x", duration=60))
            s.add_all([Job(id="j_run", video_id="v1", status="transcribing", progress=40),
                       Job(id="j_done", video_id="v1", status="ready", progress=100)])
            await s.commit()
            s.add_all([Clip(id="c_exp", job_id="j_done", start_time=0, end_time=10, duration=10, status="exporting"),
                       Clip(id="c_ok", job_id="j_done", start_time=0, end_time=10, duration=10, status="exported")])
            await s.commit()
        res = await job_runner.recover_interrupted()
        self.assertEqual(res, {"jobs": 1, "clips": 1})
        async with database.async_session_maker() as s:
            self.assertEqual((await s.get(Job, "j_run")).status, "failed")
            self.assertIn("restart", (await s.get(Job, "j_run")).error_message.lower())
            self.assertEqual((await s.get(Job, "j_done")).status, "ready")
            self.assertEqual((await s.get(Clip, "c_exp")).status, "export_failed")
            self.assertEqual((await s.get(Clip, "c_ok")).status, "exported")
        await database.engine.dispose()


if __name__ == "__main__":
    unittest.main()
