import { Fragment, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { api } from "../api";
import { isExec, useAuth } from "../App.jsx";
import { CLAIM_TYPE, Empty, ErrorBox, Loading, Pager, evidenceLines, money, useLoad, useToast } from "../lib.jsx";
import { Link } from "react-router-dom";

const SIZE = 50;
const STATUSES = { open: "Open", filed: "Filed", recovered: "Recovered", written_off: "Written off" };

export default function Claims() {
  const { user } = useAuth();
  const [sp, setSp] = useSearchParams();
  const f = { partner: sp.get("partner") || "", type: sp.get("type") || "", status: sp.get("status") || "open", page: Number(sp.get("page") || 1) };
  const set = (patch) => { const n = { ...f, page: 1, ...patch }; setSp(Object.fromEntries(Object.entries(n).filter(([k, v]) => v !== "" && !(k === "page" && v === 1)))); };
  const filt = { ...(f.partner && { partner: f.partner }), ...(f.type && { type: f.type }), status: f.status === "all" ? "" : f.status };
  const clean = Object.fromEntries(Object.entries(filt).filter(([, v]) => v));
  const { data, error, loading, reload } = useLoad(() => api.claims({ ...clean, page: f.page, page_size: SIZE }), [JSON.stringify(clean), f.page]);
  const [open, setOpen] = useState(null);
  const [exporting, setExporting] = useState(false);
  const [toast, say] = useToast();

  const change = async (c, status) => {
    try { await api.setClaim(c.id, status); say(`Claim marked ${STATUSES[status].toLowerCase()}`); reload(); } catch (e) { say(e.message); }
  };
  const exportCsv = async () => {
    setExporting(true);
    try { await api.exportClaims(clean); } catch (e) { say(e.message); } finally { setExporting(false); }
  };

  return (
    <>
      <div className="head"><div><h1>Claims</h1>
        <p>{data ? `${data.total.toLocaleString("en-IN")} claims · ${money(data.amount)}` : "Amounts partners owe us, with evidence."}</p></div>
        <button className="btn primary" onClick={exportCsv} disabled={exporting || !data?.total}>{exporting ? "Preparing…" : "Export evidence (CSV)"}</button></div>
      <div className="filters">
        <div className="field"><label htmlFor="p">Partner</label>
          <select id="p" value={f.partner} onChange={(e) => set({ partner: e.target.value })}>
            <option value="">All partners</option>{(data?.partners || (f.partner ? [f.partner] : [])).map((p) => <option key={p}>{p}</option>)}</select></div>
        <div className="field"><label htmlFor="t">Type</label>
          <select id="t" value={f.type} onChange={(e) => set({ type: e.target.value })}>
            <option value="">All types</option>{Object.entries(CLAIM_TYPE).map(([k, l]) => <option key={k} value={k}>{l}</option>)}</select></div>
        <div className="field"><label htmlFor="s">Status</label>
          <select id="s" value={f.status} onChange={(e) => set({ status: e.target.value })}>
            <option value="all">All</option>{Object.entries(STATUSES).map(([k, l]) => <option key={k} value={k}>{l}</option>)}</select></div>
      </div>
      {error ? <ErrorBox error={error} retry={reload} /> : loading && !data ? <Loading rows={8} /> :
        data.items.length === 0 ? <Empty title="No claims here" hint="Nothing matches these filters." /> : (
          <div style={{ opacity: loading ? 0.6 : 1 }}>
            <div className="table-wrap"><table>
              <thead><tr><th>Partner</th><th>Order</th><th>Type</th><th className="num">Amount</th><th className="num">Age</th><th>Status</th><th><span className="sr">Evidence</span></th></tr></thead>
              <tbody>{data.items.map((c) => (
                <Fragment key={c.id}>
                  <tr>
                    <td>{c.partner}</td><td><Link to={`/orders/${c.order_id}`}>{c.order_id}</Link></td><td>{CLAIM_TYPE[c.type]}</td>
                    <td className="num risk"><strong>{money(c.amount, { paise: true })}</strong></td>
                    <td className="num muted">{c.age_days} d</td>
                    <td>{isExec(user)
                      ? <select aria-label={`Status of claim ${c.id}`} value={c.status} onChange={(e) => change(c, e.target.value)} style={{ minHeight: 32, padding: "3px 8px" }}>
                          {Object.entries(STATUSES).map(([k, l]) => <option key={k} value={k}>{l}</option>)}</select>
                      : STATUSES[c.status]}</td>
                    <td><button className="btn small" aria-expanded={open === c.id} onClick={() => setOpen(open === c.id ? null : c.id)}>{open === c.id ? "Hide" : "Evidence"}</button></td>
                  </tr>
                  {open === c.id && <tr><td colSpan={7} className="evidence">{evidenceLines(c.evidence).map((l, i) => <p key={i}>{l}</p>)}</td></tr>}
                </Fragment>))}</tbody>
            </table></div>
            <Pager page={f.page} total={data.total} size={SIZE} onPage={(p) => set({ page: p })} />
          </div>)}
      {toast}
    </>
  );
}
