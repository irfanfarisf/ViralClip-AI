"""AI and Rule-based interesting-moment detection and ranking for ViralClip AI.

Identifies engaging short-form clip moments based on:
1. Funny conversations & laughter cues
2. Surprising statements & plot twists
3. Exciting reactions, hype & clutch moments
4. Interesting stories & narrative arcs
5. Useful explanations & actionable insights
6. Strong opening hooks
7. Complete and meaningful sentences (avoiding mid-sentence cuts and dead silence)

Supports optional Gemini / OpenAI API analysis when credentials are provided,
with a robust, deterministic local rule-based fallback that requires no paid API.
"""
from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field, asdict
from typing import Any, Dict, List, Optional, Tuple

from backend.app.config import settings

log = logging.getLogger("viralclip.clip_detector")

# --- Multilingual Signal Keyword Dictionaries ---

HYPE_WORDS = {
    # English
    "insane", "crazy", "unbelievable", "no way", "oh my god", "omg", "let's go", "lets go", "clutch",
    "wow", "holy", "what the", "amazing", "incredible", "best", "worst", "huge", "win", "won",
    "lost", "dead", "kill", "ace", "finally", "impossible", "shocked", "pog", "poggers", "cracked",
    "goat", "legendary", "unreal", "hype", "destroyed", "popped off", "clutched",
    # Malayalam (മലയാളം)
    "അടിപൊളി", "കൊള്ളാം", "മാസ്സ്", "പൊളിച്ചു", "ജയിച്ചു", "സൂപ്പർ", "ഗംഭീരം", "വിജയം", "രക്ഷയില്ല",
    # Hindi (हिन्दी)
    "गजब", "कमाल", "शानदार", "जीत", "खतरनाक", "सुपर", "मजा आ गया", "धमाका", "लाजवाब", "जबरदस्त",
    # Tamil (தமிழ்)
    "செம", "அசத்தல்", "அருமை", "வெற்றி", "சூப்பர்", "தாறுமாறு", "மாஸ்",
    # Spanish, French, German, Arabic
    "increíble", "de locos", "vamos", "épico", "gagné", "incroyable", "wahnsinn", "unglaublich", "جنوني", "رائع", "هيا",
}

SURPRISE_WORDS = {
    # English
    "no way", "unbelievable", "can't believe", "cannot believe", "what just happened", "wait what",
    "are you serious", "are you kidding", "plot twist", "unexpected", "shocking", "impossible",
    "mind blown", "how did", "out of nowhere", "never seen", "holy cow", "what is that",
    "is that real", "never expected", "turned out", "secret", "turns out", "what on earth",
    # Malayalam
    "അത്ഭുതം", "വിശ്വസിക്കാൻ പറ്റില്ല", "ഇതെന്ത്", "എങ്ങനെ സംഭവിച്ചു", "സത്യമാണോ", "കണ്ടോ", "അപ്രതീക്ഷിതം",
    # Hindi
    "अविश्वसनीय", "असंभव", "सच में", "ये क्या हुआ", "कैसे हुआ", "चौंक गए", "हैरान",
    # Tamil
    "நம்பமுடியாதது", "வாய்ப்பே இல்லை", "என்ன இது", "எப்படி நடந்தது", "ஆச்சரியம்",
    # Other
    "no me lo creo", "c'est pas vrai", "das gibt's nicht", "مستحيل", "لا يصدق",
}

FUNNY_WORDS = {
    # English
    "haha", "lol", "lmao", "hilarious", "funny", "joke", "ridiculous", "laughing", "cracking up",
    "prank", "comedy", "roast", "mess up", "screwed up", "fail", "awkward", "silly", "dumbest",
    # Malayalam
    "ചിരി", "തമാശ", "കോമഡി", "ഹാഹാ", "പൊട്ടിച്ചിരി", "വിഡ്ഢി", "തമാശക്കാരൻ",
    # Hindi
    "मजाक", "हंसी", "लोल", "हाहा", "मजेदार", "हास्य", "कॉमेडी", "पागल",
    # Tamil
    "சிரிப்பு", "நகைச்சுவை", "காமெடி", "ஹாஹா", "வேடிக்கை",
    # Other
    "jaja", "chistoso", "drôle", "lustig", "witzig", "ضحك", "مهزلة",
}

STORY_WORDS = {
    # English
    "so basically", "one time", "remember when", "years ago", "back then", "and then", "story",
    "true story", "happened to me", "listen to this", "tell you what", "in the end", "at that moment",
    "long story short", "first time", "turned around", "suddenly", "started with",
    # Malayalam
    "സത്യത്തിൽ", "കഥ", "പണ്ട്", "അന്ന്", "ഒടുവിൽ", "അങ്ങനെ", "അപ്പോൾ", "തുടങ്ങി",
    # Hindi
    "कहानी", "एक बार", "फिर क्या हुआ", "आखिर में", "सुनो", "उस समय", "शुरू हुआ",
    # Tamil
    "கதை", "ஒரு முறை", "அப்புறம்", "கடைசியில்", "அப்போது",
    # Other
    "historia", "érase una vez", "histoire", "damals", "قصة",
}

EXPLANATION_WORDS = {
    # English
    "how to", "because", "the reason", "tip", "trick", "tutorial", "step", "first thing",
    "secret is", "method", "technique", "strategy", "explained", "make sure", "key is",
    "important", "solution", "rule", "lesson", "how you", "advice", "principle", "understand",
    # Malayalam
    "എങ്ങനെ", "കാരണം", "രഹസ്യം", "രീതി", "നിർദ്ദേശം", "നിയമം", "വഴി", "മനസ്സിലാക്കുക", "പ്രധാനമാണ്",
    # Hindi
    "कैसे", "तरीका", "सीक्रेट", "सलाह", "नियम", "उपाय", "जरूरी", "वजह", "समझें",
    # Tamil
    "எப்படி", "ரகசியம்", "விளக்கம்", "குறிப்பு", "வழிமுறை", "காரணம்",
    # Other
    "cómo", "truco", "consejo", "explication", "tipp", "شرح", "طريقة", "سر",
}

HOOK_WORDS = {
    # English
    "look at this", "watch this", "did you know", "have you ever", "stop doing this",
    "wait till the end", "check this out", "the secret", "nobody knows", "number one",
    "worst mistake", "biggest mistake", "here is why", "you will never", "listen carefully",
    # Malayalam
    "ഇത് കാണൂ", "നോക്കൂ", "അറിഞ്ഞിരിക്കുക", "കാത്തിരിക്കൂ", "ശ്രദ്ധിക്കൂ", "ഒരിക്കലും ചെയ്യരുത്",
    # Hindi
    "ये देखो", "देखो", "सुनो ध्यान से", "रुकिए ज़रा", "मत छोड़ना", "क्या आपको पता है",
    # Tamil
    "பாருங்க", "இதைப் பாருங்கள்", "காத்திருங்கள்", "தெரியுமா", "கவனியுங்கள்",
    # Other
    "mira esto", "atención", "regardez", "pass auf", "انظر هذا", "شاهد حتى النهاية",
}

LAUGH_RE = re.compile(r"\b(ha(ha)+|lol|lmao|rofl|hehe+)\b", re.I)
WORD_RE = re.compile(r"[\w']+")
SENTENCE_END_RE = re.compile(r"[.!?]\s*$")


@dataclass
class ClipCandidate:
    start: float
    end: float
    score: float
    reason: str
    category: str
    title: str
    description: str
    hashtags: List[str] = field(default_factory=list)
    signals: Dict[str, float] = field(default_factory=dict)
    selected: bool = False

    @property
    def duration(self) -> float:
        return round(self.end - self.start, 3)

    def to_dict(self) -> dict:
        d = asdict(self)
        d["duration"] = self.duration
        return d


def _seg_signals(seg: dict) -> Dict[str, Any]:
    text = seg["text"].strip()
    low = text.lower()
    words = WORD_RE.findall(low)
    n_words = max(len(words), 1)
    dur = max(seg["end"] - seg["start"], 0.4)

    return {
        "text": text,
        "low": low,
        "words": n_words,
        "dur": dur,
        "wps": n_words / dur,
        "excl": text.count("!"),
        "quest": text.count("?"),
        "hype": sum(1 for k in HYPE_WORDS if k in low),
        "surprise": sum(1 for k in SURPRISE_WORDS if k in low),
        "funny": sum(1 for k in FUNNY_WORDS if k in low) + len(LAUGH_RE.findall(text)),
        "story": sum(1 for k in STORY_WORDS if k in low),
        "explanation": sum(1 for k in EXPLANATION_WORDS if k in low),
        "hook": sum(1 for k in HOOK_WORDS if k in low),
        "ends_sentence": bool(SENTENCE_END_RE.search(text)),
    }


def _energy_stats(energy: List[float], window: float, start: float, end: float) -> Tuple[float, float]:
    if not energy:
        return 0.0, 0.0
    a = int(start / window)
    b = max(int(end / window), a + 1)
    chunk = energy[a:b]
    if not chunk:
        return 0.0, 0.0
    return sum(chunk) / len(chunk), max(chunk)


def _snippet(text: str, limit: int = 160) -> str:
    cleaned = re.sub(r"\s+", " ", text).strip()
    return cleaned if len(cleaned) <= limit else cleaned[: limit - 1].rsplit(" ", 1)[0] + "…"


def detect_clips(
    segments: List[dict],
    duration: float,
    energy: Optional[List[float]] = None,
    energy_window: float = 0.5,
    min_len: float = 20.0,
    max_len: float = 45.0,
    target_len: float = 30.0,
    max_clips: int = 5,
    max_overlap: float = 0.25,
    gemini_api_key: Optional[str] = None,
    openai_api_key: Optional[str] = None,
    use_ai_api: bool = True,
) -> List[ClipCandidate]:
    """Detect and rank the most engaging moments from transcript and audio analysis.

    Prefers Gemini/OpenAI analysis when configured and enabled, with automatic fallback
    to the rule-based detection engine. Selects and flags the top 2 moments as selected.
    """
    min_len = min(min_len, duration)
    max_len = min(max_len, duration)
    target_len = min(max(target_len, min_len), max_len)

    # 1. Attempt AI API analysis if credentials exist
    if use_ai_api and segments:
        gkey = gemini_api_key or settings.GEMINI_API_KEY
        okey = openai_api_key or settings.OPENAI_API_KEY
        if gkey:
            ai_clips = _try_gemini_detect(segments, duration, gkey, min_len, max_len, target_len, max_clips)
            if ai_clips:
                return _finalize_selection(ai_clips, max_clips, max_overlap)
        elif okey:
            ai_clips = _try_openai_detect(segments, duration, okey, min_len, max_len, target_len, max_clips)
            if ai_clips:
                return _finalize_selection(ai_clips, max_clips, max_overlap)

    # 2. Local rule-based detection engine
    return _detect_rule_based(
        segments=segments,
        duration=duration,
        energy=energy,
        energy_window=energy_window,
        min_len=min_len,
        max_len=max_len,
        target_len=target_len,
        max_clips=max_clips,
        max_overlap=max_overlap,
    )


def _detect_rule_based(
    segments: List[dict],
    duration: float,
    energy: Optional[List[float]],
    energy_window: float,
    min_len: float,
    max_len: float,
    target_len: float,
    max_clips: int,
    max_overlap: float,
) -> List[ClipCandidate]:
    energy = energy or []
    global_mean = (sum(energy) / len(energy)) if energy else 0.0
    global_peak = max(energy) if energy else 0.0

    raw: List[ClipCandidate] = []

    if segments:
        sigs = [_seg_signals(s) for s in segments]

        for i, first in enumerate(segments):
            # Evaluate windows starting at segment i
            tot = {
                "excl": 0.0, "quest": 0.0, "hype": 0.0, "surprise": 0.0,
                "funny": 0.0, "story": 0.0, "explanation": 0.0, "words": 0.0,
            }

            for j in range(i, len(segments)):
                last = segments[j]
                raw_duration = last["end"] - first["start"]
                if raw_duration > max_len + 3.0:
                    break

                for k in ("excl", "quest", "hype", "surprise", "funny", "story", "explanation", "words"):
                    tot[k] += sigs[j][k]

                # Snap start and end to avoid cutting off mid-speech and silence
                start_t = _snap_start(first)
                end_t = _snap_end(last, duration)
                length = end_t - start_t

                if min_len <= length <= max_len:
                    # Score this window
                    mean_e, peak_e = _energy_stats(energy, energy_window, start_t, end_t)
                    cadence = tot["words"] / max(length, 1.0)

                    # Opening hook bonus if first segment has questions, surprises, or hook words
                    hook_score = 1.0 if (sigs[i]["quest"] or sigs[i]["surprise"] or sigs[i]["hook"] or sigs[i]["excl"]) else 0.0

                    # Sentence boundary completeness bonus
                    sentence_complete = 1.0 if sigs[j]["ends_sentence"] else 0.2

                    parts = {
                        "hype": min(tot["hype"] / 3.0, 1.0),
                        "surprise": min(tot["surprise"] / 2.5, 1.0),
                        "funny": min(tot["funny"] / 2.0, 1.0),
                        "story": min(tot["story"] / 2.5, 1.0),
                        "explanation": min(tot["explanation"] / 3.0, 1.0),
                        "exclamations": min(tot["excl"] / 3.5, 1.0),
                        "questions": min(tot["quest"] / 3.0, 1.0),
                        "cadence": min(cadence / 3.2, 1.0),
                        "loudness": min(mean_e / (global_mean * 1.6), 1.0) if global_mean else 0.0,
                        "peak": min(peak_e / global_peak, 1.0) if global_peak else 0.0,
                        "hook": hook_score,
                        "sentence_complete": sentence_complete,
                    }

                    weights = {
                        "hype": 16,
                        "surprise": 16,
                        "funny": 14,
                        "story": 12,
                        "explanation": 12,
                        "hook": 14,
                        "sentence_complete": 10,
                        "exclamations": 8,
                        "questions": 6,
                        "cadence": 8,
                        "loudness": 8 if energy else 0,
                        "peak": 4 if energy else 0,
                    }

                    wsum = sum(weights.values())
                    base_score = 100.0 * sum(parts[k] * weights[k] for k in weights) / wsum

                    # Proximity penalty: prefer clips close to target length (e.g. 30s)
                    length_penalty = 1.0 - 0.12 * min(abs(length - target_len) / target_len, 1.0)
                    score = base_score * length_penalty

                    candidate = _build_candidate(segments[i:j + 1], start_t, end_t, score, parts, tot)
                    raw.append(candidate)

    elif energy:
        raw.extend(_energy_only(energy, energy_window, duration, min_len, target_len))

    raw.sort(key=lambda c: c.score, reverse=True)
    return _finalize_selection(raw, max_clips, max_overlap)


def _snap_start(seg: dict) -> float:
    words = seg.get("words") or []
    if words and len(words) > 0:
        return max(float(words[0]["start"]) - 0.1, 0.0)
    return max(float(seg["start"]) - 0.1, 0.0)


def _snap_end(seg: dict, max_duration: float) -> float:
    words = seg.get("words") or []
    if words and len(words) > 0:
        return min(float(words[-1]["end"]) + 0.25, max_duration)
    return min(float(seg["end"]) + 0.2, max_duration)


def _build_candidate(
    segs: List[dict],
    start: float,
    end: float,
    score: float,
    parts: Dict[str, float],
    tot: Dict[str, float],
) -> ClipCandidate:
    full_text = " ".join(s["text"].strip() for s in segs)

    # Classify dominant category based on strongest signals
    cat_scores = [
        ("funny", parts["funny"]),
        ("surprise", parts["surprise"]),
        ("hype", parts["hype"] + parts["exclamations"] * 0.5),
        ("story", parts["story"]),
        ("explanation", parts["explanation"]),
        ("hook", parts["hook"]),
    ]
    cat_scores.sort(key=lambda x: -x[1])
    dominant_cat = cat_scores[0][0] if cat_scores[0][1] > 0.25 else "hype"

    # Human-readable selection reason
    reason_labels = {
        "funny": "Funny moment & comedic banter",
        "surprise": "Surprising statement & plot twist",
        "hype": "High-energy reaction & excitement peak",
        "story": "Engaging narrative & storytelling flow",
        "explanation": "Useful tip & clear explanation",
        "hook": "Strong opening hook & high retention impulse",
        "cadence": "Fast speech cadence",
        "loudness": "Loud audio reaction",
    }
    reasons = [reason_labels[cat] for cat, sc in cat_scores if sc >= 0.35 and cat in reason_labels]
    if parts["hook"] >= 0.5 and "Strong opening hook & high retention impulse" not in reasons:
        reasons.append("Strong opening hook")
    if not reasons:
        reasons = ["Cohesive conversation & complete sentence boundary"]

    reason_text = "Signals: " + ", ".join(reasons[:3])

    # Suggested Title: extract punchiest sentence or hook
    best_seg = max(segs, key=lambda s: (s["text"].count("!") * 2 + s["text"].count("?") + len(WORD_RE.findall(s["text"]))))
    title = _generate_title(best_seg["text"], dominant_cat)

    # Social hashtags
    tags = ["#shorts", f"#{dominant_cat}"]
    for word in WORD_RE.findall(full_text.lower()):
        if len(word) > 5 and word not in ("really", "actually", "because", "something"):
            tags.append(f"#{word}")
            if len(tags) >= 4:
                break

    return ClipCandidate(
        start=round(start, 3),
        end=round(end, 3),
        score=round(min(max(score, 10.0), 99.0), 1),
        reason=reason_text,
        category=dominant_cat,
        title=title,
        description=_snippet(full_text, 220),
        hashtags=tags,
        signals={k: round(v, 2) for k, v in parts.items()},
    )


def _generate_title(text: str, category: str) -> str:
    cleaned = text.strip().rstrip(".!?")
    if len(cleaned) > 55:
        cleaned = cleaned[:52].rsplit(" ", 1)[0] + "…"
    prefixes = {
        "funny": "🤣 ",
        "surprise": "🤯 ",
        "hype": "🔥 ",
        "story": "📖 ",
        "explanation": "💡 ",
        "hook": "⚡ ",
    }
    return f"{prefixes.get(category, '🔥 ')}{cleaned}"


def _finalize_selection(candidates: List[ClipCandidate], max_clips: int, max_overlap: float) -> List[ClipCandidate]:
    """Filter overlapping candidates and select the best two suitable moments."""
    picked: List[ClipCandidate] = []
    for c in candidates:
        if len(picked) >= max_clips:
            break
        if all(_overlap(c, p) <= max_overlap for p in picked):
            picked.append(c)

    # Flag top 2 suitable moments as selected
    for i, c in enumerate(picked):
        c.selected = i < 2

    return picked


def _overlap(a: ClipCandidate, b: ClipCandidate) -> float:
    inter = max(0.0, min(a.end, b.end) - max(a.start, b.start))
    return inter / max(min(a.duration, b.duration), 0.001)


def _energy_only(energy: List[float], window: float, duration: float, min_len: float, target_len: float) -> List[ClipCandidate]:
    """Fallback when no transcript is available: rank loud audio windows."""
    n = max(int(target_len / window), 1)
    if len(energy) < n:
        return []
    peak = max(energy) or 1.0
    out: List[ClipCandidate] = []
    for a in range(0, len(energy) - n + 1, max(n // 4, 1)):
        chunk = energy[a : a + n]
        mean, pk = sum(chunk) / n, max(chunk)
        start = a * window
        end = min(start + target_len, duration)
        if end - start < min_len:
            continue
        out.append(ClipCandidate(
            start=round(start, 3),
            end=round(end, 3),
            score=round(100.0 * (0.6 * mean / peak + 0.4 * pk / peak), 1),
            reason="Signals: loud audio (no speech transcript available)",
            category="hype",
            title="🔥 High-energy moment",
            description="",
            hashtags=["#shorts", "#hype"],
            signals={"loudness": round(mean, 4), "peak": round(pk, 4)},
        ))
    return out


# --- Optional AI API Integration (Gemini & OpenAI) ---

def _try_gemini_detect(
    segments: List[dict],
    video_duration: float,
    api_key: str,
    min_len: float,
    max_len: float,
    target_len: float,
    max_clips: int,
) -> Optional[List[ClipCandidate]]:
    try:
        import httpx
        url = "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent"
        headers = {"x-goog-api-key": api_key}
        transcript_lines = [f"[{s['start']:.1f}s - {s['end']:.1f}s] {s['text']}" for s in segments[:120]]
        prompt = (
            "You are an expert short-form video editor for YouTube Shorts and TikTok. "
            f"Analyze this transcript and find the top {max_clips} viral moments (duration {min_len:.0f}s to {max_len:.0f}s, target {target_len:.0f}s). "
            "The transcript may be in any language (e.g. English, Malayalam, Hindi, Tamil, Arabic, Spanish). "
            "Analyze it directly in its original language, and generate titles and reasons in the SAME language as the transcript. "
            "Ensure clips start at natural sentence beginnings and end at complete sentence boundaries. "
            "Categories must be one of: 'funny', 'surprise', 'hype', 'story', 'explanation', 'hook'. "
            "Respond ONLY with a valid JSON array of objects with keys: "
            "start_time (float), end_time (float), title (string), reason (string), category (string), score (float 50-99).\n\n"
            "Transcript:\n" + "\n".join(transcript_lines)
        )
        payload = {
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {"temperature": 0.2, "responseMimeType": "application/json"},
        }
        resp = httpx.post(url, json=payload, headers=headers, timeout=12.0)
        if resp.status_code == 200:
            data = resp.json()
            raw_text = data["candidates"][0]["content"]["parts"][0]["text"]
            items = json.loads(raw_text)
            cands = []
            for item in items:
                st = max(float(item.get("start_time", 0.0)), 0.0)
                et = min(float(item.get("end_time", video_duration)), video_duration)
                if min_len <= et - st <= max_len + 3.0:
                    cands.append(ClipCandidate(
                        start=round(st, 3),
                        end=round(et, 3),
                        score=round(float(item.get("score", 90.0)), 1),
                        reason=f"AI Detected: {item.get('reason', 'High engagement moment')}",
                        category=item.get("category", "hype"),
                        title=item.get("title", "Viral Highlight"),
                        description=_snippet(" ".join(s["text"] for s in segments if s["end"] >= st and s["start"] <= et)),
                        hashtags=["#shorts", f"#{item.get('category', 'viral')}"],
                    ))
            if cands:
                return cands
    except Exception as exc:
        log.warning("Gemini highlight detection failed (falling back to rule-based): %s", exc)
    return None


def _try_openai_detect(
    segments: List[dict],
    video_duration: float,
    api_key: str,
    min_len: float,
    max_len: float,
    target_len: float,
    max_clips: int,
) -> Optional[List[ClipCandidate]]:
    try:
        import httpx
        url = "https://api.openai.com/v1/chat/completions"
        transcript_lines = [f"[{s['start']:.1f}s - {s['end']:.1f}s] {s['text']}" for s in segments[:120]]
        prompt = (
            f"Identify the top {max_clips} viral clip windows ({min_len:.0f}s to {max_len:.0f}s) from this transcript. "
            "Analyze the transcript in its original language (e.g. Malayalam, Hindi, Tamil, English, Arabic) and write titles and reasons in that same language. "
            "Ensure sentence boundary completeness. Categories: funny, surprise, hype, story, explanation, hook. "
            "Return JSON array with keys: start_time, end_time, title, reason, category, score (50-99).\n\n"
            + "\n".join(transcript_lines)
        )
        payload = {
            "model": "gpt-4o-mini",
            "messages": [
                {"role": "system", "content": "You are a professional video shorts editor. Output JSON only."},
                {"role": "user", "content": prompt},
            ],
            "response_format": {"type": "json_object"},
            "temperature": 0.2,
        }
        headers = {"Authorization": f"Bearer {api_key}"}
        resp = httpx.post(url, json=payload, headers=headers, timeout=12.0)
        if resp.status_code == 200:
            data = resp.json()
            content = data["choices"][0]["message"]["content"]
            parsed = json.loads(content)
            items = parsed.get("clips") or parsed.get("highlights") or parsed
            if isinstance(items, list):
                cands = []
                for item in items:
                    st = max(float(item.get("start_time", 0.0)), 0.0)
                    et = min(float(item.get("end_time", video_duration)), video_duration)
                    if min_len <= et - st <= max_len + 3.0:
                        cands.append(ClipCandidate(
                            start=round(st, 3),
                            end=round(et, 3),
                            score=round(float(item.get("score", 90.0)), 1),
                            reason=f"AI Detected: {item.get('reason', 'High engagement moment')}",
                            category=item.get("category", "hype"),
                            title=item.get("title", "Viral Highlight"),
                            description=_snippet(" ".join(s["text"] for s in segments if s["end"] >= st and s["start"] <= et)),
                            hashtags=["#shorts", f"#{item.get('category', 'viral')}"],
                        ))
                if cands:
                    return cands
    except Exception as exc:
        log.warning("OpenAI highlight detection failed (falling back to rule-based): %s", exc)
    return None
