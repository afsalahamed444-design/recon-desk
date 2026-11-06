import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { ErrorBox } from "../lib.jsx";

export default function Login({ onLogin }) {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState(null);
  const [busy, setBusy] = useState(false);
  const nav = useNavigate();
  const submit = async (e) => {
    e.preventDefault(); setBusy(true); setError(null);
    try { await onLogin(email.trim().toLowerCase(), password); nav("/"); }
    catch (err) { setError(err); } finally { setBusy(false); }
  };
  return (
    <div className="login"><div className="box">
      <div className="brand" style={{ padding: 0, marginBottom: 28 }}>Recon<span>.</span>Desk</div>
      <h1>Sign in</h1>
      <p className="muted">See where every rupee of an order went.</p>
      <form onSubmit={submit}>
        <div className="field"><label htmlFor="e">Email</label>
          <input id="e" type="email" autoComplete="username" required value={email} onChange={(e) => setEmail(e.target.value)} /></div>
        <div className="field"><label htmlFor="p">Password</label>
          <input id="p" type="password" autoComplete="current-password" required value={password} onChange={(e) => setPassword(e.target.value)} /></div>
        {error && <ErrorBox error={error} />}
        <button className="btn primary" disabled={busy}>{busy ? "Signing in…" : "Sign in"}</button>
      </form>
      <p className="muted" style={{ marginTop: 22, fontSize: 13 }}>Demo accounts:{" "}
        <button className="btn link" onClick={() => setEmail("finance@companya.test")}>finance executive</button>{" · "}
        <button className="btn link" onClick={() => setEmail("cofounder@companya.test")}>co-founder</button>
      </p>
    </div></div>
  );
}
