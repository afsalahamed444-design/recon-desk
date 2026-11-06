from __future__ import annotations

import csv
import io
import re
from contextlib import asynccontextmanager
from datetime import date
from pathlib import Path

from fastapi import BackgroundTasks, Depends, FastAPI, File, Form, HTTPException, Query, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import and_, case, func, insert, select, update

from . import db, ingest, mapping as mp, service
from .config import settings
from .security import COFOUNDER, current_user, make_token, require_cofounder, require_exec, verify_password

BUCKETS = ["0-30", "31-60", "61-90", "90+"]
SOURCES = list(mp.CANONICAL)
CLAIM_STATUSES = ["open", "filed", "recovered", "written_off"]


@asynccontextmanager
async def lifespan(app: FastAPI):
    db.init_db()
    if settings.seed_on_start:
        service.seed_demo()
    yield


app = FastAPI(title="Recon Desk API", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=settings.cors, allow_methods=["*"], allow_headers=["*"])


# ---- helpers ------------------------------------------------------------------------------------
def row_dict(r):
    return {k: (v.isoformat() if hasattr(v, "isoformat") else v) for k, v in dict(r).items()}


def csv_safe(v):
    """Neutralise spreadsheet formula injection in exported text cells."""
    if isinstance(v, str) and v[:1] in ("=", "+", "-", "@", "\t", "\r"):
        return "'" + v
    return v


def bucket_expr(col):
    return case((col <= 30, "0-30"), (col <= 60, "31-60"), (col <= 90, "61-90"), else_="90+")


# ---- auth ---------------------------------------------------------------------------------------
class Login(BaseModel):
    email: str = Field(max_length=200)
    password: str = Field(max_length=200)


@app.get("/api/health")
def health():
    return {"ok": True}


@app.post("/api/auth/login")
def login(body: Login):
    with db.engine.connect() as c:
        u = c.execute(select(db.users).where(db.users.c.email == body.email.strip().lower())).mappings().first()
    if not u or not verify_password(body.password, u["password_hash"]):
        raise HTTPException(401, "Email or password is incorrect")
    return {"token": make_token(u["email"], u["role"], u["name"]),
            "user": {"email": u["email"], "name": u["name"], "role": u["role"]}}


@app.get("/api/me")
def me(user=Depends(current_user)):
    return user


# ---- uploads and mappings ----------------------------------------------------------------------
@app.get("/api/sources")
def sources(user=Depends(current_user)):
    return {s: mp.schema_for_ui(s) for s in SOURCES}


@app.post("/api/uploads")
async def upload_file(source: str = Form(...), file: UploadFile = File(...), user=Depends(require_exec)):
    if source not in SOURCES:
        raise HTTPException(422, f"source must be one of {SOURCES}")
    data = await file.read(settings.max_upload_mb * 1024 * 1024 + 1)
    if len(data) > settings.max_upload_mb * 1024 * 1024:
        raise HTTPException(413, f"File is larger than {settings.max_upload_mb} MB")
    try:
        raw = ingest.read_raw(data, file.filename or "upload.csv")
    except ValueError as e:
        raise HTTPException(422, str(e))
    try:
        with db.engine.begin() as conn:
            uid = service.register_upload(conn, source, file.filename or "upload", data, raw, user["email"])
    except FileExistsError as e:
        raise HTTPException(409, str(e))
    return {"id": uid, "source": source, "headers": list(raw.columns), "rows_total": len(raw)}


@app.get("/api/uploads")
def list_uploads(user=Depends(current_user)):
    with db.engine.connect() as c:
        rows = c.execute(select(db.uploads).order_by(db.uploads.c.id.desc()).limit(50)).mappings().all()
    return [row_dict({k: v for k, v in r.items() if k != "file_hash"}) for r in rows]


def _get_upload(conn, uid: int):
    u = conn.execute(select(db.uploads).where(db.uploads.c.id == uid)).mappings().first()
    if not u:
        raise HTTPException(404, "Upload not found")
    return u


@app.get("/api/uploads/{uid}")
def get_upload(uid: int, user=Depends(current_user)):
    with db.engine.connect() as c:
        return row_dict({k: v for k, v in _get_upload(c, uid).items() if k != "file_hash"})


@app.post("/api/uploads/{uid}/suggest")
def suggest_mapping(uid: int, user=Depends(require_exec)):
    with db.engine.connect() as c:
        u = _get_upload(c, uid)
        previous = service.active_mapping(c, u["source"])
    sample_rows = ingest.read_stored(uid, nrows=5).to_dict("records")
    sug = mp.suggest(u["source"], list(u["headers"]), sample_rows, previous)
    raw = ingest.read_stored(uid, nrows=20)
    sug["preview"] = ingest.preview(raw, u["source"], sug["mapping"])
    sug["headers"] = list(u["headers"])
    return sug


class MappingBody(BaseModel):
    mapping: dict[str, str | None]


@app.post("/api/uploads/{uid}/preview")
def preview_mapping(uid: int, body: MappingBody, user=Depends(require_exec)):
    with db.engine.connect() as c:
        u = _get_upload(c, uid)
    clean = {k: v for k, v in body.mapping.items() if v}
    errors = mp.validate_mapping(u["source"], list(u["headers"]), clean)
    if errors:
        return {"errors": errors, "preview": None}
    return {"errors": [], "preview": ingest.preview(ingest.read_stored(uid, nrows=20), u["source"], clean)}


class SaveMapping(BaseModel):
    upload_id: int
    mapping: dict[str, str | None]
    origin: str = Field(default="manual", pattern="^(ai|fuzzy|saved|manual)$")


@app.post("/api/mappings")
def save_mapping(body: SaveMapping, user=Depends(require_exec)):
    clean = {k: v for k, v in body.mapping.items() if v}
    with db.engine.begin() as conn:
        u = _get_upload(conn, body.upload_id)
        errors = mp.validate_mapping(u["source"], list(u["headers"]), clean)
        if errors:
            raise HTTPException(422, "; ".join(errors))
        return service.save_mapping_version(conn, u["source"], clean, user["email"], body.origin)


@app.get("/api/mappings")
def list_mappings(source: str | None = None, user=Depends(current_user)):
    q = select(db.mapping_versions).order_by(db.mapping_versions.c.source, db.mapping_versions.c.version.desc())
    if source:
        q = q.where(db.mapping_versions.c.source == source)
    with db.engine.connect() as c:
        return [row_dict(r) for r in c.execute(q).mappings()]


@app.post("/api/mappings/{mid}/activate")
def rollback_mapping(mid: int, user=Depends(require_exec)):
    with db.engine.begin() as conn:
        mv = conn.execute(select(db.mapping_versions).where(db.mapping_versions.c.id == mid)).mappings().first()
        if not mv:
            raise HTTPException(404, "Mapping version not found")
        conn.execute(update(db.mapping_versions).where(db.mapping_versions.c.source == mv["source"]).values(active=False))
        conn.execute(update(db.mapping_versions).where(db.mapping_versions.c.id == mid).values(active=True))
        service.audit(conn, user["email"], "mapping.rollback", f"{mv['source']} v{mv['version']}")
    return {"ok": True, "source": mv["source"], "version": mv["version"]}


class ProcessBody(BaseModel):
    mapping_version_id: int


@app.post("/api/uploads/{uid}/process", status_code=202)
def process(uid: int, body: ProcessBody, tasks: BackgroundTasks, user=Depends(require_exec)):
    with db.engine.begin() as conn:
        u = _get_upload(conn, uid)
        mv = conn.execute(select(db.mapping_versions).where(db.mapping_versions.c.id == body.mapping_version_id)).mappings().first()
        if not mv or mv["source"] != u["source"]:
            raise HTTPException(422, "Mapping version does not belong to this file type")
        if u["status"] in ("processing", "done"):
            raise HTTPException(409, f"Upload is already {u['status']}")
        conn.execute(update(db.uploads).where(db.uploads.c.id == uid).values(status="processing"))
    tasks.add_task(service.process_upload, uid, body.mapping_version_id)
    return {"id": uid, "status": "processing"}


# ---- reconciliation -----------------------------------------------------------------------------
@app.post("/api/reconcile")
def reconcile_now(user=Depends(require_exec)):
    try:
        return service.run_reconciliation(user["email"])
    except ValueError as e:
        raise HTTPException(409, str(e))


@app.get("/api/reconcile/latest")
def latest_run(user=Depends(current_user)):
    with db.engine.connect() as c:
        r = c.execute(select(db.recon_runs).order_by(db.recon_runs.c.id.desc()).limit(1)).mappings().first()
    return row_dict(r) if r else None


# ---- dashboard ----------------------------------------------------------------------------------
@app.get("/api/dashboard")
def dashboard(user=Depends(current_user)):
    cl = db.claims
    live = cl.c.status.in_(["open", "filed"])
    with db.engine.connect() as c:
        total = c.execute(select(func.coalesce(func.sum(cl.c.amount), 0), func.count()).where(live)).one()
        b = bucket_expr(cl.c.age_days)
        rows = c.execute(select(cl.c.partner, b.label("b"), func.sum(cl.c.amount), func.count())
                         .where(live).group_by(cl.c.partner, b)).all()
        by_type = c.execute(select(cl.c.type, func.sum(cl.c.amount), func.count()).where(live).group_by(cl.c.type)).all()
        by_status = c.execute(select(cl.c.status, func.sum(cl.c.amount), func.count()).group_by(cl.c.status)).all()
        statuses = c.execute(select(db.order_recon.c.status, func.count()).group_by(db.order_recon.c.status)).all()
        stat = c.execute(select(db.order_recon.c.channel, func.sum(db.order_recon.c.tcs), func.sum(db.order_recon.c.tds))
                         .group_by(db.order_recon.c.channel).order_by(db.order_recon.c.channel)).all()
        run = c.execute(select(db.recon_runs).order_by(db.recon_runs.c.id.desc()).limit(1)).mappings().first()
    matrix: dict[str, dict] = {}
    for partner, bk, amt, n in rows:
        m = matrix.setdefault(partner, {"partner": partner, "total": 0.0, "count": 0, **{k: 0.0 for k in BUCKETS}})
        m[bk] += float(amt)
        m["total"] += float(amt)
        m["count"] += n
    n_orders = sum(n for _, n in statuses)
    settled = dict(statuses).get("settled", 0)
    return {
        "at_risk": float(total[0]), "open_claims": total[1],
        "partners": sorted(matrix.values(), key=lambda m: -m["total"]), "buckets": BUCKETS,
        "by_type": [{"type": t, "amount": float(a), "count": n} for t, a, n in by_type],
        "by_status": [{"status": s, "amount": float(a), "count": n} for s, a, n in by_status],
        "order_statuses": dict(statuses), "orders": n_orders,
        "settled_pct": round(settled / n_orders, 4) if n_orders else None,
        "line_match_rate": (run["counts"] or {}).get("line_match_rate") if run else None,
        "statutory": [{"partner": p, "tcs": float(t or 0), "tds": float(d or 0)} for p, t, d in stat],
        "last_run": row_dict(run) if run else None,
    }


# ---- orders -------------------------------------------------------------------------------------
def mask_pii(name, phone, unmask: bool):
    if unmask:
        return name, phone
    return ingest.mask_name(name), ingest.mask_phone(phone)


@app.get("/api/orders")
def list_orders(status: str | None = None, channel: str | None = None, q: str | None = Query(None, max_length=60),
                sort: str = Query("diff_asc", pattern="^(diff_asc|age_desc|value_desc)$"),
                page: int = Query(1, ge=1), page_size: int = Query(50, ge=1, le=200), user=Depends(current_user)):
    t = db.order_recon
    conds = []
    if status:
        conds.append(t.c.status == status)
    if channel:
        conds.append(t.c.channel == channel)
    if q:
        conds.append(t.c.order_id.contains(re.sub(r"[^A-Za-z0-9\-]", "", q).upper()))
    where = and_(*conds) if conds else True
    order = {"diff_asc": t.c.diff.asc(), "age_desc": t.c.age_days.desc().nulls_last(), "value_desc": t.c.value.desc()}[sort]
    cols = [t.c.order_id, t.c.channel, t.c.courier, t.c.payment_mode, t.c.delivery_status, t.c.status, t.c.expected,
            t.c.received, t.c.diff, t.c.tcs, t.c.tds, t.c.due_date, t.c.age_days, t.c.value]
    with db.engine.connect() as c:
        total = c.execute(select(func.count()).select_from(t).where(where)).scalar()
        rows = c.execute(select(*cols).where(where).order_by(order, t.c.order_id).limit(page_size).offset((page - 1) * page_size)).mappings().all()
        channels = [r[0] for r in c.execute(select(t.c.channel).distinct().order_by(t.c.channel))]
    return {"total": total, "page": page, "page_size": page_size, "items": [row_dict(r) for r in rows], "channels": channels}


@app.get("/api/orders/{order_id}")
def order_detail(order_id: str, unmask: bool = False, user=Depends(current_user)):
    if unmask and user["role"] != COFOUNDER:
        raise HTTPException(403, "Only the co-founder can view customer details")
    with db.engine.begin() as conn:
        r = conn.execute(select(db.order_recon).where(db.order_recon.c.order_id == order_id)).mappings().first()
        if not r:
            raise HTTPException(404, "Order not found")
        o = conn.execute(select(db.orders.c.customer_name, db.orders.c.phone, db.orders.c.weight_kg,
                                db.orders.c.warehouse_received_date).where(db.orders.c.order_id == order_id)).mappings().first()
        lines = {
            "settlement": [row_dict(x) for x in conn.execute(select(db.settlement_lines.c.settled_amount, db.settlement_lines.c.tcs,
                           db.settlement_lines.c.tds, db.settlement_lines.c.settlement_date).where(db.settlement_lines.c.order_id == order_id)).mappings()],
            "cod": [row_dict(x) for x in conn.execute(select(db.cod_remittances.c.remitted_amount, db.cod_remittances.c.remittance_date)
                    .where(db.cod_remittances.c.order_id == order_id)).mappings()],
            "freight": [row_dict(x) for x in conn.execute(select(db.freight_invoices.c.billed_amount, db.freight_invoices.c.billed_weight_kg)
                        .where(db.freight_invoices.c.order_id == order_id)).mappings()],
        }
        cl = [row_dict(x) for x in conn.execute(select(db.claims).where(db.claims.c.order_id == order_id)).mappings()]
        if unmask:
            service.audit(conn, user["email"], "pii.unmask", order_id)
    name, phone = mask_pii(o["customer_name"], o["phone"], unmask)
    return {"recon": row_dict(r), "customer": {"name": name, "phone": phone, "masked": not unmask},
            "warehouse_received_date": o["warehouse_received_date"].isoformat() if o["warehouse_received_date"] else None,
            "lines": lines, "claims": cl}


# ---- claims -------------------------------------------------------------------------------------
def _claims_query(partner, ctype, status, min_age):
    cl = db.claims
    conds = []
    if partner:
        conds.append(cl.c.partner == partner)
    if ctype:
        conds.append(cl.c.type == ctype)
    if status:
        conds.append(cl.c.status == status)
    if min_age is not None:
        conds.append(cl.c.age_days >= min_age)
    return and_(*conds) if conds else True


@app.get("/api/claims")
def list_claims(partner: str | None = None, type: str | None = None, status: str | None = None,
                min_age: int | None = Query(None, ge=0), page: int = Query(1, ge=1),
                page_size: int = Query(50, ge=1, le=200), user=Depends(current_user)):
    cl = db.claims
    where = _claims_query(partner, type, status, min_age)
    with db.engine.connect() as c:
        total = c.execute(select(func.count(), func.coalesce(func.sum(cl.c.amount), 0)).where(where)).one()
        rows = c.execute(select(cl.c.id, cl.c.order_id, cl.c.partner, cl.c.type, cl.c.amount, cl.c.age_days, cl.c.status, cl.c.evidence)
                         .where(where).order_by(cl.c.amount.desc(), cl.c.id).limit(page_size).offset((page - 1) * page_size)).mappings().all()
        partners = [r[0] for r in c.execute(select(cl.c.partner).distinct().order_by(cl.c.partner))]
    return {"total": total[0], "amount": float(total[1]), "items": [row_dict(r) for r in rows], "partners": partners}


class ClaimStatus(BaseModel):
    status: str = Field(pattern="^(open|filed|recovered|written_off)$")


@app.patch("/api/claims/{cid}")
def update_claim(cid: int, body: ClaimStatus, user=Depends(require_exec)):
    with db.engine.begin() as conn:
        res = conn.execute(update(db.claims).where(db.claims.c.id == cid).values(status=body.status))
        if not res.rowcount:
            raise HTTPException(404, "Claim not found")
        service.audit(conn, user["email"], "claim.status", f"{cid} -> {body.status}")
    return {"id": cid, "status": body.status}


def evidence_text(e: dict) -> str:
    o, x, r, f = e["order"], e["expected"], e["received"], e["freight"]
    parts = [e["rule"], f"Order value {o['value']}; delivered {o['delivery_date']}; due {o['due_date']}.",
             f"Expected {x['total']} (commission {x['commission']}, prepaid fee {x['prepaid_fee']}, COD fee {x['cod_fee']}, "
             f"fixed {x['fixed_fee']}, return fee {x['return_fee']}).",
             f"Received {r['total']} in {r['payment_lines']} line(s)."]
    if f["billed"] is not None:
        parts.append(f"Freight billed {f['billed']} vs rate card {f['rate_card']} (declared {f['declared_weight_kg']} kg, billed {f['billed_weight_kg']} kg).")
    return " ".join(parts)


@app.get("/api/claims/export")
def export_claims(partner: str | None = None, type: str | None = None, status: str | None = None,
                  min_age: int | None = Query(None, ge=0), user=Depends(current_user)):
    cl = db.claims
    where = _claims_query(partner, type, status, min_age)
    with db.engine.connect() as c:
        rows = c.execute(select(cl).where(where).order_by(cl.c.partner, cl.c.amount.desc())).mappings().all()
        service.audit(c, user["email"], "claims.export", f"{len(rows)} rows partner={partner}")
        c.commit()

    def gen():
        buf = io.StringIO()
        w = csv.writer(buf)
        w.writerow(["claim_id", "partner", "order_id", "claim_type", "amount_inr", "age_days", "status", "evidence"])
        yield buf.getvalue()
        for r in rows:
            buf.seek(0), buf.truncate()
            w.writerow([csv_safe(v) for v in [r["id"], r["partner"], r["order_id"], r["type"], r["amount"], r["age_days"],
                                              r["status"], evidence_text(r["evidence"])]])
            yield buf.getvalue()

    fname = f"claims_{re.sub(r'[^A-Za-z0-9]+', '-', partner or 'all')}_{date.today().isoformat()}.csv"
    return StreamingResponse(gen(), media_type="text/csv", headers={"Content-Disposition": f'attachment; filename="{fname}"'})


# ---- rate cards ---------------------------------------------------------------------------------
@app.get("/api/rate-cards")
def get_rate_cards(user=Depends(current_user)):
    with db.engine.connect() as c:
        rows = c.execute(select(db.partners.c.name, db.partners.c.type, db.rate_cards)
                         .select_from(db.partners.join(db.rate_cards, db.rate_cards.c.partner_id == db.partners.c.id))
                         .order_by(db.partners.c.type, db.partners.c.name, db.rate_cards.c.effective_from.desc(), db.rate_cards.c.id.desc())).mappings().all()
    seen, out = set(), []
    for r in rows:
        if r["name"] in seen:
            continue
        seen.add(r["name"])
        out.append(row_dict(r))
    return out


class Slab(BaseModel):
    upto_kg: float = Field(gt=0, le=1000)
    rate: float = Field(ge=0, le=100000)


class RateCardBody(BaseModel):
    commission_pct: float = Field(0, ge=0, le=100)
    prepaid_fee_pct: float = Field(0, ge=0, le=100)
    cod_fee_pct: float = Field(0, ge=0, le=100)
    fixed_fee: float = Field(0, ge=0, le=10000)
    return_fee_pct: float = Field(0, ge=0, le=100)
    remit_days: int = Field(7, ge=0, le=90)
    cod_by_courier: bool = False
    weight_slabs: list[Slab] | None = None


@app.put("/api/rate-cards/{partner_id}")
def put_rate_card(partner_id: int, body: RateCardBody, user=Depends(require_exec)):
    with db.engine.begin() as conn:
        p = conn.execute(select(db.partners).where(db.partners.c.id == partner_id)).mappings().first()
        if not p:
            raise HTTPException(404, "Partner not found")
        vals = body.model_dump()
        if p["type"] == "courier":
            if not body.weight_slabs:
                raise HTTPException(422, "A courier rate card needs weight slabs")
            vals["weight_slabs"] = sorted(vals["weight_slabs"], key=lambda s: s["upto_kg"])
        else:
            vals["weight_slabs"] = None
        conn.execute(insert(db.rate_cards).values(partner_id=partner_id, effective_from=date.today(), **vals))
        service.audit(conn, user["email"], "ratecard.update", p["name"])
    return {"ok": True, "note": "Saved as a new version. Re-run reconciliation to apply it."}


# ---- frontend (single-service deploy) -----------------------------------------------------------
DIST = Path(__file__).resolve().parents[2] / "frontend" / "dist"
if DIST.exists():
    @app.get("/{path:path}", include_in_schema=False)
    def spa(path: str):
        if path.startswith("api/"):
            raise HTTPException(404, "Not found")
        f = (DIST / path).resolve()
        if path and f.is_file() and DIST in f.parents:
            return FileResponse(f)
        return FileResponse(DIST / "index.html")
