import { createContext, useContext, useState } from "react";
import { Navigate, NavLink, Route, Routes, useLocation } from "react-router-dom";
import { api, session } from "./api";
import Login from "./pages/Login.jsx";
import Overview from "./pages/Overview.jsx";
import Orders from "./pages/Orders.jsx";
import OrderDetail from "./pages/OrderDetail.jsx";
import Claims from "./pages/Claims.jsx";
import Upload from "./pages/Upload.jsx";
import RateCards from "./pages/RateCards.jsx";

const Auth = createContext(null);
export const useAuth = () => useContext(Auth);
export const isExec = (u) => u?.role === "finance_exec";

const NAV = [["/", "Overview"], ["/orders", "Orders"], ["/claims", "Claims"], ["/upload", "Upload"], ["/rates", "Rate cards"]];

function Shell({ children }) {
  const { user, logout } = useAuth();
  const role = user.role === "cofounder" ? "Co-founder" : "Finance executive";
  return (
    <div className="shell">
      <nav className="nav" aria-label="Main">
        <div className="brand">Recon<span>.</span>Desk</div>
        {NAV.map(([to, label]) => <NavLink key={to} to={to} end={to === "/"}>{label}</NavLink>)}
        <div className="who"><div>{user.name}</div><div className="muted">{role}</div>
          <button className="btn link" onClick={logout} style={{ marginTop: 6 }}>Sign out</button></div>
      </nav>
      <main className="main">
        <div className="topbar"><strong>Recon<span style={{ color: "var(--risk)" }}>.</span>Desk</strong>
          <button className="btn link" onClick={logout}>Sign out</button></div>
        {children}
      </main>
      <nav className="tabbar" aria-label="Main">
        {NAV.map(([to, label]) => <NavLink key={to} to={to} end={to === "/"}>{label}</NavLink>)}
      </nav>
    </div>
  );
}

export default function App() {
  const [user, setUser] = useState(() => session.get()?.user || null);
  const loc = useLocation();
  const logout = () => { session.clear(); setUser(null); };
  const login = async (email, password) => {
    const r = await api.login(email, password);
    session.set(r); setUser(r.user);
  };
  if (!user) {
    return loc.pathname === "/login" ? <Login onLogin={login} /> : <Navigate to="/login" replace />;
  }
  return (
    <Auth.Provider value={{ user, logout }}>
      <Shell>
        <Routes>
          <Route path="/" element={<Overview />} />
          <Route path="/orders" element={<Orders />} />
          <Route path="/orders/:id" element={<OrderDetail />} />
          <Route path="/claims" element={<Claims />} />
          <Route path="/upload" element={<Upload />} />
          <Route path="/rates" element={<RateCards />} />
          <Route path="/login" element={<Navigate to="/" replace />} />
          <Route path="*" element={<div className="state"><strong>Page not found</strong>Use the menu to get back.</div>} />
        </Routes>
      </Shell>
    </Auth.Provider>
  );
}
