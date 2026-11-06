# Deployment and running Recon Desk

GitHub: `<PASTE YOUR GITHUB REPO URL HERE>`
Live app: `<PASTE YOUR LIVE URL HERE, or write "not deployed">`

## 1. Run locally

Prerequisites: Python 3.11+ and Node 20+. No database server is needed locally: it uses SQLite by default.

```bash
git clone <repo-url> recon-desk && cd recon-desk

# Backend (terminal 1)
cd backend
python -m venv .venv && source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp ../.env.example .env                                  # optional; defaults work without it
export DEMO_PASSWORD=demo-pass-1234 JWT_SECRET=any-long-random-string   # Windows: use `set`
uvicorn app.main:app --port 8000
```

On first start the app creates the tables, the two demo users, the rate cards, and loads about 10,000 synthetic orders
through the same upload and reconciliation code that real files use (takes about 2 seconds). Open the API docs at
http://localhost:8000/docs.

```bash
# Frontend with hot reload (terminal 2)
cd frontend
npm install
npm run dev                                              # http://localhost:5173 (proxies /api to :8000)
```

Or serve everything from one process: `cd frontend && npm install && npm run build`, restart the backend, and open
http://localhost:8000.

### Tests and benchmark

```bash
cd backend
python -m pytest tests -q                                # 43 tests: engine, API, access control, AI fallback
TEST_DATABASE_URL=postgresql://user:pass@localhost/db python -m pytest tests -q   # same suite on PostgreSQL
python benchmark.py 100000                               # 100k orders + ~127k payment rows, upload to claims

cd ../frontend
npm test                                                 # 8 screen smoke tests; needs the backend running on :8000
```

### Try the upload flow with the sample files

Sign in as the finance executive, open **Upload**, choose "Settlement report" and drop
`sample_data/settlement_new_format.csv`. Its headers differ from the ones the app has seen. Review the suggested
mapping and the 20-row preview, approve it, load it, then re-run reconciliation: claims for those late payouts
disappear and money at risk drops.

## 2. Demo logins

| Role | Email | Can do |
|---|---|---|
| Finance executive | `finance@companya.test` | Everything: upload, approve mappings, edit rate cards, change claim status, re-run, export |
| Co-founder | `cofounder@companya.test` | View everything, export claims, reveal masked customer details (logged). Cannot change data |

Password for both: the value of `DEMO_PASSWORD`. Locally this is `demo-pass-1234` as set above. On the hosted app set
`DEMO_PASSWORD=demo-pass-1234` as well so this document stays accurate. These are throwaway credentials for synthetic data only.

## 3. How it is deployed

One Docker image serves the API and the built React app (`Dockerfile`, multi-stage). `render.yaml` is a Render blueprint
for one web service plus one managed PostgreSQL database.

1. Push the repository to GitHub (public).
2. On Render: New, Blueprint, pick the repo. It creates `recon-desk` (web) and `recon-db` (Postgres).
3. When prompted, set `DEMO_PASSWORD` (and optionally `ANTHROPIC_API_KEY`).
4. First boot seeds the demo data (`SEED_ON_START=true`). Health check: `/api/health`.

Any host that runs a Docker container and provides a PostgreSQL URL works the same way (Railway, Fly.io, a VM).
The app listens on `$PORT`.

## 4. Environment variables (names only)

| Name | Required | Purpose |
|---|---|---|
| `DATABASE_URL` | yes in production | PostgreSQL connection string. Defaults to local SQLite |
| `JWT_SECRET` | yes in production | Signs login tokens. If unset, a random one is generated per process |
| `DEMO_PASSWORD` | yes | Password given to the two seeded demo users |
| `ANTHROPIC_API_KEY` | no | Enables AI column-mapping suggestions. Without it the fuzzy fallback is used |
| `ANTHROPIC_MODEL` | no | Model used for suggestions (default in `.env.example`) |
| `SEED_ON_START` | no | `true` loads demo data when the database is empty |
| `SEED_ORDERS` | no | Number of synthetic orders to seed (default 10000) |
| `DATA_DIR` | no | Where uploaded files and the SQLite file live |
| `MAX_UPLOAD_MB` | no | Upload size limit (default 50) |
| `CORS_ORIGINS` | no | Only needed when the frontend is served from another origin |
| `TOLERANCE_INR`, `RETURN_WINDOW_DAYS` | no | Override the Rs 10 tolerance and the 7-day return window |

No secret is stored in the repository. `.env` is git-ignored; `.env.example` has names only.

## 5. Notes for the reviewer

- Uploaded files are stored on the server's disk (`DATA_DIR`). On a free Render plan the disk is ephemeral, so uploads
  made on the hosted demo may be lost on restart. The database keeps the loaded rows.
- Without `ANTHROPIC_API_KEY` the "AI" suggestion is the fuzzy header matcher and the screen says so. With a key, Claude
  is tried first and the fuzzy matcher is still the fallback.
- Dates in the seed data are relative to the day of the first boot, so the age buckets always look realistic.
