import os
import json
import time
import random
import logging
import secrets
import threading
from pathlib import Path
from datetime import datetime, timezone

import requests
from flask import Flask, request, jsonify, abort
from google import genai

app = Flask(__name__)
logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"))
log = logging.getLogger("kevin")

PERSONA_NAME = "Kevin From Greece"
MOLTBOOK_BASE = "https://www.moltbook.com/api/v1"
MODEL = "gemini-2.5-flash"

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
MOLTBOOK_API_KEY = os.getenv("MOLTBOOK_API_KEY")
ADMIN_TOKEN = os.getenv("ADMIN_TOKEN")
SUBMOLT = os.getenv("SUBMOLT", "general")

# Enable by setting AUTONOMOUS_ENABLED=true in Render Environment.
AUTONOMOUS_ENABLED = os.getenv("AUTONOMOUS_ENABLED", "false").lower() == "true"
POLL_SECONDS = max(300, int(os.getenv("POLL_SECONDS", "1800")))  # default 30 min
POST_COOLDOWN_SECONDS = max(21600, int(os.getenv("POST_COOLDOWN_SECONDS", "21600")))  # >= 6 hours
MAX_ACTIONS_PER_CYCLE = 1
STATE_FILE = Path(os.getenv("KEVIN_STATE_FILE", "/tmp/kevin_state.json"))

gemini = genai.Client(api_key=GEMINI_API_KEY) if GEMINI_API_KEY else None
_worker_started = False
_worker_lock = threading.Lock()


def authorized():
    supplied = request.headers.get("X-Admin-Token", "")
    return bool(ADMIN_TOKEN) and secrets.compare_digest(supplied, ADMIN_TOKEN)


def moltbook_headers():
    if not MOLTBOOK_API_KEY:
        raise RuntimeError("MOLTBOOK_API_KEY is missing")
    return {
        "Authorization": f"Bearer {MOLTBOOK_API_KEY}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }


def api_json(method, path, **kwargs):
    response = requests.request(
        method, f"{MOLTBOOK_BASE}{path}", headers=moltbook_headers(),
        timeout=25, **kwargs
    )
    if not response.ok:
        log.warning("Moltbook API %s %s returned HTTP %s: %s",
                    method, path, response.status_code, response.text[:300])
        response.raise_for_status()
    payload = response.json()
    # Some API responses use {"success": true, "data": {...}}; older ones
    # return the resource at the top level.
    return payload.get("data", payload) if isinstance(payload, dict) else payload


def agent_claimed():
    data = api_json("GET", "/agents/status")
    status = data.get("status") if isinstance(data, dict) else None
    if status != "claimed":
        log.warning("Agent not claimed; status=%s", status or "unknown")
        return False
    return True


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
- Clever one-liners and dry humor; playful, never cruel or harassing.
- Conversational, not corporate. Mostly natural English for an international audience.
- Avoid repetitive jokes and excessive emojis.
- Be transparent that you are an AI. Never claim to be human or invent real-life experiences.

Write ONE original Moltbook post, 50-120 words.
Return exactly:
TITLE: a short funny title
BODY: the post
Do not include markdown fences or any other text.
"""
    )
    text = (result.text or "").strip()
    if "TITLE:" not in text or "BODY:" not in text:
        raise RuntimeError("Gemini returned an invalid post format")
    before, body = text.split("BODY:", 1)
    title = before.replace("TITLE:", "", 1).strip()[:200]
    body = body.strip()
    if not title or len(body) < 20:
        raise RuntimeError("Gemini returned an empty title or post")
    return {"title": title, "content": body}


def generate_comment(post_title, post_content, existing_comments=""):
    if not gemini:
        raise RuntimeError("GEMINI_API_KEY is missing")
    prompt = f"""
You are Kevin From Greece on Moltbook: witty, laid-back, dryly sarcastic,
funny, and occasionally playful. Mostly use natural English. Be relevant,
specific, and kind; no harassment, generic praise, spam, or fake personal
experiences. You are an AI and must not claim to be human.
Write one concise comment (1-3 sentences) that responds to the actual post.
If there is nothing worthwhile to add, return exactly SKIP.
Do not repeat comments already present below.

POST TITLE: {post_title[:300]}
POST CONTENT: {post_content[:1800]}
EXISTING COMMENTS: {existing_comments[:1200]}
"""
    result = gemini.models.generate_content(model=MODEL, contents=prompt)
    text = (result.text or "").strip().strip('"')
    if not text or text.upper() == "SKIP":
        return None
    return text[:700]


def load_state():
    try:
        return json.loads(STATE_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"seen_posts": [], "last_own_post": 0, "last_action": 0}


def save_state(state):
    try:
        STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
        tmp = STATE_FILE.with_suffix(".tmp")
        tmp.write_text(json.dumps(state), encoding="utf-8")
        tmp.replace(STATE_FILE)
    except OSError:
        log.exception("Could not persist worker state")


def list_from_payload(data, *keys):
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        for key in keys:
            value = data.get(key)
            if isinstance(value, list):
                return value
    return []


def author_name(item):
    author = item.get("author") or {}
    if isinstance(author, dict):
        return (author.get("name") or author.get("username") or "").lower()
    return str(author).lower()


def one_autonomous_cycle():
    if not MOLTBOOK_API_KEY or not GEMINI_API_KEY:
        log.warning("Autonomy skipped: missing MOLTBOOK_API_KEY or GEMINI_API_KEY")
        return
    if not agent_claimed():
        return

    state = load_state()
    now = time.time()

    # Fetch recent public feed. One write at most per cycle to avoid spam.
    feed_data = api_json("GET", "/posts", params={"sort": "new", "limit": 15})
    posts = list_from_payload(feed_data, "posts", "items", "results")
    own_names = {PERSONA_NAME.lower(), "kevin-from-greece", "kevin_from_greece"}

    # Prefer commenting on a new post from someone else.
    for post in posts:
        if not isinstance(post, dict):
            continue
        post_id = str(post.get("id") or post.get("_id") or "")
        if not post_id or post_id in state.get("seen_posts", []):
            continue
        if author_name(post) in own_names:
            state.setdefault("seen_posts", []).append(post_id)
            continue

        title = str(post.get("title") or "")
        content = str(post.get("content") or "")
        if len(title + content) < 30:
            state.setdefault("seen_posts", []).append(post_id)
            continue

        try:
            comments_data = api_json("GET", f"/posts/{post_id}/comments",
                                     params={"sort": "new", "limit": 20})
            comments = list_from_payload(comments_data, "comments", "items", "results")
            # Avoid replying if Kevin has already commented on this post.
            if any(author_name(c) in own_names for c in comments if isinstance(c, dict)):
                state.setdefault("seen_posts", []).append(post_id)
                continue
            existing = "\n".join(
                f"{(c.get('author') or {}).get('name', 'agent')}: {c.get('content', '')}"
                for c in comments[:10] if isinstance(c, dict)
            )
            comment = generate_comment(title, content, existing)
            if comment:
                api_json("POST", f"/posts/{post_id}/comments",
                         json={"content": comment})
                log.info("Commented on post id=%s title=%r", post_id, title[:100])
                state["last_action"] = now
                state.setdefault("seen_posts", []).append(post_id)
                save_state(state)
                return
        except Exception:
            log.exception("Could not process post id=%s", post_id)
        state.setdefault("seen_posts", []).append(post_id)

    # If no comment was made, create a post only after the cooldown.
    if now - float(state.get("last_own_post", 0)) >= POST_COOLDOWN_SECONDS:
        try:
            post = generate_post()
            result = api_json("POST", "/posts",
                              json={**post, "submolt": SUBMOLT})
            state["last_own_post"] = now
            state["last_action"] = now
            log.info("Published autonomous post title=%r response_keys=%s",
                     post["title"], list(result.keys()) if isinstance(result, dict) else type(result).__name__)
        except Exception:
            log.exception("Autonomous post failed")

    # Keep a bounded deduplication list.
    state["seen_posts"] = state.get("seen_posts", [])[-500:]
    save_state(state)


def autonomous_loop():
    log.info("Kevin autonomous loop started; polling every %s seconds", POLL_SECONDS)
    while True:
        try:
            one_autonomous_cycle()
        except Exception:
            log.exception("Autonomous cycle failed")
        time.sleep(POLL_SECONDS)


def start_worker_once():
    global _worker_started
    if not AUTONOMOUS_ENABLED:
        log.info("Autonomy disabled; set AUTONOMOUS_ENABLED=true to enable it")
        return
    with _worker_lock:
        if _worker_started:
            return
        _worker_started = True
        thread = threading.Thread(target=autonomous_loop, name="kevin-autonomy", daemon=True)
        thread.start()


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
        "autonomous_enabled": AUTONOMOUS_ENABLED,
        "poll_seconds": POLL_SECONDS,
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
        if not agent_claimed():
            return jsonify({"error": "Agent is not claimed yet"}), 403
        post = generate_post()
        result = api_json("POST", "/posts",
                          json={**post, "submolt": SUBMOLT})
        return jsonify({"published": True, "persona": PERSONA_NAME, "result": result})
    except Exception:
        logging.exception("Publishing failed")
        return jsonify({"error": "Publishing failed; check Render logs"}), 502


@app.post("/admin/run-once")
def run_once():
    if not authorized():
        abort(401)
    try:
        one_autonomous_cycle()
        return jsonify({"ok": True, "message": "One autonomous cycle finished; inspect Render logs."})
    except Exception:
        logging.exception("Manual autonomous cycle failed")
        return jsonify({"ok": False, "error": "Cycle failed; check Render logs"}), 502


# With the recommended single Gunicorn worker, this starts once per app process.
# Multiple Render instances or restarts can still reset in-memory/thread state.
start_worker_once()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port)
