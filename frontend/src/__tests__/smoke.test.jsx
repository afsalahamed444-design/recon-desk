// @vitest-environment jsdom
// Integration smoke test: renders the real screens against a running backend (API_URL, default localhost:8000).
import { afterEach, beforeAll, describe, expect, it } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import App from "../App.jsx";

const API = process.env.API_URL || "http://localhost:8000";
const PASSWORD = process.env.DEMO_PASSWORD || "demo-pass-1234";

beforeAll(() => {
  const real = globalThis.fetch;
  globalThis.fetch = (url, opts) => real(String(url).startsWith("/") ? API + url : url, opts);
});
afterEach(() => { cleanup(); localStorage.clear(); });

async function signIn(email) {
  const r = await fetch("/api/auth/login", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ email, password: PASSWORD }) });
  localStorage.setItem("recon.session", JSON.stringify(await r.json()));
}
const open = (path) => render(<MemoryRouter initialEntries={[path]}><App /></MemoryRouter>);

describe("screens", () => {
  it("login shows an error for a wrong password", async () => {
    open("/login");
    fireEvent.change(screen.getByLabelText("Email"), { target: { value: "finance@companya.test" } });
    fireEvent.change(screen.getByLabelText("Password"), { target: { value: "wrong-password" } });
    fireEvent.click(screen.getByRole("button", { name: "Sign in" }));
    expect((await screen.findByRole("alert")).textContent).toMatch(/incorrect/i);
  });

  it("overview shows money at risk, partner table and statutory note", async () => {
    await signIn("finance@companya.test");
    open("/");
    expect(await screen.findByText(/at risk across/)).toBeTruthy();
    expect(screen.getAllByText("Marketplace 1").length).toBeGreaterThan(0);
    expect(screen.getByText(/not as leakage/)).toBeTruthy();
    expect(screen.getByRole("button", { name: /Re-run reconciliation/ })).toBeTruthy();
  });

  it("co-founder sees no write buttons", async () => {
    await signIn("cofounder@companya.test");
    open("/");
    await screen.findByText(/at risk across/);
    expect(screen.queryByRole("button", { name: /Re-run reconciliation/ })).toBeNull();
  });

  it("orders list loads and filters by status", async () => {
    await signIn("finance@companya.test");
    open("/orders?status=unpaid_past_due");
    await waitFor(() => expect(document.querySelectorAll("tbody .chip.bad").length).toBeGreaterThan(5));
  });

  it("order detail for the brief's COD example shows -1,409 and masked customer", async () => {
    await signIn("finance@companya.test");
    open("/orders/ORD-W-204118");
    expect(await screen.findByText("ORD-W-204118")).toBeTruthy();
    await waitFor(() => expect(screen.getAllByText(/−₹1,409/).length).toBeGreaterThan(0));
    expect(screen.queryByText("Asha Nair")).toBeNull();
    expect(screen.getByText(/Only the co-founder can reveal/)).toBeTruthy();
  });

  it("co-founder can reveal customer details", async () => {
    await signIn("cofounder@companya.test");
    open("/orders/ORD-W-204118");
    fireEvent.click(await screen.findByRole("button", { name: /Reveal customer details/ }));
    expect(await screen.findByText("Asha Nair")).toBeTruthy();
  });

  it("claims list renders with export and evidence toggle", async () => {
    await signIn("finance@companya.test");
    open("/claims?partner=Courier%20A");
    expect(await screen.findByRole("button", { name: /Export evidence/ })).toBeTruthy();
    fireEvent.click((await screen.findAllByRole("button", { name: "Evidence" }))[0]);
    expect(await screen.findByText(/Expected/)).toBeTruthy();
  });

  it("rate cards and upload screens render", async () => {
    await signIn("finance@companya.test");
    open("/rates");
    expect(await screen.findByText("Marketplace 2")).toBeTruthy();
    cleanup();
    open("/upload");
    expect(await screen.findByText(/Drop a CSV or Excel file/)).toBeTruthy();
    expect(await screen.findByText("Recent uploads")).toBeTruthy();
  });
});
