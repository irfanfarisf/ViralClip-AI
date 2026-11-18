"""AI and Rule-based YouTube Shorts Metadata Generation.

Generates high-engagement, truthful metadata for vertical video clips:
1. Three engaging title suggestions (< 60 chars)
2. One recommended title
3. Short YouTube Shorts description (2-3 concise lines)
4. Relevant hashtags (4-6 tags starting with #)
5. Thumbnail text suggestion (2-4 bold uppercase words)
6. Suggested thumbnail timestamp (optimal frame within the clip window)

Strictly grounded in the actual clip transcript — never invents events or facts.
Provides deterministic local rule-based generation with optional Gemini/OpenAI API enhancement.
"""
from __future__ import annotations

import json
import logging
import re
from typing import Any, Dict, List, Optional

import httpx

from backend.app.config import settings

log = logging.getLogger("viralclip.metadata_generator")

WORD_RE = re.compile(r"[\w']+")
SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?])\s+")

STOP_WORDS = {
    "a", "about", "above", "after", "again", "against", "all", "am", "an", "and", "any", "are", "aren't",
    "as", "at", "be", "because", "been", "before", "being", "below", "between", "both", "but", "by",
    "can't", "cannot", "could", "couldn't", "did", "didn't", "do", "does", "doesn't", "doing", "don't",
    "down", "during", "each", "few", "for", "from", "further", "had", "hadn't", "has", "hasn't", "have",
    "haven't", "having", "he", "he'd", "he'll", "he's", "her", "here", "here's", "hers", "herself",
    "him", "himself", "his", "how", "how's", "i", "i'd", "i'll", "i'm", "i've", "if", "in", "into",
    "is", "isn't", "it", "it's", "its", "itself", "let's", "me", "more", "most", "mustn't", "my",
    "myself", "no", "nor", "not", "of", "off", "on", "once", "only", "or", "other", "ought", "our",
    "ours", "ourselves", "out", "over", "own", "same", "shan't", "she", "she'd", "she'll", "she's",
    "should", "shouldn't", "so", "some", "such", "than", "that", "that's", "the", "their", "theirs",
    "them", "themselves", "then", "there", "there's", "these", "they", "they'd", "they'll", "they're",
    "they've", "this", "those", "through", "to", "too", "under", "until", "up", "very", "was", "wasn't",
    "we", "we'd", "we'll", "we're", "we've", "were", "weren't", "what", "what's", "when", "when's",
    "where", "where's", "which", "while", "who", "who's", "whom", "why", "why's", "with", "won't",
    "would", "wouldn't", "you", "you'd", "you'll", "you're", "you've", "your", "yours", "yourself",
    "yourselves", "like", "just", "really", "actually", "yeah", "okay", "um", "uh", "gonna", "wanna",
}

CATEGORY_EMOJIS = {
    "hype": "🔥",
    "funny": "🤣",
    "surprise": "🤯",
    "story": "📖",
    "explanation": "💡",
    "hook": "⚡",
    "energy": "⚡",
    "laughter": "😂",
    "insight": "💡",
}

CATEGORY_TAGS = {
    "hype": "#gaming",
    "funny": "#comedy",
    "surprise": "#plotTwist",
    "story": "#storytime",
    "explanation": "#howTo",
    "hook": "#shortsViral",
    "energy": "#clutch",
    "laughter": "#funnyShorts",
    "insight": "#tipsAndTricks",
}

THUMBNAIL_PHRASES = {
    "hype": ["INSANE MOMENT!", "WHAT A PLAY!", "LET'S GO!", "UNBELIEVABLE!"],
    "funny": ["WAIT FOR IT! 😂", "CAN'T STOP LAUGHING", "HE DID NOT! 💀", "INSTANT REGRET"],
    "surprise": ["NO WAY! 🤯", "PLOT TWIST!", "HOW DID THIS HAPPEN?", "DID YOU SEE THAT?!"],
    "story": ["TRUE STORY!", "IT ACTUALLY HAPPENED", "LISTEN TO THIS", "NEVER EXPECTED THIS"],
    "explanation": ["PRO TIP 💡", "HOW IT WORKS", "DO THIS INSTEAD", "THE REAL SECRET"],
    "hook": ["WATCH THIS! ⚡", "DON'T MISS THIS", "WAIT TILL THE END", "MUST WATCH!"],
}


def clean_text_for_title(text: str, max_chars: int = 55) -> str:
    cleaned = re.sub(r"\s+", " ", text).strip().strip("\"'").rstrip(".!?,")
    if len(cleaned) > max_chars:
        trimmed = cleaned[:max_chars - 1].rsplit(" ", 1)[0]
        cleaned = (trimmed or cleaned[:max_chars - 1]) + "…"
    return cleaned


def extract_keywords(text: str, max_words: int = 4) -> List[str]:
    words = WORD_RE.findall(text.lower())
    seen = set()
    result = []
    for w in words:
        if len(w) >= 4 and w not in STOP_WORDS and not w.isdigit() and w not in seen:
            seen.add(w)
            result.append(w)
            if len(result) >= max_words:
                break
    return result


def generate_rule_based_metadata(
    transcript_text: str,
    duration: float,
    start_time: float = 0.0,
    end_time: Optional[float] = None,
    category: str = "hype",
    words: Optional[List[dict]] = None,
) -> Dict[str, Any]:
    """Deterministic, truthful metadata generation based strictly on the transcript."""
    if end_time is None:
        end_time = start_time + max(duration, 1.0)
    duration = max(end_time - start_time, 1.0)

    cat = category.lower() if category else "hype"
    emoji = CATEGORY_EMOJIS.get(cat, "🔥")
    text = transcript_text.strip() if transcript_text else ""

    # Split into sentences or clauses
    raw_sentences = [s.strip() for s in SENTENCE_SPLIT_RE.split(text) if s.strip()]
    if not raw_sentences and text:
        raw_sentences = [text]

    # --- Title 1: Recommended Hook (best punchline or opening hook) ---
    best_sentence = raw_sentences[0] if raw_sentences else "Unbelievable Short Highlight"
    # Prefer sentence with exclamation or question if available
    for s in raw_sentences:
        if any(punct in s for punct in ("!", "?")) and len(s) >= 12:
            best_sentence = s
            break
    t1_clean = clean_text_for_title(best_sentence, 50)
    title_1 = f"{emoji} {t1_clean}"

    # --- Title 2: Question / Curiosity Angle ---
    question_candidates = [s for s in raw_sentences if "?" in s]
    if question_candidates:
        t2_clean = clean_text_for_title(question_candidates[0], 50)
        title_2 = f"🤔 {t2_clean}"
    else:
        # Grounded curiosity title based on category and first phrase
        first_phrase = clean_text_for_title(raw_sentences[0] if raw_sentences else "This Moment", 35)
        curiosity_prefixes = {
            "funny": "Wait, Did He Say: ",
            "surprise": "Did That Just Happen?! ",
            "hype": "How Did This Happen?! ",
            "story": "The Story Behind: ",
            "explanation": "Here Is The Truth: ",
            "hook": "Wait For The End: ",
        }
        prefix = curiosity_prefixes.get(cat, "Look At This: ")
        t2_body = clean_text_for_title(f"{prefix}\"{first_phrase}\"", 54)
        title_2 = t2_body

    # --- Title 3: High Energy / Action Statement ---
    if len(raw_sentences) > 1 and raw_sentences[-1] != best_sentence:
        alt_sentence = raw_sentences[-1]
    elif len(raw_sentences) > 2:
        alt_sentence = raw_sentences[1]
    else:
        alt_sentence = best_sentence

    keywords = extract_keywords(text, 3)
    kw_str = " ".join(k.capitalize() for k in keywords[:2]) if keywords else "Clip"
    t3_clean = clean_text_for_title(alt_sentence, 45)

    action_frames = {
        "hype": f"⚡ Insane {kw_str}! ({t3_clean})",
        "funny": f"😂 Comedic Timing: {t3_clean}",
        "surprise": f"🤯 Plot Twist in {kw_str}!",
        "story": f"📖 Real Experience: {t3_clean}",
        "explanation": f"💡 Actionable Tip: {t3_clean}",
        "hook": f"🎯 You Need To See: {t3_clean}",
    }
    title_3 = clean_text_for_title(action_frames.get(cat, f"🔥 Peak Moment: {t3_clean}"), 55)

    # Ensure titles are distinct
    titles = [title_1]
    if title_2 != title_1:
        titles.append(title_2)
    else:
        titles.append(f"👀 Watch What Happened! ({clean_text_for_title(text, 25)})")

    if title_3 not in titles:
        titles.append(title_3)
    else:
        titles.append(f"🏆 Top Clip Highlight: {clean_text_for_title(text, 30)}")

    titles = titles[:3]
    while len(titles) < 3:
        titles.append(f"✨ Viral Short Moment #{len(titles)+1}")

    recommended_title = titles[0]

    # --- Description: 2-3 concise lines grounded in transcript ---
    summary_sentence = clean_text_for_title(text, 140) if text else "Exciting vertical clip highlight."
    desc_lines = [
        f"\"{summary_sentence}\"",
        f"⏱️ Highlight timecode: {start_time:.1f}s - {end_time:.1f}s ({duration:.1f}s duration).",
        "🔥 Edited into 9:16 vertical short with auto animated subtitles.",
    ]
    description = "\n\n".join(desc_lines)

    # --- Hashtags ---
    tags = ["#shorts", "#viral"]
    cat_tag = CATEGORY_TAGS.get(cat, f"#{cat}")
    if cat_tag not in tags:
        tags.append(cat_tag)

    for kw in keywords:
        htag = f"#{kw.lower()}"
        if htag not in tags:
            tags.append(htag)
        if len(tags) >= 5:
            break

    # --- Thumbnail Text Suggestion (2-4 uppercase bold words) ---
    thumb_phrases = THUMBNAIL_PHRASES.get(cat, THUMBNAIL_PHRASES["hype"])
    low_text = text.lower()
    if "no way" in low_text:
        thumbnail_text = "NO WAY! 🤯"
    elif "clutch" in low_text:
        thumbnail_text = "INSANE CLUTCH!"
    elif "impossible" in low_text:
        thumbnail_text = "IT'S IMPOSSIBLE!"
    elif "wait" in low_text or "look" in low_text:
        thumbnail_text = "WAIT FOR IT! 👀"
    elif "how did" in low_text:
        thumbnail_text = "HOW DID HE?! ⚡"
    elif keywords:
        thumbnail_text = f"{keywords[0].upper()} MOMENT!"
    else:
        thumbnail_text = thumb_phrases[0]

    # --- Suggested Thumbnail Timestamp ---
    # Default: 42% through the clip duration
    suggested_ts = start_time + duration * 0.42
    if words:
        # Check if any word carries exclamation or high energy
        for w in words:
            w_text = w.get("word", "")
            w_start = float(w.get("start", start_time))
            if start_time <= w_start <= end_time:
                if any(k in w_text.lower() for k in ("!", "insane", "crazy", "wow", "holy", "no way")):
                    suggested_ts = w_start
                    break

    suggested_ts = round(min(max(suggested_ts, start_time), end_time), 2)

    return {
        "titles": titles,
        "recommended_title": recommended_title,
        "description": description,
        "hashtags": tags,
        "thumbnail_text": thumbnail_text,
        "thumbnail_timestamp": suggested_ts,
    }


def generate_gemini_metadata(
    transcript_text: str,
    duration: float,
    start_time: float,
    end_time: float,
    category: str,
    api_key: str,
) -> Optional[Dict[str, Any]]:
    """Generate shorts metadata via Google Gemini API (gemini-2.0-flash)."""
    try:
        url = "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent"
        headers = {"x-goog-api-key": api_key}
        prompt = (
            "You are an expert short-form YouTube Shorts and TikTok video editor.\n"
            "Generate metadata strictly grounded in this transcript. Do NOT invent events or facts.\n"
            "IMPORTANT: Write the titles, description, hashtags, and thumbnail text in the SAME LANGUAGE as the transcript (e.g. Malayalam if the transcript is in Malayalam, Hindi if in Hindi, English if in English).\n"
            "Avoid misleading clickbait. Keep titles concise (< 60 chars) and engaging.\n\n"
            f"Transcript: \"{transcript_text}\"\n"
            f"Category: {category}\n"
            f"Time window: {start_time:.1f}s to {end_time:.1f}s (duration: {duration:.1f}s)\n\n"
            "Output valid JSON ONLY with the following schema:\n"
            "{\n"
            '  "titles": ["title 1", "title 2", "title 3"],\n'
            '  "recommended_title": "one of the titles above",\n'
            '  "description": "2-3 sentence description summarizing the real transcript",\n'
            '  "hashtags": ["#shorts", "#tag1", "#tag2", "#tag3", "#tag4"],\n'
            '  "thumbnail_text": "2-4 PUNCHY UPPERCASE WORDS",\n'
            f'  "thumbnail_timestamp": <float between {start_time:.1f} and {end_time:.1f}>\n'
            "}"
        )
        payload = {
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {"temperature": 0.3, "responseMimeType": "application/json"},
        }
        resp = httpx.post(url, json=payload, headers=headers, timeout=10.0)
        if resp.status_code == 200:
            data = resp.json()
            raw_text = data["candidates"][0]["content"]["parts"][0]["text"]
            parsed = json.loads(raw_text)
            titles = parsed.get("titles", [])
            if isinstance(titles, list) and len(titles) >= 3:
                ts = float(parsed.get("thumbnail_timestamp", start_time + duration * 0.42))
                ts = round(min(max(ts, start_time), end_time), 2)
                return {
                    "titles": [str(t)[:60] for t in titles[:3]],
                    "recommended_title": str(parsed.get("recommended_title", titles[0]))[:60],
                    "description": str(parsed.get("description", "")),
                    "hashtags": [str(h) for h in parsed.get("hashtags", ["#shorts", "#viral"])],
                    "thumbnail_text": str(parsed.get("thumbnail_text", "VIRAL SHORT")).upper()[:30],
                    "thumbnail_timestamp": ts,
                }
    except Exception as exc:
        log.warning("Gemini metadata generation failed, using rule-based fallback: %s", exc)
    return None


def generate_openai_metadata(
    transcript_text: str,
    duration: float,
    start_time: float,
    end_time: float,
    category: str,
    api_key: str,
) -> Optional[Dict[str, Any]]:
    """Generate shorts metadata via OpenAI API (gpt-4o-mini)."""
    try:
        url = "https://api.openai.com/v1/chat/completions"
        prompt = (
            "Generate YouTube Shorts metadata based strictly on this transcript. "
            "Write the titles, description, hashtags and thumbnail text in the SAME LANGUAGE as the transcript (e.g. Malayalam, Hindi, Tamil, English). "
            "Do NOT invent events or use misleading clickbait. Titles must be under 60 characters.\n\n"
            f"Transcript: \"{transcript_text}\"\n"
            f"Category: {category}\n"
            f"Time window: {start_time:.1f}s to {end_time:.1f}s ({duration:.1f}s)\n\n"
            "Return JSON object with keys: titles (list of 3 strings), recommended_title (string), "
            "description (string), hashtags (list of 4-6 strings with #), thumbnail_text (2-4 uppercase words), "
            f"thumbnail_timestamp (float between {start_time:.1f} and {end_time:.1f})."
        )
        payload = {
            "model": "gpt-4o-mini",
            "messages": [
                {"role": "system", "content": "You are a professional YouTube Shorts editor. Output JSON only."},
                {"role": "user", "content": prompt},
            ],
            "response_format": {"type": "json_object"},
            "temperature": 0.3,
        }
        headers = {"Authorization": f"Bearer {api_key}"}
        resp = httpx.post(url, json=payload, headers=headers, timeout=10.0)
        if resp.status_code == 200:
            data = resp.json()
            parsed = json.loads(data["choices"][0]["message"]["content"])
            titles = parsed.get("titles", [])
            if isinstance(titles, list) and len(titles) >= 3:
                ts = float(parsed.get("thumbnail_timestamp", start_time + duration * 0.42))
                ts = round(min(max(ts, start_time), end_time), 2)
                return {
                    "titles": [str(t)[:60] for t in titles[:3]],
                    "recommended_title": str(parsed.get("recommended_title", titles[0]))[:60],
                    "description": str(parsed.get("description", "")),
                    "hashtags": [str(h) for h in parsed.get("hashtags", ["#shorts", "#viral"])],
                    "thumbnail_text": str(parsed.get("thumbnail_text", "VIRAL SHORT")).upper()[:30],
                    "thumbnail_timestamp": ts,
                }
    except Exception as exc:
        log.warning("OpenAI metadata generation failed, using rule-based fallback: %s", exc)
    return None


def generate_shorts_metadata(
    transcript_text: str,
    duration: float,
    start_time: float = 0.0,
    end_time: Optional[float] = None,
    category: str = "hype",
    words: Optional[List[dict]] = None,
    gemini_api_key: Optional[str] = None,
    openai_api_key: Optional[str] = None,
    use_ai_api: bool = True,
) -> Dict[str, Any]:
    """Generate high-converting, truthful shorts metadata with AI or deterministic fallback."""
    if end_time is None:
        end_time = start_time + max(duration, 1.0)
    duration = max(end_time - start_time, 1.0)

    # Try Gemini if key is available
    gkey = gemini_api_key or settings.GEMINI_API_KEY
    if use_ai_api and gkey:
        res = generate_gemini_metadata(transcript_text, duration, start_time, end_time, category, gkey)
        if res:
            return res

    # Try OpenAI if key is available
    okey = openai_api_key or settings.OPENAI_API_KEY
    if use_ai_api and okey:
        res = generate_openai_metadata(transcript_text, duration, start_time, end_time, category, okey)
        if res:
            return res

    # Fallback to local rule-based generator
    return generate_rule_based_metadata(
        transcript_text=transcript_text,
        duration=duration,
        start_time=start_time,
        end_time=end_time,
        category=category,
        words=words,
    )
