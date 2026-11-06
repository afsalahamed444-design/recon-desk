"""Column mapping: canonical schemas, suggestions (AI first, fuzzy fallback) and validation.

The AI only ever sees header names and a few sample values from columns that do not look like
personal data. Whatever it returns is validated against the real headers and the canonical schema
before it is shown, and a human must approve it before it is saved.
"""
from __future__ import annotations

import json
import re
from difflib import SequenceMatcher

import httpx

from .config import settings

# source -> field -> (required, type, synonyms)
CANONICAL: dict[str, dict[str, dict]] = {
    "orders": {
        "order_id": dict(required=True, type="text", syn=["order id", "order no", "order number", "order ref", "order"]),
        "channel": dict(required=True, type="text", syn=["channel", "sales channel", "marketplace", "platform", "source"]),
        "value": dict(required=True, type="money", syn=["value", "order value", "amount", "selling price", "invoice value", "total"]),
        "payment_mode": dict(required=True, type="text", syn=["payment", "payment mode", "payment method", "pay type"]),
        "delivery_status": dict(required=True, type="text", syn=["delivery status", "status", "order status", "shipment status"]),
        "order_date": dict(required=False, type="date", syn=["order date", "placed on", "created at", "date"]),
        "delivery_date": dict(required=False, type="date", syn=["delivery date", "delivered on", "delivered at", "status date"]),
        "courier": dict(required=False, type="text", syn=["courier", "carrier", "logistics partner", "shipping partner"]),
        "weight_kg": dict(required=False, type="number", syn=["weight", "weight kg", "declared weight", "dead weight"]),
        "warehouse_received_date": dict(required=False, type="date", syn=["warehouse received", "return received", "grn date", "received at warehouse", "scan date"]),
        "customer_name": dict(required=False, type="text", syn=["customer name", "buyer name", "name"]),
        "phone": dict(required=False, type="text", syn=["phone", "mobile", "contact", "phone number"]),
    },
    "settlement": {
        "order_id": dict(required=True, type="text", syn=["order id", "order no", "order number", "order ref", "order item id"]),
        "settled_amount": dict(required=True, type="money", syn=["settled amount", "net payout", "settlement amount", "payout", "net amount", "amount settled"]),
        "tcs": dict(required=False, type="money", syn=["tcs", "gst tcs", "tcs deducted", "tax collected at source"]),
        "tds": dict(required=False, type="money", syn=["tds", "income tax tds", "tds deducted", "tds 194o"]),
        "settlement_date": dict(required=False, type="date", syn=["settlement date", "payout date", "settled on", "paid on", "date"]),
    },
    "cod": {
        "order_id": dict(required=True, type="text", syn=["order id", "order ref", "awb order ref", "order no", "reference"]),
        "remitted_amount": dict(required=True, type="money", syn=["remitted amount", "cod remitted", "cod amount", "remittance", "cod collected", "amount remitted"]),
        "remittance_date": dict(required=False, type="date", syn=["remittance date", "remitted on", "utr date", "paid on", "date"]),
    },
    "freight": {
        "order_id": dict(required=True, type="text", syn=["order id", "order ref", "order no", "reference"]),
        "billed_amount": dict(required=True, type="money", syn=["billed amount", "freight charged", "freight amount", "shipping charge", "total charges", "freight"]),
        "billed_weight_kg": dict(required=False, type="number", syn=["billed weight", "charged weight", "weight charged", "weight kg", "weight"]),
    },
}

PII_HEADER = re.compile(r"name|phone|mobile|contact|address|email|pincode|pin code|buyer|customer", re.I)
PHONE_LIKE = re.compile(r"\d{8,}")


def required_fields(source: str) -> list[str]:
    return [k for k, v in CANONICAL[source].items() if v["required"]]


def schema_for_ui(source: str) -> list[dict]:
    return [{"field": k, "required": v["required"], "type": v["type"]} for k, v in CANONICAL[source].items()]


def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9 ]+", " ", str(s).lower().replace("₹", " ")).strip()


def fuzzy_suggest(source: str, headers: list[str]) -> dict[str, dict]:
    """Greedy best-first assignment of headers to canonical fields. Returns field -> {column, confidence}."""
    pairs = []
    for field, spec in CANONICAL[source].items():
        for h in headers:
            nh = _norm(h)
            best = max([SequenceMatcher(None, nh, syn).ratio() for syn in spec["syn"]] +
                       [1.0 if nh == _norm(field.replace("_", " ")) else 0.0])
            if any(nh == syn for syn in spec["syn"]):
                best = 1.0
            pairs.append((best, field, h))
    out, used_f, used_h = {}, set(), set()
    for score, field, h in sorted(pairs, reverse=True):
        if field in used_f or h in used_h or score < 0.6:
            continue
        out[field] = {"column": h, "confidence": round(score, 2)}
        used_f.add(field)
        used_h.add(h)
    return out


def safe_samples(headers: list[str], rows: list[dict], n: int = 5) -> dict[str, list[str]]:
    """Sample values per column for the AI prompt. Personal-data columns send nothing."""
    out = {}
    for h in headers:
        if PII_HEADER.search(h):
            out[h] = []
            continue
        vals = [str(r.get(h, ""))[:40] for r in rows[:n]]
        out[h] = ["<redacted>" if PHONE_LIKE.fullmatch(re.sub(r"\D", "", v) or "x") and len(re.sub(r"\D", "", v)) >= 10 else v for v in vals]
    return out


def validate_suggestion(source: str, headers: list[str], raw: dict) -> dict[str, dict]:
    """Keep only entries that name a real header and a real canonical field, one header per field."""
    ok, used = {}, set()
    for field, val in (raw or {}).items():
        if field not in CANONICAL[source] or not isinstance(val, dict):
            continue
        col, conf = val.get("column"), val.get("confidence")
        if col not in headers or col in used or not isinstance(conf, (int, float)):
            continue
        ok[field] = {"column": col, "confidence": round(max(0.0, min(1.0, float(conf))), 2)}
        used.add(col)
    return ok


def ai_suggest(source: str, headers: list[str], samples: dict[str, list[str]]) -> dict[str, dict] | None:
    """Ask Claude for a mapping. Returns None on any failure so the caller can fall back."""
    if not settings.anthropic_key:
        return None
    fields = {k: v["type"] for k, v in CANONICAL[source].items()}
    prompt = (
        "Map the columns of a finance report to canonical fields.\n"
        f"Report type: {source}\nCanonical fields (name: type): {json.dumps(fields)}\n"
        f"File columns with sample values: {json.dumps(samples, ensure_ascii=False)}\n"
        'Reply with ONLY JSON: {"<canonical field>": {"column": "<exact file column>", "confidence": 0-1}}. '
        "Omit a field if no column fits. Use each column at most once. Never guess when unsure."
    )
    try:
        r = httpx.post("https://api.anthropic.com/v1/messages", timeout=20, headers={
            "x-api-key": settings.anthropic_key, "anthropic-version": "2023-06-01", "content-type": "application/json"},
            json={"model": settings.anthropic_model, "max_tokens": 800, "messages": [{"role": "user", "content": prompt}]})
        r.raise_for_status()
        text = "".join(b.get("text", "") for b in r.json().get("content", []))
        text = re.sub(r"^```(?:json)?|```$", "", text.strip(), flags=re.M).strip()
        return validate_suggestion(source, headers, json.loads(text))
    except Exception:  # network, auth, bad JSON: fall back, never crash the upload flow
        return None


def suggest(source: str, headers: list[str], rows: list[dict], previous: dict | None = None) -> dict:
    """Order of trust: saved mapping that still fits > AI > fuzzy. Low confidence is flagged for a human."""
    if previous and all(col in headers for col in previous.values()) and \
            all(f in previous for f in required_fields(source)):
        sug = {f: {"column": c, "confidence": 1.0} for f, c in previous.items()}
        origin = "saved"
    else:
        sug = ai_suggest(source, headers, safe_samples(headers, rows))
        origin = "ai"
        if not sug:
            sug, origin = fuzzy_suggest(source, headers), "fuzzy"
    threshold = 0.85 if origin == "saved" else 0.9
    needs_check = [f for f, v in sug.items() if v["confidence"] < threshold]
    missing = [f for f in required_fields(source) if f not in sug]
    return {"origin": origin, "mapping": {f: v["column"] for f, v in sug.items()},
            "confidence": {f: v["confidence"] for f, v in sug.items()},
            "needs_check": needs_check, "missing_required": missing}


def validate_mapping(source: str, headers: list[str], mapping: dict) -> list[str]:
    errs = []
    for f in mapping:
        if f not in CANONICAL[source]:
            errs.append(f"Unknown field '{f}'")
    for f in required_fields(source):
        if not mapping.get(f):
            errs.append(f"Required field '{f}' is not mapped")
    cols = [c for c in mapping.values() if c]
    for c in cols:
        if c not in headers:
            errs.append(f"Column '{c}' is not in the file")
    if len(cols) != len(set(cols)):
        errs.append("A column is mapped to more than one field")
    return errs
