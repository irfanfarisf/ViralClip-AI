"""Subtitle generation from real word timestamps: ASS (animated word highlight) and SRT.

Each spoken word becomes its own Dialogue event in which that word is highlighted and
animated ("pop", "bounce", "scale_glow", "fade"), while the rest of the phrase stays
in the base colour.
Timing is relative to the clip start so the file can be burned into the trimmed video.
Safe margins are enforced for 9:16 vertical video (1080x1920) so subtitles never overlap
platform overlays or phone borders.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Dict, List, Optional
from backend.app.translation import detect_script, resolve_font_for_script

PLAY_W, PLAY_H = 1080, 1920

# Safe vertical margins for 1080x1920 short-form video:
# Bottom: 340px above bottom edge (safe from caption/sound/controls)
# Top: 280px below top edge (safe from search/top bar)
# Center: 0px offset
# Sides: 80px margin left/right
MARGIN_LEFT_RIGHT = 80
DEFAULT_MARGIN_V_BOTTOM = 340
DEFAULT_MARGIN_V_TOP = 280

PRESET_STYLES = {
    "classic_white": {
        "font": "Arial",
        "font_size": 76,
        "primary": "#FFFFFF",
        "highlight": "#FFF066",
        "outline": "#000000",
        "outline_width": 5.0,
        "shadow": 2.5,
        "animation": "pop",
        "bold": True,
        "uppercase": True,
        "has_background": False,
    },
    "yellow_highlight": {
        "font": "Arial",
        "font_size": 80,
        "primary": "#FFFFFF",
        "highlight": "#FFD700",
        "outline": "#000000",
        "outline_width": 5.5,
        "shadow": 2.5,
        "animation": "pop",
        "bold": True,
        "uppercase": True,
        "has_background": False,
    },
    "bold_creator": {
        "font": "Impact",
        "font_size": 86,
        "primary": "#FFFFFF",
        "highlight": "#22C55E",
        "outline": "#000000",
        "outline_width": 6.0,
        "shadow": 3.0,
        "animation": "bounce",
        "bold": True,
        "uppercase": True,
        "has_background": True,
        "background_color": "#000000",
        "background_alpha": 0.65,
    },
    "neon_glow": {
        "font": "Arial",
        "font_size": 76,
        "primary": "#00F0FF",
        "highlight": "#D946EF",
        "outline": "#110B29",
        "outline_width": 4.5,
        "shadow": 3.5,
        "animation": "scale_glow",
        "bold": True,
        "uppercase": True,
        "has_background": False,
    },
    "minimal_captions": {
        "font": "Arial",
        "font_size": 66,
        "primary": "#F8FAFC",
        "highlight": "#38BDF8",
        "outline": "#0F172A",
        "outline_width": 3.0,
        "shadow": 1.5,
        "animation": "fade",
        "bold": False,
        "uppercase": False,
        "has_background": False,
    },
}

# Legacy preset aliases for backward compatibility
PRESET_ALIASES = {
    "beast_yellow": "yellow_highlight",
    "clean_white": "classic_white",
    "boxed_black": "bold_creator",
    "neon_cyan": "neon_glow",
    "fire_gradient": "yellow_highlight",
}


@dataclass
class SubtitleStyle:
    preset: str = "yellow_highlight"
    font: str = "Arial"
    font_size: int = 80
    primary: str = "#FFFFFF"
    highlight: str = "#FFD700"
    outline: str = "#000000"
    outline_width: float = 5.5
    shadow: float = 2.5
    position: str = "bottom"          # bottom | center | top
    position_y: Optional[int] = None  # percentage from top: 0..100
    uppercase: bool = True
    bold: bool = True
    max_words: int = 4
    max_chunk_seconds: float = 2.0
    pop_scale: int = 120              # percent for the active word (e.g. 120%)
    animation: str = "pop"            # pop | bounce | scale_glow | fade | none
    has_background: bool = False
    background_color: str = "#000000"
    background_alpha: float = 0.65
    enabled: bool = True
    language: Optional[str] = None
    subtitle_language: Optional[str] = None
    translated_words: Optional[List[dict]] = None

    @classmethod
    def from_dict(cls, d: Optional[Dict]) -> "SubtitleStyle":
        d = dict(d or {})
        preset_name = d.get("preset", "yellow_highlight")
        preset_key = PRESET_ALIASES.get(preset_name, preset_name)
        base_vals = dict(PRESET_STYLES.get(preset_key, PRESET_STYLES["yellow_highlight"]))
        base_vals["preset"] = preset_key

        # Map camelCase from the frontend
        alias = {
            "fontFamily": "font",
            "fontSize": "font_size",
            "textColor": "primary",
            "highlightColor": "highlight",
            "outlineColor": "outline",
            "outlineWidth": "outline_width",
            "shadowDepth": "shadow",
            "positionY": "position_y",
            "isUppercase": "uppercase",
            "animateKaraoke": None,  # handled by animation
            "maxWordsPerLine": "max_words",
            "popScale": "pop_scale",
            "hasBackground": "has_background",
            "backgroundColor": "background_color",
            "backgroundAlpha": "background_alpha",
            "subtitleLanguage": "subtitle_language",
            "translatedWords": "translated_words",
            "showSubtitles": "enabled",
        }

        # Size string presets from frontend: sm=62, md=72, lg=82, xl=92
        font_size_map = {"sm": 62, "md": 72, "lg": 82, "xl": 92}
        if isinstance(d.get("fontSize"), str) and d["fontSize"] in font_size_map:
            d["fontSize"] = font_size_map[d["fontSize"]]

        # Handle font family mapping to safe system fonts
        font_family_map = {
            "Montserrat": "Arial",  # fallback to standard system sans if Montserrat not in fontconfig
            "Inter": "Arial",
            "Bebas Neue": "Impact",
            "Impact": "Impact",
            "Arial": "Arial",
            "Roboto": "Arial",
            "Nirmala UI": "Nirmala UI",
            "Nirmala": "Nirmala UI",
            "Segoe UI": "Segoe UI",
            "Malgun Gothic": "Malgun Gothic",
            "MS Gothic": "MS Gothic",
        }
        if "fontFamily" in d and d["fontFamily"] in font_family_map:
            d["fontFamily"] = font_family_map[d["fontFamily"]]

        for k, v in d.items():
            mapped_key = alias.get(k, k)
            if mapped_key is not None and v is not None:
                base_vals[mapped_key] = v

        fields = cls.__dataclass_fields__
        kwargs = {}
        for k, v in base_vals.items():
            if k in fields and v is not None:
                t_str = str(fields[k].type)
                try:
                    if isinstance(v, (list, dict)) or "List" in t_str or "Dict" in t_str:
                        kwargs[k] = v
                    elif "int" in t_str and "float" not in t_str:
                        kwargs[k] = int(round(float(v)))
                    elif "float" in t_str:
                        kwargs[k] = float(v)
                    elif "bool" in t_str:
                        if isinstance(v, bool):
                            kwargs[k] = v
                        else:
                            kwargs[k] = str(v).lower() in ("true", "1", "yes")
                    else:
                        kwargs[k] = str(v)
                except (TypeError, ValueError):
                    kwargs[k] = v
        return cls(**kwargs)


def _ass_color(hex_color: str, alpha: float = 0.0) -> str:
    """Format hex color into ASS format (&HAABBGGRR&). Alpha in [0.0 (opaque) .. 1.0 (transparent)]."""
    h = str(hex_color).lstrip("#")
    if not re.fullmatch(r"[0-9a-fA-F]{6}", h):
        h = "FFFFFF"
    a_int = min(max(int(round(alpha * 255)), 0), 255)
    return f"&H{a_int:02X}{h[4:6]}{h[2:4]}{h[0:2]}&".upper()


def _ts(sec: float) -> str:
    sec = max(sec, 0.0)
    cs = int(round(sec * 100))
    return f"{cs // 360000}:{cs // 6000 % 60:02d}:{cs // 100 % 60:02d}.{cs % 100:02d}"


def _esc(text: str) -> str:
    return text.replace("\\", "").replace("{", "(").replace("}", ")").replace("\n", " ")


def collect_translated_words(translated_words: List[dict], start: float, end: float) -> List[dict]:
    """Shift and clamp translated words relative to the clip window [start, end]."""
    if not translated_words:
        return []
    dur = max(end - start, 0.1)

    # Determine whether the entire word list is already clip-relative (0..dur)
    # rather than in absolute video timeline seconds [start..end].
    valid_items = [w for w in translated_words if isinstance(w, dict) and w.get("word")]
    if not valid_items:
        return []

    has_absolute_match = any(
        float(w.get("end", 0.0)) > start + 0.01 and float(w.get("start", 0.0)) < end - 0.01
        for w in valid_items
    )
    all_clip_relative = (
        start > 1.0
        and not has_absolute_match
        and all(0.0 <= float(w.get("start", 0.0)) < dur and float(w.get("end", 0.0)) <= dur + 0.5 for w in valid_items)
    )

    words: List[dict] = []
    for w in valid_items:
        w_start = float(w.get("start", 0.0))
        w_end = float(w.get("end", 0.0))
        if all_clip_relative:
            s_rel = max(w_start, 0.0)
            e_rel = min(w_end, dur)
            if e_rel > s_rel:
                words.append({"word": w["word"], "start": round(s_rel, 3), "end": round(e_rel, 3)})
        elif w_end > start + 0.01 and w_start < end - 0.01:
            s_rel = max(w_start - start, 0.0)
            e_rel = min(w_end - start, dur)
            if e_rel > s_rel:
                words.append({"word": w["word"], "start": round(s_rel, 3), "end": round(e_rel, 3)})
    return words


def collect_words(segments: List[dict], start: float, end: float) -> List[dict]:
    """Words fully inside [start, end], times shifted so the clip starts at 0."""
    words = []
    for seg in segments:
        if seg["end"] < start or seg["start"] > end:
            continue
        seg_words = seg.get("words") or []
        if not seg_words:
            toks = seg["text"].split()
            if not toks:
                continue
            step = (seg["end"] - seg["start"]) / len(toks)
            seg_words = [
                {
                    "word": t,
                    "start": seg["start"] + i * step,
                    "end": seg["start"] + (i + 1) * step,
                }
                for i, t in enumerate(toks)
            ]
        for w in seg_words:
            if w["end"] > start + 0.01 and w["start"] < end - 0.01:
                w_s = max(w["start"] - start, 0.0)
                w_e = min(w["end"] - start, end - start)
                if w_e > w_s:
                    words.append({
                        "word": w["word"],
                        "start": w_s,
                        "end": w_e,
                    })
    return words


def chunk_words(words: List[dict], style: SubtitleStyle) -> List[List[dict]]:
    chunks: List[List[dict]] = []
    cur: List[dict] = []
    for w in words:
        cur_chars = sum(len(x.get("word", "")) for x in cur) + len(cur)
        next_len = len(w.get("word", ""))
        if cur and (
            len(cur) >= style.max_words
            or w["end"] - cur[0]["start"] > style.max_chunk_seconds
            or w["start"] - cur[-1]["end"] > 0.75
            or (cur_chars + next_len > 36 and len(cur) >= 2)
            or re.search(r"[.!?।؟。！？]$", cur[-1]["word"])
        ):
            chunks.append(cur)
            cur = []
        cur.append(w)
    if cur:
        chunks.append(cur)
    return chunks


def _get_active_word_tags(style: SubtitleStyle, hi_color: str, base_color: str) -> tuple[str, str]:
    """Return (open_tags, close_tags) for active word animation."""
    anim = style.animation.lower()
    pop = style.pop_scale

    if anim == "bounce":
        # Scale to 128%, bounce down to 96% in 80ms, settle at 105% at 160ms
        p1 = int(round(pop * 1.08))
        open_tag = f"{{\\c{hi_color}\\fscx{p1}\\fscy{p1}\\t(0,80,\\fscx96\\fscy96)\\t(80,160,\\fscx105\\fscy105)}}"
    elif anim == "scale_glow":
        open_tag = f"{{\\c{hi_color}\\fscx{pop}\\fscy{pop}\\t(0,100,\\fscx104\\fscy104)}}"
    elif anim == "fade":
        open_tag = f"{{\\c{hi_color}\\alpha&H88&\\t(0,80,\\alpha&H00&)}}"
    elif anim == "none":
        open_tag = f"{{\\c{hi_color}}}"
    else:  # default: "pop"
        # Start at pop scale (e.g. 120%) and smoothly ease to 106% in first 80ms
        open_tag = f"{{\\c{hi_color}\\fscx{pop}\\fscy{pop}\\t(0,80,\\fscx106\\fscy106)}}"

    close_tag = f"{{\\c{base_color}\\fscx100\\fscy100\\alpha&H00&}}"
    return open_tag, close_tag


def generate_ass(words: List[dict], style: Optional[SubtitleStyle] = None) -> str:
    st = style or SubtitleStyle()

    # Use translated words if words list is empty but style contains them
    if not words and st.translated_words:
        words = list(st.translated_words)

    # Detect script across the entire clip and resolve appropriate Unicode font (e.g. Nirmala UI for Malayalam/Indic)
    sample_text = " ".join(w.get("word", "") for w in words) if words else ""
    resolved_font = resolve_font_for_script(sample_text, st.font)

    # Determine vertical alignment and margin
    align = 2  # bottom center
    if st.position == "center":
        align = 5
        margin_v = 0
    elif st.position == "top":
        align = 8
        margin_v = DEFAULT_MARGIN_V_TOP
    else:  # bottom
        align = 2
        if st.position_y is not None:
            # Map position_y (e.g. 78% from top) to bottom MarginV
            # Clamped to safe margins (bottom >= 220px, top <= 1920-220px)
            raw_v = int(round(PLAY_H * (1.0 - (st.position_y / 100.0))))
            margin_v = min(max(raw_v, 220), PLAY_H - 260)
        else:
            margin_v = DEFAULT_MARGIN_V_BOTTOM

    # Background box vs outline + shadow
    border_style = 3 if st.has_background else 1
    outline_val = 14.0 if st.has_background else st.outline_width
    shadow_val = 0.0 if st.has_background else st.shadow
    back_color = _ass_color(st.background_color, 1.0 - st.background_alpha) if st.has_background else "&H64000000&"
    outline_color = back_color if st.has_background else _ass_color(st.outline)

    header = (
        "[Script Info]\n"
        "ScriptType: v4.00+\n"
        f"PlayResX: {PLAY_W}\n"
        f"PlayResY: {PLAY_H}\n"
        "WrapStyle: 2\n"
        "ScaledBorderAndShadow: yes\n\n"
        "[V4+ Styles]\n"
        "Format: Name,Fontname,Fontsize,PrimaryColour,SecondaryColour,OutlineColour,BackColour,Bold,Italic,"
        "Underline,StrikeOut,ScaleX,ScaleY,Spacing,Angle,BorderStyle,Outline,Shadow,Alignment,MarginL,MarginR,"
        "MarginV,Encoding\n"
        f"Style: Default,{_esc(resolved_font)},{st.font_size},{_ass_color(st.primary)},{_ass_color(st.highlight)},"
        f"{outline_color},{back_color},{-1 if st.bold else 0},0,0,0,100,100,0,0,{border_style},{outline_val:.1f},"
        f"{shadow_val:.1f},{align},{MARGIN_LEFT_RIGHT},{MARGIN_LEFT_RIGHT},{margin_v},1\n\n"
        "[Events]\n"
        "Format: Layer,Start,End,Style,Name,MarginL,MarginR,MarginV,Effect,Text\n"
    )

    hi_col = _ass_color(st.highlight)
    base_col = _ass_color(st.primary)
    open_tag, close_tag = _get_active_word_tags(st, hi_col, base_col)

    lines = []
    chunks = chunk_words(words, st)
    last_end = 0.0
    for c_idx, chunk in enumerate(chunks):
        next_chunk_start = chunks[c_idx + 1][0]["start"] if c_idx + 1 < len(chunks) else None
        is_rtl = any(detect_script(cw["word"]) == "arabic" for cw in chunk)
        for i, w in enumerate(chunk):
            t0 = max(w["start"], last_end)
            raw_t1 = chunk[i + 1]["start"] if i + 1 < len(chunk) else max(w["end"], t0 + 0.12)
            if i == len(chunk) - 1 and next_chunk_start is not None:
                raw_t1 = min(raw_t1, max(next_chunk_start, t0 + 0.05))
            t1 = max(raw_t1, t0 + 0.05)
            last_end = t1
            def _fmt_word(cw: dict) -> str:
                w_str = cw["word"]
                w_script = detect_script(w_str)
                # Only apply uppercase to Latin text to prevent breaking Indic/complex script conjuncts
                if st.uppercase and w_script == "latin":
                    w_str = w_str.upper()
                txt = _esc(w_str)
                if w_script != "latin":
                    w_font = resolve_font_for_script(w_str, resolved_font)
                    if w_font != resolved_font:
                        return f"{{\\fn{_esc(w_font)}}}{txt}{{\\fn{_esc(resolved_font)}}}"
                return txt

            if is_rtl:
                # In libass, each inline override block starts an LTR-ordered visual run while
                # FriBidi shapes text inside each run RTL. Place post-active words on the left,
                # active word in the middle, and pre-active words on the right so visual order
                # reads strictly right-to-left with the highlight advancing right-to-left.
                formatted = [_fmt_word(cw) for cw in chunk]
                left_run = " ".join(formatted[i + 1 :])
                active_run = f"{open_tag}{formatted[i]}{close_tag}"
                right_run = " ".join(formatted[:i])
                line_text = " ".join(p for p in (left_run, active_run, right_run) if p)
            else:
                parts = []
                for j, cw in enumerate(chunk):
                    txt = _fmt_word(cw)
                    if j == i:
                        parts.append(f"{open_tag}{txt}{close_tag}")
                    else:
                        parts.append(txt)
                line_text = " ".join(parts)
            lines.append(f"Dialogue: 0,{_ts(t0)},{_ts(t1)},Default,,0,0,0,,{line_text}")

    return header + "\n".join(lines) + ("\n" if lines else "")


def _srt_ts(sec: float) -> str:
    ms = int(round(max(sec, 0) * 1000))
    return f"{ms // 3600000:02d}:{ms // 60000 % 60:02d}:{ms // 1000 % 60:02d},{ms % 1000:03d}"


def generate_srt(words: List[dict], style: Optional[SubtitleStyle] = None) -> str:
    st = style or SubtitleStyle()
    out = []
    for n, chunk in enumerate(chunk_words(words, st), 1):
        text = " ".join(w["word"] for w in chunk)
        out.append(f"{n}\n{_srt_ts(chunk[0]['start'])} --> {_srt_ts(chunk[-1]['end'])}\n{text}\n")
    return "\n".join(out)
