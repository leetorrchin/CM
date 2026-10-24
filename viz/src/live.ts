import { api, dark, esc, getVenue, logout, mmss, socket, type LiveMsg, type SessionInfo } from "./api";
import { parseEdgeKey, RunView } from "./render";
import type { RunLog, Venue } from "./types";

const $ = <T extends HTMLElement>(id: string) => document.getElementById(id) as T;
const fmt = (n: number) => Math.round(n).toLocaleString();

let venue: Venue | null = null;
let view: RunView | null = null;
let msg: LiveMsg | null = null;
let armed = 0;
let sid = "";
let sessions: SessionInfo[] = [];
let stopSocket: (() => void) | null = null;
const SID_KEY = "crowd.sid";
const keep = <T>(f: () => T): void => { try { f(); } catch { /* storage blocked */ } };
const base = () => `/api/sessions/${encodeURIComponent(sid)}`;
const log: RunLog = { runId: "live", venueId: "", planner: "", scenario: "", states: [], events: [], metrics: null, duration: 0 };

function say(text: string | null): void {
  const el = $("msg");
  el.hidden = !text;
  el.textContent = text ?? "";
}
async function act<T>(p: Promise<T>): Promise<void> {
  try { await p; say(null); } catch (e) { say((e as Error).message); }
}

async function setVenue(id: string): Promise<void> {
  venue = sid ? await api<Venue>(`${base()}/venue`) : await getVenue(id);
  log.venueId = id;
  view = new RunView($("cv") as HTMLCanvasElement, venue, log);
}

function zoneName(id: string): string { return venue?.zones.find((z) => z.id === id)?.name ?? id; }
function gateName(id: string): string { return venue?.thresholds.find((t) => t.id === id)?.name ?? id; }

function renderPanel(): void {
  if (!msg || !venue) return;
  $("clock").textContent = `· ${mmss(msg.t_s)}`;
  document.querySelectorAll<HTMLElement>("#modes button").forEach((b) => b.classList.toggle("on", b.dataset.mode === msg!.mode));
  $("pause").textContent = msg.paused ? "Resume" : "Pause";
  const sp = $("speed") as HTMLSelectElement;
  if (![...sp.options].some((o) => Number(o.value) === msg!.speed)) sp.add(new Option(`${msg.speed}x`, String(msg.speed)));
  sp.value = String(msg.speed);
  $("done").hidden = !(msg.active === 0 && msg.cleared > 0);
  const inZones = Object.values(msg.zones).reduce((a, b) => a + b, 0);
  const transit = Object.values(msg.transit).reduce((a, b) => a + b, 0);
  const queued = Object.values(msg.queues).reduce((a, b) => a + b, 0);
  $("stats").innerHTML = [
    ["People", fmt(msg.people)], ["Out of the venue", fmt(msg.cleared)], ["Still moving", fmt(msg.active)],
    ["Waiting at gates", fmt(queued)], ["Crossing gates", fmt(transit)], ["In zones", fmt(inZones)],
    ["Phones joined", fmt(msg.guests ?? 0)], ["Queue switches", fmt(msg.queue_switches)], ["Redirected", fmt(msg.redirected)], ["Planner", esc(msg.planner)],
  ].map(([k, v]) => `<dt>${k}</dt><dd>${v}</dd>`).join("");
  const top = Object.entries(msg.queues).sort((a, b) => b[1] - a[1]).slice(0, 5);
  $("queues").innerHTML = top.length
    ? top.map(([k, n]) => { const e = parseEdgeKey(k); return `<li>${fmt(n)} <small>${esc(gateName(e.tid))} to ${esc(zoneName(e.to))}</small></li>`; }).join("")
    : "<li><small>none</small></li>";
  const closed = $("closed");
  closed.innerHTML = msg.closed.length
    ? msg.closed.map((id) => `<li>${esc(gateName(id))} <button class="btn alt small" data-reopen="${esc(id)}" type="button">Reopen</button></li>`).join("")
    : "<li class='muted'>none</li>";
}

function frame(ts: number): void {
  if (view && msg) {
    log.states = [msg];
    log.planner = msg.planner;
    log.scenario = msg.scenario;
    view.draw(msg.t_s, { level: "all", labels: true, dark: dark(), wall: ts / 1000 });
  }
  requestAnimationFrame(frame);
}

async function onMsg(m: any): Promise<void> {
  if (m.type === "ended") { await refreshSessions(); return; }
  if (m.type !== "state" || m.id !== sid) return;
  if (!venue || venue.id !== m.venue) await setVenue(m.venue);
  msg = m;
  renderPanel();
}

async function fillSession(): Promise<void> {
  const venues = await api<{ id: string; name: string; source: string }[]>("/api/venues");
  const vs = $("venueSel") as HTMLSelectElement;
  vs.innerHTML = venues.map((v) => `<option value="${esc(v.id)}">${esc(v.name)}${v.source === "user" ? " (yours)" : ""}</option>`).join("");
  const pl = await api<string[]>("/api/planners");
  $("plSel").innerHTML = pl.map((p) => `<option ${p === "adaptive" ? "selected" : ""}>${esc(p)}</option>`).join("");
  const fillScenarios = async () => {
    const sc = await api<string[]>(`/api/scenarios?venue=${encodeURIComponent(vs.value)}`);
    $("scSel").innerHTML = sc.map((s) => `<option>${esc(s)}</option>`).join("");
  };
  vs.onchange = fillScenarios;
  await fillScenarios();
}

function renderSessions(): void {
  $("sessions").innerHTML = sessions.map((s) =>
    `<li><button type="button" data-sid="${esc(s.id)}" class="${s.id === sid ? "on" : ""}"><b>${esc(s.id)}</b> ${esc(s.name)}<br><small class="muted">${fmt(s.people)} people · ${esc(s.mode)}${s.paused ? " · paused" : ""}</small></button></li>`).join("");
  $("noSession").hidden = sessions.length > 0;
  const cur = sessions.find((s) => s.id === sid);
  $("joinBox").hidden = !cur;
  $("del").hidden = !cur;
  if (cur) {
    $("code").textContent = cur.id;
    $("appUrl").textContent = `${location.origin}/app.html?s=${cur.id}`;
    $("guestInfo").textContent = `${cur.guests} phone${cur.guests === 1 ? "" : "s"} joined${cur.demo_people ? " · demo people on" : ""}${cur.recording ? " · recording" : ""}`;
  }
}

function select(id: string): void {
  stopSocket?.();
  stopSocket = null;
  sid = id;
  msg = null;
  venue = null;
  view = null;
  keep(() => id ? localStorage.setItem(SID_KEY, id) : localStorage.removeItem(SID_KEY));
  history.replaceState(null, "", id ? `?s=${encodeURIComponent(id)}` : location.pathname);
  renderSessions();
  if (!id) return;
  stopSocket = socket(`/ws/sessions/${encodeURIComponent(id)}`, (m) => void onMsg(m), (up) => {
    const c = $("conn");
    c.textContent = up ? "live" : "reconnecting";
    c.classList.toggle("bad", !up);
  });
}

async function refreshSessions(): Promise<void> {
  try { sessions = await api<SessionInfo[]>("/api/sessions"); } catch { return; }
  if (!sessions.some((s) => s.id === sid)) {
    const want = new URLSearchParams(location.search).get("s") ?? (() => { try { return localStorage.getItem(SID_KEY) ?? ""; } catch { return ""; } })();
    select(sessions.find((s) => s.id === want)?.id ?? sessions[0]?.id ?? "");
  } else renderSessions();
}

function wire(): void {
  $("sessions").addEventListener("click", (e) => {
    const id = (e.target as HTMLElement).closest("button")?.dataset.sid;
    if (id && id !== sid) select(id);
  });
  $("del").onclick = () => {
    if (!sid || !confirm(`Stop event ${sid}? Phones that joined will be disconnected.`)) return;
    void act(api(base(), undefined, "DELETE").then(refreshSessions));
  };
  $("modes").addEventListener("click", (e) => {
    const b = (e.target as HTMLElement).closest("button");
    if (!b) return;
    const mode = b.dataset.mode!;
    if (mode === "evacuation" && msg?.mode !== "evacuation") {
      if (Date.now() - armed > 3000) {
        armed = Date.now();
        b.textContent = "Confirm evacuation";
        setTimeout(() => { b.textContent = "Evacuate"; armed = 0; }, 3000);
        return;
      }
      b.textContent = "Evacuate";
    }
    armed = 0;
    void act(api(`${base()}/mode`, { mode }));
  });
  $("restart").onclick = () => void act(api(`${base()}/restart`, {}));
  $("pause").onclick = () => void act(api(`${base()}/pause`, { paused: !msg?.paused }));
  ($("speed") as HTMLSelectElement).onchange = (e) => void act(api(`${base()}/speed`, { speed: Number((e.target as HTMLSelectElement).value) }));
  $("closed").addEventListener("click", (e) => {
    const id = (e.target as HTMLElement).dataset.reopen;
    if (id) void act(api(`${base()}/closure`, { threshold: id, closed: false }));
  });
  $("start").onclick = () => void act((async () => {
    const created = await api<SessionInfo>("/api/sessions", {
      name: ($("evName") as HTMLInputElement).value.trim(),
      venue: ($("venueSel") as HTMLSelectElement).value, scenario: ($("scSel") as HTMLSelectElement).value,
      planner: ($("plSel") as HTMLSelectElement).value, total: Number(($("total") as HTMLInputElement).value) || undefined,
      speed: msg?.speed ?? 5, demo_people: ($("demoPeople") as HTMLInputElement).checked, record: ($("rec") as HTMLInputElement).checked,
    });
    await refreshSessions();
    select(created.id);
    ($("newCard") as HTMLDetailsElement).open = false;
  })());
  $("logout").onclick = (e) => { e.preventDefault(); logout(); };
  const cv = $("cv") as HTMLCanvasElement;
  cv.addEventListener("click", (e) => {
    if (!view || !msg) return;
    const r = cv.getBoundingClientRect();
    const th = view.thresholdAt(e.clientX - r.left, e.clientY - r.top, "all");
    if (th) void act(api(`${base()}/closure`, { threshold: th.id, closed: !msg.closed.includes(th.id) }));
  });
  const tip = $("tip");
  cv.addEventListener("mousemove", (e) => {
    if (!view || !msg || !venue) { tip.hidden = true; return; }
    const r = cv.getBoundingClientRect(), x = e.clientX - r.left, y = e.clientY - r.top;
    const th = view.thresholdAt(x, y, "all");
    const z = th ? undefined : view.zoneAt(x, y, "all");
    cv.style.cursor = th ? "pointer" : "default";
    if (!th && !z) { tip.hidden = true; return; }
    tip.hidden = false;
    tip.style.left = `${e.clientX + 12}px`; tip.style.top = `${e.clientY + 12}px`;
    if (th) tip.innerHTML = `<b>${esc(th.name ?? th.id)}</b><br>${th.width_m} m wide${msg.closed.includes(th.id) ? " · closed" : ""}<br><span class="muted">click to ${msg.closed.includes(th.id) ? "reopen" : "close"}</span>`;
    else if (z) { const n = view.lastCounts[z.id] ?? 0; tip.innerHTML = `<b>${esc(z.name ?? z.id)}</b><br>${fmt(n)} people in or passing through`; }
  });
  cv.addEventListener("mouseleave", () => { tip.hidden = true; });
  new ResizeObserver(() => view?.resize()).observe($("map"));
}

wire();
void (async () => {
  try {
    const h = await api<{ auth: boolean }>("/api/health");
    $("logout").hidden = !h.auth;
    await fillSession();
    await refreshSessions();
    setInterval(() => void refreshSessions(), 4000);
  } catch (e) { say(`Could not reach the server: ${(e as Error).message}`); }
})();
requestAnimationFrame(frame);
