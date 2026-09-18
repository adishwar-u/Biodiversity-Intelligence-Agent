# Biodiversity Intelligence Agent — frontend

React (Vite) chat UI for the agent. Talks to the FastAPI backend in
[`../server.py`](../server.py) — no reasoning logic lives here, this is
purely a renderer for the session/profile/recommendation JSON that API
returns.

## Run

From this directory:

```bash
npm install
npm run dev
```

Requires the backend running separately (from the project root):

```bash
pip install -r requirements.txt
uvicorn server:app --reload
```

Backend defaults to `http://localhost:8000`; override with `VITE_API_URL`
in `.env` if it runs elsewhere.

## Layout

- `src/api.js` — fetch wrapper for `/api/session`, `/api/chat`, `/api/reset`
- `src/App.jsx` — chat state, sidebar profile panel, message list
- `src/RecommendationCard.jsx` — one intervention card (mechanism, causal
  cascade, metrics, tradeoffs, sources)
- `src/App.css` — plain CSS, no framework
