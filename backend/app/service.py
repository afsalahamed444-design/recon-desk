"""Database-facing operations. Kept out of the HTTP layer so seeding, tests and the API share them."""
from __future__ import annotations

import time
from datetime import date

import pandas as pd
from sqlalchemy import delete, func, insert, select, update

from . import db, ingest
from .config import settings
from .mapping import CANONICAL, fuzzy_suggest, required_fields
from .recon import reconcile
from .security import COFOUNDER, EXEC, hash_password
from . import sample


def audit(conn, email: str, action: str, detail: str = ""):
    conn.execute(insert(db.audit_log).values(user_email=email, action=action, detail=detail[:500]))


# ---- reference data -----------------------------------------------------------------------------
def seed_reference(conn):
    if conn.execute(select(func.count()).select_from(db.users)).scalar():
        return
    pw = hash_password(settings.demo_password)
    conn.execute(insert(db.users), [
        dict(email="finance@companya.test", name="Finance Executive", role=EXEC, password_hash=pw),
        dict(email="cofounder@companya.test", name="Finance Co-founder", role=COFOUNDER, password_hash=pw),
    ])
    for name in sample.RATE_CARDS:
        pid = conn.execute(insert(db.partners).values(name=name, type="channel")).inserted_primary_key[0]
        conn.execute(insert(db.rate_cards).values(partner_id=pid, effective_from=date(2026, 4, 1),
                                                  **sample.RATE_CARDS[name]))
    for name, slabs in sample.SLABS.items():
        pid = conn.execute(insert(db.partners).values(name=name, type="courier")).inserted_primary_key[0]
        conn.execute(insert(db.rate_cards).values(partner_id=pid, effective_from=date(2026, 4, 1),
                                                  weight_slabs=slabs, remit_days=10))


def load_rates(conn) -> tuple[pd.DataFrame, dict]:
    """Latest rate card per partner. ASSUMPTION: one rate card in force at a time (latest effective_from)."""
    rows = conn.execute(select(db.partners.c.name, db.partners.c.type, db.rate_cards).select_from(
        db.partners.join(db.rate_cards, db.rate_cards.c.partner_id == db.partners.c.id))
        .order_by(db.rate_cards.c.effective_from, db.rate_cards.c.id)).mappings().all()
    latest = {}
    for r in rows:
        latest[r["name"]] = r
    chan = pd.DataFrame([{k: r[k] for k in ["name", "commission_pct", "prepaid_fee_pct", "cod_fee_pct", "fixed_fee",
                                            "return_fee_pct", "remit_days", "cod_by_courier"]}
                         for r in latest.values() if r["type"] == "channel"]).set_index("name")
    slabs = {r["name"]: r["weight_slabs"] for r in latest.values() if r["type"] == "courier"}
    return chan, slabs


# ---- mappings -----------------------------------------------------------------------------------
def active_mapping(conn, source: str) -> dict | None:
    row = conn.execute(select(db.mapping_versions.c.mapping).where(
        db.mapping_versions.c.source == source, db.mapping_versions.c.active.is_(True))).first()
    return row[0] if row else None


def save_mapping_version(conn, source: str, mapping: dict, email: str, origin: str) -> dict:
    last = conn.execute(select(func.max(db.mapping_versions.c.version)).where(
        db.mapping_versions.c.source == source)).scalar() or 0
    conn.execute(update(db.mapping_versions).where(db.mapping_versions.c.source == source).values(active=False))
    vid = conn.execute(insert(db.mapping_versions).values(
        source=source, version=last + 1, mapping=mapping, created_by=email, active=True, origin=origin)).inserted_primary_key[0]
    audit(conn, email, "mapping.save", f"{source} v{last + 1}")
    return {"id": vid, "version": last + 1}


# ---- upload processing --------------------------------------------------------------------------
def process_upload(upload_id: int, mapping_version_id: int):
    """Runs in a background task. Marks the upload done or failed; never raises."""
    t0 = time.time()
    try:
        with db.engine.begin() as conn:
            up = conn.execute(select(db.uploads).where(db.uploads.c.id == upload_id)).mappings().one()
            mv = conn.execute(select(db.mapping_versions).where(db.mapping_versions.c.id == mapping_version_id)).mappings().one()
            conn.execute(update(db.uploads).where(db.uploads.c.id == upload_id).values(
                status="processing", mapping_version_id=mapping_version_id))
        raw = ingest.read_stored(upload_id)
        clean, rejected = ingest.apply_mapping(raw, up["source"], mv["mapping"])
        with db.engine.begin() as conn:
            stats = ingest.load_clean(conn, up["source"], clean, upload_id)
            notes = {"reject_reasons": rejected["reason"].value_counts().to_dict() if len(rejected) else {}}
            conn.execute(update(db.uploads).where(db.uploads.c.id == upload_id).values(
                status="done", rows_total=len(raw), rows_loaded=stats["loaded"], rows_rejected=len(rejected),
                rows_duplicate=stats["duplicates"], notes=notes, seconds=round(time.time() - t0, 2)))
    except Exception as e:  # surface a readable error to the UI instead of a stuck spinner
        with db.engine.begin() as conn:
            conn.execute(update(db.uploads).where(db.uploads.c.id == upload_id).values(
                status="failed", error=f"{type(e).__name__}: {str(e)[:300]}", seconds=round(time.time() - t0, 2)))


def register_upload(conn, source: str, filename: str, data: bytes, raw: pd.DataFrame, email: str) -> int:
    h = ingest.sha256(data)
    dup = conn.execute(select(db.uploads.c.id).where(db.uploads.c.file_hash == h)).first()
    if dup:
        raise FileExistsError(f"This exact file was already uploaded (upload #{dup[0]})")
    uid = conn.execute(insert(db.uploads).values(
        source=source, filename=filename[:300], file_hash=h, headers=list(raw.columns), rows_total=len(raw),
        created_by=email)).inserted_primary_key[0]
    raw.to_csv(ingest.stored_path(uid), index=False)
    audit(conn, email, "upload", f"{source} {filename} {len(raw)} rows")
    return uid


# ---- reconciliation -----------------------------------------------------------------------------
def _table_df(conn, table, cols=None):
    return pd.read_sql(select(table), conn)


def run_reconciliation(email: str, as_of: date | None = None) -> dict:
    t0 = time.time()
    as_of = as_of or date.today()
    with db.engine.begin() as conn:
        rates, slabs = load_rates(conn)
        o = _table_df(conn, db.orders)
        s = _table_df(conn, db.settlement_lines)
        c = _table_df(conn, db.cod_remittances)
        f = _table_df(conn, db.freight_invoices)
        if o.empty:
            raise ValueError("No orders loaded yet. Upload an orders file first.")
        recon, cl, summary = reconcile(o, s, c, f, rates, slabs, as_of, settings.tolerance, settings.return_window_days)

        known = set(recon["order_id"])
        orphan = int(sum((~x.isin(known)).sum() for x in [s["order_id"], c["order_id"], f["order_id"]]))
        total_lines = int(len(s) + len(c) + len(f))
        summary["payment_lines"] = total_lines
        summary["orphan_lines"] = orphan
        summary["line_match_rate"] = round(1 - orphan / total_lines, 4) if total_lines else 1.0

        conn.execute(delete(db.order_recon))
        cols = [c_.name for c_ in db.order_recon.columns]
        out = recon[[c_ for c_ in cols if c_ in recon.columns]].copy()
        for dc in ["order_date", "delivery_date", "due_date"]:
            out[dc] = out[dc].dt.date
        out = out.astype(object).where(out.notna(), None)
        recs = out.to_dict("records")
        for i in range(0, len(recs), 5000):
            conn.execute(insert(db.order_recon), recs[i:i + 5000])

        # claims: keep human-set status on claims that still exist; drop open claims no longer raised
        prev = {(r.order_id, r.type): r.status for r in conn.execute(select(db.claims.c.order_id, db.claims.c.type, db.claims.c.status))}
        conn.execute(delete(db.claims))
        crecs = []
        for r in cl.itertuples():
            st = prev.get((r.order_id, r.type), "open")
            crecs.append(dict(order_id=r.order_id, partner=r.partner, type=r.type, amount=float(r.amount),
                              age_days=int(r.age_days), status=st, evidence=r.evidence))
        for i in range(0, len(crecs), 5000):
            conn.execute(insert(db.claims), crecs[i:i + 5000])
        now_keys = {(x["order_id"], x["type"]) for x in crecs}
        summary["claims_resolved_since_last_run"] = sum(1 for k, v in prev.items() if v == "open" and k not in now_keys)
        summary["seconds"] = round(time.time() - t0, 2)
        summary["as_of"] = as_of.isoformat()
        conn.execute(insert(db.recon_runs).values(as_of=as_of, seconds=summary["seconds"], orders=summary["orders"],
                                                  counts=summary, created_by=email))
        audit(conn, email, "reconcile", f"{summary['orders']} orders in {summary['seconds']}s")
    return summary


# ---- demo seeding -------------------------------------------------------------------------------
def seed_demo(n: int | None = None, email: str = "seed"):
    """Create reference data, then push the sample files through the SAME ingestion path users use."""
    n = n or settings.seed_orders
    with db.engine.begin() as conn:
        seed_reference(conn)
        if conn.execute(select(func.count()).select_from(db.orders)).scalar():
            return
    tmp = settings.data_dir / "seed_files"
    paths = sample.write_files(tmp, n)
    for source in ["orders", "settlement", "cod", "freight"]:
        data = paths[source].read_bytes()
        raw = ingest.read_raw(data, paths[source].name)
        guess = fuzzy_suggest(source, list(raw.columns))
        mapping = {f: v["column"] for f, v in guess.items()}
        with db.engine.begin() as conn:
            mv = save_mapping_version(conn, source, mapping, email, "fuzzy")
            uid = register_upload(conn, source, paths[source].name, data, raw, email)
        process_upload(uid, mv["id"])
    run_reconciliation(email)
