# Kevin From Greece — Render deployment

This bundle contains:
- `app.py`: the Flask web service (`/`, `/health`, `/preview`, `/publish`)
- `autonomous_worker.py`: a separate long-running autonomous Moltbook worker
- `requirements.txt`: Python dependencies

## Important: deploy as TWO Render services from the SAME GitHub repository

### 1. Web Service
- Build command: `pip install -r requirements.txt`
- Start command: `gunicorn app:app --bind 0.0.0.0:$PORT`
- Environment variables: `GEMINI_API_KEY`, `MOLTBOOK_API_KEY`, `ADMIN_TOKEN`

### 2. Background Worker
- Build command: `pip install -r requirements.txt`
- Start command: `python autonomous_worker.py`
- Environment variables: `GEMINI_API_KEY`, `MOLTBOOK_API_KEY`, `POLL_SECONDS=600`
- Optional: `STATE_FILE=/var/data/kevin_state.json` only if a Render persistent disk is attached at `/var/data`.

Copy secret values into each service's Environment page; do not commit keys to GitHub.
The worker's state file is local unless a persistent disk is configured. Without a persistent disk, state may reset on redeploy/restart and duplicate prevention is less reliable.

## Behavior and safety
- Checks the feed periodically (default 10 minutes; minimum 5 minutes).
- Makes at most one write action per cycle.
- Creates its own post no more often than every 6 hours.
- It can skip posts when it has nothing useful to add.
- Check Render logs after first deploy to verify the actual Moltbook API response shapes and comment endpoint behavior.
- If the Moltbook API returns a 404/400 for feed/comments, stop the worker and adjust the endpoint to match the current API documentation before enabling it again.
