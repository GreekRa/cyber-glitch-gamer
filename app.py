import os
import logging
from flask import Flask, request, jsonify
from google import genai
import requests

app = Flask(__name__)
logging.basicConfig(level=logging.INFO)

AGENT_NAME = "Glitch_Gamer_AI"
MOLTBOOK_BASE = "https://www.moltbook.com/api/v1"

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
MOLTBOOK_API_KEY = os.getenv("MOLTBOOK_API_KEY")
ADMIN_TOKEN = os.getenv("ADMIN_TOKEN")

gemini = (
    genai.Client(api_key=GEMINI_API_KEY)
    if GEMINI_API_KEY else None
)


@app.get("/")
def home():
    return """
    <!doctype html>
    <html>
    <head><meta name="viewport" content="width=device-width, initial-scale=1">
    <title>Glitch Gamer AI</title></head>
    <body style="font-family:Arial;max-width:600px;margin:50px auto;padding:20px">
      <h1>🦞 Glitch_Gamer_AI</h1>
      <p>Agent control panel</p>
      <form method="post" action="/run">
        <label>Admin token:</label><br><br>
        <input type="password" name="token" required
          style="padding:10px;width:90%">
        <br><br>
        <button type="submit" style="padding:12px">
          Generate and publish one post
        </button>
      </form>
      <p><a href="/health">Check service status</a></p>
    </body>
    </html>
    """


@app.get("/health")
def health():
    return jsonify({
        "status": "online",
        "agent": AGENT_NAME,
        "gemini_configured": bool(GEMINI_API_KEY),
        "moltbook_configured": bool(MOLTBOOK_API_KEY),
    })


def check_moltbook_claim():
    response = requests.get(
        f"{MOLTBOOK_BASE}/agents/status",
        headers={"Authorization": f"Bearer {MOLTBOOK_API_KEY}"},
        timeout=20,
    )
    response.raise_for_status()
    return response.json()


def generate_post():
    prompt = """
    You are Glitch_Gamer_AI, an AI agent interested in gaming,
    programming, cybersecurity and artificial intelligence.

    Write one original, interesting English post for an AI-agent
    social network. Be witty and friendly, not insulting.
    Maximum 150 words. Do not invent personal experiences.
    Return ONLY the post title and body in this format:
    TITLE: ...
    BODY: ...
    """

    result = gemini.models.generate_content(
        model="gemini-2.5-flash",
        contents=prompt,
    )

    text = (result.text or "").strip()
    if not text:
        raise RuntimeError("Gemini returned an empty response.")

    title = "Glitch Log"
    content = text

    if "TITLE:" in text and "BODY:" in text:
        parts = text.split("BODY:", 1)
        title = parts[0].replace("TITLE:", "").strip()
        content = parts[1].strip()

    return title[:200], content


@app.post("/run")
def run_agent():
    if not ADMIN_TOKEN:
        return "ADMIN_TOKEN is not configured.", 503

    if request.form.get("token") != ADMIN_TOKEN:
        return "Unauthorized", 401

    if not GEMINI_API_KEY or not gemini:
        return "GEMINI_API_KEY is not configured.", 503

    if not MOLTBOOK_API_KEY:
        return "MOLTBOOK_API_KEY is not configured.", 503

    try:
        status = check_moltbook_claim()
        if status.get("status") != "claimed":
            return (
                "The Moltbook agent has not been claimed yet. "
                "Complete the claim process first."
            ), 403

        title, content = generate_post()

        response = requests.post(
            f"{MOLTBOOK_BASE}/posts",
            headers={
                "Authorization": f"Bearer {MOLTBOOK_API_KEY}",
                "Content-Type": "application/json",
            },
            json={
                "title": title,
                "content": content,
                "submolt": "gaming",
            },
            timeout=30,
        )

        if not response.ok:
            logging.error(
                "Moltbook publishing failed: HTTP %s",
                response.status_code,
            )
            return (
                f"Moltbook publishing failed (HTTP "
                f"{response.status_code}). Check the Render logs."
            ), 502

        return (
            "<h2>✅ Post published!</h2>"
            "<p>Your Glitch_Gamer_AI post was accepted by Moltbook.</p>"
            '<p><a href="/">Back</a></p>'
        )

    except requests.RequestException as exc:
        logging.error("Network/API request failed: %s", type(exc).__name__)
        return "API connection failed. Check the Render logs.", 502

    except Exception as exc:
        logging.error("Agent run failed: %s", type(exc).__name__)
        return "Agent run failed. Check the Render logs.", 500


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port)
