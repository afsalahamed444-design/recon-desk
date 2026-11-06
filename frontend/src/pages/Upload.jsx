import { useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api";
import { isExec, useAuth } from "../App.jsx";
import { Empty, ErrorBox, Loading, SOURCE_LABEL, date, useLoad, useToast } from "../lib.jsx";

const ORIGIN_TEXT = {
  ai: "Suggested by AI from the column names and a few sample values. Check it before approving.",
  fuzzy: "AI was unavailable or unsure, so these were matched from column names. Check it before approving.",
  saved: "Your saved mapping still fits this file.",
  manual: "Mapped by hand.",
};

export default function Upload() {
  const { user } = useAuth();
  const [step, setStep] = useState("choose");
  const [source, setSource] = useState("orders");
  const [up, setUp] = useState(null);       // uploaded file
  const [sug, setSug] = useState(null);     // suggestion payload
  const [mapping, setMapping] = useState({});
  const [origin, setOrigin] = useState("manual");
  const [preview, setPreview] = useState(null);
  const [errors, setErrors] = useState([]);
  const [err, setErr] = useState(null);
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState(null);
  const [toast, say] = useToast();
  const sources = useLoad(api.sources);
  const history = useLoad(api.uploads, [step]);
  const fileRef = useRef();
  const [over, setOver] = useState(false);

  const reset = () => { setStep("choose"); setUp(null); setSug(null); setResult(null); setErr(null); };

  const pick = async (file) => {
    if (!file) return;
    setBusy(true); setErr(null);
    try {
      const u = await api.uploadFile(source, file);
      const s = await api.suggest(u.id);
      setUp(u); setSug(s); setMapping(s.mapping); setOrigin(s.origin); setPreview(s.preview); setErrors([]); setStep("map");
    } catch (e) { setErr(e); } finally { setBusy(false); }
  };

  // live 20-row preview whenever the mapping is edited
  const first = useRef(true);
  useEffect(() => {
    if (step !== "map") { first.current = true; return; }
    if (first.current) { first.current = false; return; }
    const t = setTimeout(async () => {
      try { const r = await api.preview(up.id, mapping); setErrors(r.errors); setPreview(r.preview); } catch (e) { setErr(e); }
    }, 250);
    return () => clearTimeout(t);
  }, [mapping]); // eslint-disable-line

  const approve = async () => {
    setBusy(true); setErr(null);
    try {
      const v = await api.saveMapping(up.id, mapping, origin);
      await api.process(up.id, v.id);
      setStep("process");
    } catch (e) { setErr(e); setBusy(false); return; }
    setBusy(false);
  };

  // poll processing
  useEffect(() => {
    if (step !== "process") return;
    const t = setInterval(async () => {
      try { const u = await api.upload(up.id); if (u.status === "done" || u.status === "failed") { clearInterval(t); setResult(u); } } catch (e) { clearInterval(t); setErr(e); }
    }, 900);
    return () => clearInterval(t);
  }, [step, up]);

  const reconcile = async () => {
    setBusy(true);
    try { const s = await api.reconcile(); say(`Reconciled ${s.orders.toLocaleString("en-IN")} orders in ${s.seconds}s`); } catch (e) { setErr(e); } finally { setBusy(false); }
  };

  const labels = { choose: 1, map: 2, process: 3 };
  const canWrite = isExec(user);

  return (
    <>
      <div className="head"><div><h1>Upload</h1><p>Add a partner report. Column names can change; you approve how they map.</p></div></div>
      <div className="steps" aria-label="Progress">
        {["Choose file", "Check columns", "Load"].map((s, i) => <span key={s} className={`step ${labels[step] === i + 1 ? "on" : labels[step] > i + 1 ? "done" : ""}`}>{i + 1}. {s}</span>)}
      </div>
      {err && <div style={{ marginBottom: 16 }}><ErrorBox error={err} /></div>}

      {step === "choose" && (
        <>
          {!canWrite ? <div className="note">Uploading is limited to finance executives. You can review past uploads below.</div> : (
            <>
              <div className="field" style={{ marginBottom: 14 }}><label>What kind of file is it?</label>
                <div className="seg" role="radiogroup">{Object.entries(SOURCE_LABEL).map(([k, l]) => (
                  <button key={k} role="radio" aria-checked={source === k} className={source === k ? "on" : ""} onClick={() => setSource(k)}>{l}</button>))}</div></div>
              <div className={`drop ${over ? "over" : ""}`} tabIndex={0} role="button" onClick={() => fileRef.current.click()}
                   onKeyDown={(e) => (e.key === "Enter" || e.key === " ") && fileRef.current.click()}
                   onDragOver={(e) => { e.preventDefault(); setOver(true); }} onDragLeave={() => setOver(false)}
                   onDrop={(e) => { e.preventDefault(); setOver(false); pick(e.dataTransfer.files[0]); }}>
                {busy ? "Reading file and suggesting columns…" : <><strong style={{ color: "var(--ink)" }}>Drop a CSV or Excel file</strong><br />or click to browse · up to 50 MB</>}
                <input ref={fileRef} type="file" accept=".csv,.xlsx,.xls" hidden onChange={(e) => { pick(e.target.files[0]); e.target.value = ""; }} />
              </div>
              <p className="muted" style={{ marginTop: 8, fontSize: 13 }}>Sample files to try are in the repository's <code>sample_data/</code> folder, including a settlement file in a changed format.</p>
            </>)}
          <div className="section"><h2>Recent uploads</h2>
            {history.error ? <ErrorBox error={history.error} retry={history.reload} /> : history.loading && !history.data ? <Loading rows={3} /> :
              history.data.length === 0 ? <Empty title="Nothing uploaded yet" hint="Your uploads will be listed here." /> : (
                <div className="table-wrap"><table>
                  <thead><tr><th>File</th><th>Type</th><th className="num">Rows</th><th className="num">Loaded</th><th className="num">Rejected</th><th className="num">Duplicates</th><th>Status</th><th>When</th></tr></thead>
                  <tbody>{history.data.map((u) => (
                    <tr key={u.id}><td>{u.filename}</td><td>{SOURCE_LABEL[u.source]}</td><td className="num">{u.rows_total.toLocaleString("en-IN")}</td>
                      <td className="num">{u.rows_loaded.toLocaleString("en-IN")}</td><td className="num">{u.rows_rejected}</td><td className="num">{u.rows_duplicate}</td>
                      <td><span className={`chip ${u.status === "done" ? "good" : u.status === "failed" ? "bad" : ""}`}>{u.status}</span></td><td className="muted">{date(u.created_at)}</td></tr>))}</tbody>
                </table></div>)}
          </div>
        </>)}

      {step === "map" && sug && (
        <>
          <div className={`note ${origin === "saved" ? "" : ""}`} style={{ marginBottom: 16 }}>
            <strong style={{ color: "var(--ink)" }}>{SOURCE_LABEL[up.source]} · {up.rows_total.toLocaleString("en-IN")} rows.</strong> {ORIGIN_TEXT[origin]}
            {sug.missing_required.length > 0 && <> Required fields still to map: <strong>{sug.missing_required.join(", ")}</strong>.</>}
          </div>
          <div className="grid2">
            <div>
              <h2>Map columns</h2>
              {(sources.data?.[up.source] || []).map((f) => {
                const conf = sug.confidence[f.field];
                const check = sug.needs_check.includes(f.field) && mapping[f.field] === sug.mapping[f.field];
                return (
                  <div className="map-row" key={f.field}>
                    <label htmlFor={`m-${f.field}`}>{f.field.replace(/_/g, " ")}{f.required && <span className="risk"> *</span>}</label>
                    <select id={`m-${f.field}`} value={mapping[f.field] || ""} onChange={(e) => setMapping({ ...mapping, [f.field]: e.target.value || null })}>
                      <option value="">{f.required ? "Choose a column…" : "Not mapped"}</option>{up.headers.map((h) => <option key={h}>{h}</option>)}</select>
                    <span>{mapping[f.field] !== sug.mapping[f.field] ? <span className="badge">Changed by you</span>
                      : check ? <span className="badge warn">Needs your check{conf ? ` · ${Math.round(conf * 100)}%` : ""}</span>
                      : conf ? <span className="badge">{origin === "saved" ? "Saved" : `${Math.round(conf * 100)}% sure`}</span> : null}</span>
                  </div>);
              })}
            </div>
            <VersionList source={up.source} onRolled={() => say("Rolled back. Re-open the file to use that mapping.")} />
          </div>
          <div className="section">
            <h2>Preview — first 20 rows as they will be loaded</h2>
            {errors.length > 0 ? <ErrorBox error={{ message: errors.join(" · ") }} /> : !preview ? <Loading rows={3} /> : (
              <>
                <div className="table-wrap" style={{ maxHeight: 360 }}><table>
                  <thead><tr>{preview.columns.map((c) => <th key={c}>{c.replace(/_/g, " ")}</th>)}</tr></thead>
                  <tbody>{preview.rows.map((r, i) => <tr key={i}>{preview.columns.map((c) => <td key={c} className={typeof r[c] === "number" ? "num" : ""}>{r[c] ?? <span className="muted">—</span>}</td>)}</tr>)}</tbody>
                </table></div>
                {preview.rejected > 0 && <p className="risk" style={{ marginTop: 8, fontSize: 13 }}>{preview.rejected} of these rows would be rejected: {Object.entries(preview.reject_reasons).map(([k, v]) => `${v} × ${k}`).join(", ")}.</p>}
                <p className="muted" style={{ marginTop: 8, fontSize: 13 }}>Customer names and phone numbers are masked in previews.</p>
              </>)}
          </div>
          <div style={{ display: "flex", gap: 10, marginTop: 24 }}>
            <button className="btn primary" disabled={busy || errors.length > 0 || sug.missing_required.some((f) => !mapping[f])} onClick={approve}>{busy ? "Saving…" : "Approve mapping and load file"}</button>
            <button className="btn" onClick={reset}>Cancel</button>
          </div>
        </>)}

      {step === "process" && (
        <div className="card" style={{ maxWidth: 560 }}>
          {!result ? (<><h2>Loading {up.rows_total.toLocaleString("en-IN")} rows</h2><div className="progress" role="progressbar" aria-label="Loading"><i /></div></>) :
            result.status === "failed" ? (<><ErrorBox error={{ message: `The file could not be loaded. ${result.error}` }} /><button className="btn" style={{ marginTop: 14 }} onClick={reset}>Start over</button></>) : (
              <>
                <h2>Loaded</h2>
                <dl className="kv">
                  <dt>Rows read</dt><dd>{result.rows_total.toLocaleString("en-IN")}</dd>
                  <dt>Loaded</dt><dd>{result.rows_loaded.toLocaleString("en-IN")}</dd>
                  <dt>Rejected</dt><dd>{result.rows_rejected}{result.rows_rejected > 0 && <span className="muted"> — {Object.entries(result.notes?.reject_reasons || {}).map(([k, v]) => `${v} × ${k}`).join(", ")}</span>}</dd>
                  <dt>Exact duplicates</dt><dd>{result.rows_duplicate} skipped</dd>
                  <dt>Time</dt><dd>{result.seconds}s</dd>
                </dl>
                <div style={{ display: "flex", gap: 10, marginTop: 18, flexWrap: "wrap" }}>
                  <button className="btn primary" onClick={reconcile} disabled={busy}>{busy ? "Reconciling…" : "Re-run reconciliation"}</button>
                  <Link className="btn" to="/">See money at risk</Link>
                  <button className="btn" onClick={reset}>Upload another</button>
                </div>
              </>)}
        </div>)}
      {toast}
    </>
  );
}

function VersionList({ source, onRolled }) {
  const { user } = useAuth();
  const { data, error, loading, reload } = useLoad(() => api.mappings(source), [source]);
  const [busy, setBusy] = useState(null);
  const roll = async (id) => { setBusy(id); try { await api.activateMapping(id); onRolled(); reload(); } finally { setBusy(null); } };
  return (
    <div>
      <h2>Saved versions</h2>
      {error ? <ErrorBox error={error} retry={reload} /> : loading && !data ? <Loading rows={3} /> : data.length === 0 ? <p className="muted">No saved mapping yet. Approving this one creates version 1.</p> : (
        <div>{data.slice(0, 6).map((v) => (
          <div key={v.id} style={{ display: "flex", justifyContent: "space-between", alignItems: "center", padding: "8px 0", borderBottom: "1px solid var(--line)" }}>
            <span>v{v.version} {v.active && <span className="chip good">active</span>}<br /><span className="muted" style={{ fontSize: 12.5 }}>{date(v.created_at)} · {v.created_by}</span></span>
            {!v.active && isExec(user) && <button className="btn small" disabled={busy === v.id} onClick={() => roll(v.id)}>Roll back to this</button>}
          </div>))}</div>)}
    </div>
  );
}
