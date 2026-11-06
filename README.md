# Recon Desk

Order-level reconciliation of sales, settlements, COD remittances and freight for a D2C home-textiles brand.
Upload partner reports, see per order whether the right amount arrived, and get a claims list with evidence.

- Backend: FastAPI + SQLAlchemy (PostgreSQL in production, SQLite for local use)
- Frontend: React + Vite, plain CSS
- Matching and expected amounts are **rules** (`backend/app/recon.py`); AI only suggests column mappings (`backend/app/mapping.py`)

See `deployment.md` for setup, and `docs/` for the design document.

```
backend/app/recon.py      matching engine (pure functions, unit tested)
backend/app/mapping.py    column mapping: AI suggestion, fuzzy fallback, validation
backend/app/ingest.py     parsing, cleaning, bulk load
backend/app/service.py    seeding, upload processing, reconciliation run
backend/app/main.py       REST API, auth, access control
backend/app/sample.py     synthetic data generator with planted discrepancies
backend/benchmark.py      100k-row timing
frontend/src/pages/       the 8 screens
```
