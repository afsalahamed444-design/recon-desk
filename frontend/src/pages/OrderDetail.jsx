import { useState } from "react";
import { Link, useParams } from "react-router-dom";
import { api } from "../api";
import { useAuth } from "../App.jsx";
import { CLAIM_TYPE, Chip, ErrorBox, Loading, date, evidenceLines, money, useLoad } from "../lib.jsx";

export default function OrderDetail() {
  const { id } = useParams();
  const { user } = useAuth();
  const [unmask, setUnmask] = useState(false);
  const { data, error, loading, reload } = useLoad(() => api.order(id, unmask), [id, unmask]);

  if (error) return <><Back /><ErrorBox error={error} retry={reload} /></>;
  if (loading && !data) return <><Back /><Loading rows={7} /></>;
  const { recon: r, customer, lines, claims } = data;
  const fee = (label, v) => v ? <tr><td>− {label}</td><td className="num">{money(v, { paise: true })}</td></tr> : null;
  const isReturn = r.return_fee > 0 || /return|rto/i.test(r.delivery_status);

  return (
    <>
      <Back />
      <div className="head"><div><h1>{r.order_id}</h1><p>{r.channel} · {r.payment_mode} · {r.delivery_status}</p></div><Chip status={r.status} /></div>
      <div className="grid2">
        <div>
          <div className="card">
            <h2>Expected vs received</h2>
            <table className="ledger"><tbody>
              {!isReturn && <tr><td>Order value</td><td className="num">{money(r.value, { paise: true })}</td></tr>}
              {fee("Commission", r.commission)}{fee("Payment gateway fee", r.prepaid_fee)}{fee("COD fee", r.cod_fee)}{fee("Fixed fee", r.fixed_fee)}
              {isReturn && <tr><td>Reverse deduction on return</td><td className="num">{money(-r.return_fee, { paise: true })}</td></tr>}
              <tr className="sum"><td>Expected from rate card</td><td className="num">{money(r.expected)}</td></tr>
              <tr><td>Received ({r.pay_lines} line{r.pay_lines === 1 ? "" : "s"})</td><td className="num">{money(r.received, { paise: true })}</td></tr>
              <tr className="sum diff"><td>Difference</td><td className={`num ${r.diff < -10 ? "risk" : ""}`}>{money(r.diff, { paise: true, sign: true })}</td></tr>
            </tbody></table>
            <p className="muted" style={{ marginTop: 10, fontSize: 13 }}>Differences of ₹10 or less are tolerated. Due {date(r.due_date)}{r.age_days ? ` · ${r.age_days} days overdue` : ""}.</p>
          </div>

          <div className="card">
            <h2>Deducted at source — not leakage</h2>
            <table className="ledger"><tbody>
              <tr><td>GST TCS</td><td className="num">{money(r.tcs, { paise: true })}</td></tr>
              <tr><td>Income-tax TDS</td><td className="num">{money(r.tds, { paise: true })}</td></tr>
            </tbody></table>
          </div>

          {r.billed_freight != null && (
            <div className="card"><h2>Freight</h2>
              <table className="ledger"><tbody>
                <tr><td>Billed by {r.courier}</td><td className="num">{money(r.billed_freight, { paise: true })}</td></tr>
                <tr><td>Rate card for {r.weight_kg ?? "—"} kg</td><td className="num">{money(r.expected_freight, { paise: true })}</td></tr>
                <tr className="sum"><td>Billed weight</td><td className="num">{r.billed_weight_kg ?? "—"} kg</td></tr>
              </tbody></table></div>)}

          {claims.length > 0 && (
            <div className="card"><h2>Claims raised</h2>
              {claims.map((c) => (
                <div key={c.id} style={{ marginBottom: 14 }}>
                  <div style={{ display: "flex", justifyContent: "space-between" }}><strong>{CLAIM_TYPE[c.type]} · {c.partner}</strong><strong className="risk">{money(c.amount, { paise: true })}</strong></div>
                  <div className="evidence" style={{ borderRadius: 8, marginTop: 8 }}>{evidenceLines(c.evidence).map((l, i) => <p key={i}>{l}</p>)}</div>
                </div>))}
            </div>)}
        </div>

        <div>
          <div className="card">
            <h2>Payment lines</h2>
            {lines.settlement.length + lines.cod.length === 0 ? <p className="muted">No settlement or COD line found for this order.</p> :
              <table className="ledger"><tbody>
                {lines.settlement.map((l, i) => <tr key={`s${i}`}><td>Settlement · {date(l.settlement_date)}</td><td className="num">{money(l.settled_amount, { paise: true })}</td></tr>)}
                {lines.cod.map((l, i) => <tr key={`c${i}`}><td>COD remittance · {date(l.remittance_date)}</td><td className="num">{money(l.remitted_amount, { paise: true })}</td></tr>)}
              </tbody></table>}
          </div>
          <div className="card">
            <h2>Order</h2>
            <dl className="kv">
              <dt>Ordered</dt><dd>{date(r.order_date)}</dd><dt>Delivered</dt><dd>{date(r.delivery_date)}</dd>
              <dt>Courier</dt><dd>{r.courier || "—"}</dd>
              {isReturn && <><dt>Warehouse scan</dt><dd>{data.warehouse_received_date ? date(data.warehouse_received_date) : <span className="risk">Not received</span>}</dd></>}
              <dt>Customer</dt><dd>{customer.name || "—"}</dd><dt>Phone</dt><dd>{customer.phone || "—"}</dd>
            </dl>
            {customer.masked ? (user.role === "cofounder"
              ? <button className="btn small" style={{ marginTop: 12 }} onClick={() => setUnmask(true)}>Reveal customer details</button>
              : <p className="muted" style={{ marginTop: 12, fontSize: 13 }}>Customer details are masked. Only the co-founder can reveal them.</p>)
              : <p className="muted" style={{ marginTop: 12, fontSize: 13 }}>Revealed for this view. This access is logged.</p>}
          </div>
        </div>
      </div>
    </>
  );
}
const Back = () => <p style={{ marginBottom: 14 }}><Link className="muted" to="/orders">← Orders</Link></p>;
