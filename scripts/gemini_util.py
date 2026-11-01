"""
gemini_util.py
--------------
Tiny shared Gemini helper. Fails LOUDLY (raises with the real response body)
so a bad key / deprecated model / safety block never turns into a silent
fallback again.
"""

import os
import json
import requests

MODEL = os.environ.get("GEMINI_MODEL", "gemini-3.1-flash-lite")

# Relaxed so casual profanity doesn't trip the filter. Only high-severity blocks.
SAFETY = [
    {"category": c, "threshold": "BLOCK_ONLY_HIGH"}
    for c in (
        "HARM_CATEGORY_HARASSMENT",
        "HARM_CATEGORY_HATE_SPEECH",
        "HARM_CATEGORY_SEXUALLY_EXPLICIT",
        "HARM_CATEGORY_DANGEROUS_CONTENT",
    )
]


def call(parts, json_mode=False, temperature=0.9, timeout=60):
    key = os.environ.get("GEMINI_API_KEY")
    if not key:
        raise RuntimeError("GEMINI_API_KEY is not set")

    url = f"https://generativelanguage.googleapis.com/v1beta/models/{MODEL}:generateContent"
    gen_cfg = {"temperature": temperature}
    if json_mode:
        gen_cfg["responseMimeType"] = "application/json"

    resp = requests.post(
        url,
        headers={"x-goog-api-key": key},
        json={
            "contents": [{"parts": parts}],
            "generationConfig": gen_cfg,
            "safetySettings": SAFETY,
        },
        timeout=timeout,
    )
    if resp.status_code != 200:
        raise RuntimeError(f"Gemini HTTP {resp.status_code}: {resp.text[:500]}")

    data = resp.json()
    try:
        return data["candidates"][0]["content"]["parts"][0]["text"]
    except Exception:
        raise RuntimeError(f"Gemini returned no text (safety block?): {json.dumps(data)[:500]}")
