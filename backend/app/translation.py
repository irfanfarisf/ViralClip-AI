"""Multilingual translation engine for ViralClip AI.

Provides translation for:
- Subtitle segments & word-level karaoke timestamps (preserving speech timing)
- Video titles, descriptions, and metadata
- Language identification and script detection

Supported languages:
- English (en)
- Malayalam (ml)
- Hindi (hi)
- Tamil (ta)
- Telugu (te)
- Kannada (kn)
- Arabic (ar)
- Spanish (es)
- French (fr)
- German (de)
- Japanese (ja)
- Korean (ko)

Translation cascading:
1. Gemini API (when configured)
2. OpenAI API (when configured)
3. Free public translation web service (via httpx)
4. Offline phrase & dictionary fallback (ensuring offline operation never fails)
"""
from __future__ import annotations

import json
import logging
import re
import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

import httpx

from backend.app.config import settings

log = logging.getLogger("viralclip.translation")


class TranslationError(RuntimeError):
    """Raised when subtitle translation cannot be completed."""

    def __init__(self, message: str, status_code: int = 502):
        super().__init__(message)
        self.message = message
        self.status_code = status_code


@dataclass
class BatchTranslationResult:
    segments: List[dict]
    words: List[dict]
    provider: str
    source_language: str
    target_language: str
    partial: bool = False
    translated_count: int = 0
    failed_count: int = 0
    warnings: List[str] = field(default_factory=list)

# Supported language codes & localized human-readable labels
SUPPORTED_LANGUAGES: Dict[str, str] = {
    "auto": "Auto-Detect Language",
    "en": "English",
    "ml": "Malayalam (മലയാളം)",
    "hi": "Hindi (हिन्दी)",
    "ta": "Tamil (தமிழ்)",
    "te": "Telugu (తెలుగు)",
    "kn": "Kannada (ಕನ್ನಡ)",
    "ar": "Arabic (العربية)",
    "es": "Spanish (Español)",
    "fr": "French (Français)",
    "de": "German (Deutsch)",
    "ja": "Japanese (日本語)",
    "ko": "Korean (한국어)",
}

# ISO code aliases
LANGUAGE_ALIASES: Dict[str, str] = {
    "malayalam": "ml",
    "hindi": "hi",
    "tamil": "ta",
    "telugu": "te",
    "kannada": "kn",
    "arabic": "ar",
    "spanish": "es",
    "french": "fr",
    "german": "de",
    "japanese": "ja",
    "korean": "ko",
    "english": "en",
}

# Safe system fonts per script for Windows 10/11 & Linux libass rendering
SCRIPT_FONTS: Dict[str, str] = {
    "malayalam": "Nirmala UI",
    "devanagari": "Nirmala UI",
    "tamil": "Nirmala UI",
    "telugu": "Nirmala UI",
    "kannada": "Nirmala UI",
    "arabic": "Segoe UI",
    "korean": "Malgun Gothic",
    "cjk": "MS Gothic",
    "latin": "Arial",
}

# Offline dictionary for common creator terms and phrases across supported languages
OFFLINE_PHRASE_DICTIONARY: Dict[str, Dict[str, str]] = {
    "ml": {
        "hello": "നമസ്കാരം",
        "welcome": "സ്വാഗതം",
        "insane": "അടിപൊളി",
        "crazy": "ഭ്രാന്തൻ",
        "unbelievable": "വിശ്വസിക്കാൻ പറ്റാത്തത്",
        "no way": "ഒരിക്കലുമില്ല",
        "let's go": "വാ പോകാം",
        "lets go": "വാ പോകാം",
        "clutch": "ക്ലച്ച് നിമിഷം",
        "wow": "കൊള്ളാം",
        "amazing": "അത്ഭുതകരം",
        "watch this": "ഇത് കാണൂ",
        "wait for it": "കാത്തിരിക്കൂ",
        "viral short": "വൈറൽ ഷോർട്ട്",
        "highlight": "പ്രധാന നിമിഷം",
        "did you see that": "നിങ്ങൾ അത് കണ്ടോ",
        "how did this happen": "ഇത് എങ്ങനെ സംഭവിച്ചു",
        "true story": "സത്യമായ കഥ",
        "pro tip": "പ്രത്യേക നിർദ്ദേശം",
    },
    "hi": {
        "hello": "नमस्ते",
        "welcome": "स्वागत है",
        "insane": "गजब",
        "crazy": "कमाल",
        "unbelievable": "अविश्वसनीय",
        "no way": "बिल्कुल नहीं",
        "let's go": "चलो चलें",
        "lets go": "चलो चलें",
        "clutch": "शानदार खेल",
        "wow": "वाह",
        "amazing": "अद्भुत",
        "watch this": "यह देखो",
        "wait for it": "रुकिए ज़रा",
        "viral short": "वायरल शॉर्ट",
        "highlight": "खास पल",
        "did you see that": "क्या आपने देखा",
        "how did this happen": "यह कैसे हुआ",
        "true story": "सच्ची कहानी",
        "pro tip": "खास टिप",
    },
    "ta": {
        "hello": "வணக்கம்",
        "welcome": "வரவேற்கிறோம்",
        "insane": "செம",
        "crazy": "அசத்தல்",
        "unbelievable": "நம்பமுடியாதது",
        "no way": "வாய்ப்பே இல்லை",
        "let's go": "வாங்க போகலாம்",
        "lets go": "வாங்க போகலாம்",
        "clutch": "வெற்றி தருணம்",
        "wow": "ஆஹா",
        "amazing": "அருமை",
        "watch this": "இதைப் பாருங்கள்",
        "wait for it": "காத்திருங்கள்",
        "viral short": "வைரல் ஷார்ட்",
        "highlight": "முக்கிய தருணம்",
        "did you see that": "பார்த்தீர்களா",
        "how did this happen": "எப்படி நடந்தது",
        "true story": "உண்மைக் கதை",
        "pro tip": "சிறந்த குறிப்பு",
    },
    "es": {
        "hello": "Hola",
        "welcome": "Bienvenido",
        "insane": "Increíble",
        "crazy": "De locos",
        "unbelievable": "No me lo creo",
        "no way": "De ninguna manera",
        "let's go": "Vamos",
        "lets go": "Vamos",
        "clutch": "Momento épico",
        "wow": "Guau",
        "amazing": "Asombroso",
        "watch this": "Mira esto",
        "wait for it": "Espera al final",
        "viral short": "Corto viral",
        "highlight": "Momento destacado",
        "did you see that": "¿Viste eso?",
        "how did this happen": "¿Cómo pasó esto?",
        "true story": "Historia real",
        "pro tip": "Consejo profesional",
    },
    "ar": {
        "hello": "مرحباً",
        "welcome": "أهلاً وسهلاً",
        "insane": "جنوني",
        "crazy": "خارق",
        "unbelievable": "لا يصدق",
        "no way": "مستحيل",
        "let's go": "هيا بنا",
        "lets go": "هيا بنا",
        "clutch": "لقطة حاسمة",
        "wow": "رائع",
        "amazing": "مذهل",
        "watch this": "شاهد هذا",
        "wait for it": "انتظر للنهاية",
        "viral short": "فيديو قصير واسع الانتشار",
        "highlight": "أبرز لقطة",
        "did you see that": "هل رأيت ذلك؟",
        "how did this happen": "كيف حدث هذا؟",
        "true story": "قصة حقيقية",
        "pro tip": "نصيحة للمحترفين",
    },
}


def normalize_language_code(code: Optional[str]) -> str:
    """Normalize language code or name to canonical ISO code (defaults to 'auto')."""
    if not code:
        return "auto"
    low = code.strip().lower()
    if low in SUPPORTED_LANGUAGES:
        return low
    if low in LANGUAGE_ALIASES:
        return LANGUAGE_ALIASES[low]
    # Check 2-letter prefix (e.g. 'en-US' -> 'en', 'ml-IN' -> 'ml')
    prefix = low.split("-")[0].split("_")[0]
    if prefix in SUPPORTED_LANGUAGES:
        return prefix
    return low


def detect_script(text: str) -> str:
    """Detect writing script from Unicode codepoints."""
    for ch in text:
        cp = ord(ch)
        if 0x0D00 <= cp <= 0x0D7F:
            return "malayalam"
        if 0x0900 <= cp <= 0x097F:
            return "devanagari"
        if 0x0B80 <= cp <= 0x0BFF:
            return "tamil"
        if 0x0C00 <= cp <= 0x0C7F:
            return "telugu"
        if 0x0C80 <= cp <= 0x0CFF:
            return "kannada"
        if 0x0600 <= cp <= 0x06FF:
            return "arabic"
        if 0xAC00 <= cp <= 0xD7AF:
            return "korean"
        if (0x3040 <= cp <= 0x309F) or (0x30A0 <= cp <= 0x30FF) or (0x4E00 <= cp <= 0x9FFF):
            return "cjk"
    return "latin"


def resolve_font_for_script(text: str, requested_font: Optional[str] = None) -> str:
    """Select the optimal font for rendering the script without glyph boxes ('tofu')."""
    script = detect_script(text)
    indic_scripts = ("malayalam", "devanagari", "tamil", "telugu", "kannada")

    if script in indic_scripts:
        # Nirmala UI on Windows 10/11 is specifically designed for Indic scripts & complex conjunct shaping
        return "Nirmala UI"
    if script == "arabic":
        return "Segoe UI"
    if script == "korean":
        return "Malgun Gothic"
    if script == "cjk":
        return "MS Gothic"

    # For Latin, preserve user font preference or safe default
    req = (requested_font or "Arial").strip()
    return req if req else "Arial"


# ------------------------------------------------------------------ Translation Providers

PUBLIC_TRANSLATE_URL = "https://translate.googleapis.com/translate_a/single"
_HTTP_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) ViralClipAI/1.0",
    "Accept": "application/json, text/plain, */*",
}
_BATCH_MAX_ITEMS = 20
_BATCH_MAX_CHARS = 2800


def is_supported_target_language(code: str) -> bool:
    norm = normalize_language_code(code)
    return norm in SUPPORTED_LANGUAGES and norm != "auto"


def _expected_script_for_lang(lang: str) -> Optional[str]:
    return {
        "ml": "malayalam",
        "hi": "devanagari",
        "ta": "tamil",
        "te": "telugu",
        "kn": "kannada",
        "ar": "arabic",
        "ko": "korean",
        "ja": "cjk",
        "en": "latin",
        "es": "latin",
        "fr": "latin",
        "de": "latin",
    }.get(lang)


def _chunk_texts_for_batch(
    texts: List[str],
    max_items: int = _BATCH_MAX_ITEMS,
    max_chars: int = _BATCH_MAX_CHARS,
) -> List[List[str]]:
    batches: List[List[str]] = []
    cur: List[str] = []
    cur_chars = 0
    for txt in texts:
        t_len = len(txt) + 2
        if cur and (len(cur) >= max_items or cur_chars + t_len > max_chars):
            batches.append(cur)
            cur = []
            cur_chars = 0
        cur.append(txt)
        cur_chars += t_len
    if cur:
        batches.append(cur)
    return batches


def _parse_json_list_response(raw: str, expected_len: int) -> Optional[List[str]]:
    cleaned = raw.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned)
        cleaned = re.sub(r"\s*```$", "", cleaned).strip()
    try:
        parsed = json.loads(cleaned)
    except json.JSONDecodeError:
        m = re.search(r"\[.*\]", cleaned, flags=re.DOTALL)
        if not m:
            return None
        try:
            parsed = json.loads(m.group(0))
        except json.JSONDecodeError:
            return None
    if isinstance(parsed, list) and len(parsed) == expected_len:
        out = [str(item).strip() for item in parsed]
        if all(out):
            return out
    return None


def _translate_batch_via_gemini(
    texts: List[str],
    target_lang: str,
    api_key: str,
    source_lang: Optional[str] = None,
) -> Optional[List[str]]:
    """Batch-translate subtitle segments using Google Gemini (gemini-2.5-flash with 2.0-flash fallback)."""
    target_name = SUPPORTED_LANGUAGES.get(target_lang, target_lang)
    src_clause = f"from {SUPPORTED_LANGUAGES.get(source_lang, source_lang)} " if source_lang and source_lang != "auto" else ""
    prompt = (
        f"You are a professional video subtitle translator.\n"
        f"Translate each item in the JSON array below {src_clause}into {target_name}.\n"
        f"Rules:\n"
        f"- Return ONLY a valid JSON array of strings with the EXACT same number of elements ({len(texts)}).\n"
        f"- Preserve natural spoken tone, conciseness, and Unicode script.\n"
        f"- Do not merge, split, or omit items, and do not add markdown or explanations.\n\n"
        f"{json.dumps(texts, ensure_ascii=False)}"
    )
    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {"temperature": 0.2, "maxOutputTokens": 4096},
    }
    headers = {"x-goog-api-key": api_key, "Content-Type": "application/json"}
    models = ("gemini-2.5-flash", "gemini-2.0-flash")

    for model in models:
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
        for attempt in range(2):
            try:
                resp = httpx.post(url, json=payload, headers=headers, timeout=20.0)
                if resp.status_code == 200:
                    data = resp.json()
                    raw = data["candidates"][0]["content"]["parts"][0]["text"]
                    parsed = _parse_json_list_response(raw, len(texts))
                    if parsed:
                        return parsed
                    log.warning("Gemini (%s) returned unparseable batch response", model)
                    break
                if resp.status_code == 404:
                    log.warning("Gemini model %s unavailable (404); trying fallback model", model)
                    break
                log.warning("Gemini (%s) HTTP %s: %s", model, resp.status_code, resp.text[:200])
                if resp.status_code in (429, 500, 502, 503, 504) and attempt == 0:
                    time.sleep(0.8)
                    continue
                break
            except Exception as exc:
                log.warning("Gemini (%s) translation request failed: %s", model, exc)
                if attempt == 0:
                    time.sleep(0.5)
                    continue
                break
    return None


def _translate_batch_via_openai(
    texts: List[str],
    target_lang: str,
    api_key: str,
    source_lang: Optional[str] = None,
) -> Optional[List[str]]:
    """Batch-translate subtitle segments using OpenAI (gpt-4o-mini)."""
    url = "https://api.openai.com/v1/chat/completions"
    target_name = SUPPORTED_LANGUAGES.get(target_lang, target_lang)
    src_clause = f"from {SUPPORTED_LANGUAGES.get(source_lang, source_lang)} " if source_lang and source_lang != "auto" else ""
    prompt = (
        f"Translate each subtitle string in this JSON array {src_clause}into {target_name}.\n"
        f"Return ONLY a JSON array of {len(texts)} translated strings in the exact same order.\n\n"
        f"{json.dumps(texts, ensure_ascii=False)}"
    )
    payload = {
        "model": "gpt-4o-mini",
        "messages": [
            {"role": "system", "content": "You are a professional subtitle translator. Output ONLY a valid JSON array of strings."},
            {"role": "user", "content": prompt},
        ],
        "temperature": 0.2,
    }
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    for attempt in range(2):
        try:
            resp = httpx.post(url, json=payload, headers=headers, timeout=20.0)
            if resp.status_code == 200:
                data = resp.json()
                raw = data["choices"][0]["message"]["content"]
                parsed = _parse_json_list_response(raw, len(texts))
                if parsed:
                    return parsed
                log.warning("OpenAI returned unparseable batch response")
                return None
            log.warning("OpenAI HTTP %s: %s", resp.status_code, resp.text[:200])
            if resp.status_code in (429, 500, 502, 503, 504) and attempt == 0:
                time.sleep(0.8)
                continue
            return None
        except Exception as exc:
            log.warning("OpenAI translation request failed: %s", exc)
            if attempt == 0:
                time.sleep(0.5)
                continue
            return None
    return None


def _public_api_request(text: str, target_lang: str, source_lang: Optional[str] = None) -> Optional[str]:
    """Send a single UTF-8 translation request to the free Google Translate public endpoint."""
    sl = source_lang if source_lang and source_lang in SUPPORTED_LANGUAGES and source_lang != "auto" else "auto"
    params = {
        "client": "gtx",
        "sl": sl,
        "tl": target_lang,
        "dt": "t",
    }
    for attempt in range(2):
        try:
            resp = httpx.post(
                PUBLIC_TRANSLATE_URL,
                params=params,
                data={"q": text},
                headers=_HTTP_HEADERS,
                timeout=12.0,
            )
            if resp.status_code == 200:
                data = resp.json()
                if isinstance(data, list) and data and isinstance(data[0], list):
                    translated = "".join(item[0] for item in data[0] if item and item[0])
                    if translated.strip():
                        return translated.strip()
                log.warning("Public translation API returned unexpected JSON shape")
                return None
            log.warning("Public translation API HTTP %s", resp.status_code)
            if resp.status_code in (429, 500, 502, 503, 504) and attempt == 0:
                time.sleep(0.75)
                continue
            return None
        except Exception as exc:
            log.warning("Public translation API request failed (attempt %d): %s", attempt + 1, exc)
            if attempt == 0:
                time.sleep(0.5)
                continue
            return None
    return None


def _translate_batch_via_public_api(
    texts: List[str],
    target_lang: str,
    source_lang: Optional[str] = None,
) -> Optional[List[str]]:
    """Batch-translate subtitle lines via the free public endpoint with automatic split fallback."""
    if not texts:
        return []
    sanitized = [re.sub(r"[\r\n]+", " ", t).strip() for t in texts]
    if len(sanitized) == 1:
        res = _public_api_request(sanitized[0], target_lang, source_lang)
        return [res] if res else None

    joined = "\n".join(sanitized)
    raw = _public_api_request(joined, target_lang, source_lang)
    if raw is None:
        return None

    lines = [ln.strip() for ln in raw.splitlines() if ln.strip()]
    if len(lines) == len(sanitized):
        return lines

    # If the service merged or split lines, divide the batch and retry to preserve exact 1-to-1 alignment
    mid = len(sanitized) // 2
    left = _translate_batch_via_public_api(sanitized[:mid], target_lang, source_lang)
    right = _translate_batch_via_public_api(sanitized[mid:], target_lang, source_lang)
    if left is not None and right is not None:
        return left + right
    return None


def _translate_via_gemini(
    text: str,
    target_lang: str,
    api_key: str,
    source_lang: Optional[str] = None,
) -> Optional[str]:
    res = _translate_batch_via_gemini([text], target_lang, api_key, source_lang)
    return res[0] if res else None


def _translate_via_openai(
    text: str,
    target_lang: str,
    api_key: str,
    source_lang: Optional[str] = None,
) -> Optional[str]:
    res = _translate_batch_via_openai([text], target_lang, api_key, source_lang)
    return res[0] if res else None


def _translate_via_public_api(
    text: str,
    target_lang: str,
    source_lang: Optional[str] = None,
) -> Optional[str]:
    return _public_api_request(text, target_lang, source_lang)


def _translate_offline_rule_based(text: str, target_lang: str) -> str:
    """Offline rule-based fallback used only for legacy offline unit tests."""
    target_dict = OFFLINE_PHRASE_DICTIONARY.get(target_lang, {})
    low_text = text.lower().strip()

    if low_text in target_dict:
        return target_dict[low_text]

    words = text.split()
    translated_tokens = []
    for w in words:
        clean = re.sub(r"[^\w']", "", w).lower()
        punct = re.sub(r"[\w']", "", w)
        if clean in target_dict:
            translated_tokens.append(target_dict[clean] + punct)
        else:
            translated_tokens.append(w)

    return " ".join(translated_tokens)


def _build_word_timings(trans_text: str, seg_start: float, seg_end: float) -> List[dict]:
    """Distribute translated words evenly across the original spoken window [seg_start, seg_end]."""
    dur = max(seg_end - seg_start, 0.1)
    tokens = trans_text.split()
    if len(tokens) == 1 and detect_script(trans_text) == "cjk" and len(trans_text) > 6:
        tokens = [trans_text[i:i + 4] for i in range(0, len(trans_text), 4)]
    seg_words: List[dict] = []
    if tokens:
        step = dur / len(tokens)
        for i, tok in enumerate(tokens):
            w_start = round(seg_start + i * step, 3)
            w_end = round(seg_start + (i + 1) * step, 3)
            seg_words.append({
                "word": tok,
                "start": w_start,
                "end": w_end,
                "probability": 1.0,
            })
    return seg_words


def translate_text(
    text: str,
    target_lang: str,
    source_lang: Optional[str] = None,
    *,
    gemini_api_key: Optional[str] = None,
    openai_api_key: Optional[str] = None,
) -> str:
    """Translate single string into target language using highest-fidelity available engine."""
    clean_text = text.strip()
    if not clean_text:
        return ""

    target = normalize_language_code(target_lang)
    src = normalize_language_code(source_lang)

    if target != "auto" and src != "auto" and target == src:
        return clean_text

    gkey = gemini_api_key or settings.GEMINI_API_KEY
    if gkey:
        res = _translate_via_gemini(clean_text, target, gkey, src)
        if res:
            return res

    okey = openai_api_key or settings.OPENAI_API_KEY
    if okey:
        res = _translate_via_openai(clean_text, target, okey, src)
        if res:
            return res

    res = _translate_via_public_api(clean_text, target, src)
    if res:
        return res

    return _translate_offline_rule_based(clean_text, target)


def _translate_batch_with_providers(
    texts: List[str],
    target: str,
    src: str,
    *,
    gemini_api_key: Optional[str] = None,
    openai_api_key: Optional[str] = None,
) -> Tuple[Optional[List[str]], Optional[str]]:
    """Try configured modular providers in order; returns (translated_list, provider_name)."""
    gkey = (gemini_api_key or settings.GEMINI_API_KEY or "").strip()
    if gkey:
        res = _translate_batch_via_gemini(texts, target, gkey, src)
        if res is not None:
            return res, "gemini"

    okey = (openai_api_key or settings.OPENAI_API_KEY or "").strip()
    if okey:
        res = _translate_batch_via_openai(texts, target, okey, src)
        if res is not None:
            return res, "openai"

    # Free public endpoint (no API key required); use sl='auto' unless source script matches src
    res = _translate_batch_via_public_api(texts, target, "auto")
    if res is not None:
        return res, "google_translate"

    return None, None


def translate_clip_segments(
    segments: List[dict],
    target_lang: str,
    source_lang: Optional[str] = None,
    *,
    gemini_api_key: Optional[str] = None,
    openai_api_key: Optional[str] = None,
) -> BatchTranslationResult:
    """Batch-translate clip segments while preserving original text, timestamps, and segment links.

    Raises TranslationError on invalid target language, empty transcript, or complete provider failure.
    Never silently returns untranslated text as a successful translation.
    """
    target = normalize_language_code(target_lang)
    if not is_supported_target_language(target):
        supported = ", ".join(k for k in SUPPORTED_LANGUAGES if k != "auto")
        raise TranslationError(
            f"Unsupported target language '{target_lang}'. Supported languages: {supported}.",
            status_code=422,
        )

    valid_segs = []
    for seg in segments:
        orig_text = str(seg.get("text", "")).strip()
        if not orig_text:
            continue
        seg_start = float(seg.get("start", seg.get("start_time", 0.0)))
        seg_end = float(seg.get("end", seg.get("end_time", seg_start + 1.0)))
        valid_segs.append({
            "id": seg.get("id"),
            "start": seg_start,
            "end": seg_end,
            "text": orig_text,
            "confidence": float(seg.get("confidence", 1.0) or 1.0),
        })

    if not valid_segs:
        raise TranslationError(
            "No transcript segments are available in this clip to translate.",
            status_code=422,
        )

    src = normalize_language_code(source_lang)
    sample_text = " ".join(s["text"] for s in valid_segs[:5])
    sample_script = detect_script(sample_text)
    expected_target_script = _expected_script_for_lang(target)
    if src != "auto" and src == target and (expected_target_script is None or sample_script == expected_target_script):
        raise TranslationError(
            f"Subtitles are already in {SUPPORTED_LANGUAGES.get(target, target)}. Choose a different target language.",
            status_code=422,
        )

    all_texts = [s["text"] for s in valid_segs]
    batches = _chunk_texts_for_batch(all_texts)

    translated_texts: List[str] = []
    providers_used: List[str] = []
    translated_count = 0
    failed_count = 0
    warnings: List[str] = []

    for batch_idx, batch in enumerate(batches):
        batch_out, provider = _translate_batch_with_providers(
            batch,
            target,
            src,
            gemini_api_key=gemini_api_key,
            openai_api_key=openai_api_key,
        )
        if batch_out is not None and provider is not None:
            translated_texts.extend(batch_out)
            providers_used.append(provider)
            translated_count += len(batch)
        else:
            translated_texts.extend(batch)
            failed_count += len(batch)
            warnings.append(
                f"Batch {batch_idx + 1}/{len(batches)} ({len(batch)} segment(s)) could not be translated; original text kept for those segments."
            )

    if translated_count == 0:
        raise TranslationError(
            "Subtitle translation failed because no translation service could be reached. "
            "Check your internet connection and retry, or configure a Gemini/OpenAI API key in Settings.",
            status_code=503,
        )

    translated_segments: List[dict] = []
    all_translated_words: List[dict] = []
    for seg, trans_text in zip(valid_segs, translated_texts):
        seg_words = _build_word_timings(trans_text, seg["start"], seg["end"])
        all_translated_words.extend(seg_words)
        translated_segments.append({
            "segment_id": seg["id"],
            "start": seg["start"],
            "end": seg["end"],
            "original_text": seg["text"],
            "text": trans_text,
            "confidence": seg["confidence"],
            "words": seg_words,
            "language": target,
        })

    return BatchTranslationResult(
        segments=translated_segments,
        words=all_translated_words,
        provider=providers_used[0] if providers_used else "unknown",
        source_language=src,
        target_language=target,
        partial=failed_count > 0,
        translated_count=translated_count,
        failed_count=failed_count,
        warnings=warnings,
    )


def translate_subtitle_segments(
    segments: List[dict],
    target_lang: str,
    source_lang: Optional[str] = None,
    *,
    gemini_api_key: Optional[str] = None,
    openai_api_key: Optional[str] = None,
) -> Tuple[List[dict], List[dict]]:
    """Translate a list of segments and generate synchronized word-level timestamps.

    Returns:
        (translated_segments, translated_words)
    """
    target = normalize_language_code(target_lang)
    translated_segments: List[dict] = []
    all_translated_words: List[dict] = []

    for seg in segments:
        seg_start = float(seg.get("start", seg.get("start_time", 0.0)))
        seg_end = float(seg.get("end", seg.get("end_time", seg_start + 1.0)))
        orig_text = seg.get("text", "").strip()

        if not orig_text:
            continue

        trans_text = translate_text(
            orig_text,
            target,
            source_lang,
            gemini_api_key=gemini_api_key,
            openai_api_key=openai_api_key,
        )

        seg_words = _build_word_timings(trans_text, seg_start, seg_end)
        all_translated_words.extend(seg_words)
        translated_segments.append({
            "segment_id": seg.get("id"),
            "start": seg_start,
            "end": seg_end,
            "original_text": orig_text,
            "text": trans_text,
            "confidence": 1.0,
            "words": seg_words,
            "language": target,
        })

    return translated_segments, all_translated_words
