import io

import pandas as pd
import pytest

from app import mapping as mp
from app.main import csv_safe


def test_login_rejects_bad_password(client):
    r = client.post("/api/auth/login", json={"email": "finance@companya.test", "password": "wrong"})
    assert r.status_code == 401


@pytest.mark.parametrize("path", ["/api/dashboard", "/api/orders", "/api/claims", "/api/rate-cards", "/api/uploads"])
def test_endpoints_require_sign_in(client, path):
    assert client.get(path).status_code == 401


def test_tampered_token_rejected(client, exec_h):
    bad = {"Authorization": exec_h["Authorization"][:-3] + "abc"}
    assert client.get("/api/me", headers=bad).status_code == 401


def test_cofounder_cannot_write(client, cofounder_h):
    files = {"file": ("x.csv", b"a,b\n1,2\n", "text/csv")}
    assert client.post("/api/uploads", data={"source": "cod"}, files=files, headers=cofounder_h).status_code == 403
    assert client.post("/api/reconcile", headers=cofounder_h).status_code == 403
    assert client.patch("/api/claims/1", json={"status": "filed"}, headers=cofounder_h).status_code == 403
    assert client.put("/api/rate-cards/1", json={}, headers=cofounder_h).status_code == 403


def test_dashboard_has_at_risk_and_statutory_separate(client, exec_h):
    d = client.get("/api/dashboard", headers=exec_h).json()
    assert d["at_risk"] > 0 and d["partners"] and d["buckets"] == ["0-30", "31-60", "61-90", "90+"]
    assert sum(p["total"] for p in d["partners"]) == pytest.approx(d["at_risk"], rel=1e-6)
    assert any(s["tcs"] > 0 for s in d["statutory"])


def test_brief_fixture_orders_in_api(client, exec_h):
    r = client.get("/api/orders/ORD-W-204118", headers=exec_h).json()
    assert r["recon"]["status"] == "unpaid_past_due" and r["recon"]["diff"] == -1409
    assert client.get("/api/orders/NOPE", headers=exec_h).status_code == 404


def test_pii_masked_by_default_and_unmask_is_cofounder_only_and_audited(client, exec_h, cofounder_h):
    masked = client.get("/api/orders/ORD-W-204118", headers=exec_h).json()["customer"]
    assert masked["masked"] and "Asha" not in masked["name"] and "9000000001" not in masked["phone"]
    assert client.get("/api/orders/ORD-W-204118?unmask=true", headers=exec_h).status_code == 403
    real = client.get("/api/orders/ORD-W-204118?unmask=true", headers=cofounder_h).json()["customer"]
    assert real["name"] == "Asha Nair" and not real["masked"]
    from sqlalchemy import select
    from app import db
    with db.engine.connect() as c:
        assert c.execute(select(db.audit_log).where(db.audit_log.c.action == "pii.unmask")).first()


def test_orders_filters_and_validation(client, exec_h):
    r = client.get("/api/orders?status=unpaid_past_due&page_size=5", headers=exec_h).json()
    assert r["total"] > 0 and all(i["status"] == "unpaid_past_due" for i in r["items"])
    assert client.get("/api/orders?sort=bogus", headers=exec_h).status_code == 422
    assert client.get("/api/orders?page_size=100000", headers=exec_h).status_code == 422
    assert client.get("/api/orders?q=' OR 1=1 --", headers=exec_h).status_code == 200  # sanitised, not injected


def test_claims_export_is_csv_safe_and_free_of_personal_data(client, exec_h):
    r = client.get("/api/claims/export?partner=Courier A", headers=exec_h)
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/csv")
    body = r.text
    assert body.startswith("claim_id,partner,order_id") and "Asha" not in body and "9000000001" not in body
    assert csv_safe("=HYPERLINK(1)") == "'=HYPERLINK(1)" and csv_safe("@x") == "'@x" and csv_safe(-5) == -5


def test_claim_status_update_validated(client, exec_h):
    cid = client.get("/api/claims?page_size=1", headers=exec_h).json()["items"][0]["id"]
    assert client.patch(f"/api/claims/{cid}", json={"status": "nonsense"}, headers=exec_h).status_code == 422
    assert client.patch(f"/api/claims/{cid}", json={"status": "filed"}, headers=exec_h).status_code == 200


def test_rate_card_validation(client, exec_h):
    assert client.put("/api/rate-cards/1", json={"commission_pct": -5}, headers=exec_h).status_code == 422
    assert client.put("/api/rate-cards/1", json={"commission_pct": 500}, headers=exec_h).status_code == 422


# ---- upload -> mapping -> process flow ---------------------------------------------------------
def _upload(client, h, source, csv_text, name="f.csv"):
    return client.post("/api/uploads", data={"source": source}, files={"file": (name, csv_text.encode(), "text/csv")}, headers=h)


def test_upload_rejects_bad_types_and_duplicates(client, exec_h):
    assert _upload(client, exec_h, "cod", "a,b\n1,2\n", "evil.exe").status_code == 422
    assert _upload(client, exec_h, "nonsense", "a,b\n1,2\n").status_code == 422
    assert _upload(client, exec_h, "cod", "only_one_col\n1\n").status_code == 422
    ok = _upload(client, exec_h, "cod", "Ref,Amt\nORD-W-100001,100\n")
    assert ok.status_code == 200
    assert _upload(client, exec_h, "cod", "Ref,Amt\nORD-W-100001,100\n").status_code == 409


def test_changed_format_flow_with_fallback_preview_save_process_and_rollback(client, exec_h):
    csv_text = ("Order Item ID,Amount Settled (INR),GST TCS,Income Tax TDS,Paid On\n"
                "ORD-N-999991,500.50,5,5,03-11-2026\nORD-N-999992,(20.00),0,0,04-11-2026\n,10,0,0,04-11-2026\n")
    up = _upload(client, exec_h, "settlement", csv_text).json()
    sug = client.post(f"/api/uploads/{up['id']}/suggest", headers=exec_h).json()
    assert sug["origin"] in ("fuzzy", "saved")
    assert sug["missing_required"] == []                      # fallback finds both required fields
    assert len(sug["preview"]["rows"]) <= 20 and sug["preview"]["rejected"] == 1   # blank order id rejected

    bad = client.post(f"/api/uploads/{up['id']}/preview", json={"mapping": {"order_id": "Nope"}}, headers=exec_h).json()
    assert bad["errors"]
    assert client.post("/api/mappings", json={"upload_id": up["id"], "mapping": {"order_id": "Order Item ID"}}, headers=exec_h).status_code == 422

    v = client.post("/api/mappings", json={"upload_id": up["id"], "mapping": sug["mapping"], "origin": sug["origin"]}, headers=exec_h).json()
    assert client.post(f"/api/uploads/{up['id']}/process", json={"mapping_version_id": v["id"]}, headers=exec_h).status_code == 202
    done = client.get(f"/api/uploads/{up['id']}", headers=exec_h).json()
    assert done["status"] == "done" and done["rows_loaded"] == 2 and done["rows_rejected"] == 1
    assert client.post(f"/api/uploads/{up['id']}/process", json={"mapping_version_id": v["id"]}, headers=exec_h).status_code == 409

    # versioning and rollback
    versions = client.get("/api/mappings?source=settlement", headers=exec_h).json()
    assert len(versions) >= 2 and sum(1 for x in versions if x["active"]) == 1
    older = [x for x in versions if not x["active"]][0]
    assert client.post(f"/api/mappings/{older['id']}/activate", headers=exec_h).status_code == 200
    now = client.get("/api/mappings?source=settlement", headers=exec_h).json()
    assert [x for x in now if x["active"]][0]["id"] == older["id"]


def test_reconcile_endpoint_returns_run_summary(client, exec_h):
    s = client.post("/api/reconcile", headers=exec_h).json()
    assert s["orders"] > 1000 and s["line_match_rate"] > 0.9 and "by_status" in s


# ---- AI mapping guard rails -------------------------------------------------------------------
def test_validate_suggestion_discards_hallucinated_columns_and_fields():
    headers = ["Order No", "Net Payout"]
    raw = {"order_id": {"column": "Order No", "confidence": 0.99}, "settled_amount": {"column": "Made Up", "confidence": 0.9},
           "bogus_field": {"column": "Net Payout", "confidence": 0.9}, "tcs": {"column": "Order No", "confidence": 0.5}}
    ok = mp.validate_suggestion("settlement", headers, raw)
    assert ok == {"order_id": {"column": "Order No", "confidence": 0.99}}   # reused column dropped too


def test_ai_failure_falls_back_to_fuzzy(monkeypatch):
    monkeypatch.setattr(mp.settings, "anthropic_key", "sk-fake")
    monkeypatch.setattr(mp.httpx, "post", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")))
    r = mp.suggest("cod", ["Order Ref", "COD Remitted", "Remitted On"], [])
    assert r["origin"] == "fuzzy" and r["mapping"]["order_id"] == "Order Ref" and not r["missing_required"]


def test_ai_garbage_json_falls_back(monkeypatch):
    class R:
        def raise_for_status(self): pass
        def json(self): return {"content": [{"type": "text", "text": "not json at all"}]}
    monkeypatch.setattr(mp.settings, "anthropic_key", "sk-fake")
    monkeypatch.setattr(mp.httpx, "post", lambda *a, **k: R())
    assert mp.suggest("cod", ["Order Ref", "COD Remitted"], [])["origin"] == "fuzzy"


def test_ai_valid_json_is_used_but_low_confidence_is_flagged(monkeypatch):
    class R:
        def raise_for_status(self): pass
        def json(self): return {"content": [{"type": "text", "text":
            '```json\n{"order_id":{"column":"Ref","confidence":0.95},"remitted_amount":{"column":"Amt","confidence":0.6}}\n```'}]}
    monkeypatch.setattr(mp.settings, "anthropic_key", "sk-fake")
    monkeypatch.setattr(mp.httpx, "post", lambda *a, **k: R())
    r = mp.suggest("cod", ["Ref", "Amt"], [])
    assert r["origin"] == "ai" and r["needs_check"] == ["remitted_amount"]


def test_saved_mapping_is_reused_when_headers_unchanged_and_not_when_changed():
    prev = {"order_id": "Order Ref", "remitted_amount": "COD Remitted"}
    assert mp.suggest("cod", ["Order Ref", "COD Remitted"], [], prev)["origin"] == "saved"
    assert mp.suggest("cod", ["Reference", "Amount Remitted"], [], prev)["origin"] == "fuzzy"


def test_personal_data_never_sent_to_ai():
    rows = [{"Customer Name": "Asha Nair", "Mobile": "9876543210", "Net Payout": "100", "Ref": "9876543210"}]
    s = mp.safe_samples(["Customer Name", "Mobile", "Net Payout", "Ref"], rows)
    assert s["Customer Name"] == [] and s["Mobile"] == [] and s["Net Payout"] == ["100"] and s["Ref"] == ["<redacted>"]
