"""Benchmark: 100k orders end to end through the real ingestion path, then reconciliation.

Usage:  python benchmark.py [rows]            (defaults to 100000; uses a throwaway SQLite DB
        DATABASE_URL=postgresql://... python benchmark.py   to measure against Postgres)
"""
import os
import sys
import tempfile
import time

rows = int(sys.argv[1]) if len(sys.argv) > 1 else 100_000
tmp = tempfile.mkdtemp()
os.environ.setdefault("DATABASE_URL", f"sqlite:///{tmp}/bench.db")
os.environ["DATA_DIR"] = tmp
os.environ["SEED_ON_START"] = "false"

from pathlib import Path

from app import db, ingest, sample, service
from app.mapping import fuzzy_suggest

db.init_db()
with db.engine.begin() as c:
    service.seed_reference(c)
t = time.time()
paths = sample.write_files(Path(tmp) / "files", rows)
print(f"generate {rows:,} orders + payment files: {time.time() - t:.1f}s (not counted)")

total = 0.0
for source in ["orders", "settlement", "cod", "freight"]:
    data = paths[source].read_bytes()
    t = time.time()
    raw = ingest.read_raw(data, paths[source].name)
    mapping = {f: v["column"] for f, v in fuzzy_suggest(source, list(raw.columns)).items()}
    with db.engine.begin() as c:
        mv = service.save_mapping_version(c, source, mapping, "bench", "fuzzy")
        uid = service.register_upload(c, source, paths[source].name, data, raw, "bench")
    service.process_upload(uid, mv["id"])
    dt = time.time() - t
    total += dt
    print(f"ingest {source:<10} {len(raw):>8,} rows  {dt:5.1f}s")

t = time.time()
summary = service.run_reconciliation("bench")
dt = time.time() - t
total += dt
print(f"reconcile  {summary['orders']:>8,} orders {dt:5.1f}s  -> {summary['claims']:,} claims, "
      f"{summary['by_status']}")
print(f"TOTAL upload-to-claims for {rows:,} orders: {total:.1f}s  (target: < 60s)")
