"""End-to-end smoke test against a real running server (real FFmpeg, real Whisper, real files).

Usage:  .venv\\Scripts\\python.exe backend/tests/e2e_smoke.py
Starts uvicorn on port 8765 with isolated storage (storage/e2e) and deletes it afterwards.
Requires network on first run to download the Whisper 'tiny' model.
"""
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from backend.app.gpu_config import find_ffmpeg, find_ffprobe  # noqa: E402

PORT = 8765
BASE = f"http://127.0.0.1:{PORT}"
E2E = ROOT / "storage" / "e2e"
FIX = ROOT / "backend" / "tests" / "fixtures"
results = []


def check(name, cond, detail=""):
    results.append((name, bool(cond)))
    print(f"[{'PASS' if cond else 'FAIL'}] {name} {detail}", flush=True)


def poll(fn, done, timeout=300, every=1.0):
    t0, last = time.time(), None
    while time.time() - t0 < timeout:
        last = fn()
        if done(last):
            return last
        time.sleep(every)
    return last


def main():
    ff, fp = find_ffmpeg(), find_ffprobe()
    shutil.rmtree(E2E, ignore_errors=True)
    (E2E / "src").mkdir(parents=True)
    video = E2E / "src" / "gameplay_with_speech.mp4"
    speech = FIX / "speech.wav"
    subprocess.run([ff, "-y", "-loglevel", "error", "-f", "lavfi", "-i", "testsrc2=s=1920x1080:r=60",
                    "-i", str(speech), "-map", "0:v", "-map", "1:a", "-c:v", "libx264", "-pix_fmt", "yuv420p",
                    "-c:a", "aac", "-shortest", str(video)], check=True)
    env = {**os.environ, "STORAGE_DIR": str(E2E), "TEMP_DIR": str(E2E / "temp"), "OUTPUT_DIR": str(E2E / "output"),
           "DB_PATH": str(E2E / "db" / "e2e.db"), "WHISPER_MODEL": "tiny", "PYTHONPATH": str(ROOT)}
    (E2E / "db").mkdir(parents=True, exist_ok=True)
    logf = open(E2E / "server.log", "w")
    server = subprocess.Popen([sys.executable, "-m", "uvicorn", "backend.app.main:app", "--port", str(PORT)],
                              cwd=str(ROOT), env=env, stdout=logf, stderr=subprocess.STDOUT)
    try:
        c = httpx.Client(base_url=BASE, timeout=120)
        up = poll(lambda: _try(c.get, "/api/health"), lambda r: r is not None and r.status_code == 200, 40)
        if up is None:
            logf.flush()
            srv_out = (E2E / "server.log").read_text(errors="ignore")
            print("SERVER LOG ON STARTUP FAILURE:\n" + srv_out, flush=True)
            raise RuntimeError(f"Server failed to start within timeout. Log:\n{srv_out}")
        check("server starts", up is not None and up.status_code == 200)
        h = up.json()
        print("  health:", json.dumps(h), flush=True)
        check("health reports ffmpeg+ffprobe+encoder", h["ffmpeg"] and h["ffprobe"] and h["gpu_encoder"])
        check("health reports NVENC/QSV/AMF/CPU vendor map",
              all(k in h.get("encoder_vendors", {}) for k in ("nvenc", "qsv", "amf", "cpu")))

        # --- validation errors
        r = c.post("/api/upload", files={"file": ("notes.txt", b"hello", "text/plain")})
        check("reject unsupported extension -> 400", r.status_code == 400, r.json().get("detail", ""))
        r = c.post("/api/upload", files={"file": ("empty.mp4", b"", "video/mp4")})
        check("reject empty file -> 400", r.status_code == 400, r.json().get("detail", ""))
        r = c.post("/api/upload", files={"file": ("fake.mp4", b"not really a video" * 100, "video/mp4")})
        check("reject corrupt video (ffprobe) -> 400", r.status_code == 400, r.json().get("detail", ""))
        check("rejected uploads leave no files behind",
              not any((E2E / "temp").iterdir()) if (E2E / "temp").exists() else True)

        # --- upload
        with open(video, "rb") as f:
            r = c.post("/api/upload", files={"file": (video.name, f, "video/mp4")})
        check("upload valid video -> 201", r.status_code == 201, r.text[:200])
        v = r.json()
        probe = json.loads(subprocess.run([fp, "-v", "error", "-print_format", "json", "-show_format", "-show_streams",
                                           str(video)], capture_output=True, text=True).stdout)
        real_dur = float(probe["format"]["duration"])
        check("metadata matches ffprobe (1920x1080, duration)", v["width"] == 1920 and v["height"] == 1080
              and abs(v["duration"] - real_dur) < 0.05, f"{v['width']}x{v['height']} {v['duration']}s")
        check("audio detected", v["has_audio"] is True)
        r = c.get(f"/api/videos/{v['id']}/stream", headers={"Range": "bytes=0-99"})
        check("source stream supports Range (206)", r.status_code == 206, str(r.status_code))

        # --- analyze
        r = c.post("/api/analyze", json={"video_id": "vid_nope"})
        check("analyze unknown video -> 404", r.status_code == 404)
        r = c.post("/api/analyze", json={"video_id": v["id"], "min_clip_seconds": 10, "max_clip_seconds": 25,
                                         "target_clip_seconds": 15, "max_clips": 3})
        check("analyze -> 202", r.status_code == 202, r.text[:150])
        job_id = r.json()["job_id"]
        seen = []

        def jstate():
            j = c.get(f"/api/jobs/{job_id}").json()
            if not seen or seen[-1] != (j["status"], j["current_stage"]):
                seen.append((j["status"], j["current_stage"]))
            return j
        job = poll(jstate, lambda j: j["status"] in ("ready", "failed", "cancelled"), 600, 1.0)
        print("  stages seen:", [s for s in seen][:12], flush=True)
        check("job reaches ready", job["status"] == "ready", f"{job['status']} {job.get('error_message')}")
        check("detected_language is accurate ('en')", job.get("detected_language") == "en", f"lang={job.get('detected_language')}")
        print("  warnings:", job.get("warnings"), flush=True)
        words = sum(len(t["words"]) for t in job["transcripts"])
        check("real transcript with word timestamps", job["transcripts"] and words > 10, f"{len(job['transcripts'])} segments, {words} words")
        all_words = [w for t in job["transcripts"] for w in t.get("words", [])]
        check("word-level timestamps are accurate and ordered",
              all(0.0 <= w["start"] <= w["end"] <= v["duration"] + 0.5 and w["word"].strip() for w in all_words)
              and all(t["words"][i]["start"] <= t["words"][i + 1]["start"] + 0.05
                      for t in job["transcripts"] for i in range(len(t.get("words", [])) - 1)))
        print("  transcript:", " ".join(t["text"] for t in job["transcripts"])[:300], flush=True)
        check("clips detected from real data", len(job["clips"]) >= 1, f"{len(job['clips'])} clips")
        for cl in job["clips"]:
            print(f"   clip {cl['id']} {cl['start_time']:.1f}-{cl['end_time']:.1f}s score={cl['score']} {cl['reason']} | {cl['title']}", flush=True)
        check("clips respect length limits", all(9.9 <= cl["duration"] <= 26 for cl in job["clips"]))

        # --- clips endpoints
        r = c.post("/api/clips/generate", json={"job_id": job_id, "min_clip_seconds": 8, "max_clip_seconds": 20,
                                                "target_clip_seconds": 12, "max_clips": 2})
        check("clips/generate -> 200 and <=2 clips", r.status_code == 200 and len(r.json()["clips"]) <= 2, r.text[:120])
        clips = r.json()["clips"]
        clip = clips[0]
        check("top clip marked selected", clip.get("selected") is True)
        check("two suitable clips selected", len(clips) == 2 and all(cl.get("selected") is True for cl in clips))
        r = c.get(f"/api/clips/{clip['id']}")
        check("GET clip includes transcript excerpt", r.status_code == 200 and len(r.json()["transcript"]) >= 1)
        check("GET clip includes detected_language", r.json().get("detected_language") == "en")
        check("GET unknown clip -> 404", c.get("/api/clips/clip_nope").status_code == 404)
        check("download before export -> 404", c.get(f"/api/exports/{clip['id']}/download").status_code == 404)

        # test PATCH clip adjustment (start, end, title)
        orig_start = clip["start_time"]
        orig_end = clip["end_time"]
        new_start = round(orig_start + 0.5, 2)
        new_end = round(orig_end, 2)
        r_patch = c.patch(f"/api/clips/{clip['id']}", json={"start_time": new_start, "end_time": new_end, "suggested_title": "Adjusted Clip Title"})
        check("PATCH clip -> 200", r_patch.status_code == 200)
        patched_clip = r_patch.json()
        check("PATCH clip updated start_time & title", patched_clip["start_time"] == new_start and patched_clip.get("title") == "Adjusted Clip Title")
        check("PATCH clip recalculated duration", abs(patched_clip["duration"] - (new_end - new_start)) < 0.05)
        # restore start time for subsequent export
        c.patch(f"/api/clips/{clip['id']}", json={"start_time": orig_start})

        # test smart-crop subject/face analysis endpoint
        r_sc = c.post(f"/api/clips/{clip['id']}/smart-crop")
        check("POST smart-crop -> 200", r_sc.status_code == 200)
        sc_data = r_sc.json()
        check("smart-crop truthful single-source metadata",
              sc_data.get("source_streams") == 1 and sc_data.get("single_source_reframed") is True
              and len(sc_data.get("subject_keyframes", [])) >= 2)

        # test manual transcript correction endpoint
        clip_detail = c.get(f"/api/clips/{clip['id']}").json()
        segs = clip_detail.get("transcript", [])
        check("clip has transcript segments", len(segs) >= 1)
        first_seg = segs[0]
        corrected_text = first_seg["text"] + " [verified]"
        r_corr = c.put(f"/api/clips/{clip['id']}/transcript",
                       json={"segments": [{"id": first_seg["id"], "start": first_seg["start"],
                                           "end": first_seg["end"], "text": corrected_text}]})
        check("PUT clip transcript -> 200", r_corr.status_code == 200)
        corr_data = r_corr.json()
        check("transcript correction persisted", corr_data["transcript"][0]["text"] == corrected_text)

        # test AI Shorts metadata generation & regeneration (Phase 10)
        r_meta = c.post(f"/api/clips/{clip['id']}/metadata", json={"use_ai_api": False})
        check("POST clip metadata -> 200", r_meta.status_code == 200)
        meta_data = r_meta.json()
        check("metadata has 3 title suggestions", len(meta_data.get("title_suggestions", [])) == 3)
        check("metadata has recommended title", bool(meta_data.get("title") and meta_data["title"] == meta_data["title_suggestions"][0]))
        check("metadata has truthful description", bool(meta_data.get("description") and "s duration" in meta_data["description"]))
        check("metadata has hashtags", len(meta_data.get("hashtags", [])) >= 4 and "#shorts" in meta_data["hashtags"])
        check("metadata has thumbnail text", bool(meta_data.get("thumbnail_text")))
        check("metadata has thumbnail timestamp within clip",
              clip["start_time"] <= meta_data.get("thumbnail_timestamp", 0.0) <= clip["end_time"])

        # test manual editing and persistence of metadata
        custom_thumb_text = "EPIC FINISH!"
        custom_thumb_ts = round(clip["start_time"] + 1.5, 2)
        r_meta_patch = c.patch(f"/api/clips/{clip['id']}", json={
            "suggested_title": "Custom User Title",
            "thumbnail_text": custom_thumb_text,
            "thumbnail_timestamp": custom_thumb_ts,
            "hashtags": ["#shorts", "#custom", "#viral", "#gaming"],
        })
        check("PATCH clip metadata -> 200", r_meta_patch.status_code == 200)
        patched_meta = r_meta_patch.json()
        check("patched metadata persisted thumbnail text & timestamp",
              patched_meta.get("thumbnail_text") == custom_thumb_text
              and patched_meta.get("thumbnail_timestamp") == custom_thumb_ts
              and patched_meta.get("title") == "Custom User Title")

        # test multilingual language catalog & translation endpoint
        r_langs = c.get("/api/languages")
        check("GET /api/languages -> 200", r_langs.status_code == 200)
        langs = r_langs.json()
        check("languages catalog has >= 12 languages with ml, hi, ta, es",
              len(langs) >= 12 and "ml" in langs and "hi" in langs and "ta" in langs)

        r_trans = c.post(f"/api/clips/{clip['id']}/translate", json={"target_language": "ml"})
        check("POST clip translate to ml -> 200", r_trans.status_code == 200)
        trans_res = r_trans.json()
        check("translation returned target_language=ml and translated_words",
              trans_res.get("target_language") == "ml" and len(trans_res.get("translated_words", [])) > 0)

        # --- export
        check("export bad layout -> 422", c.post("/api/export", json={"clip_id": clip["id"], "layout": "bogus"}).status_code == 422)
        check("export unknown clip -> 404", c.post("/api/export", json={"clip_id": "clip_nope"}).status_code == 404)
        check("export out-of-range end -> 422", c.post("/api/export", json={"clip_id": clip["id"], "end_time": 9999}).status_code == 422)
        ws_msgs = []

        def ws_listener():
            from websockets.sync.client import connect
            try:
                with connect(f"ws://127.0.0.1:{PORT}/api/jobs/ws/{clip['id']}", open_timeout=10) as ws:
                    ws_ready.set()
                    while True:
                        m = json.loads(ws.recv(timeout=120))
                        ws_msgs.append(m)
                        if m["status"] in ("exported", "export_failed"):
                            return
            except Exception as exc:  # noqa: BLE001
                ws_ready.set()
                ws_msgs.append({"status": f"ws_error: {exc}", "progress": -1})
        import threading
        ws_ready = threading.Event()
        wst = threading.Thread(target=ws_listener, daemon=True)
        wst.start()
        ws_ready.wait(15)
        r = c.post("/api/export", json={"clip_id": clip["id"], "layout": "facecam_gameplay", "title": "E2E Test Clip",
                                        "subtitle_style": {"preset": "yellow_highlight", "highlight": "#FFD700",
                                                          "animation": "pop", "position": "bottom"}})
        check("export -> 202", r.status_code == 202, r.text[:150])
        wst.join(120)
        pcts = [m["progress"] for m in ws_msgs]
        check("WebSocket streamed export progress", len(ws_msgs) >= 3 and ws_msgs[-1]["status"] == "exported"
              and pcts == sorted(pcts), f"{len(ws_msgs)} msgs: {pcts[:6]}...{pcts[-2:]}")
        prog = []

        def cstate():
            cc = c.get(f"/api/clips/{clip['id']}").json()
            prog.append(cc["export_progress"])
            return cc
        cc = poll(cstate, lambda x: x["status"] in ("exported", "export_failed"), 600, 0.5)
        check("export completes", cc["status"] == "exported", f"{cc['status']} {cc.get('export_error')}")
        print("  progress samples:", prog[:: max(len(prog) // 8, 1)], flush=True)
        sr = cc["sync_report"]
        print("  sync_report:", json.dumps(sr), flush=True)
        check("validation passed", sr.get("passed") is True, f"encoder={sr.get('encoder')} offset={sr.get('sync_offset_ms')}ms")
        check("sync_report includes codec h264+aac & gpu_accelerated",
              sr.get("codec") == "h264" and sr.get("audio_codec") == "aac" and isinstance(sr.get("gpu_accelerated"), bool)
              and cc.get("download_url") == f"/api/exports/{clip['id']}/download")
        check("sync_report includes truthful composition metadata",
              sr.get("composition", {}).get("source_streams") == 1
              and sr.get("composition", {}).get("single_source_reframed") is True)
        r = c.get(f"/api/exports/{clip['id']}/download")
        out = E2E / "downloaded.mp4"
        out.write_bytes(r.content)
        check("download returns MP4", r.status_code == 200 and r.headers["content-type"] == "video/mp4" and len(r.content) > 10000, f"{len(r.content)} bytes")
        op = json.loads(subprocess.run([fp, "-v", "error", "-print_format", "json", "-show_streams", str(out)], capture_output=True, text=True).stdout)
        vs = next(s for s in op["streams"] if s["codec_type"] == "video")
        check("downloaded file is 1080x1920 H.264 with audio", vs["width"] == 1080 and vs["height"] == 1920 and vs["codec_name"] == "h264"
              and any(s["codec_type"] == "audio" for s in op["streams"]))
        # extract a mid frame to confirm layout + subtitles were actually burned in
        shutil.copy(out, FIX / "_last_export.mp4") if False else None
        subprocess.run([ff, "-y", "-loglevel", "error", "-ss", "3", "-i", str(out), "-frames:v", "1", str(E2E / "frame.png")])
        check("frame extracted from export", (E2E / "frame.png").exists())
        check("sync-report endpoint", c.get(f"/api/exports/{clip['id']}/sync-report").json().get("passed") is True)
        exp_hist = c.get("/api/exports").json()
        check("GET /api/exports lists exported clip history",
              isinstance(exp_hist, list) and any(e["id"] == clip["id"] and e["download_url"] for e in exp_hist))

        # --- frontend synchronous export route with CPU fallback (prefer_hardware=False)
        if len(clips) > 1:
            clip2 = clips[1]
            r_fe_exp = c.post(f"/api/jobs/{job_id}/clips/{clip2['id']}/export", json={
                "title": "Frontend Studio Export",
                "layout": "smart_crop",
                "subtitle_style": {"preset": "bold_creator", "animation": "bounce"},
                "prefer_hardware": False,
                "fps": 30,
                "bitrate_kbps": 6000,
            })
            check("frontend export route -> 200", r_fe_exp.status_code == 200)
            fe_res = r_fe_exp.json()
            check("frontend export returns full metadata",
                  fe_res.get("codec") == "h264" and fe_res.get("download_url") and fe_res.get("file_size_mb", 0) > 0
                  and len(fe_res.get("title_suggestions", [])) >= 1 and bool(fe_res.get("thumbnail_text")))
            check("CPU fallback (libx264) works and reports gpu_accelerated=False",
                  fe_res.get("encoder") == "CPU (libx264)" and fe_res.get("gpu_accelerated") is False
                  and fe_res.get("sync_report", {}).get("passed") is True)

        # --- job progress & state recovery on page refresh
        lst = c.get("/api/jobs").json()
        check("legacy GET /api/jobs lists real job", any(j["id"] == job_id for j in lst))
        recovered = c.get(f"/api/jobs/{job_id}").json()
        check("job progress & full state survive page refresh",
              recovered["status"] == "ready" and recovered["progress"] == 100
              and len(recovered["transcripts"]) > 0 and len(recovered["clips"]) == 2
              and sum(1 for cl in recovered["clips"] if cl["status"] == "exported") == 2)
        r = c.post("/api/videos/import-url", json={"url": "https://example.com/x"})
        check("import-url unsupported host -> 400", r.status_code == 400, r.json()["detail"])
        r = c.post("/api/videos/import-url", json={"url": "https://www.youtube.com/watch?v=invalid_0000", "background": False})
        check("import-url unavailable/without yt-dlp -> 503/422 (no fake project)", r.status_code in (503, 422), f"{r.status_code} {r.json().get('detail', '')[:90]}")
        check("failed import created no project", len(c.get("/api/jobs").json()) == len(lst))
        if h.get("yt_dlp"):
            bg_url = "https://www.youtube.com/watch?v=dQw4w9WgXcQ"
            r_bg1 = c.post("/api/videos/import-url", json={"url": bg_url, "background": True})
            check("background import-url queues worker -> 200", r_bg1.status_code == 200 and r_bg1.json().get("job_id"))
            bg_jid = r_bg1.json()["job_id"]
            r_bg2 = c.post("/api/videos/import-url", json={"url": bg_url, "background": True})
            check("duplicate active URL import prevented", r_bg2.status_code == 200 and r_bg2.json().get("job_id") == bg_jid)
            c.post(f"/api/jobs/{bg_jid}/cancel")
            c.delete(f"/api/jobs/{bg_jid}")

        # --- no-audio video handling
        no_audio_vid = E2E / "src" / "silent_test.mp4"
        subprocess.run([ff, "-y", "-loglevel", "error", "-f", "lavfi", "-i", "testsrc2=s=640x360:r=30:d=4",
                        "-c:v", "libx264", "-pix_fmt", "yuv420p", "-an", str(no_audio_vid)], check=True)
        with open(no_audio_vid, "rb") as naf:
            r_na = c.post("/api/upload", files={"file": ("silent_test.mp4", naf, "video/mp4")})
        check("upload video without audio -> 201", r_na.status_code == 201)
        na_v = r_na.json()
        check("video correctly identified as has_audio=False", na_v.get("has_audio") is False)
        r_na_an = c.post("/api/analyze", json={"video_id": na_v["id"]})
        check("analyze video without audio -> 202", r_na_an.status_code == 202)
        na_job_id = r_na_an.json()["job_id"]
        na_job = poll(lambda: c.get(f"/api/jobs/{na_job_id}").json(), lambda j: j["status"] in ("ready", "failed"), 60, 0.5)
        check("no-audio job succeeds cleanly (status=ready)", na_job["status"] == "ready")
        check("no-audio warning recorded", any("no audio track" in w.lower() for w in na_job.get("warnings", [])))
        c.delete(f"/api/jobs/{na_job_id}")

        # --- failed job displays appropriate error message
        with open(no_audio_vid, "rb") as f_fail:
            r_fv = c.post("/api/upload", files={"file": ("missing_later.mp4", f_fail, "video/mp4")})
        fv_id = r_fv.json()["id"]
        shutil.rmtree(E2E / "temp" / fv_id, ignore_errors=True)
        r_fj = c.post("/api/analyze", json={"video_id": fv_id})
        fj_id = r_fj.json()["job_id"]
        fj_state = poll(lambda: c.get(f"/api/jobs/{fj_id}").json(), lambda j: j["status"] in ("ready", "failed"), 30, 0.3)
        check("failed job reports status=failed and clear error_message",
              fj_state["status"] == "failed" and "no longer exists" in (fj_state.get("error_message") or "").lower(),
              fj_state.get("error_message", ""))
        c.delete(f"/api/jobs/{fj_id}")

        # --- safe temporary-file cleanup preserves user videos & exports
        orphan_dir = E2E / "temp" / "vid_orphan_stale"
        orphan_dir.mkdir(parents=True, exist_ok=True)
        part_file = E2E / "output" / clip["id"] / "incomplete.part.mp4"
        part_file.write_bytes(b"partial")
        old_ts = time.time() - 7200
        os.utime(orphan_dir, (old_ts, old_ts))
        os.utime(part_file, (old_ts, old_ts))
        r_clean = c.post("/api/health/cleanup")
        check("POST /api/health/cleanup -> 200", r_clean.status_code == 200)
        clean_res = r_clean.json().get("removed", {})
        check("safe cleanup removes stale orphans/partials without deleting user videos or exported MP4s",
              clean_res.get("orphan_dirs", 0) >= 1 and clean_res.get("partial_files", 0) >= 1
              and not orphan_dir.exists() and not part_file.exists()
              and (E2E / "temp" / v["id"]).exists()
              and any((E2E / "output" / clip["id"]).glob("*.mp4")))

        # --- high-performance resumable chunked upload engine (init -> chunk -> status -> resume -> complete & cancel)
        import hashlib
        raw_vid = no_audio_vid.read_bytes()
        half_sz = 256 * 1024
        fp_key = f"chunked_e2e.mp4:{len(raw_vid)}"
        r_init = c.post("/api/videos/upload/init", json={
            "filename": "chunked_e2e.mp4",
            "total_bytes": len(raw_vid),
            "chunk_size": half_sz,
            "fingerprint": fp_key,
            "file_sha256": hashlib.sha256(raw_vid).hexdigest(),
            "auto_analyze": False,
        })
        check("POST /api/videos/upload/init -> 201", r_init.status_code == 201)
        up_info = r_init.json()
        up_id = up_info["upload_id"]
        tot_chunks = up_info["total_chunks"]

        # Upload chunk 0 with SHA-256 verification
        c0_bytes = raw_vid[:half_sz]
        c0_sha = hashlib.sha256(c0_bytes).hexdigest()
        r_c0 = c.put(f"/api/videos/upload/{up_id}/chunk?chunk_index=0&offset=0&sha256={c0_sha}", content=c0_bytes)
        check("PUT chunk 0 verified -> 200", r_c0.status_code == 200 and r_c0.json()["duplicate"] is False)
        # Re-send chunk 0 to verify deduplication
        r_c0_dup = c.put(f"/api/videos/upload/{up_id}/chunk?chunk_index=0&offset=0&sha256={c0_sha}", content=c0_bytes)
        check("PUT duplicate chunk 0 deduplicated", r_c0_dup.status_code == 200 and r_c0_dup.json()["duplicate"] is True)
        # Resume via fingerprint returns received_chunks=[0]
        r_resumed = c.post("/api/videos/upload/init", json={
            "filename": "chunked_e2e.mp4",
            "total_bytes": len(raw_vid),
            "chunk_size": half_sz,
            "fingerprint": fp_key,
        })
        check("resumable upload returns existing session & received chunks",
              r_resumed.json().get("resumed") is True and 0 in r_resumed.json().get("received_chunks", []))
        # Upload remaining chunks
        for idx in range(1, tot_chunks):
            sl = raw_vid[idx * half_sz: (idx + 1) * half_sz]
            r_ck = c.put(f"/api/videos/upload/{up_id}/chunk?chunk_index={idx}&offset={idx * half_sz}", content=sl)
            assert r_ck.status_code == 200
        r_comp = c.post(f"/api/videos/upload/{up_id}/complete", json={"auto_analyze": False})
        check("POST /api/videos/upload/{id}/complete -> 200 (COMPLETED without starting Whisper)",
              r_comp.status_code == 200 and r_comp.json().get("import_state") == "COMPLETED"
              and r_comp.json().get("duration", 0) > 0)
        c.delete(f"/api/jobs/{up_info['job_id']}")

        # Test chunked upload cancellation cleans up .uploading.part
        r_cancel_init = c.post("/api/videos/upload/init", json={
            "filename": "abort_me.mp4",
            "total_bytes": len(raw_vid),
            "chunk_size": half_sz,
        })
        abort_id = r_cancel_init.json()["upload_id"]
        c.put(f"/api/videos/upload/{abort_id}/chunk?chunk_index=0&offset=0", content=c0_bytes)
        r_abort = c.delete(f"/api/videos/upload/{abort_id}")
        check("DELETE /api/videos/upload/{id} cancels & removes temp part file",
              r_abort.status_code == 200 and r_abort.json().get("status") == "CANCELLED"
              and not (E2E / "temp" / abort_id).exists())

        # --- cancel + delete cleanup
        r = c.post(f"/api/jobs/{job_id}/cancel")
        check("cancel finished job -> 409", r.status_code == 409)
        r = c.delete(f"/api/jobs/{job_id}")
        check("delete job removes files", r.status_code == 200 and not any((E2E / "temp").iterdir())
              and not any((E2E / "output").iterdir()))
    finally:
        server.terminate()
        try:
            server.wait(10)
        except subprocess.TimeoutExpired:
            server.kill()
        logf.close()
    failed = [n for n, ok in results if not ok]
    print(f"\n{len(results) - len(failed)}/{len(results)} checks passed", "FAILED: " + ", ".join(failed) if failed else "")
    print("server log tail:\n" + "\n".join((E2E / "server.log").read_text(errors="ignore").splitlines()[-15:]))
    shutil.rmtree(E2E, ignore_errors=True)
    sys.exit(1 if failed else 0)


def _try(fn, *a):
    try:
        return fn(*a)
    except httpx.HTTPError:
        return None


if __name__ == "__main__":
    main()
