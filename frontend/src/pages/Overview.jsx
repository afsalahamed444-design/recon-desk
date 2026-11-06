import { useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { api } from "../api";
import { isExec, useAuth } from "../App.jsx";
import { CLAIM_TYPE, Empty, ErrorBox, Loading, date, lakh, money, useLoad, useToast } from "../lib.jsx";

export default function Overview() {
  const { user } = useAuth();
  const { data: d, error, loading, reload } = useLoad(api.dashboard);
  const [busy, setBusy] = useState(false);
  const [toast, say] = useToast();
  const nav = useNavigate();

  const rerun = async () => {
    setBusy(true);
    try { const s = await api.reconcile(); say(`Reconciled ${s.orders.toLocaleString("en-IN")} orders in ${s.seconds}s`); reload(); }
    catch (e) { say(e.message); } finally { setBusy(false); }
  };

  if (loading && !d) return <><Header /><Loading rows={6} /></>;
  if (error) return <><Header /><ErrorBox error={error} retry={reload} /></>;
  if (!d.orders) return <><Header /><Empty title="No orders reconciled yet" hint="Upload your order, settlement, COD and freight files to begin."><Link className="btn primary" to="/upload">Upload files</Link></Empty></>;

  const maxCell = Math.max(1, ...d.partners.flatMap((p) => d.buckets.map((b) => p[b])));
  const maxType = Math.max(1, ...d.by_type.map((t) => t.amount));
  const pct = (v) => (v == null ? "—" : `${(v * 100).toFixed(1)}%`);

  return (
    <>
      <Header action={isExec(user) && <button className="btn" onClick={rerun} disabled={busy}>{busy ? "Reconciling…" : "Re-run reconciliation"}</button>}
              sub={d.last_run ? `As of ${date(d.last_run.as_of)} · ${d.orders.toLocaleString("en-IN")} orders in ${d.last_run.seconds}s` : null} />
      <div className="hero">
        <div className="big" aria-label={`Money at risk ${money(d.at_risk)}`}>{lakh(d.at_risk)}</div>
        <div className="sub">at risk across {d.open_claims.toLocaleString("en-IN")} open claims · {money(d.at_risk)}</div>
      </div>
      <div className="stats">
        <div className="stat"><div className="v">{pct(d.settled_pct)}</div><div className="l">orders settled correctly</div></div>
        <div className="stat"><div className="v">{pct(d.line_match_rate)}</div><div className="l">payment lines matched to an order</div></div>
        <div className="stat"><div className="v">{(d.order_statuses.unpaid_past_due || 0).toLocaleString("en-IN")}</div><div className="l">orders unpaid past due</div></div>
        <div className="stat"><div className="v">{(d.order_statuses.pending || 0).toLocaleString("en-IN")}</div><div className="l">not yet due (not counted as risk)</div></div>
      </div>

      <div className="section">
        <h2>By partner and age</h2>
        {d.partners.length === 0 ? <Empty title="Nothing at risk" hint="All open claims are resolved." /> : (
          <div className="table-wrap"><table>
            <thead><tr><th>Partner</th>{d.buckets.map((b) => <th key={b} className="num">{b} days</th>)}<th className="num">Total</th></tr></thead>
            <tbody>{d.partners.map((p) => (
              <tr key={p.partner} className="click" tabIndex={0} onClick={() => nav(`/claims?partner=${encodeURIComponent(p.partner)}`)}
                  onKeyDown={(e) => e.key === "Enter" && nav(`/claims?partner=${encodeURIComponent(p.partner)}`)}>
                <td>{p.partner}</td>
                {d.buckets.map((b) => <td key={b} className="num heat" style={{ "--a": (p[b] / maxCell) * 0.28 }}><span>{p[b] ? money(p[b]) : "–"}</span></td>)}
                <td className="num"><strong>{money(p.total)}</strong></td>
              </tr>))}</tbody>
          </table></div>)}
        <p className="muted" style={{ marginTop: 8, fontSize: 13 }}>Age counts days past the date payment was due. Select a partner to see its claims.</p>
      </div>

      <div className="section">
        <h2>By type of leakage</h2>
        {d.by_type.map((t) => (
          <Link key={t.type} className="bar-row" to={`/claims?type=${t.type}`}>
            <span className="bar-label">{CLAIM_TYPE[t.type]} <span className="muted">· {t.count.toLocaleString("en-IN")}</span></span>
            <span className="bar"><i style={{ width: `${(t.amount / maxType) * 100}%` }} /></span>
            <span className="num">{money(t.amount)}</span>
          </Link>))}
      </div>

      <div className="section">
        <h2>GST TCS and income-tax TDS deducted</h2>
        <div className="note" style={{ marginBottom: 12 }}>Statutory deductions are shown here, not as leakage. They are excluded from every shortfall and claim.</div>
        <div className="table-wrap"><table>
          <thead><tr><th>Channel</th><th className="num">TCS</th><th className="num">TDS</th></tr></thead>
          <tbody>{d.statutory.filter((s) => s.tcs || s.tds).map((s) => (
            <tr key={s.partner}><td>{s.partner}</td><td className="num">{money(s.tcs)}</td><td className="num">{money(s.tds)}</td></tr>))}</tbody>
        </table></div>
      </div>
      {toast}
    </>
  );
}

function Header({ action, sub }) {
  return <div className="head"><div><h1>Money at risk</h1><p>{sub || "What partners owe you, by age."}</p></div>{action}</div>;
}
