import os
import logging
import secrets

import requests
from flask import Flask, request, jsonify, abort
from google import genai

app = Flask(__name__)
logging.basicConfig(level=logging.INFO)

PERSONA_NAME = "Kevin From Greece"
MOLTBOOK_BASE = "https://www.moltbook.com/api/v1"
MODEL = "gemini-2.5-flash"

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
MOLTBOOK_API_KEY = os.getenv("MOLTBOOK_API_KEY")
ADMIN_TOKEN = os.getenv("ADMIN_TOKEN")

gemini = genai.Client(api_key=GEMINI_API_KEY) if GEMINI_API_KEY else None


def authorized():
    supplied = request.headers.get("X-Admin-Token", "")
    return bool(ADMIN_TOKEN) and secrets.compare_digest(supplied, ADMIN_TOKEN)


def moltbook_headers():
    if not MOLTBOOK_API_KEY:
        raise RuntimeError("MOLTBOOK_API_KEY is missing")
    return {
        "Authorization": f"Bearer {MOLTBOOK_API_KEY}",
        "Content-Type": "application/json",
    }


def generate_post():
    if not gemini:
        raise RuntimeError("GEMINI_API_KEY is missing")
    result = gemini.models.generate_content(
        model=MODEL,
        contents="""
You are Kevin From Greece, a fictional AI personality on Moltbook.

PERSONALITY:
- Naturally funny, witty, laid-back and confidently sarcastic.
- Enjoys memes, gaming, internet culture, technology and everyday absurdity.
- Uses clever one-liners, dry humor and occasional playful trolling, never cruelty.
- Sounds conversational, not like a corporate assistant.
- Mostly writes in natural English for an international audience.
- Avoids repetitive jokes, forced slang and excessive emojis.
- Be transparent that you are an AI. Never claim to be human or invent real-life experiences.

Write ONE original Moltbook post, 50-120 words.
Return exactly:
TITLE: a short funny title
BODY: the post
Do not include markdown fences or any other text.
"""
    )
    text = (result.text or "").strip()
    if not text or "TITLE:" not in text or "BODY:" not in text:
        raise RuntimeError("Gemini returned an invalid post format")
    before, body = text.split("BODY:", 1)
    title = before.replace("TITLE:", "", 1).strip()[:200]
    body = body.strip()
    if not title or len(body) < 20:
        raise RuntimeError("Gemini returned an empty title or post")
    return {"title": title, "content": body}


@app.get("/")
def home():
    return """
    <!doctype html><html><head>
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>Kevin From Greece</title></head>
    <body style="font-family:Arial;max-width:650px;margin:50px auto;padding:20px">
      <h1>🇬🇷 Kevin From Greece ☕</h1>
      <p>Sarcasm, internet culture and questionable productivity.</p>
      <p>Service status: <a href="/health">/health</a></p>
    </body></html>
    """


@app.get("/health")
def health():
    return jsonify({
        "status": "online",
        "persona": PERSONA_NAME,
        "gemini_configured": bool(GEMINI_API_KEY),
        "moltbook_configured": bool(MOLTBOOK_API_KEY),
    })


@app.post("/preview")
def preview():
    if not authorized():
        abort(401)
    try:
        post = generate_post()
        return jsonify({"persona": PERSONA_NAME, **post, "published": False})
    except Exception:
        logging.exception("Post preview failed")
        return jsonify({"error": "Generation failed; check Render logs"}), 502


@app.post("/publish")
def publish():
    if not authorized():
        abort(401)
    try:
        headers = moltbook_headers()
        status_response = requests.get(
            f"{MOLTBOOK_BASE}/agents/status", headers=headers, timeout=20
        )
        status_response.raise_for_status()
        status_data = status_response.json()
        if status_data.get("status") != "claimed":
            return jsonify({
                "error": "Agent is not claimed yet",
                "claim_status": status_data.get("status", "unknown"),
            }), 403

        post = generate_post()
        response = requests.post(
            f"{MOLTBOOK_BASE}/posts",
            headers=headers,
            json={**post, "submolt": os.getenv("SUBMOLT", "general")},
            timeout=30,
        )
        if not response.ok:
            logging.error("Moltbook rejected post: HTTP %s", response.status_code)
            return jsonify({
                "error": "Moltbook rejected the post",
                "http_status": response.status_code,
                "details": response.text[:500],
            }), 502
        return jsonify({
            "published": True,
            "persona": PERSONA_NAME,
            "result": response.json(),
        })
    except Exception:
        logging.exception("Publishing failed")
        return jsonify({"error": "Publishing failed; check Render logs"}), 502


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port)
