"""Synthetic sample data for Company A. All names and phone numbers are invented.

Plants known discrepancies so the app has something to find:
unpaid COD / settlements, short payments, over-deducted returns, freight overcharges,
returns that never reached the warehouse, duplicate lines, rows with a blank order id,
and a later settlement file in a changed column format (to exercise AI column mapping).
The three example rows from the client's brief are included verbatim as fixtures.
"""
from __future__ import annotations

from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd

CHANNELS = ["Website", "Marketplace 1", "Marketplace 2", "Marketplace 3", "Quick-commerce 1", "Quick-commerce 2"]
SHARE = [0.40, 0.20, 0.12, 0.08, 0.12, 0.08]
PREFIX = {"Website": "W", "Marketplace 1": "M", "Marketplace 2": "N", "Marketplace 3": "P",
          "Quick-commerce 1": "Q", "Quick-commerce 2": "R"}

# ASSUMPTION: rate cards are illustrative; the brief gives none.
RATE_CARDS = {
    "Website":          dict(commission_pct=0, prepaid_fee_pct=2, cod_fee_pct=6, fixed_fee=0, return_fee_pct=4, remit_days=10, cod_by_courier=True),
    "Marketplace 1":    dict(commission_pct=25, prepaid_fee_pct=0, cod_fee_pct=0, fixed_fee=0, return_fee_pct=4, remit_days=7, cod_by_courier=False),
    "Marketplace 2":    dict(commission_pct=22, prepaid_fee_pct=0, cod_fee_pct=0, fixed_fee=20, return_fee_pct=4, remit_days=7, cod_by_courier=False),
    "Marketplace 3":    dict(commission_pct=18, prepaid_fee_pct=0, cod_fee_pct=0, fixed_fee=10, return_fee_pct=5, remit_days=7, cod_by_courier=False),
    "Quick-commerce 1": dict(commission_pct=28, prepaid_fee_pct=0, cod_fee_pct=0, fixed_fee=0, return_fee_pct=3, remit_days=3, cod_by_courier=False),
    "Quick-commerce 2": dict(commission_pct=30, prepaid_fee_pct=0, cod_fee_pct=0, fixed_fee=0, return_fee_pct=3, remit_days=3, cod_by_courier=False),
}
SLABS = {
    "Courier A": [{"upto_kg": 0.5, "rate": 45}, {"upto_kg": 1, "rate": 68}, {"upto_kg": 2, "rate": 105},
                  {"upto_kg": 5, "rate": 180}, {"upto_kg": 999, "rate": 320}],
    "Courier B": [{"upto_kg": 0.5, "rate": 42}, {"upto_kg": 1, "rate": 65}, {"upto_kg": 2, "rate": 100},
                  {"upto_kg": 5, "rate": 175}, {"upto_kg": 999, "rate": 310}],
}
FIRST = ["Asha", "Ravi", "Meena", "Kiran", "Divya", "Arjun", "Sneha", "Vikram", "Priya", "Rohit", "Lakshmi", "Imran"]
LAST = ["Nair", "Sharma", "Reddy", "Iyer", "Gupta", "Khan", "Patel", "Das", "Menon", "Joshi", "Rao", "Singh"]
WEIGHTS = np.array([0.3, 0.4, 0.8, 1.2, 1.8, 3.5])


def _slab_rate(courier: str, w: float) -> float:
    for s in SLABS[courier]:
        if w <= s["upto_kg"]:
            return s["rate"]
    return SLABS[courier][-1]["rate"]


def _expected(ch: str, value: float, cod: bool, ret: bool) -> float:
    r = RATE_CARDS[ch]
    if ret:
        return round(-value * r["return_fee_pct"] / 100)
    fee = value * r["commission_pct"] / 100 + (value * r["cod_fee_pct"] / 100 if cod else value * r["prepaid_fee_pct"] / 100)
    return round(value - fee - r["fixed_fee"])


def generate(n: int = 10_000, seed: int = 7, as_of: date | None = None) -> dict[str, pd.DataFrame]:
    rng = np.random.default_rng(seed)
    as_of = pd.Timestamp(as_of or date.today())
    ch = rng.choice(CHANNELS, size=n, p=SHARE)
    value = np.round(rng.choice([499, 699, 899, 1199, 1499, 1799, 2398, 2999], size=n) * rng.uniform(0.9, 1.1, n), 0)
    cod = (ch == "Website") & (rng.random(n) < 0.55)
    is_ret = rng.random(n) < 0.075
    order_date = as_of - pd.to_timedelta(rng.integers(12, 150, n), unit="D")
    delivery = order_date + pd.to_timedelta(rng.integers(3, 8, n) + np.where(is_ret, rng.integers(6, 10, n), 0), unit="D")
    courier = np.where(ch == "Website", rng.choice(["Courier A", "Courier B"], n), None)
    weight = np.where(ch == "Website", rng.choice(WEIGHTS, n), np.nan)
    lost_return = is_ret & (rng.random(n) < 0.25)
    wh = pd.Series(delivery + pd.to_timedelta(rng.integers(1, 5, n), unit="D"))
    wh[~is_ret | lost_return] = pd.NaT
    ids = np.array([f"ORD-{PREFIX[c]}-{100000 + i}" for i, c in enumerate(ch)])

    orders = pd.DataFrame({
        "order_id": ids, "channel": ch, "order_date": order_date, "value": value,
        "payment_mode": np.where(cod, "COD", "Prepaid"),
        "delivery_status": np.where(is_ret, "Returned to warehouse", "Delivered"),
        "delivery_date": delivery, "courier": courier, "weight_kg": weight, "warehouse_received_date": wh,
        "customer_name": [f"{rng.choice(FIRST)} {rng.choice(LAST)}" for _ in range(n)],
        "phone": ["9" + "".join(map(str, rng.integers(0, 10, 9))) for _ in range(n)],
    })

    # --- fixtures straight from the brief ---------------------------------------------------------
    d = lambda k: as_of - pd.Timedelta(days=k)
    fx = pd.DataFrame([
        dict(order_id="ORD-W-204118", channel="Website", order_date=d(44), value=1499, payment_mode="COD",
             delivery_status="Delivered", delivery_date=d(40), courier="Courier A", weight_kg=0.4,
             warehouse_received_date=pd.NaT, customer_name="Asha Nair", phone="9000000001"),
        dict(order_id="ORD-M-88120", channel="Marketplace 1", order_date=d(35), value=1199, payment_mode="Prepaid",
             delivery_status="Delivered", delivery_date=d(30), courier=None, weight_kg=np.nan,
             warehouse_received_date=pd.NaT, customer_name="Ravi Sharma", phone="9000000002"),
        dict(order_id="ORD-W-204377", channel="Website", order_date=d(50), value=2398, payment_mode="Prepaid",
             delivery_status="Returned to warehouse", delivery_date=d(38), courier="Courier B", weight_kg=1.2,
             warehouse_received_date=d(35), customer_name="Meena Iyer", phone="9000000003"),
    ])
    orders = pd.concat([fx, orders], ignore_index=True)
    N = len(orders)

    # --- payments ---------------------------------------------------------------------------------
    rem = orders["channel"].map(lambda c: RATE_CARDS[c]["remit_days"]).to_numpy()
    cod_o = (orders["payment_mode"] == "COD").to_numpy()
    ret_o = orders["delivery_status"].str.contains("Return").to_numpy()
    exp = np.array([_expected(c, v, k, r) for c, v, k, r in zip(orders.channel, orders.value, cod_o, ret_o)], dtype=float)
    u = rng.random(N)
    pay_date = orders["delivery_date"] + pd.to_timedelta(rem + rng.integers(-2, 3, N), unit="D")
    paid = (pay_date <= as_of).to_numpy()
    unpaid = (u < 0.045) & ~ret_o
    paid_amt = exp + rng.uniform(-6, 6, N)
    short = (u >= 0.045) & (u < 0.09)
    paid_amt = np.where(short, paid_amt - rng.uniform(15, 180, N), paid_amt)
    over = (u >= 0.09) & (u < 0.10)
    paid_amt = np.where(over, paid_amt + rng.uniform(20, 100, N), paid_amt)
    ret_over = ret_o & (rng.random(N) < 0.15)
    paid_amt = np.where(ret_over, paid_amt - rng.uniform(20, 90, N), paid_amt)
    has_line = paid & ~unpaid & ~(ret_o & cod_o)
    # fixtures: exact values from the brief
    fx_i = {oid: i for i, oid in enumerate(orders.order_id[:3])}
    has_line[fx_i["ORD-W-204118"]] = False
    paid_amt[fx_i["ORD-M-88120"]], has_line[fx_i["ORD-M-88120"]] = 862, True
    paid_amt[fx_i["ORD-W-204377"]], has_line[fx_i["ORD-W-204377"]] = -142, True
    pay_date.iloc[fx_i["ORD-M-88120"]] = d(22)
    pay_date.iloc[fx_i["ORD-W-204377"]] = d(25)

    pay = orders.assign(amt=np.round(paid_amt, 2), pay_date=pay_date)[has_line].copy()
    is_cod_line = (pay.payment_mode == "COD")
    pct = np.where(pay.channel.isin(["Website"]), 0, 0.01)
    pay["tcs"] = np.where(pay.amt > 0, np.round(pay.value * pct, 2), 0)
    pay["tds"] = pay["tcs"]
    settlement = pay[~is_cod_line].rename(columns={"amt": "settled_amount", "pay_date": "settlement_date"})
    settlement = settlement[["order_id", "settled_amount", "tcs", "tds", "settlement_date"]]
    cod_lines = pay[is_cod_line].rename(columns={"amt": "remitted_amount", "pay_date": "remittance_date"})
    cod_lines = cod_lines[["order_id", "remitted_amount", "remittance_date"]]

    # noise: exact duplicate lines and blank order ids
    dup = settlement.sample(frac=0.003, random_state=seed)
    settlement = pd.concat([settlement, dup], ignore_index=True)
    r = rng.random(len(settlement))
    settlement.loc[r < 0.001, "order_id"] = ""                                   # unusable row: rejected at load
    orphan = (r >= 0.001) & (r < 0.004)                                           # id not in orders: unmatched line
    settlement.loc[orphan, "order_id"] = [f"ORD-X-{900000 + i}" for i in range(int(orphan.sum()))]

    # later payouts arrive in a file with a changed format (not loaded at seed time)
    late = settlement["settlement_date"] >= (as_of - pd.Timedelta(days=5))
    late_file = settlement[late].copy()
    settlement = settlement[~late]

    # --- freight ----------------------------------------------------------------------------------
    fr = orders[orders.courier.notna() & ~ret_o].copy()
    base = np.array([_slab_rate(c, w) for c, w in zip(fr.courier, fr.weight_kg)], dtype=float)
    over_f = rng.random(len(fr)) < 0.035
    bump = rng.choice([0.6, 1.0, 1.5], len(fr))
    billed_w = np.where(over_f, fr.weight_kg + bump, fr.weight_kg)
    billed = np.array([_slab_rate(c, w) for c, w in zip(fr.courier, billed_w)], dtype=float)
    billed = np.where(over_f & (billed - base <= 10), base + rng.uniform(15, 60, len(fr)), billed)
    freight = pd.DataFrame({"order_id": fr.order_id.to_numpy(), "billed_amount": np.round(billed, 2),
                            "billed_weight_kg": billed_w})
    fixture_fr = freight.order_id.eq("ORD-W-204118")
    freight.loc[fixture_fr, ["billed_amount", "billed_weight_kg"]] = [45.0, 0.4]
    # the planted wrong-slab example is ORD-W-204118 only when randomly hit; keep it clean

    return {"orders": orders, "settlement": settlement, "cod": cod_lines, "freight": freight, "late_settlement": late_file}


def write_files(out: Path, n: int = 10_000, seed: int = 7, as_of: date | None = None) -> dict[str, Path]:
    """Write partner-style CSVs with their own header names (so column mapping has work to do)."""
    out.mkdir(parents=True, exist_ok=True)
    t = generate(n, seed, as_of)
    fmt = lambda s: pd.to_datetime(s).dt.strftime("%Y-%m-%d")
    o = t["orders"].copy()
    for c in ["order_date", "delivery_date", "warehouse_received_date"]:
        o[c] = fmt(o[c]).replace("NaT", "")
    o = o.rename(columns={"order_id": "Order ID", "channel": "Channel", "order_date": "Order Date", "value": "Value ₹",
                          "payment_mode": "Payment", "delivery_status": "Delivery Status", "delivery_date": "Delivery Date",
                          "courier": "Courier", "weight_kg": "Weight (kg)", "warehouse_received_date": "Warehouse Received",
                          "customer_name": "Customer Name", "phone": "Phone"})
    s = t["settlement"].assign(settlement_date=lambda x: fmt(x.settlement_date)).rename(columns={
        "order_id": "Order No", "settled_amount": "Net Payout", "tcs": "TCS", "tds": "TDS", "settlement_date": "Settlement Date"})
    c = t["cod"].assign(remittance_date=lambda x: fmt(x.remittance_date)).rename(columns={
        "order_id": "Order Ref", "remitted_amount": "COD Remitted", "remittance_date": "Remitted On"})
    f = t["freight"].rename(columns={"order_id": "Order Ref", "billed_weight_kg": "Charged Weight", "billed_amount": "Freight Charged"})
    late = t["late_settlement"].assign(settlement_date=lambda x: pd.to_datetime(x.settlement_date).dt.strftime("%d-%m-%Y")).rename(
        columns={"order_id": "Order Item ID", "settled_amount": "Amount Settled (INR)", "tcs": "GST TCS",
                 "tds": "Income Tax TDS", "settlement_date": "Paid On"})
    files = {"orders": o, "settlement": s, "cod": c, "freight": f, "settlement_new_format": late}
    paths = {}
    for k, df in files.items():
        p = out / f"{k}.csv"
        df.to_csv(p, index=False)
        paths[k] = p
    return paths


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--rows", type=int, default=10_000)
    ap.add_argument("--out", default="../sample_data")
    a = ap.parse_args()
    for k, p in write_files(Path(a.out), a.rows).items():
        print(k, p)
