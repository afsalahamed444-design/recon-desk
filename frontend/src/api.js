const KEY = "recon.session";

export const session = {
  get() { try { return JSON.parse(localStorage.getItem(KEY)); } catch { return null; } },
  set(v) { localStorage.setItem(KEY, JSON.stringify(v)); },
  clear() { localStorage.removeItem(KEY); },
};

async function request(path, { method = "GET", body, form } = {}) {
  const s = session.get();
  const headers = {};
  if (s?.token) headers.Authorization = `Bearer ${s.token}`;
  if (body) headers["Content-Type"] = "application/json";
  let res;
  try {
    res = await fetch(`/api${path}`, { method, headers, body: form || (body ? JSON.stringify(body) : undefined) });
  } catch {
    throw new Error("Can't reach the server. Check your connection and try again.");
  }
  if (res.status === 401 && s) { session.clear(); window.location.assign("/login"); }
  if (!res.ok) {
    let msg = `Something went wrong (${res.status})`;
    try {
      const d = await res.json();
      msg = typeof d.detail === "string" ? d.detail : Array.isArray(d.detail) ? d.detail.map((x) => x.msg).join("; ") : msg;
    } catch { /* keep default */ }
    throw new Error(msg);
  }
  return res;
}

const json = async (path, opts) => (await request(path, opts)).json();

export const api = {
  login: (email, password) => json("/auth/login", { method: "POST", body: { email, password } }),
  dashboard: () => json("/dashboard"),
  latestRun: () => json("/reconcile/latest"),
  reconcile: () => json("/reconcile", { method: "POST" }),
  orders: (params) => json(`/orders?${new URLSearchParams(params)}`),
  order: (id, unmask = false) => json(`/orders/${encodeURIComponent(id)}${unmask ? "?unmask=true" : ""}`),
  claims: (params) => json(`/claims?${new URLSearchParams(params)}`),
  setClaim: (id, status) => json(`/claims/${id}`, { method: "PATCH", body: { status } }),
  exportClaims: async (params) => {
    const res = await request(`/claims/export?${new URLSearchParams(params)}`);
    const blob = await res.blob();
    const name = /filename="(.+)"/.exec(res.headers.get("Content-Disposition") || "")?.[1] || "claims.csv";
    const a = Object.assign(document.createElement("a"), { href: URL.createObjectURL(blob), download: name });
    document.body.appendChild(a); a.click(); a.remove();
  },
  sources: () => json("/sources"),
  uploads: () => json("/uploads"),
  upload: (id) => json(`/uploads/${id}`),
  uploadFile: (source, file) => { const f = new FormData(); f.append("source", source); f.append("file", file); return json("/uploads", { method: "POST", form: f }); },
  suggest: (id) => json(`/uploads/${id}/suggest`, { method: "POST" }),
  preview: (id, mapping) => json(`/uploads/${id}/preview`, { method: "POST", body: { mapping } }),
  saveMapping: (upload_id, mapping, origin) => json("/mappings", { method: "POST", body: { upload_id, mapping, origin } }),
  mappings: (source) => json(`/mappings?source=${source}`),
  activateMapping: (id) => json(`/mappings/${id}/activate`, { method: "POST" }),
  process: (id, mapping_version_id) => json(`/uploads/${id}/process`, { method: "POST", body: { mapping_version_id } }),
  rateCards: () => json("/rate-cards"),
  saveRateCard: (pid, body) => json(`/rate-cards/${pid}`, { method: "PUT", body }),
};
