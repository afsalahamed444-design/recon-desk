import pandas as pd
import pytest

from app.recon import ORDER_COLS, expected_freight, reconcile

AS_OF = pd.Timestamp("2026-11-05")
RATES = pd.DataFrame([
    dict(name="Website", commission_pct=0, prepaid_fee_pct=2, cod_fee_pct=6, fixed_fee=0, return_fee_pct=4,
         remit_days=10, cod_by_courier=True),
    dict(name="Marketplace 1", commission_pct=25, prepaid_fee_pct=0, cod_fee_pct=0, fixed_fee=0,
         return_fee_pct=4, remit_days=7, cod_by_courier=False),
]).set_index("name")
SLABS = {"Courier A": [{"upto_kg": 0.5, "rate": 45}, {"upto_kg": 1, "rate": 68}, {"upto_kg": 2, "rate": 105},
                       {"upto_kg": 999, "rate": 320}]}


def order(oid, channel="Website", value=1000.0, pay="Prepaid", status="Delivered", delivered="2026-09-01",
          courier=None, weight=None, wh=None):
    return dict(order_id=oid, channel=channel, courier=courier, order_date=pd.Timestamp(delivered) - pd.Timedelta(days=3),
                value=value, payment_mode=pay, delivery_status=status, delivery_date=pd.Timestamp(delivered),
                weight_kg=weight, warehouse_received_date=pd.Timestamp(wh) if wh else pd.NaT)


def run(orders, settle=(), cod=(), freight=(), as_of=AS_OF):
    o = pd.DataFrame(orders, columns=ORDER_COLS)
    s = pd.DataFrame(list(settle), columns=["order_id", "settled_amount", "tcs", "tds"]) if settle else pd.DataFrame()
    c = pd.DataFrame(list(cod), columns=["order_id", "remitted_amount"]) if cod else pd.DataFrame()
    f = pd.DataFrame(list(freight), columns=["order_id", "billed_amount", "billed_weight_kg"]) if freight else pd.DataFrame()
    recon, claims, summary = reconcile(o, s, c, f, RATES, SLABS, as_of)
    return recon.set_index("order_id"), claims, summary


# ---- the three rows from the client's brief, as fixtures --------------------------------------
def test_brief_fixture_unpaid_cod():
    r, claims, _ = run([order("ORD-W-204118", value=1499, pay="COD", courier="Courier A", delivered="2026-09-20")])
    row = r.loc["ORD-W-204118"]
    assert row.expected == 1409 and row.received == 0 and row["diff"] == -1409
    assert row.status == "unpaid_past_due"
    c = claims.iloc[0]
    assert c.type == "unpaid_past_due" and c.amount == 1409 and c.partner == "Courier A"  # COD owed by courier


def test_brief_fixture_short_paid_marketplace():
    r, claims, _ = run([order("ORD-M-88120", channel="Marketplace 1", value=1199)],
                       settle=[("ORD-M-88120", 862, 0, 0)])
    row = r.loc["ORD-M-88120"]
    assert row.expected == 899 and round(row["diff"]) == -37
    assert row.status == "short_paid" and claims.iloc[0].partner == "Marketplace 1"


def test_brief_fixture_return_overdeducted():
    r, claims, _ = run([order("ORD-W-204377", value=2398, status="Returned to warehouse", wh="2026-09-05")],
                       settle=[("ORD-W-204377", -142, 0, 0)])
    row = r.loc["ORD-W-204377"]
    assert row.expected == -96 and row["diff"] == -46 and row.status == "short_paid"
    assert claims.iloc[0].amount == 46


# ---- tolerance boundary ----------------------------------------------------------------------
@pytest.mark.parametrize("received,status", [(990, "settled"), (989.5, "short_paid"), (1010, "settled"), (1011, "overpaid")])
def test_tolerance_boundary_is_strictly_more_than_10(received, status):
    # Marketplace 1, value 1000 -> expected 750
    r, _, _ = run([order("A", channel="Marketplace 1")], settle=[("A", received - 250, 0, 0)])
    assert r.loc["A"].expected == 750
    assert r.loc["A"].status == status


def test_exactly_ten_short_is_settled_and_ten_point_01_is_short():
    r, _, _ = run([order("A", channel="Marketplace 1"), order("B", channel="Marketplace 1")],
                  settle=[("A", 740, 0, 0), ("B", 739.99, 0, 0)])
    assert r.loc["A"].status == "settled" and r.loc["B"].status == "short_paid"


# ---- TCS / TDS --------------------------------------------------------------------------------
def test_tcs_and_tds_never_count_as_short_payment():
    r, claims, _ = run([order("A", channel="Marketplace 1")], settle=[("A", 750, 10, 7.5)])
    assert r.loc["A"].status == "settled" and r.loc["A"]["diff"] == 0
    assert r.loc["A"].tcs == 10 and r.loc["A"].tds == 7.5 and claims.empty


# ---- unpaid / pending -------------------------------------------------------------------------
def test_unpaid_only_after_remittance_window():
    # marketplace remit 7 days: delivered 2026-10-31 -> due 11-07, still pending on 11-05
    r, claims, _ = run([order("A", channel="Marketplace 1", delivered="2026-10-31"),
                        order("B", channel="Marketplace 1", delivered="2026-10-20")])
    assert r.loc["A"].status == "pending" and r.loc["B"].status == "unpaid_past_due"
    assert list(claims.order_id) == ["B"]


def test_partial_payment_is_short_not_unpaid():
    r, claims, _ = run([order("A", channel="Marketplace 1")], settle=[("A", 300, 0, 0)])
    assert r.loc["A"].status == "short_paid" and claims.iloc[0].amount == 450


def test_split_payments_across_settlement_and_cod_are_summed():
    r, _, _ = run([order("A", channel="Marketplace 1")], settle=[("A", 400, 0, 0), ("A", 350, 0, 0)])
    assert r.loc["A"].received == 750 and r.loc["A"].status == "settled"


# ---- freight ----------------------------------------------------------------------------------
def test_freight_slab_lookup_and_overcharge():
    s = expected_freight(pd.Series([0.4, 0.5, 0.51, 1.5, 50, None]), pd.Series(["Courier A"] * 6), SLABS)
    assert list(s[:5]) == [45, 45, 68, 105, 320] and pd.isna(s[5])
    r, claims, _ = run([order("A", pay="COD", courier="Courier A", weight=0.4, value=1000)],
                       cod=[("A", 940)], freight=[("A", 68, 0.9)])
    assert r.loc["A"].status == "freight_overcharged"
    c = claims[claims.type == "freight_overcharged"].iloc[0]
    assert c.amount == 23 and c.partner == "Courier A"


def test_freight_within_tolerance_not_flagged():
    r, _, _ = run([order("A", pay="COD", courier="Courier A", weight=0.4)], cod=[("A", 940)],
                  freight=[("A", 55, 0.4)])
    assert r.loc["A"].status == "settled"


# ---- returns ----------------------------------------------------------------------------------
def test_return_not_received_after_window_only():
    r, claims, _ = run([order("A", status="Returned to warehouse", delivered="2026-11-01"),
                        order("B", status="RTO delivered", delivered="2026-10-01"),
                        order("C", status="Returned", delivered="2026-10-01", wh="2026-10-05")])
    assert r.loc["A"].status != "return_not_received"       # only 4 days, still inside window
    assert r.loc["B"].status == "return_not_received"
    assert r.loc["C"].status != "return_not_received"
    assert list(claims.order_id) == ["B"] and claims.iloc[0].amount == 1000


# ---- precedence, duplicates, unknown channel --------------------------------------------------
def test_status_precedence_but_each_issue_gets_a_claim():
    r, claims, _ = run([order("A", channel="Website", pay="COD", courier="Courier A", weight=0.4, value=1000)],
                       cod=[("A", 900)], freight=[("A", 120, 0.4)])
    assert r.loc["A"].status == "freight_overcharged"            # freight outranks short_paid
    assert set(claims.type) == {"freight_overcharged", "short_paid"}


def test_duplicate_order_rows_keep_last():
    r, _, summary = run([order("A", value=500), order("A", value=1000)])
    assert summary["orders"] == 1 and r.loc["A"].value == 1000


def test_unknown_channel_is_unrated_not_a_claim():
    r, claims, _ = run([order("A", channel="Mystery Shop")])
    assert r.loc["A"].status == "unrated" and claims.empty


def test_claim_evidence_has_no_personal_data():
    _, claims, _ = run([order("A", channel="Marketplace 1")], settle=[("A", 500, 0, 0)])
    text = str(claims.iloc[0].evidence).lower()
    assert "customer" not in text and "phone" not in text
    assert claims.iloc[0].evidence["statutory_not_leakage"] == {"tcs": 0.0, "tds": 0.0}
