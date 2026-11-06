import { useState } from "react";
import { api } from "../api";
import { isExec, useAuth } from "../App.jsx";
import { ErrorBox, Loading, date, useLoad, useToast } from "../lib.jsx";

const PCT = [["commission_pct", "Commission %"], ["prepaid_fee_pct", "Prepaid gateway fee %"], ["cod_fee_pct", "COD fee %"], ["return_fee_pct", "Return fee %"]];

export default function RateCards() {
  const { user } = useAuth();
  const { data, error, loading, reload } = useLoad(api.rateCards);
  const [edit, setEdit] = useState(null);
  const [toast, say] = useToast();
  if (error) return <ErrorBox error={error} retry={reload} />;
  if (loading && !data) return <><Head /><Loading rows={6} /></>;
  const channels = data.filter((p) => p.type === "channel"), couriers = data.filter((p) => p.type === "courier");

  return (
    <>
      <Head />
      <div className="note" style={{ marginBottom: 20 }}>Expected amount = order value − commission − gateway or COD fee − fixed fee. Returns expect only the return fee, as a deduction. Saving creates a new version; re-run reconciliation to apply it.</div>
      <h2>Channels</h2>
      <div className="table-wrap" style={{ marginBottom: 28 }}><table>
        <thead><tr><th>Partner</th>{PCT.map(([, l]) => <th key={l} className="num">{l}</th>)}<th className="num">Fixed ₹</th><th className="num">Pays in</th><th>Since</th><th /></tr></thead>
        <tbody>{channels.map((p) => (
          <tr key={p.partner_id}><td>{p.name}</td>{PCT.map(([k]) => <td key={k} className="num">{p[k]}</td>)}
            <td className="num">{p.fixed_fee}</td><td className="num">{p.remit_days} d</td><td className="muted">{date(p.effective_from)}</td>
            <td>{isExec(user) && <button className="btn small" onClick={() => setEdit(p)}>Edit</button>}</td></tr>))}</tbody>
      </table></div>
      <h2>Couriers — freight by weight slab</h2>
      <div className="table-wrap"><table>
        <thead><tr><th>Courier</th><th>Slabs (up to kg → ₹)</th><th>Since</th><th /></tr></thead>
        <tbody>{couriers.map((p) => (
          <tr key={p.partner_id}><td>{p.name}</td>
            <td>{(p.weight_slabs || []).map((s) => `${s.upto_kg >= 999 ? "above" : "≤" + s.upto_kg} → ₹${s.rate}`).join("   ·   ")}</td>
            <td className="muted">{date(p.effective_from)}</td>
            <td>{isExec(user) && <button className="btn small" onClick={() => setEdit(p)}>Edit</button>}</td></tr>))}</tbody>
      </table></div>
      {edit && <Editor p={edit} onClose={() => setEdit(null)} onSaved={(m) => { setEdit(null); say(m); reload(); }} />}
      {toast}
    </>
  );
}
const Head = () => <div className="head"><div><h1>Rate cards</h1><p>What each partner should charge. This drives every expected amount.</p></div></div>;

function Editor({ p, onClose, onSaved }) {
  const [v, setV] = useState({ ...p, weight_slabs: p.weight_slabs || [] });
  const [err, setErr] = useState(null);
  const [busy, setBusy] = useState(false);
  const num = (k) => (e) => setV({ ...v, [k]: e.target.value === "" ? "" : Number(e.target.value) });
  const slab = (i, k) => (e) => setV({ ...v, weight_slabs: v.weight_slabs.map((s, j) => (j === i ? { ...s, [k]: Number(e.target.value) } : s)) });
  const save = async () => {
    setBusy(true); setErr(null);
    try {
      const body = p.type === "courier" ? { remit_days: v.remit_days, weight_slabs: v.weight_slabs }
        : { ...Object.fromEntries([...PCT.map(([k]) => k), "fixed_fee", "remit_days"].map((k) => [k, Number(v[k])])), cod_by_courier: !!v.cod_by_courier };
      const r = await api.saveRateCard(p.partner_id, body); onSaved(r.note);
    } catch (e) { setErr(e); } finally { setBusy(false); }
  };
  return (
    <div className="card" style={{ marginTop: 24 }} role="form" aria-label={`Edit ${p.name}`}>
      <h2>Edit {p.name}</h2>
      {p.type === "channel" ? (
        <div className="filters">{[...PCT, ["fixed_fee", "Fixed fee ₹"], ["remit_days", "Remittance days"]].map(([k, l]) => (
          <div className="field" key={k}><label htmlFor={k}>{l}</label><input id={k} type="number" min="0" step="0.1" value={v[k]} onChange={num(k)} /></div>))}
          <label style={{ display: "flex", gap: 8, alignItems: "center", minHeight: 38 }}><input type="checkbox" style={{ width: "auto", minHeight: 0 }} checked={!!v.cod_by_courier} onChange={(e) => setV({ ...v, cod_by_courier: e.target.checked })} /> COD collected by courier</label></div>
      ) : v.weight_slabs.map((s, i) => (
        <div className="filters" key={i} style={{ marginBottom: 8 }}>
          <div className="field"><label htmlFor={`u${i}`}>Up to kg</label><input id={`u${i}`} type="number" min="0.1" step="0.1" value={s.upto_kg} onChange={slab(i, "upto_kg")} /></div>
          <div className="field"><label htmlFor={`r${i}`}>Rate ₹</label><input id={`r${i}`} type="number" min="0" value={s.rate} onChange={slab(i, "rate")} /></div></div>))}
      {err && <ErrorBox error={err} />}
      <div style={{ display: "flex", gap: 10, marginTop: 14 }}><button className="btn primary" onClick={save} disabled={busy}>{busy ? "Saving…" : "Save new version"}</button><button className="btn" onClick={onClose}>Cancel</button></div>
    </div>
  );
}
