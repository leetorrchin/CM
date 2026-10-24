import { api, getToken, setToken } from "./api";

const $ = <T extends HTMLElement>(id: string) => document.getElementById(id) as T;
const next = (() => {
  const n = new URLSearchParams(location.search).get("next") ?? "/";
  return n.startsWith("/") && !n.startsWith("//") && !n.startsWith("/login.html") ? n : "/";
})();

function say(t: string | null): void { const m = $("msg"); m.hidden = !t; m.textContent = t ?? ""; }

async function boot(): Promise<void> {
  try {
    const h = await api<{ auth: boolean }>("/api/health");
    if (!h.auth) { location.replace(next); return; }
    if (getToken()) {
      try { await api("/api/me"); location.replace(next); return; } catch { /* token expired, stay here */ }
    }
  } catch (e) { say(`Could not reach the server: ${(e as Error).message}`); }
}

$("f").addEventListener("submit", async (e) => {
  e.preventDefault();
  say(null);
  try {
    const r = await api<{ token: string }>("/api/login", { username: ($("u") as HTMLInputElement).value, password: ($("p") as HTMLInputElement).value });
    setToken(r.token);
    location.replace(next);
  } catch (err) { say((err as Error).message); }
});
void boot();
