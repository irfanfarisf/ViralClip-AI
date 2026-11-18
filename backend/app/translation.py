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

import logging
import re
from typing import Dict, List, Optional, Tuple

import httpx

from backend.app.config import settings

log = logging.getLogger("viralclip.translation")

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

def _translate_via_gemini(
    text: str,
    target_lang: str,
    api_key: str,
    source_lang: Optional[str] = None,
) -> Optional[str]:
    """Translate text using Google Gemini 2.0 Flash."""
    try:
        url = "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent"
        headers = {"x-goog-api-key": api_key}
        target_name = SUPPORTED_LANGUAGES.get(target_lang, target_lang)
        src_clause = f"from {source_lang} " if source_lang and source_lang != "auto" else ""
        prompt = (
            f"You are an expert video subtitle translator.\n"
            f"Translate the following text {src_clause}into {target_name}.\n"
            f"Requirements:\n"
            f"- Preserve meaning, natural colloquial tone, and emotional energy suitable for short-form video subtitles.\n"
            f"- Output ONLY the translated text without explanations, quotes, or markdown.\n\n"
            f"Text: {text}"
        )
        payload = {
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {"temperature": 0.2, "maxOutputTokens": 500},
        }
        resp = httpx.post(url, json=payload, headers=headers, timeout=8.0)
        if resp.status_code == 200:
            data = resp.json()
            out = data["candidates"][0]["content"]["parts"][0]["text"].strip()
            if out:
                return out
    except Exception as exc:
        log.warning("Gemini translation failed: %s", exc)
    return None


def _translate_via_openai(
    text: str,
    target_lang: str,
    api_key: str,
    source_lang: Optional[str] = None,
) -> Optional[str]:
    """Translate text using OpenAI (gpt-4o-mini)."""
    try:
        url = "https://api.openai.com/v1/chat/completions"
        target_name = SUPPORTED_LANGUAGES.get(target_lang, target_lang)
        src_clause = f"from {source_lang} " if source_lang and source_lang != "auto" else ""
        prompt = (
            f"Translate the following short video subtitle {src_clause}into {target_name}.\n"
            f"Keep the natural tone, emotion and conciseness for video captions.\n"
            f"Return ONLY the translated text without extra formatting or quotes.\n\n"
            f"{text}"
        )
        payload = {
            "model": "gpt-4o-mini",
            "messages": [
                {"role": "system", "content": "You are a professional subtitle translator. Output translated text only."},
                {"role": "user", "content": prompt},
            ],
            "temperature": 0.2,
        }
        headers = {"Authorization": f"Bearer {api_key}"}
        resp = httpx.post(url, json=payload, headers=headers, timeout=8.0)
        if resp.status_code == 200:
            data = resp.json()
            out = data["choices"][0]["message"]["content"].strip()
            if out:
                return out
    except Exception as exc:
        log.warning("OpenAI translation failed: %s", exc)
    return None


def _translate_via_public_api(
    text: str,
    target_lang: str,
    source_lang: Optional[str] = None,
) -> Optional[str]:
    """Translate text using public translation endpoint with timeout."""
    try:
        url = "https://translate.googleapis.com/translate_a/single"
        sl = source_lang if source_lang and source_lang != "auto" else "auto"
        params = {
            "client": "gtx",
            "sl": sl,
            "tl": target_lang,
            "dt": "t",
            "q": text,
        }
        resp = httpx.get(url, params=params, timeout=5.0)
        if resp.status_code == 200:
            data = resp.json()
            translated = "".join(item[0] for item in data[0] if item and item[0])
            if translated.strip():
                return translated.strip()
    except Exception as exc:
        log.debug("Public translation API unavailable (%s); falling back to offline engine", exc)
    return None


def _translate_offline_rule_based(text: str, target_lang: str) -> str:
    """Offline rule-based fallback when offline or no API keys available."""
    target_dict = OFFLINE_PHRASE_DICTIONARY.get(target_lang, {})
    low_text = text.lower().strip()

    # Exact phrase match
    if low_text in target_dict:
        return target_dict[low_text]

    # Partial phrase substitution for creator terms
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

    # If source and target are the same language, no translation needed
    if target != "auto" and src != "auto" and target == src:
        return clean_text

    # 1. Try Gemini
    gkey = gemini_api_key or settings.GEMINI_API_KEY
    if gkey:
        res = _translate_via_gemini(clean_text, target, gkey, src)
        if res:
            return res

    # 2. Try OpenAI
    okey = openai_api_key or settings.OPENAI_API_KEY
    if okey:
        res = _translate_via_openai(clean_text, target, okey, src)
        if res:
            return res

    # 3. Try Public Web API
    res = _translate_via_public_api(clean_text, target, src)
    if res:
        return res

    # 4. Offline Fallback
    return _translate_offline_rule_based(clean_text, target)


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
        dur = max(seg_end - seg_start, 0.1)
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

        # Distribute translated words evenly across the original spoken window [seg_start, seg_end]
        tokens = trans_text.split()
        seg_words = []
        if tokens:
            step = dur / len(tokens)
            for i, tok in enumerate(tokens):
                w_start = round(seg_start + i * step, 3)
                w_end = round(seg_start + (i + 1) * step, 3)
                w_obj = {
                    "word": tok,
                    "start": w_start,
                    "end": w_end,
                    "probability": 1.0,
                }
                seg_words.append(w_obj)
                all_translated_words.append(w_obj)

        translated_segments.append({
            "start": seg_start,
            "end": seg_end,
            "text": trans_text,
            "confidence": 1.0,
            "words": seg_words,
            "language": target,
        })

    return translated_segments, all_translated_words
