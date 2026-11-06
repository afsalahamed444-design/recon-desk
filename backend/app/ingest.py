"""Reading uploaded files, applying an approved mapping, cleaning, and bulk loading."""
from __future__ import annotations

import hashlib
import re
from pathlib import Path

import numpy as np
import pandas as pd
from sqlalchemy import bindparam, insert, select, update

from . import db
from .config import settings
from .mapping import CANONICAL

ALLOWED_EXT = {".csv", ".xlsx", ".xls"}
TABLES = {"orders": db.orders, "settlement": db.settlement_lines, "cod": db.cod_remittances,
          "freight": db.freight_invoices}


def upload_dir() -> Path:
    p = settings.data_dir / "uploads"
    p.mkdir(parents=True, exist_ok=True)
    return p


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def read_raw(data: bytes, filename: str) -> pd.DataFrame:
    """Parse CSV/Excel as text so nothing is silently coerced. Raises ValueError on unusable files."""
    ext = Path(filename).suffix.lower()
    if ext not in ALLOWED_EXT:
        raise ValueError("Only .csv, .xlsx files are accepted")
    import io
    try:
        if ext == ".csv":
            df = pd.read_csv(io.BytesIO(data), dtype=str, keep_default_na=False, encoding_errors="replace",
                             skipinitialspace=True)
        else:
            df = pd.read_excel(io.BytesIO(data), dtype=str, keep_default_na=False)
    except Exception as e:
        raise ValueError(f"Could not read file: {type(e).__name__}") from e
    df.columns = [str(c).strip() for c in df.columns]
    df = df.loc[:, [c for c in df.columns if c and not c.startswith("Unnamed:")]]
    if df.empty or len(df.columns) < 2:
        raise ValueError("File has no data rows or fewer than two columns")
    return df


def stored_path(upload_id: int) -> Path:
    return upload_dir() / f"{upload_id}.csv"


def read_stored(upload_id: int, nrows: int | None = None) -> pd.DataFrame:
    return pd.read_csv(stored_path(upload_id), dtype=str, keep_default_na=False, nrows=nrows)


# ---- cleaning ----------------------------------------------------------------------------------
def parse_money(s: pd.Series) -> pd.Series:
    t = s.astype(str).str.strip()
    neg = t.str.match(r"^\(.*\)$") | t.str.startswith("-")
    t = t.str.replace(r"[^0-9.]", "", regex=True)
    out = pd.to_numeric(t, errors="coerce")
    return out.where(~neg, -out)


def parse_dates(s: pd.Series) -> pd.Series:
    t = s.astype(str).str.strip()
    res = pd.to_datetime(t.str[:10], format="%Y-%m-%d", errors="coerce")
    for fmt in ("%d-%m-%Y", "%d/%m/%Y", "%d %b %Y", "%d-%b-%Y", "%d/%m/%y"):
        m = res.isna() & t.ne("")
        if not m.any():
            break
        res[m] = pd.to_datetime(t[m], format=fmt, errors="coerce")
    return res


def norm_payment(s: pd.Series) -> pd.Series:
    cod = s.astype(str).str.lower().str.contains(r"\bcod\b|cash on delivery|cash", regex=True)
    return pd.Series(np.where(cod, "COD", "Prepaid"), index=s.index)


def apply_mapping(raw: pd.DataFrame, source: str, mapping: dict) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Return (clean, rejected). Rejected rows carry a `reason`."""
    spec = CANONICAL[source]
    out = pd.DataFrame(index=raw.index)
    for field, meta in spec.items():
        col = mapping.get(field)
        if not col or col not in raw.columns:
            out[field] = pd.NA
            continue
        s = raw[col]
        if meta["type"] == "money":
            out[field] = parse_money(s)
        elif meta["type"] == "number":
            out[field] = pd.to_numeric(s.str.replace(r"[^0-9.]", "", regex=True), errors="coerce")
        elif meta["type"] == "date":
            out[field] = parse_dates(s)
        else:
            out[field] = s.astype(str).str.strip().replace({"": pd.NA})
    out["order_id"] = out["order_id"].astype("string").str.strip().str.upper()
    if source == "orders":
        out["payment_mode"] = norm_payment(out["payment_mode"].fillna(""))
        out["courier"] = out["courier"].astype("string")
    reason = pd.Series("", index=out.index)
    reason[out["order_id"].isna() | out["order_id"].eq("")] = "missing order id"
    for field in [f for f, m in spec.items() if m["required"] and f != "order_id"]:
        bad = out[field].isna() & reason.eq("")
        reason[bad] = f"missing or invalid {field}"
    if source == "orders":
        bad = out["value"].le(0) & reason.eq("")
        reason[bad] = "non-positive order value"
    ok = reason.eq("")
    rejected = raw[~ok].copy()
    rejected["reason"] = reason[~ok]
    return out[ok].reset_index(drop=True), rejected


def preview(raw: pd.DataFrame, source: str, mapping: dict, n: int = 20) -> dict:
    head = raw.head(n)
    clean, rejected = apply_mapping(head, source, mapping)
    cols = [f for f in CANONICAL[source] if mapping.get(f)]
    shown = clean[cols].copy()
    for c in shown.columns:
        if str(shown[c].dtype).startswith("datetime"):
            shown[c] = shown[c].dt.strftime("%Y-%m-%d")
    if "customer_name" in shown:
        shown["customer_name"] = shown["customer_name"].map(mask_name)
    if "phone" in shown:
        shown["phone"] = shown["phone"].map(mask_phone)
    shown = shown.astype(object).where(shown.notna(), None)
    return {"columns": cols, "rows": shown.to_dict("records"), "rejected": int(len(rejected)),
            "reject_reasons": rejected["reason"].value_counts().to_dict() if len(rejected) else {}}


def mask_name(v) -> str | None:
    if v is None or (not isinstance(v, str) and pd.isna(v)):
        return None
    return " ".join(w[0] + "•" * min(len(w) - 1, 4) for w in str(v).split())


def mask_phone(v) -> str | None:
    if v is None or (not isinstance(v, str) and pd.isna(v)):
        return None
    d = re.sub(r"\D", "", str(v))
    return "••••••" + d[-3:] if len(d) >= 3 else "••••"


# ---- bulk load ---------------------------------------------------------------------------------
def _records(df: pd.DataFrame) -> list[dict]:
    d = df.copy()
    for c in d.columns:
        if str(d[c].dtype).startswith("datetime"):
            d[c] = d[c].dt.date
    d = d.astype(object).where(d.notna(), None)
    return d.to_dict("records")


def load_clean(conn, source: str, clean: pd.DataFrame, upload_id: int) -> dict:
    """Insert cleaned rows. Orders upsert by id; payment lines drop exact duplicates."""
    table = TABLES[source]
    stats = {"loaded": 0, "duplicates": 0}
    if source == "orders":
        clean = clean.drop_duplicates("order_id", keep="last")
        ids = set(r[0] for r in conn.execute(select(table.c.order_id)))
        is_new = ~clean["order_id"].isin(ids)
        new, old = clean[is_new], clean[~is_new]
        cols = [c for c in clean.columns if c in table.c]
        for i in range(0, len(new), 5000):
            conn.execute(insert(table), _records(new[cols].iloc[i:i + 5000]))
        if len(old):
            conn.execute(update(table).where(table.c.order_id == bindparam("b_oid")),
                         [{"b_oid": r["order_id"], **{k: v for k, v in r.items() if k != "order_id"}}
                          for r in _records(old[cols])])
        stats["loaded"] = len(clean)
        return stats
    key_cols = [c for c in clean.columns if c in table.c and c != "order_id"]
    before = len(clean)
    clean = clean.drop_duplicates(["order_id"] + key_cols)
    stats["duplicates"] = before - len(clean)
    clean = clean.assign(upload_id=upload_id)
    cols = [c for c in clean.columns if c in table.c]
    for i in range(0, len(clean), 5000):
        conn.execute(insert(table), _records(clean[cols].iloc[i:i + 5000]))
    stats["loaded"] = len(clean)
    return stats
