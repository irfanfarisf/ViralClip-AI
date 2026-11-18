import re
import unittest

from backend.app import video_processor as vp
from backend.app.clip_detector import detect_clips
from backend.app.export import validate_output
from backend.app.job_runner import safe_filename
from backend.app.subtitle_generator import (SubtitleStyle, chunk_words, collect_words, generate_ass,
                                            generate_srt)
from backend.app.video_import import ImportFailure, classify_url, safe_display_name, validate_extension
from pathlib import Path


class TestImportValidation(unittest.TestCase):
    def test_extension_allowlist(self):
        self.assertEqual(validate_extension("a.MP4"), ".mp4")
        for bad in ("a.exe", "a.txt", "noext", None, "a.mp4.exe"):
            with self.assertRaises(ImportFailure):
                validate_extension(bad)

    def test_classify_url(self):
        self.assertEqual(classify_url("https://www.youtube.com/watch?v=abc"), "youtube")
        self.assertEqual(classify_url("https://youtu.be/abc"), "youtube")
        self.assertEqual(classify_url("https://www.twitch.tv/videos/123"), "twitch")
        for bad in ("ftp://youtube.com/x", "https://evil.com/youtube.com", "https://youtube.com.evil.com/x",
                    "not a url", "https://example.com"):
            with self.assertRaises(ImportFailure):
                classify_url(bad)

    def test_display_name_strips_paths(self):
        self.assertEqual(safe_display_name("../../etc/passwd.mp4"), "passwd.mp4")
        self.assertNotIn("/", safe_display_name("a/b\\c<>.mp4"))

    def test_safe_filename(self):
        n = safe_filename('We "won"! / ..\\x', "clip_1")
        self.assertTrue(n.endswith("_clip_1.mp4"))
        self.assertIsNone(re.search(r'[\\/:*?"<>|]', n))


class TestVideoProcessor(unittest.TestCase):
    def test_default_layout_geometry(self):
        self.assertEqual((vp.OUT_W, vp.OUT_H), (1080, 1920))
        self.assertEqual(vp.FACECAM_H + vp.GAMEPLAY_H, 1920)
        self.assertAlmostEqual(vp.OUT_W / vp.GAMEPLAY_H, 3 / 4)  # gameplay region is 3:4

    def test_graph_facecam_top_gameplay_bottom(self):
        g = vp.build_filter_graph("facecam_gameplay", ass_filename="s.ass")
        self.assertIn("1080:480", g)
        self.assertIn("1080:1440", g)
        self.assertLess(g.index("[face]"), g.index("[game]"))
        self.assertIn("vstack=inputs=2", g)
        self.assertIn("ass=s.ass", g)
        self.assertTrue(g.endswith("[vout]"))

    def test_all_layouts_build(self):
        for layout in vp.LAYOUTS:
            self.assertTrue(vp.build_filter_graph(layout).endswith("[vout]"))
        with self.assertRaises(ValueError):
            vp.build_filter_graph("nope")

    def test_crop_normalisation(self):
        self.assertEqual(vp.normalize_crop(None), (0.0, 0.0, 1.0, 1.0))
        x, y, w, h = vp.normalize_crop({"x": 0.9, "y": 0.9, "w": 0.5, "h": 0.5})
        self.assertAlmostEqual(x + w, 1.0)
        self.assertAlmostEqual(y + h, 1.0)  # clamped inside the frame
        x, y, w, h = vp.normalize_crop({"zoom": 2, "offsetX": -1, "offsetY": 5})
        self.assertAlmostEqual(w, 0.5)
        self.assertEqual(x, 0.0)
        self.assertAlmostEqual(y, 0.5)  # offset clamped to +1

    def test_render_command(self):
        from backend.app.gpu_config import CPU_ENCODER
        cmd = vp.build_render_command("ffmpeg", "in.mp4", "out.mp4", 5, 20, "g[vout]", CPU_ENCODER, True)
        self.assertIn("libx264", cmd)
        self.assertEqual(cmd[cmd.index("-ss") + 1], "5.000")
        self.assertIn("cfr", cmd)
        self.assertIn("+faststart", cmd)
        self.assertIn("aresample=48000:async=1:first_pts=0", cmd)
        no_audio = vp.build_render_command("ffmpeg", "in.mp4", "out.mp4", 0, 5, "g[vout]", CPU_ENCODER, False)
        self.assertIn("-an", no_audio)

    def test_additional_layouts_smart_pip_fullscreen_custom(self):
        # 1. Smart vertical crop with dynamic subject trajectory
        kfs = [(0.0, 0.25, 0.5), (2.0, 0.50, 0.5), (4.0, 0.75, 0.5)]
        g_smart = vp.build_filter_graph("smart_crop", gameplay_crop={"zoom": 1.1, "offsetX": 0.1}, keyframes=kfs)
        self.assertIn("(iw-ow)*", g_smart)
        self.assertIn("gte(t,", g_smart)
        self.assertTrue(g_smart.endswith("[vout]"))

        # 2. Full-screen video
        g_full = vp.build_filter_graph("fullscreen", gameplay_crop={"offsetY": 10})
        self.assertIn("boxblur=25:5", g_full)
        self.assertIn("scale=1080:-2", g_full)
        self.assertIn("overlay=(W-w)/2:", g_full)

        # 3. Facecam picture-in-picture
        g_pip = vp.build_filter_graph("gameplay_pip", facecam_crop={"pipScale": 30, "pipCorner": "top_left"})
        self.assertIn("overlay=36:72", g_pip)
        self.assertIn("pad=", g_pip)

        # 4. Custom crop (single & split)
        g_cust = vp.build_filter_graph("custom", gameplay_crop={"x": 0.1, "y": 0.1, "w": 0.6, "h": 0.8})
        self.assertIn("scale=1080:1920", g_cust)
        g_cust_split = vp.build_filter_graph("custom", facecam_crop={"split": True, "heightPercent": 40})
        self.assertIn("vstack=inputs=2", g_cust_split)

    def test_real_video_all_layouts_composition_and_smart_crop(self):
        import shutil
        import subprocess
        import tempfile
        from backend.app.export import render_clip
        from backend.app.gpu_config import find_ffmpeg

        ff = find_ffmpeg()
        self.assertIsNotNone(ff)
        tmp = Path(tempfile.mkdtemp(prefix="vc_phase6_"))
        try:
            src = tmp / "moving_subject.mp4"
            # Generate 3.5s 1920x1080 video with a bright moving subject via overlay(x=100+t*420) + 48kHz audio tone
            subprocess.run([
                ff, "-y", "-loglevel", "error",
                "-f", "lavfi", "-i", "color=c=0x101420:s=1920x1080:r=30:d=3.5",
                "-f", "lavfi", "-i", "color=c=yellow:s=320x320:r=30:d=3.5",
                "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=48000:duration=3.5",
                "-filter_complex", "[0:v][1:v]overlay=x='100+t*420':y=380[v]",
                "-map", "[v]", "-map", "2:a",
                "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", str(src)
            ], check=True)

            # Verify OpenCV subject analysis tracks the moving subject and is truthful about single-source
            comp = vp.analyze_video_composition(str(src), 0.0, 3.2, num_samples=5)
            self.assertEqual(comp["source_streams"], 1)
            self.assertTrue(comp["single_source_reframed"])
            kfs = comp["subject_keyframes"]
            self.assertGreaterEqual(len(kfs), 3)
            # Subject moves from left (x~200) toward right (x~1480), so cx increases over time
            self.assertGreater(kfs[-1][1], kfs[0][1] + 0.05)

            # Render and validate all 5 Phase 6 layouts on the real video
            layouts_to_test = [
                ("facecam_gameplay", {"zoom": 1.2, "offsetY": -0.2}, {"zoom": 1.0, "offsetY": 0.0}),
                ("smart_crop", {}, {"zoom": 1.05, "offsetX": 0.0}),
                ("fullscreen", {}, {"zoom": 1.0, "offsetY": 0.1}),
                ("gameplay_pip", {"pipScale": 28, "pipCorner": "bottom_right"}, {"zoom": 1.0}),
                ("custom", {}, {"x": 0.15, "y": 0.05, "w": 0.7, "h": 0.9}),
            ]
            for layout_name, fc_crop, gp_crop in layouts_to_test:
                out_mp4 = tmp / f"out_{layout_name}.mp4"
                res = render_clip(
                    str(src), out_mp4, 0.2, 3.2, has_audio=True,
                    layout=layout_name, facecam_crop=fc_crop, gameplay_crop=gp_crop,
                    burn_subtitles=False,
                )
                self.assertTrue(out_mp4.exists(), f"{layout_name} output missing")
                self.assertEqual(res["resolution"], "1080x1920")
                self.assertTrue(res["sync_report"]["passed"], f"{layout_name} validation failed: {res['sync_report']}")
                self.assertEqual(res["composition"]["layout"], layout_name)
                self.assertEqual(res["composition"]["source_streams"], 1)
                self.assertTrue(res["composition"]["single_source_reframed"])
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


SEGS = [
    {"start": 0.0, "end": 6.0, "text": "So today we are just chilling and talking about the weather.", "words": []},
    {"start": 6.5, "end": 12.0, "text": "Oh my god, that was insane! No way, did you see that clutch?", "words": []},
    {"start": 12.5, "end": 19.0, "text": "Unbelievable! Let's go, we actually won! Holy cow!", "words": []},
    {"start": 40.0, "end": 47.0, "text": "And then I made some tea and sat down quietly.", "words": []},
    {"start": 47.5, "end": 56.0, "text": "The tea was warm and the room was calm.", "words": []},
]


class TestClipDetector(unittest.TestCase):
    def test_ranks_exciting_segment_first_and_is_deterministic(self):
        a = detect_clips(SEGS, 60, min_len=10, max_len=30, target_len=15, max_clips=3)
        b = detect_clips(SEGS, 60, min_len=10, max_len=30, target_len=15, max_clips=3)
        self.assertEqual([c.to_dict() for c in a], [c.to_dict() for c in b])
        self.assertTrue(a)
        self.assertLess(a[0].start, 20)  # excited section, not the calm tea section
        self.assertGreater(a[0].score, a[-1].score - 0.001)
        self.assertTrue("excitement peak" in a[0].reason or "High-energy" in a[0].reason or a[0].category == "hype")

    def test_bounds_and_overlap(self):
        clips = detect_clips(SEGS, 60, min_len=10, max_len=30, max_clips=5)
        for c in clips:
            self.assertGreaterEqual(c.start, 0)
            self.assertLessEqual(c.end, 60)
            self.assertLessEqual(c.duration, 31)
        for i, a in enumerate(clips):
            for b in clips[i + 1:]:
                inter = max(0, min(a.end, b.end) - max(a.start, b.start))
                self.assertLessEqual(inter / min(a.duration, b.duration), 0.25)

    def test_no_transcript_and_no_audio_returns_nothing(self):
        self.assertEqual(detect_clips([], 60), [])

    def test_energy_only_is_labelled_honestly(self):
        energy = [0.01] * 120 + [0.5] * 60 + [0.01] * 60
        clips = detect_clips([], 120, energy, min_len=10, target_len=20, max_clips=1)
        self.assertEqual(len(clips), 1)
        self.assertEqual(clips[0].category, "hype")
        self.assertIn("no speech", clips[0].reason)
        self.assertTrue(55 <= clips[0].start + 10 <= 95)

    def test_selects_best_two_moments(self):
        clips = detect_clips(SEGS, 60, min_len=10, max_len=30, max_clips=4)
        if len(clips) >= 2:
            self.assertTrue(clips[0].selected)
            self.assertTrue(clips[1].selected)
            if len(clips) > 2:
                self.assertFalse(clips[2].selected)

    def test_categories_classification(self):
        funny_segs = [
            {"start": 0.0, "end": 12.0, "text": "That is so hilarious! We were cracking up laughing haha lol!", "words": []},
            {"start": 12.1, "end": 22.0, "text": "What a silly ridiculous joke, best comedy fail ever.", "words": []},
        ]
        c_funny = detect_clips(funny_segs, 25, min_len=10, max_len=24, target_len=15)
        self.assertTrue(c_funny)
        self.assertEqual(c_funny[0].category, "funny")

        story_segs = [
            {"start": 0.0, "end": 11.0, "text": "So basically one time years ago back then this true story happened.", "words": []},
            {"start": 11.1, "end": 22.0, "text": "And then in the end it was a complete adventure long story short.", "words": []},
        ]
        c_story = detect_clips(story_segs, 25, min_len=10, max_len=24, target_len=15)
        self.assertTrue(c_story)
        self.assertEqual(c_story[0].category, "story")

        expl_segs = [
            {"start": 0.0, "end": 11.0, "text": "Here is the tutorial on how to understand the secret technique step by step.", "words": []},
            {"start": 11.1, "end": 22.0, "text": "The key is to follow this important strategy and rule because it works.", "words": []},
        ]
        c_expl = detect_clips(expl_segs, 25, min_len=10, max_len=24, target_len=15)
        self.assertTrue(c_expl)
        self.assertEqual(c_expl[0].category, "explanation")


class TestSubtitles(unittest.TestCase):
    WORDS = [{"word": w, "start": 10 + i * 0.4, "end": 10.35 + i * 0.4}
             for i, w in enumerate("No way, that was insane! Let's go".split())]

    def test_collect_words_shifts_to_clip_time(self):
        seg = [{"start": 10, "end": 13, "text": "x", "words": self.WORDS}]
        w = collect_words(seg, 9.0, 14.0)
        self.assertAlmostEqual(w[0]["start"], 1.0)
        self.assertEqual(len(w), len(self.WORDS))
        self.assertEqual(collect_words(seg, 20, 30), [])

    def test_ass_has_one_event_per_word_with_highlight(self):
        words = collect_words([{"start": 10, "end": 13, "text": "x", "words": self.WORDS}], 10, 14)
        ass = generate_ass(words, SubtitleStyle(highlight="#00E5FF"))
        events = [l for l in ass.splitlines() if l.startswith("Dialogue:")]
        self.assertEqual(len(events), len(words))
        self.assertIn("PlayResX: 1080", ass)
        self.assertIn("&H00FFE500&", ass)  # #00E5FF in ASS BGR order
        self.assertIn("NO", events[0])

    def test_chunking_limits(self):
        chunks = chunk_words(self.WORDS, SubtitleStyle(max_words=3))
        self.assertTrue(all(len(c) <= 3 for c in chunks))
        self.assertEqual(sum(len(c) for c in chunks), len(self.WORDS))

    def test_srt_and_escaping(self):
        srt = generate_srt([{"word": "hi{x}", "start": 0.0, "end": 0.5}])
        self.assertIn("00:00:00,000 --> 00:00:00,500", srt)
        ass = generate_ass([{"word": "a{b}\\c", "start": 0, "end": 1}])
        self.assertNotIn("a{b}", ass)

    def test_style_from_frontend_camel_case(self):
        st = SubtitleStyle.from_dict({"fontSize": "90", "highlightColor": "#FF0000", "bogus": 1, "maxWords": None})
        self.assertEqual(st.font_size, 90)
        self.assertEqual(st.highlight, "#FF0000")
        self.assertEqual(st.max_words, 4)

    def test_all_five_presets_generation(self):
        presets = ["classic_white", "yellow_highlight", "bold_creator", "neon_glow", "minimal_captions"]
        words = collect_words([{"start": 10, "end": 13, "text": "x", "words": self.WORDS}], 10, 14)
        for p in presets:
            st = SubtitleStyle.from_dict({"preset": p})
            ass = generate_ass(words, st)
            self.assertIn("PlayResX: 1080", ass)
            self.assertIn("PlayResY: 1920", ass)
            self.assertIn("Style: Default", ass)
            events = [l for l in ass.splitlines() if l.startswith("Dialogue:")]
            self.assertEqual(len(events), len(words))

    def test_safe_margins_and_position_y(self):
        words = collect_words([{"start": 10, "end": 13, "text": "x", "words": self.WORDS}], 10, 14)
        # Safe side margins = 80px
        ass_bottom = generate_ass(words, SubtitleStyle.from_dict({"position": "bottom"}))
        self.assertIn(",80,80,340,1", ass_bottom)

        ass_top = generate_ass(words, SubtitleStyle.from_dict({"position": "top"}))
        self.assertIn(",80,80,280,1", ass_top)

        # Custom position_y (e.g. 76% from top -> 1920*(1-0.76) = 461px from bottom)
        ass_custom = generate_ass(words, SubtitleStyle.from_dict({"positionY": 76}))
        self.assertIn(",80,80,461,1", ass_custom)

    def test_word_animations_and_boxed_background(self):
        words = collect_words([{"start": 10, "end": 13, "text": "x", "words": self.WORDS}], 10, 14)
        # Bounce animation
        ass_bounce = generate_ass(words, SubtitleStyle.from_dict({"animation": "bounce"}))
        self.assertIn("\\t(0,80,", ass_bounce)
        self.assertIn("\\t(80,160,", ass_bounce)

        # Fade animation
        ass_fade = generate_ass(words, SubtitleStyle.from_dict({"animation": "fade"}))
        self.assertIn("\\alpha&H88&", ass_fade)

        # Boxed background (BorderStyle=3)
        ass_box = generate_ass(words, SubtitleStyle.from_dict({"hasBackground": True}))
        self.assertIn(",0,0,3,14.0,0.0,", ass_box)


class TestValidateOutput(unittest.TestCase):
    def test_missing_file_fails_cleanly(self):
        r = validate_output(Path("definitely_missing.mp4"), 10, True)
        self.assertFalse(r["passed"])

    def test_gpu_detection_and_encoder_configuration(self):
        from backend.app.gpu_config import CPU_ENCODER, EncoderInfo, configure_encoder, detect_encoders

        enc_info = detect_encoders()
        self.assertTrue(enc_info["ffmpeg"])
        self.assertTrue(enc_info["ffprobe"])
        vendors = enc_info.get("vendors", {})
        for vkey in ("nvenc", "qsv", "amf", "cpu"):
            self.assertIn(vkey, vendors)
            self.assertIn("available", vendors[vkey])
        self.assertTrue(vendors["cpu"]["available"])

        # Test bitrate & quality configuration for NVENC, QSV, AMF, and CPU
        nv = configure_encoder(EncoderInfo("h264_nvenc", "hardware", "NVENC"), bitrate_kbps=6000, quality="high")
        self.assertIn("6000k", nv.args)
        self.assertIn("p5", nv.args)

        qsv = configure_encoder(EncoderInfo("h264_qsv", "hardware", "QSV"), bitrate_kbps=5000, quality="balanced")
        self.assertIn("5000k", qsv.args)

        amf = configure_encoder(EncoderInfo("h264_amf", "hardware", "AMF"), bitrate_kbps=7000, quality="fast")
        self.assertIn("7000k", amf.args)
        self.assertIn("speed", amf.args)

        cpu = configure_encoder(CPU_ENCODER, bitrate_kbps=4500, quality="high")
        self.assertIn("-crf", cpu.args)
        self.assertIn("18", cpu.args)
        self.assertIn("5625k", cpu.args)

    def test_cpu_fallback_and_configurable_fps_bitrate_export(self):
        import shutil
        import subprocess
        import tempfile
        from backend.app.export import render_clip
        from backend.app.gpu_config import find_ffmpeg

        ff = find_ffmpeg()
        tmp = Path(tempfile.mkdtemp(prefix="vc_phase8_"))
        try:
            src = tmp / "source_clip.mp4"
            subprocess.run([
                ff, "-y", "-loglevel", "error",
                "-f", "lavfi", "-i", "testsrc2=s=1280x720:r=30:d=3.5",
                "-f", "lavfi", "-i", "sine=frequency=520:sample_rate=48000:duration=3.5",
                "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", str(src)
            ], check=True)

            out_cpu = tmp / "exported_cpu_24fps.mp4"
            res = render_clip(
                str(src), out_cpu, 0.2, 3.2, has_audio=True,
                layout="facecam_gameplay", prefer_hardware=False,
                fps=24, bitrate_kbps=3500, quality="fast",
                segments=[{"start": 0.3, "end": 2.9, "text": "Testing CPU export", "words": [
                    {"word": "Testing", "start": 0.3, "end": 1.1},
                    {"word": "CPU", "start": 1.1, "end": 1.9},
                    {"word": "export", "start": 1.9, "end": 2.9},
                ]}],
            )
            self.assertTrue(out_cpu.exists())
            self.assertFalse(res["gpu_accelerated"])  # Never claim GPU when CPU was used
            self.assertEqual(res["encoder"]["name"], "libx264")
            self.assertEqual(res["codec"], "h264")
            self.assertEqual(res["audio_codec"], "aac")
            self.assertEqual(res["resolution"], "1080x1920")
            self.assertAlmostEqual(res["fps"], 24.0, delta=0.5)
            self.assertTrue(res["sync_report"]["passed"])
            self.assertTrue(res["sync_report"]["checks"].get("codec_aac"))
            self.assertTrue(res["sync_report"]["checks"].get("fps_matches"))
            # Verify temp files were safely cleaned up
            self.assertFalse(any(p.name.startswith("render_") or p.name.endswith(".part.mp4") for p in tmp.iterdir()))
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


class TestTranscriptionUnits(unittest.TestCase):
    def test_whisper_availability(self):
        from backend.app.transcription import whisper_available
        self.assertTrue(whisper_available())

    def test_transcription_result_backward_compatibility(self):
        from backend.app.transcription import TranscriptionResult
        segs = [{"start": 0.0, "end": 2.5, "text": "Hello world", "words": [{"word": "Hello", "start": 0.0, "end": 1.0, "probability": 0.99}]}]
        res = TranscriptionResult(segs, language="en", language_probability=0.985, duration=2.5, model_name="tiny")
        # List behavior
        self.assertIsInstance(res, list)
        self.assertEqual(len(res), 1)
        self.assertEqual(res[0]["text"], "Hello world")
        # Metadata access
        self.assertEqual(res.language, "en")
        self.assertEqual(res.language_probability, 0.985)
        self.assertEqual(res.model_name, "tiny")
        self.assertEqual(res.duration, 2.5)
        self.assertEqual(res.get("language"), "en")
        d = res.to_dict()
        self.assertEqual(d["language"], "en")
        self.assertEqual(len(d["segments"]), 1)

    def test_load_wav_float32_rejects_invalid_wav(self):
        import io, wave
        from backend.app.transcription import load_wav_float32, TranscriptionError
        buf = io.BytesIO()
        with wave.open(buf, "wb") as wf:
            wf.setnchannels(2)  # stereo (invalid, must be mono 16kHz)
            wf.setsampwidth(2)
            wf.setframerate(44100)
            wf.writeframes(b"\x00" * 4410)
        buf.seek(0)
        import tempfile
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
            f.write(buf.getvalue())
            tmp_path = f.name
        try:
            with self.assertRaises(TranscriptionError):
                load_wav_float32(tmp_path)
        finally:
            Path(tmp_path).unlink(missing_ok=True)


class TestShortsMetadataGenerator(unittest.TestCase):
    def test_generate_rule_based_metadata_structure(self):
        from backend.app.metadata_generator import generate_shorts_metadata
        transcript = (
            "Look at this right now! Are you actually seeing what is happening here?! "
            "There is literally no way this play works out. If we clutch this round it is over!"
        )
        meta = generate_shorts_metadata(
            transcript_text=transcript,
            duration=10.4,
            start_time=2.0,
            end_time=12.4,
            category="hype",
            use_ai_api=False,
        )

        self.assertIn("titles", meta)
        self.assertEqual(len(meta["titles"]), 3)
        for t in meta["titles"]:
            self.assertIsInstance(t, str)
            self.assertGreater(len(t), 3)
            self.assertLessEqual(len(t), 60)

        self.assertEqual(meta["recommended_title"], meta["titles"][0])

        self.assertIn("description", meta)
        self.assertIn("2.0s - 12.4s", meta["description"])
        self.assertIn("9:16 vertical short", meta["description"])

        self.assertIn("hashtags", meta)
        self.assertGreaterEqual(len(meta["hashtags"]), 4)
        self.assertIn("#shorts", meta["hashtags"])
        self.assertIn("#viral", meta["hashtags"])
        for h in meta["hashtags"]:
            self.assertTrue(h.startswith("#"))

        self.assertIn("thumbnail_text", meta)
        self.assertTrue(meta["thumbnail_text"].isupper() or any(c.isupper() for c in meta["thumbnail_text"]))
        self.assertLessEqual(len(meta["thumbnail_text"]), 35)

        self.assertIn("thumbnail_timestamp", meta)
        self.assertGreaterEqual(meta["thumbnail_timestamp"], 2.0)
        self.assertLessEqual(meta["thumbnail_timestamp"], 12.4)

    def test_truthful_grounding_categories(self):
        from backend.app.metadata_generator import generate_rule_based_metadata
        # Funny
        f_meta = generate_rule_based_metadata(
            "Haha that was so hilarious! I cannot believe he just tripped over nothing.",
            duration=8.0, start_time=5.0, end_time=13.0, category="funny"
        )
        self.assertIn("🤣", f_meta["titles"][0])
        self.assertIn("#comedy", f_meta["hashtags"])

        # Surprise
        s_meta = generate_rule_based_metadata(
            "Wait, what just happened? Did you see that secret room open up?!",
            duration=9.0, start_time=10.0, end_time=19.0, category="surprise"
        )
        self.assertIn("🤯", s_meta["titles"][0])
        self.assertIn("#plotTwist", s_meta["hashtags"])

    def test_word_timestamp_energy_focus(self):
        from backend.app.metadata_generator import generate_shorts_metadata
        words = [
            {"word": "Look", "start": 3.0, "end": 3.4},
            {"word": "at", "start": 3.5, "end": 3.6},
            {"word": "this", "start": 3.7, "end": 3.9},
            {"word": "insane!", "start": 7.5, "end": 8.0},
        ]
        meta = generate_shorts_metadata(
            transcript_text="Look at this insane!",
            duration=6.0,
            start_time=3.0,
            end_time=9.0,
            category="hype",
            words=words,
            use_ai_api=False,
        )
        self.assertEqual(meta["thumbnail_timestamp"], 7.5)

    def test_ai_fallback_on_invalid_keys(self):
        from backend.app.metadata_generator import generate_shorts_metadata
        # Passing invalid keys should never crash, but fall back seamlessly
        meta = generate_shorts_metadata(
            transcript_text="Quick tutorial on how to configure your video settings properly.",
            duration=12.0,
            start_time=0.0,
            end_time=12.0,
            category="explanation",
            gemini_api_key="invalid_test_key_12345",
            openai_api_key="sk-invalidtestkey12345",
            use_ai_api=True,
        )
        self.assertEqual(len(meta["titles"]), 3)
        self.assertIn("#howTo", meta["hashtags"])
        self.assertGreaterEqual(meta["thumbnail_timestamp"], 0.0)
        self.assertLessEqual(meta["thumbnail_timestamp"], 12.0)


class TestWindowsPreparationAndCleanup(unittest.TestCase):
    def test_preflight_sync_preserves_user_videos_and_exports(self):
        import os
        import shutil
        import sqlite3
        import tempfile
        import time
        from backend.app.config import settings
        from backend.app import job_runner

        tmp_root = Path(tempfile.mkdtemp(prefix="vc_clean_test_"))
        orig_temp, orig_out, orig_db = settings.TEMP_DIR, settings.OUTPUT_DIR, settings.DB_PATH
        try:
            settings.TEMP_DIR = str(tmp_root / "temp")
            settings.OUTPUT_DIR = str(tmp_root / "output")
            settings.DB_PATH = str(tmp_root / "db" / "test.db")

            # Run initial preflight to create tables
            job_runner.preflight_sync()

            # Register a real user video and a mid-flight interrupted job
            with sqlite3.connect(settings.DB_PATH) as conn:
                conn.execute(
                    "INSERT INTO videos (id, filename, source_type, file_path, file_size_mb, duration, width, height, fps, is_vfr, codec, audio_codec, status, created_at) "
                    "VALUES ('vid_keep', 'user.mp4', 'local', 'x', 5.0, 10.0, 1920, 1080, 30.0, 0, 'h264', 'aac', 'ready', CURRENT_TIMESTAMP)"
                )
                conn.execute(
                    "INSERT INTO jobs (id, video_id, status, progress, current_stage, settings, created_at, updated_at) "
                    "VALUES ('job_mid', 'vid_keep', 'transcribing', 45, 'Transcribing', '{}', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
                )
                conn.commit()

            # Create user video file & exported MP4 (MUST NOT BE DELETED)
            user_vid = Path(settings.TEMP_DIR) / "vid_keep" / "source.mp4"
            user_vid.parent.mkdir(parents=True, exist_ok=True)
            user_vid.write_bytes(b"real_user_video")

            exported_mp4 = Path(settings.OUTPUT_DIR) / "clip_keep" / " viral_short.mp4"
            exported_mp4.parent.mkdir(parents=True, exist_ok=True)
            exported_mp4.write_bytes(b"real_exported_mp4")

            # Create stale temporary artifacts (SHOULD BE CLEANED)
            work_dir = Path(settings.TEMP_DIR) / "vid_keep" / "_work"
            work_dir.mkdir(parents=True, exist_ok=True)
            (work_dir / "audio.wav").write_bytes(b"scratch")

            orphan_dir = Path(settings.TEMP_DIR) / "vid_orphan"
            orphan_dir.mkdir(parents=True, exist_ok=True)

            part_mp4 = Path(settings.OUTPUT_DIR) / "clip_keep" / "temp.part.mp4"
            part_mp4.write_bytes(b"partial")

            old_t = time.time() - 7200
            for p in (user_vid, user_vid.parent, exported_mp4, work_dir, orphan_dir, part_mp4):
                os.utime(p, (old_t, old_t))

            res = job_runner.preflight_sync()
            self.assertEqual(res["recovered"]["jobs"], 1)
            self.assertEqual(res["cleaned"]["orphan_dirs"], 1)
            self.assertEqual(res["cleaned"]["work_dirs"], 1)
            self.assertEqual(res["cleaned"]["partial_files"], 1)

            # Verify user files are untouched
            self.assertTrue(user_vid.exists())
            self.assertTrue(exported_mp4.exists())
            # Verify temporary leftovers are gone
            self.assertFalse(work_dir.exists())
            self.assertFalse(orphan_dir.exists())
            self.assertFalse(part_mp4.exists())
        finally:
            settings.TEMP_DIR, settings.OUTPUT_DIR, settings.DB_PATH = orig_temp, orig_out, orig_db
            shutil.rmtree(tmp_root, ignore_errors=True)

    def test_env_example_and_gitignore_protect_credentials(self):
        root = Path(__file__).resolve().parents[3]
        env_ex = (root / ".env.example").read_text(encoding="utf-8")
        gitignore = (root / ".gitignore").read_text(encoding="utf-8")
        self.assertIn("GEMINI_API_KEY=", env_ex)
        self.assertIn("OPENAI_API_KEY=", env_ex)
        # Ensure no actual key values follow GEMINI_API_KEY= or OPENAI_API_KEY= in .env.example
        for line in env_ex.splitlines():
            if line.startswith(("GEMINI_API_KEY=", "OPENAI_API_KEY=")):
                self.assertEqual(line.split("=", 1)[1].strip(), "")
        self.assertIn(".env", gitignore)
        self.assertTrue((root / "setup.bat").exists())
        self.assertTrue((root / "start.bat").exists())


class TestHighPerformanceImportEngine(unittest.TestCase):
    def test_disk_space_check_raises_507(self):
        from backend.app import video_import as vi
        self.assertGreater(vi.check_disk_space(1024), 0)
        with self.assertRaises(vi.ImportFailure) as ctx:
            vi.check_disk_space(10 ** 16)  # 10 PB required -> 507 Insufficient Storage
        self.assertEqual(ctx.exception.status, 507)

    def test_chunked_upload_resume_deduplication_checksum_and_cancel(self):
        import hashlib
        import shutil
        import tempfile
        from backend.app.config import settings
        from backend.app import video_import as vi

        tmp_dir = Path(tempfile.mkdtemp(prefix="vc_chunk_unit_"))
        orig_temp = settings.TEMP_DIR
        settings.TEMP_DIR = str(tmp_dir)
        try:
            c0 = b"A" * (256 * 1024)
            c1 = b"B" * (256 * 1024)
            total_b = len(c0) + len(c1)
            fp = "unit_stream.mp4:524288"

            s1 = vi.init_chunked_upload("unit_stream.mp4", total_b, chunk_size=256 * 1024, fingerprint=fp)
            uid = s1["upload_id"]
            self.assertFalse(s1["resumed"])
            self.assertEqual(s1["total_chunks"], 2)

            # Reject bad SHA-256
            with self.assertRaises(vi.ImportFailure) as bad_sha:
                vi.write_upload_chunk(uid, 0, c0, expected_sha256="0" * 64)
            self.assertEqual(bad_sha.exception.status, 422)

            # Accept valid chunk 0
            sha0 = hashlib.sha256(c0).hexdigest()
            r0 = vi.write_upload_chunk(uid, 0, c0, expected_sha256=sha0)
            self.assertFalse(r0["duplicate"])
            self.assertEqual(r0["chunks_received"], 1)

            # Duplicate chunk 0 is idempotent
            r0_dup = vi.write_upload_chunk(uid, 0, c0, expected_sha256=sha0)
            self.assertTrue(r0_dup["duplicate"])
            self.assertEqual(r0_dup["chunks_received"], 1)

            # Resume via fingerprint returns existing upload_id and received chunk 0
            s_resumed = vi.init_chunked_upload("unit_stream.mp4", total_b, chunk_size=256 * 1024, fingerprint=fp)
            self.assertTrue(s_resumed["resumed"])
            self.assertEqual(s_resumed["upload_id"], uid)
            self.assertIn("0", s_resumed["received_chunks"])

            # Cancel removes .uploading.part and session metadata
            part_file = Path(s1["part_path"])
            self.assertTrue(part_file.exists())
            c_res = vi.cancel_chunked_upload(uid)
            self.assertEqual(c_res["status"], "CANCELLED")
            self.assertFalse(part_file.exists())
        finally:
            settings.TEMP_DIR = orig_temp
            shutil.rmtree(tmp_dir, ignore_errors=True)

    def test_default_16mb_chunk_size_and_whisper_hardware_and_windowed_wav(self):
        import io
        import tempfile
        import wave
        from backend.app import transcription, video_import as vi, video_processor as vp

        self.assertEqual(vi.DEFAULT_UPLOAD_CHUNK_SIZE, 16 * 1024 * 1024)
        hw = transcription.detect_whisper_hardware("cpu", "int8")
        self.assertEqual(hw["device"], "cpu")
        self.assertEqual(hw["compute_type"], "int8")
        self.assertFalse(hw["gpu_accelerated"])
        self.assertGreaterEqual(hw["cpu_threads"], 2)

        # Create a 4-second 16 kHz mono WAV file and verify windowed reading + audio validation
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tf:
            wav_p = tf.name
        try:
            with wave.open(wav_p, "wb") as wf:
                wf.setnchannels(1)
                wf.setsampwidth(2)
                wf.setframerate(16000)
                wf.writeframes(b"\x10\x00" * (16000 * 4))
            self.assertTrue(vp.validate_extracted_wav(wav_p, 4.0))
            self.assertAlmostEqual(transcription.get_wav_duration(wav_p), 4.0, places=2)
            win = transcription.read_wav_window_float32(wav_p, 1.0, 1.5)
            self.assertEqual(win.size, 16000 * 1.5)
        finally:
            Path(wav_p).unlink(missing_ok=True)



class TestMultilingualSupport(unittest.TestCase):
    def test_language_normalization(self):
        from backend.app.translation import normalize_language_code

        self.assertEqual(normalize_language_code("malayalam"), "ml")
        self.assertEqual(normalize_language_code("ML"), "ml")
        self.assertEqual(normalize_language_code("ml-IN"), "ml")
        self.assertEqual(normalize_language_code("hindi"), "hi")
        self.assertEqual(normalize_language_code("HI"), "hi")
        self.assertEqual(normalize_language_code("tamil"), "ta")
        self.assertEqual(normalize_language_code("arabic"), "ar")
        self.assertEqual(normalize_language_code("spanish"), "es")
        self.assertEqual(normalize_language_code("french"), "fr")
        self.assertEqual(normalize_language_code("german"), "de")
        self.assertEqual(normalize_language_code("japanese"), "ja")
        self.assertEqual(normalize_language_code("korean"), "ko")
        self.assertEqual(normalize_language_code("auto"), "auto")
        self.assertEqual(normalize_language_code(None), "auto")
        self.assertEqual(normalize_language_code(""), "auto")

    def test_script_detection_and_font_resolution(self):
        from backend.app.translation import detect_script, resolve_font_for_script

        # Malayalam script
        ml_text = "നമസ്കാരം സ്വാഗതം"
        self.assertEqual(detect_script(ml_text), "malayalam")
        self.assertEqual(resolve_font_for_script(ml_text), "Nirmala UI")
        self.assertEqual(resolve_font_for_script(ml_text, requested_font="Impact"), "Nirmala UI")

        # Devanagari script
        hi_text = "नमस्ते आप कैसे हैं"
        self.assertEqual(detect_script(hi_text), "devanagari")
        self.assertEqual(resolve_font_for_script(hi_text), "Nirmala UI")

        # Tamil script
        ta_text = "வணக்கம் நண்பர்களே"
        self.assertEqual(detect_script(ta_text), "tamil")
        self.assertEqual(resolve_font_for_script(ta_text), "Nirmala UI")

        # Arabic script
        ar_text = "مرحبا بكم"
        self.assertEqual(detect_script(ar_text), "arabic")
        self.assertEqual(resolve_font_for_script(ar_text), "Segoe UI")

        # CJK script (Japanese)
        ja_text = "こんにちは世界"
        self.assertEqual(detect_script(ja_text), "cjk")
        self.assertEqual(resolve_font_for_script(ja_text), "MS Gothic")

        # Korean script
        ko_text = "안녕하세요"
        self.assertEqual(detect_script(ko_text), "korean")
        self.assertEqual(resolve_font_for_script(ko_text), "Malgun Gothic")

        # Latin script
        en_text = "Hello world"
        self.assertEqual(detect_script(en_text), "latin")
        self.assertEqual(resolve_font_for_script(en_text, requested_font="Montserrat"), "Montserrat")

    def test_ass_generation_with_malayalam_script(self):
        from backend.app.subtitle_generator import SubtitleStyle, generate_ass

        words = [
            {"word": "നമസ്കാരം", "start": 0.5, "end": 1.2, "probability": 0.99},
            {"word": "സുഹൃത്തുക്കളെ", "start": 1.3, "end": 2.1, "probability": 0.98},
        ]
        style = SubtitleStyle.from_dict({
            "preset": "bold_creator",
            "language": "ml",
            "font_family": "Nirmala UI",
            "uppercase": True,  # should be safe for non-Latin
        })

        ass_content = generate_ass(words, style)
        # Font should resolve to Nirmala UI for Malayalam text
        self.assertIn("Nirmala UI", ass_content)
        # Malayalam characters must be intact in the subtitle stream
        self.assertIn("നമസ്കാരം", ass_content)
        self.assertIn("സുഹൃത്തുക്കളെ", ass_content)

    def test_multilingual_keywords_in_clip_detector(self):
        from backend.app.clip_detector import HYPE_WORDS, _seg_signals, detect_clips

        # Malayalam hype words
        self.assertIn("പൊളിച്ചു", HYPE_WORDS)
        self.assertIn("അടിപൊളി", HYPE_WORDS)
        # Hindi hype words
        self.assertIn("धमाका", HYPE_WORDS)
        self.assertIn("खतरनाक", HYPE_WORDS)
        # Tamil hype words
        self.assertIn("அசத்தல்", HYPE_WORDS)

        # Verify _seg_signals detects Malayalam signals
        seg_ml = {"text": "ഇത് ശരിക്കും അടിപൊളി മാസ്സ് മൊമെന്റ് ആണ്!", "start": 10.0, "end": 15.0}
        signals = _seg_signals(seg_ml)
        self.assertGreater(signals["hype"], 0)

        # Verify detect_clips prioritizes high-energy multilingual segment
        segs = [
            {"text": "ഇന്ന് നമ്മൾ വെറുതെ ഇരിക്കുന്നു.", "start": 0.0, "end": 8.0, "words": []},
            {"text": "അടിപൊളി! പൊളിച്ചു! നാം ജയിച്ചു!", "start": 10.0, "end": 18.0, "words": []},
        ]
        clips = detect_clips(segs, 25.0, min_len=6, max_len=12)
        self.assertTrue(len(clips) > 0)
        self.assertGreaterEqual(clips[0].start, 8.0)

    def test_offline_translation_and_timestamp_distribution(self):
        from backend.app.translation import translate_subtitle_segments

        input_segments = [
            {
                "start": 2.0,
                "end": 5.0,
                "text": "hello welcome",
                "words": [
                    {"word": "hello", "start": 2.0, "end": 3.0},
                    {"word": "welcome", "start": 3.5, "end": 4.8},
                ],
            }
        ]

        trans_segs, trans_words = translate_subtitle_segments(input_segments, target_lang="ml", source_lang="en")
        self.assertEqual(len(trans_segs), 1)
        self.assertGreater(len(trans_words), 0)

        # Monotonicity & bounds check
        for w in trans_words:
            self.assertGreaterEqual(w["start"], 2.0)
            self.assertLessEqual(w["end"], 5.01)
            self.assertLessEqual(w["start"], w["end"])

    def test_malayalam_speech_transcription_and_language_detection(self):
        from backend.app.transcription import transcribe_audio, whisper_available
        from pathlib import Path

        fixture_path = Path("backend/tests/fixtures/malayalam_speech.wav")
        if not fixture_path.exists() or not whisper_available():
            self.skipTest("Malayalam audio fixture or faster-whisper not available")

        # Transcribe first 5 seconds with auto language detection
        result = transcribe_audio(
            str(fixture_path),
            duration=5.0,
            language="auto",
            model_name="base",
            device="cpu",
            compute_type="int8",
        )
        self.assertEqual(result.language, "ml")
        self.assertGreaterEqual(result.language_probability, 0.8)
        self.assertGreater(len(result), 0)


    def test_window_boundaries_do_not_lose_or_duplicate_speech(self):
        from backend.app.transcription import transcribe_audio, whisper_available

        import tempfile
        import wave

        src = Path("backend/tests/fixtures/malayalam_speech.wav")
        if not src.exists() or not whisper_available():
            self.skipTest("speech fixture or faster-whisper unavailable")
        tmp = Path(tempfile.mkdtemp()) / "crop.wav"
        with wave.open(str(src), "rb") as r, wave.open(str(tmp), "wb") as w:  # first 50 s only (keeps test fast)
            w.setparams(r.getparams())
            w.writeframes(r.readframes(16000 * 50))
        wav = tmp
        try:
            whole = list(transcribe_audio(str(wav), 50.0, language="ml", model_name="base", device="cpu"))
            split = list(transcribe_audio(str(wav), 50.0, language="ml", model_name="base", device="cpu",
                                          window_seconds=20.0))
        finally:
            tmp.unlink(missing_ok=True)
        for segs in (whole, split):
            for a, b in zip(segs, segs[1:]):
                self.assertLessEqual(a["start"], b["start"])
                self.assertLessEqual(a["end"], b["start"] + 1.0)  # whisper may overlap slightly; no repeats
        w_whole = sum(len(s["words"]) for s in whole)
        w_split = sum(len(s["words"]) for s in split)
        self.assertGreater(w_whole, 10)
        self.assertLessEqual(abs(w_whole - w_split), max(5, int(w_whole * 0.25)))  # nothing lost at boundaries
        self.assertLessEqual(split[-1]["end"], 50.3)


if __name__ == "__main__":
    unittest.main()
