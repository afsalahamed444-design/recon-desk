import { useEffect, useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { api } from "../api";
import { Chip, Empty, ErrorBox, Loading, Pager, STATUS, date, money, useLoad } from "../lib.jsx";

const SIZE = 50;

export default function Orders() {
  const [sp, setSp] = useSearchParams();
  const nav = useNavigate();
  const f = { status: sp.get("status") || "", channel: sp.get("channel") || "", q: sp.get("q") || "", sort: sp.get("sort") || "diff_asc", page: Number(sp.get("page") || 1) };
  const [q, setQ] = useState(f.q);
  const set = (patch) => { const n = { ...f, page: 1, ...patch }; setSp(Object.fromEntries(Object.entries(n).filter(([k, v]) => v && !(k === "page" && v === 1) && !(k === "sort" && v === "diff_asc")))); };
  useEffect(() => { const t = setTimeout(() => q !== f.q && set({ q }), 350); return () => clearTimeout(t); }, [q]); // eslint-disable-line
  const params = { page: f.page, page_size: SIZE, sort: f.sort, ...(f.status && { status: f.status }), ...(f.channel && { channel: f.channel }), ...(f.q && { q: f.q }) };
  const { data, error, loading, reload } = useLoad(() => api.orders(params), [JSON.stringify(params)]);

  return (
    <>
      <div className="head"><div><h1>Orders</h1><p>Every order, what we expected and what arrived. Largest shortfalls first.</p></div></div>
      <div className="filters">
        <div className="field"><label htmlFor="q">Order ID</label><input id="q" placeholder="e.g. ORD-W-204118" value={q} onChange={(e) => setQ(e.target.value)} /></div>
        <div className="field"><label htmlFor="s">Status</label>
          <select id="s" value={f.status} onChange={(e) => set({ status: e.target.value })}>
            <option value="">All statuses</option>{Object.entries(STATUS).map(([k, [l]]) => <option key={k} value={k}>{l}</option>)}
          </select></div>
        <div className="field"><label htmlFor="c">Channel</label>
          <select id="c" value={f.channel} onChange={(e) => set({ channel: e.target.value })}>
            <option value="">All channels</option>{(data?.channels || []).map((c) => <option key={c}>{c}</option>)}
          </select></div>
        <div className="field"><label htmlFor="o">Sort</label>
          <select id="o" value={f.sort} onChange={(e) => set({ sort: e.target.value })}>
            <option value="diff_asc">Largest shortfall</option><option value="age_desc">Most overdue</option><option value="value_desc">Highest value</option>
          </select></div>
      </div>
      {error ? <ErrorBox error={error} retry={reload} /> : loading && !data ? <Loading rows={8} /> :
        data.items.length === 0 ? <Empty title="No orders match" hint="Try clearing a filter." /> : (
          <div style={{ opacity: loading ? 0.6 : 1, transition: "opacity .15s" }}>
            <div className="table-wrap"><table>
              <thead><tr><th>Order</th><th>Channel</th><th>Status</th><th className="num">Expected</th><th className="num">Received</th><th className="num">Difference</th><th className="num">Overdue</th></tr></thead>
              <tbody>{data.items.map((o) => (
                <tr key={o.order_id} className="click" tabIndex={0} onClick={() => nav(`/orders/${o.order_id}`)} onKeyDown={(e) => e.key === "Enter" && nav(`/orders/${o.order_id}`)}>
                  <td>{o.order_id}</td><td>{o.channel}</td><td><Chip status={o.status} /></td>
                  <td className="num">{money(o.expected)}</td><td className="num">{money(o.received)}</td>
                  <td className={`num ${o.diff < -10 ? "risk" : ""}`}>{o.diff < -10 ? <strong>{money(o.diff)}</strong> : money(o.diff)}</td>
                  <td className="num muted">{o.age_days ? `${o.age_days} d` : o.due_date ? "" : "—"}</td>
                </tr>))}</tbody>
            </table></div>
            <Pager page={f.page} total={data.total} size={SIZE} onPage={(p) => set({ page: p })} />
          </div>)}
    </>
  );
}
