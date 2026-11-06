import { useCallback, useEffect, useRef, useState } from "react";

const inr = new Intl.NumberFormat("en-IN", { maximumFractionDigits: 0 });
const inr2 = new Intl.NumberFormat("en-IN", { minimumFractionDigits: 2, maximumFractionDigits: 2 });

export function money(v, { paise = false, sign = false } = {}) {
  if (v === null || v === undefined || Number.isNaN(v)) return "—";
  const n = Number(v);
  const s = (paise ? inr2 : inr).format(Math.abs(n));
  return `${n < 0 ? "−" : sign && n > 0 ? "+" : ""}₹${s}`;
}
export function lakh(v) {
  const n = Number(v || 0);
  if (Math.abs(n) >= 1e7) return `₹${(n / 1e7).toFixed(2)} crore`;
  if (Math.abs(n) >= 1e5) return `₹${(n / 1e5).toFixed(2)} lakh`;
  return money(n);
}
export function date(d) {
  if (!d) return "—";
  return new Date(d).toLocaleDateString("en-IN", { day: "2-digit", month: "short", year: "numeric" });
}

export const STATUS = {
  settled: ["Settled", "good"], pending: ["Not yet due", ""], short_paid: ["Short-paid", "bad"],
  unpaid_past_due: ["Unpaid past due", "bad"], freight_overcharged: ["Freight overcharged", "bad"],
  return_not_received: ["Return not received", "bad"], overpaid: ["Overpaid", ""], unrated: ["No rate card", ""],
};
export const CLAIM_TYPE = {
  unpaid_past_due: "Unpaid past due", short_paid: "Short-paid", freight_overcharged: "Freight overcharged",
  return_not_received: "Return not received",
};
export const SOURCE_LABEL = { orders: "Orders", settlement: "Settlement report", cod: "COD remittance", freight: "Freight invoice" };

export const Chip = ({ status }) => {
  const [label, tone] = STATUS[status] || [status, ""];
  return <span className={`chip ${tone}`}>{label}</span>;
};

export const Loading = ({ rows = 5 }) => (
  <div aria-busy="true" aria-label="Loading" style={{ display: "grid", gap: 12 }}>
    {Array.from({ length: rows }, (_, i) => <div key={i} className="skel" style={{ width: `${95 - i * 7}%` }} />)}
  </div>
);
export const Empty = ({ title, hint, children }) => (
  <div className="state"><strong>{title}</strong>{hint}{children && <div style={{ marginTop: 14 }}>{children}</div>}</div>
);
export const ErrorBox = ({ error, retry }) => (
  <div className="error" role="alert"><span>{error?.message || String(error)}</span>{retry && <button className="btn small" onClick={retry}>Try again</button>}</div>
);

/** Fetch helper with loading / error / reload. */
export function useLoad(fn, deps = []) {
  const [state, set] = useState({ data: null, error: null, loading: true });
  const seq = useRef(0);
  const load = useCallback(() => {
    const id = ++seq.current;
    set((s) => ({ ...s, loading: true, error: null }));
    fn().then((data) => id === seq.current && set({ data, error: null, loading: false }))
        .catch((error) => id === seq.current && set({ data: null, error, loading: false }));
  }, deps); // eslint-disable-line
  useEffect(load, [load]);
  return { ...state, reload: load };
}

export function useToast() {
  const [msg, setMsg] = useState("");
  useEffect(() => { if (msg) { const t = setTimeout(() => setMsg(""), 2600); return () => clearTimeout(t); } }, [msg]);
  return [msg ? <div className="toast" role="status">{msg}</div> : null, setMsg];
}

export function Pager({ page, total, size, onPage }) {
  const pages = Math.max(1, Math.ceil(total / size));
  return (
    <div className="pager">
      <span>{total.toLocaleString("en-IN")} results</span>
      <span style={{ display: "flex", gap: 8, alignItems: "center" }}>
        <button className="btn small" disabled={page <= 1} onClick={() => onPage(page - 1)}>Previous</button>
        <span>Page {page} of {pages}</span>
        <button className="btn small" disabled={page >= pages} onClick={() => onPage(page + 1)}>Next</button>
      </span>
    </div>
  );
}

export function evidenceLines(e) {
  const o = e.order, x = e.expected, r = e.received, f = e.freight, s = e.statutory_not_leakage;
  const out = [e.rule,
    `Order value ${money(o.value)} · delivered ${date(o.delivery_date)} · payment due ${date(o.due_date)}.`,
    `Expected ${money(x.total)}: commission ${money(x.commission)}, prepaid fee ${money(x.prepaid_fee)}, COD fee ${money(x.cod_fee)}, fixed fee ${money(x.fixed_fee)}, return fee ${money(x.return_fee)}.`,
    `Received ${money(r.total)} across ${r.payment_lines} line(s).`];
  if (f.billed != null) out.push(`Freight billed ${money(f.billed)} against rate card ${money(f.rate_card)} (declared ${f.declared_weight_kg ?? "—"} kg, billed ${f.billed_weight_kg ?? "—"} kg).`);
  if (s.tcs || s.tds) out.push(`TCS ${money(s.tcs, { paise: true })} and TDS ${money(s.tds, { paise: true })} were deducted at source and are not part of this claim.`);
  return out;
}
