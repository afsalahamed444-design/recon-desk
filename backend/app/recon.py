"""Order-level reconciliation engine. Pure functions over DataFrames: no database, no AI.

Expected amount (non-return):  value - commission - prepaid fee - COD fee - fixed fee
Expected amount (return):      -(return fee)            (reverse deduction the partner may charge)
Received:                      settlement lines + COD remittance lines (TCS and TDS are NOT included)
Difference:                    received - expected      (negative = short)

Status precedence, first match wins:
  return_not_received > unpaid_past_due > freight_overcharged > short_paid > unrated > overpaid > pending > settled
Every raised issue still becomes its own claim, so an order short-paid AND freight-overcharged
shows one status but produces two claims.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

STATUSES = ["settled", "pending", "short_paid", "unpaid_past_due", "freight_overcharged",
            "return_not_received", "overpaid", "unrated"]
CLAIM_TYPES = ["unpaid_past_due", "short_paid", "freight_overcharged", "return_not_received"]

RULE_TEXT = {
    "unpaid_past_due": "No settlement or COD remittance line found, and the partner's remittance window has passed.",
    "short_paid": "Amount received is below the amount expected from the rate card by more than the tolerance.",
    "freight_overcharged": "Freight billed exceeds the courier rate-card amount for the shipment weight by more than the tolerance.",
    "return_not_received": "Order shows as returned but no warehouse receipt scan within the return window.",
}

ORDER_COLS = ["order_id", "channel", "courier", "order_date", "value", "payment_mode", "delivery_status",
              "delivery_date", "weight_kg", "warehouse_received_date"]


def _empty(cols):
    return pd.DataFrame({c: pd.Series(dtype="object") for c in cols})


def expected_freight(weights: pd.Series, couriers: pd.Series, slabs: dict[str, list[dict]]) -> pd.Series:
    """Rate-card freight for a shipment weight. Slab = smallest upto_kg >= weight."""
    out = pd.Series(np.nan, index=weights.index, dtype="float64")
    w = pd.to_numeric(weights, errors="coerce")
    for name, rows in (slabs or {}).items():
        if not rows:
            continue
        rows = sorted(rows, key=lambda r: r["upto_kg"])
        thr = np.array([r["upto_kg"] for r in rows], dtype=float)
        rate = np.array([r["rate"] for r in rows], dtype=float)
        m = (couriers == name) & w.notna()
        if m.any():
            idx = np.clip(np.searchsorted(thr, w[m].to_numpy(), side="left"), 0, len(rows) - 1)
            out.loc[m] = rate[idx]
    return out


def reconcile(orders: pd.DataFrame, settle: pd.DataFrame, cod: pd.DataFrame, freight: pd.DataFrame,
              rates: pd.DataFrame, slabs: dict, as_of, tol: float = 10.0, return_window: int = 7):
    """Return (recon_df, claims_df, summary dict). `rates` is indexed by channel partner name."""
    as_of = pd.Timestamp(as_of)
    o = orders[ORDER_COLS].drop_duplicates("order_id", keep="last").copy()
    for c in ["order_date", "delivery_date", "warehouse_received_date"]:
        o[c] = pd.to_datetime(o[c], errors="coerce")

    settle = settle if len(settle) else _empty(["order_id", "settled_amount", "tcs", "tds"])
    cod = cod if len(cod) else _empty(["order_id", "remitted_amount"])
    freight = freight if len(freight) else _empty(["order_id", "billed_amount", "billed_weight_kg"])

    s = settle.groupby("order_id").agg(settled=("settled_amount", "sum"), tcs=("tcs", "sum"),
                                       tds=("tds", "sum"), n_s=("order_id", "size"))
    c = cod.groupby("order_id").agg(remitted=("remitted_amount", "sum"), n_c=("order_id", "size"))
    f = freight.groupby("order_id").agg(billed_freight=("billed_amount", "sum"),
                                        billed_weight_kg=("billed_weight_kg", "max"))
    df = o.set_index("order_id").join(s).join(c).join(f)
    for col in ["settled", "tcs", "tds", "remitted", "n_s", "n_c"]:
        df[col] = df[col].fillna(0)
    df["pay_lines"] = (df["n_s"] + df["n_c"]).astype(int)
    df = df.join(rates.add_prefix("r_"), on="channel")

    rate_missing = df["r_commission_pct"].isna()
    is_cod = df["payment_mode"].astype(str).str.upper().eq("COD")
    is_ret = df["delivery_status"].astype(str).str.lower().str.contains("return|rto", na=False)
    v = df["value"].astype(float)

    commission = v * df["r_commission_pct"].fillna(0) / 100
    prepaid_fee = np.where(~is_cod, v * df["r_prepaid_fee_pct"].fillna(0) / 100, 0.0)
    cod_fee = np.where(is_cod, v * df["r_cod_fee_pct"].fillna(0) / 100, 0.0)
    fixed_fee = df["r_fixed_fee"].fillna(0)
    return_fee = v * df["r_return_fee_pct"].fillna(0) / 100

    expected = np.where(is_ret, -return_fee, v - commission - prepaid_fee - cod_fee - fixed_fee)
    df["expected"] = np.where(rate_missing, np.nan, np.round(expected, 0))
    df["commission"] = np.where(is_ret, 0.0, commission)
    df["prepaid_fee"] = np.where(is_ret, 0.0, prepaid_fee)
    df["cod_fee"] = np.where(is_ret, 0.0, cod_fee)
    df["fixed_fee"] = np.where(is_ret, 0.0, fixed_fee)
    df["return_fee"] = np.where(is_ret, return_fee, 0.0)
    df["received"] = df["settled"] + df["remitted"]          # TCS / TDS deliberately excluded
    df["diff"] = df["received"] - df["expected"]
    has_pay = df["pay_lines"] > 0

    # dates
    base = df["delivery_date"].fillna(df["order_date"])
    df["due_date"] = base + pd.to_timedelta(df["r_remit_days"], unit="D")
    past_due = (df["due_date"] < as_of).fillna(False)
    df["age_days"] = (as_of - df["due_date"]).dt.days.clip(lower=0)

    # freight
    df["expected_freight"] = expected_freight(df["weight_kg"], df["courier"], slabs)
    freight_over = df["billed_freight"] - df["expected_freight"]
    f_freight = df["billed_freight"].notna() & (freight_over > tol)

    f_ret = is_ret & df["warehouse_received_date"].isna() & ((as_of - base).dt.days > return_window).fillna(False)
    f_unpaid = ~is_ret & ~has_pay & past_due & ~rate_missing & (df["expected"] > 0)
    f_short = has_pay & ~rate_missing & (df["diff"] < -tol)
    f_over = has_pay & ~rate_missing & (df["diff"] > tol)

    df["status"] = np.select(
        [f_ret, f_unpaid, f_freight, f_short, rate_missing, f_over, ~is_ret & ~has_pay],
        ["return_not_received", "unpaid_past_due", "freight_overcharged", "short_paid", "unrated",
         "overpaid", "pending"], default="settled")
    flag_names = {"return_not_received": f_ret, "unpaid_past_due": f_unpaid,
                  "freight_overcharged": f_freight, "short_paid": f_short}
    df["flags"] = ""
    for name, mask in flag_names.items():
        df.loc[mask, "flags"] = df.loc[mask, "flags"] + name + ","
    df["flags"] = df["flags"].str.rstrip(",")

    claims = _build_claims(df, flag_names, freight_over, is_cod, as_of, return_window, base)
    recon = df.reset_index()
    summary = {"orders": int(len(recon)), "by_status": recon["status"].value_counts().to_dict(),
               "claims": int(len(claims)), "claim_amount": float(claims["amount"].sum()) if len(claims) else 0.0}
    return recon, claims, summary


def _build_claims(df, flag_names, freight_over, is_cod, as_of, return_window, base):
    cod_courier = is_cod & df["r_cod_by_courier"].fillna(False).astype(bool) & df["courier"].notna()
    chan_partner = np.where(cod_courier, df["courier"], df["channel"])
    ret_partner = np.where(df["courier"].notna(), df["courier"], df["channel"])
    spec = {
        "unpaid_past_due": (df["expected"], chan_partner, df["age_days"]),
        "short_paid": (-df["diff"], chan_partner, df["age_days"]),
        "freight_overcharged": (freight_over, df["courier"], df["age_days"]),
        "return_not_received": (df["value"], ret_partner,
                                ((as_of - base).dt.days - return_window).clip(lower=0)),
    }
    parts = []
    for ctype, mask in flag_names.items():
        if not mask.any():
            continue
        amount, partner, age = spec[ctype]
        sub = df[mask]
        parts.append(pd.DataFrame({
            "order_id": sub.index, "type": ctype,
            "partner": pd.Series(partner, index=df.index)[mask].to_numpy(),
            "amount": np.round(amount[mask].to_numpy(dtype=float), 2),
            "age_days": age[mask].fillna(0).astype(int).to_numpy()}))
    if not parts:
        return pd.DataFrame(columns=["order_id", "type", "partner", "amount", "age_days", "evidence"])
    cl = pd.concat(parts, ignore_index=True)
    cl = cl[cl["amount"] > 0].reset_index(drop=True)
    cl["evidence"] = [evidence_for(df.loc[r.order_id], r.type, r.amount) for r in cl.itertuples()]
    return cl


def _num(x):
    return None if pd.isna(x) else round(float(x), 2)


def _date(x):
    return None if pd.isna(x) else pd.Timestamp(x).date().isoformat()


def evidence_for(row, ctype: str, amount: float) -> dict:
    """Self-contained evidence record for a claim. Contains no customer personal data."""
    return {
        "rule": RULE_TEXT[ctype], "claim_amount": amount,
        "order": {"channel": row["channel"], "courier": None if pd.isna(row["courier"]) else row["courier"],
                  "payment_mode": row["payment_mode"], "delivery_status": row["delivery_status"],
                  "value": _num(row["value"]), "order_date": _date(row["order_date"]),
                  "delivery_date": _date(row["delivery_date"]), "due_date": _date(row["due_date"]),
                  "warehouse_received_date": _date(row["warehouse_received_date"])},
        "expected": {"commission": _num(row["commission"]), "prepaid_fee": _num(row["prepaid_fee"]),
                     "cod_fee": _num(row["cod_fee"]), "fixed_fee": _num(row["fixed_fee"]),
                     "return_fee": _num(row["return_fee"]), "total": _num(row["expected"])},
        "received": {"settlement": _num(row["settled"]), "cod_remitted": _num(row["remitted"]),
                     "total": _num(row["received"]), "payment_lines": int(row["pay_lines"])},
        "statutory_not_leakage": {"tcs": _num(row["tcs"]), "tds": _num(row["tds"])},
        "freight": {"billed": _num(row["billed_freight"]), "rate_card": _num(row["expected_freight"]),
                    "declared_weight_kg": _num(row["weight_kg"]), "billed_weight_kg": _num(row["billed_weight_kg"])},
    }
