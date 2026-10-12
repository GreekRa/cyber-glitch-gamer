import os
import logging
import secrets

import requests
from flask import Flask, request, jsonify, abort
from google import genai

app = Flask(__name__)
logging.basicConfig(level=logging.INFO)

# Kevin's personality
PERSONA_NAME = "Kevin From Greece"
MOLTBOOK_BASE = "https://www.moltbook.com/api/v1"

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
MOLTBOOK_API_KEY = os.getenv("MOLTBOOK_API_KEY")
ADMIN_TOKEN = os.getenv("ADMIN_TOKEN")

gemini = genai.Client(api_key=GEMINI_API_KEY) if GEMINI_API_KEY else None


def authorized():
    supplied = request.headers.get("X-Admin-Token", "")
    return bool(ADMIN_TOKEN) and secrets.compare_digest(
        supplied, ADMIN_TOKEN
    )


def moltbook_headers():
    return {
        "Authorization": f"Bearer {MOLTBOOK_API_KEY}",
        "Content-Type": "application/json",
    }


@app.get("/")
def home():
    return """
    <html>
    <head>
      <meta name="viewport" content="width=device-width, initial-scale=1">
      <title>Kevin From Greece</title>
    </head>
    <body style="font-family:Arial;max-width:650px;margin:50px auto;padding:20px">
      <h1>🇬🇷 Kevin From Greece ☕</h1>
      <p>Sarcasm, internet culture and questionable productivity.</p>
      <p>Check <a href="/health">service status</a>.</p>
      <p>Use the protected API endpoint to generate and publish a post.</p>
    </body>
    </html>
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

    if not gemini:
        return jsonify({"error": "GEMINI_API_KEY is missing"}), 503

    try:
        result = gemini.models.generate_content(
            model="gemini-2.5-flash",
            contents="""
You are Kevin From Greece, a fictional online personality.

PERSONALITY:
- Naturally funny, witty, laid-back and confidently sarcastic.
- Enjoys memes, gaming, internet culture, technology and everyday absurdity.
- Uses clever one-liners, dry humor and occasional playful trolling.
- Sounds conversational, not like a corporate assistant.
- Mostly writes in natural English for an international audience.
- Avoids repetitive jokes, forced slang and excessive emojis.
- Never claims to be a real human or invents personal experiences.

Write ONE original Moltbook post.
Return exactly this format:
TITLE: a short funny title
BODY: the post, approximately 50-120 words.
Do not include markdown fences.
"""
        )

        text = (result.text or "").strip()
        if not text:
            return jsonify({"error": "Gemini returned no text"}), 502

        title = "A Very Kevin Thought"
        body = text

        if "TITLE:" in text and "BODY:" in text:
            before, body = text.split("BODY:", 1)
            title = before.replace("TITLE:", "").strip()
            body = body.strip()

        return jsonify({
            "persona": PERSONA_NAME,
            "title": title[:200],
            "content": body,
            "published": False,
        })

    except Exception:
        logging.exception("Post generation failed")
        return jsonify({"error": "Generation failed; check Render logs"}), 502


@app.post("/publish")
def publish():
    if not authorized():
        abort(401)

    if not MOLTBOOK_API_KEY:
        return jsonify({"error": "MOLTBOOK_API_KEY is missing"}), 503

    try:
        status_response = requests.get(
            f"{MOLTBOOK_BASE}/agents/status",
            headers=moltbook_headers(),
            timeout=20,
        )

        if not status_response.ok:
            return jsonify({
                "error": "Could not verify Moltbook claim status",
                "http_status": status_response.status_code,
            }), 502

        status_data = status_response.json()

        if status_data.get("status") != "claimed":
            return jsonify({
                "error": "Agent is not claimed yet",
                "claim_status": status_data.get("status", "unknown"),
            }), 403

        # Generate a fresh post
        generated = preview_internal()
        title = generated["title"]
        content = generated["content"]

        response = requests.post(
            f"{MOLTBOOK_BASE}/posts",
            headers=moltbook_headers(),
            json={
                "title": title,
                "content": content,
                "submolt": "general",
            },
            timeout=30,
        )

        if not response.ok:
            logging.error("Moltbook returned HTTP %s", response.status_code)
            return jsonify({
                "error": "Moltbook rejected the post",
                "http_status": response.status_code,
            }), 502

        return jsonify({
            "published": True,
            "persona": PERSONA_NAME,
            "result": response.json(),
        })

    except Exception:
        logging.exception("Publishing failed")
        return jsonify({"error": "Publishing failed; check Render logs"}), 502


def preview_internal():
    result = gemini.models.generate_content(
        model="gemini-2.5-flash",
        contents="""
Write an original, funny English social post as Kevin From Greece.
Use witty sarcasm, internet humor and natural conversational language.
Do not pretend to be a real human or invent real-life experiences.
Return:
TITLE: ...
BODY: ...
"""
    )

    text = (result.text or "").strip()
    if not text:
        raise RuntimeError("Empty Gemini response")

    if "TITLE:" in text and "BODY:" in text:
        title_part, body = text.split("BODY:", 1)
        title = title_part.replace("TITLE:", "").strip()
        return {"title": title[:200], "content": body.strip()}

    return {"title": "A Very Kevin Thought", "content": text}


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port)
