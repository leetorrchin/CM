import { api, dark, esc, getVenue, socket, type Guidance, type LiveMsg } from "./api";
import { RunView } from "./render";
import type { RunLog, Venue } from "./types";

const $ = <T extends HTMLElement>(id: string) => document.getElementById(id) as T;
const KEY = "crowd.pid";
const safe = <T>(f: () => T, d: T): T => { try { return f(); } catch { return d; } };

let venue: Venue | null = null;
let view: RunView | null = null;
let pid: string | null = null;
let g: Guidance | null = null;
let live: LiveMsg | null = null;
let stops: Array<() => void> = [];
const log: RunLog = { runId: "phone", venueId: "", planner: "", scenario: "", states: [], events: [], metrics: null, duration: 0 };

const zoneName = (id?: string) => (id && venue?.zones.find((z) => z.id === id)?.name) || id || "";
const gateName = (id?: string, toward?: string) => (id && venue?.thresholds.find((t) => t.id === id)?.name) || (toward ? `the gate to ${zoneName(toward)}` : "the next gate");
const destName = (id: string) => id === "nearest_safe" ? "the nearest safe exit" : (venue?.destinations?.find((d) => d.id === id)?.name ?? id);

function show(which: "join" | "main"): void {
  $("join").hidden = which !== "join";
  $("main").hidden = which !== "main";
}

function describe(x: Guidance): { title: string; detail: string; cls: string } {
  const evac = x.mode === "evacuation";
  const rate = (() => {
    const th = venue?.thresholds.find((t) => t.id === x.next_threshold);
    return th ? Math.max(0.3, th.width_m * 1.3) : 1;
  })();
  const group = x.group_size > 1 ? ` Your group of ${x.group_size} moves together.` : "";
  if (x.arrived) return { title: `You're at ${destName(x.destination)}`, detail: `You have arrived.${group}`, cls: "ok" };
  if (x.state === "stuck") return { title: "No open route right now", detail: "Stay where you are and follow staff instructions.", cls: "evac" };
  if (x.state === "transit") return { title: `Crossing ${gateName(x.crossing, x.to_zone)}`, detail: `Into ${zoneName(x.to_zone)}.${group}`, cls: evac ? "evac" : "" };
  if (x.state === "queued") {
    const ahead = x.queue_ahead ?? 0;
    const wait = Math.max(5, Math.round(ahead / rate / 5) * 5);
    return {
      title: `Wait for ${gateName(x.next_threshold, x.next_zone)}`,
      detail: `About ${ahead.toLocaleString()} people ahead, roughly ${wait} s. Then into ${zoneName(x.next_zone)}.${group}`,
      cls: evac ? "evac" : "",
    };
  }
  if (x.next_threshold) {
    return {
      title: `${evac ? "Evacuate: go" : "Go"} to ${gateName(x.next_threshold, x.next_zone)}`,
      detail: `Then into ${zoneName(x.next_zone)}, on the way to ${destName(x.destination)}.${group}`,
      cls: evac ? "evac" : "",
    };
  }
  return { title: "Finding your route", detail: `Heading to ${destName(x.destination)}.`, cls: evac ? "evac" : "" };
}

function render(): void {
  if (!g || !venue) return;
  if (g.error) {
    $("iTitle").textContent = "Lost this person";
    $("iDetail").textContent = "They may have left the venue or the session was restarted.";
    return;
  }
  const d = describe(g);
  $("instr").className = `card instr ${d.cls}`;
  $("iTitle").textContent = d.title;
  $("iDetail").textContent = d.detail;
  const b = $("banner");
  b.hidden = g.mode !== "evacuation";
  b.className = "evac";
  b.textContent = "EVACUATION. Follow the route shown.";
  const facts: [string, string][] = [["You are in", zoneName(g.zone)], ["Going to", destName(g.destination)], ["Mode", g.mode]];
  if (g.group_size > 1) facts.push(["Group", `${g.group_size} people together`]);
  if (!g.following && !pid?.startsWith("guest-")) facts.push(["Note", "this person is not using the app's route"]);
  $("facts").innerHTML = facts.map(([k, v]) => `<dt>${esc(k)}</dt><dd>${esc(v)}</dd>`).join("");
  $("closedList").innerHTML = g.closed.map((id) => `<li>${esc(gateName(id, id))} is closed</li>`).join("");
}

function overlay(ctx: CanvasRenderingContext2D, v: RunView): void {
  if (!g || g.error) return;
  const cen = (id?: string) => (id ? v.info.get(id)?.cen : undefined);
  const px = (p: [number, number]) => v.tr.toScreen(p[0], p[1]);
  const here = cen(g.state === "transit" ? g.from_zone : g.zone);
  if (!here) return;
  const th = venue?.thresholds.find((t) => t.id === (g!.next_threshold ?? g!.crossing));
  const next = cen(g.next_zone ?? g.to_zone);
  const accent = getComputedStyle(document.documentElement).getPropertyValue(g.mode === "evacuation" ? "--bad" : "--accent").trim();
  const a = px(here);
  if (th && next) {
    const mid = px([(th.segment[0][0] + th.segment[1][0]) / 2, (th.segment[0][1] + th.segment[1][1]) / 2]);
    const b = px(next);
    ctx.strokeStyle = accent; ctx.lineWidth = 4; ctx.lineCap = "round"; ctx.setLineDash([10, 7]);
    ctx.beginPath(); ctx.moveTo(a[0], a[1]); ctx.lineTo(mid[0], mid[1]); ctx.lineTo(b[0], b[1]); ctx.stroke();
    ctx.setLineDash([]);
    const ang = Math.atan2(b[1] - mid[1], b[0] - mid[0]);
    ctx.fillStyle = accent; ctx.beginPath();
    ctx.moveTo(b[0], b[1]);
    ctx.lineTo(b[0] - 14 * Math.cos(ang - 0.45), b[1] - 14 * Math.sin(ang - 0.45));
    ctx.lineTo(b[0] - 14 * Math.cos(ang + 0.45), b[1] - 14 * Math.sin(ang + 0.45));
    ctx.fill();
  }
  ctx.fillStyle = accent; ctx.strokeStyle = "#fff"; ctx.lineWidth = 3;
  ctx.beginPath(); ctx.arc(a[0], a[1], 9, 0, Math.PI * 2); ctx.stroke(); ctx.fill();
}

function frame(ts: number): void {
  if (view && live) {
    log.states = [live];
    view.draw(live.t_s, { level: "all", labels: true, numbers: false, dark: dark(), wall: ts / 1000, overlay, heading: false });
  }
  requestAnimationFrame(frame);
}

async function enter(id: string): Promise<void> {
  pid = id;
  safe(() => localStorage.setItem(KEY, id), undefined);
  history.replaceState(null, "", `#p=${encodeURIComponent(id)}`);
  const first = await api<Guidance>(`/api/guidance/${encodeURIComponent(id)}`);
  const h = await api<{ session: { venue: string } | null }>("/api/health");
  if (!h.session) throw new Error("no session is running");
  venue = await getVenue(h.session.venue);
  log.venueId = venue.id;
  view = new RunView($("cv") as HTMLCanvasElement, venue, log);
  new ResizeObserver(() => view?.resize()).observe($("map"));
  g = first;
  const isGuest = id.startsWith("guest-");
  $("destRow").hidden = !isGuest;
  if (isGuest) {
    const sel = $("dest") as HTMLSelectElement;
    sel.innerHTML = `<option value="nearest_safe">Nearest safe exit</option>` +
      (venue.destinations ?? []).filter((d) => d.kind !== "entry").map((d) => `<option value="${esc(d.id)}">${esc(d.name ?? d.id)}</option>`).join("");
    sel.value = first.destination;
    sel.onchange = () => void api(`/api/guidance/${encodeURIComponent(id)}/destination`, { destination: sel.value }).catch(() => {});
  }
  stops.forEach((s) => s());
  stops = [
    socket(`/ws/guide/${encodeURIComponent(id)}`, (m) => { g = m; render(); }),
    socket("/ws/live", (m) => { if (m.type === "state") live = m; }),
  ];
  show("main");
  render();
}

function leave(): void {
  stops.forEach((s) => s());
  stops = [];
  pid = null;
  safe(() => localStorage.removeItem(KEY), undefined);
  history.replaceState(null, "", location.pathname);
  $("banner").hidden = true;
  void showJoin();
}

async function showJoin(): Promise<void> {
  show("join");
  const err = $("joinErr");
  err.hidden = true;
  try {
    const h = await api<{ session: { venue: string } | null }>("/api/health");
    if (!h.session) throw new Error("No event is running right now. Ask the organiser to start a session in the control room.");
    venue = await getVenue(h.session.venue);
    const crowdZones = venue.zones.filter((z) => z.kind !== "restricted");
    $("where").innerHTML = crowdZones.map((z) => `<option value="${esc(z.id)}">${esc(z.name ?? z.id)}</option>`).join("");
    $("to").innerHTML = `<option value="nearest_safe">Nearest safe exit</option>` +
      (venue.destinations ?? []).filter((d) => d.kind !== "entry").map((d) => `<option value="${esc(d.id)}">${esc(d.name ?? d.id)}</option>`).join("");
    const people = await api<{ id: string; group_size: number; zone: string }[]>("/api/people?limit=6");
    $("people").innerHTML = people.map((p) =>
      `<li><button data-pid="${esc(p.id)}" type="button">${esc(p.id)} · ${esc(zoneName(p.zone))}${p.group_size > 1 ? ` · group of ${p.group_size}` : ""}</button></li>`).join("");
  } catch (e) {
    err.hidden = false;
    err.textContent = (e as Error).message;
  }
}

function wire(): void {
  $("joinBtn").onclick = async () => {
    try {
      const r = await api<{ person_id: string }>("/api/guest", {
        zone: ($("where") as HTMLSelectElement).value, destination: ($("to") as HTMLSelectElement).value });
      await enter(r.person_id);
    } catch (e) { $("joinErr").hidden = false; $("joinErr").textContent = (e as Error).message; }
  };
  $("people").addEventListener("click", async (e) => {
    const id = (e.target as HTMLElement).closest("button")?.dataset.pid;
    if (!id) return;
    try { await enter(id); } catch (err) { $("joinErr").hidden = false; $("joinErr").textContent = (err as Error).message; }
  });
  $("leave").onclick = leave;
}

async function start(): Promise<void> {
  wire();
  requestAnimationFrame(frame);
  if (import.meta.env.PROD && "serviceWorker" in navigator) navigator.serviceWorker.register("/sw.js").catch(() => {});
  const fromHash = new URLSearchParams(location.hash.slice(1)).get("p");
  const saved = fromHash ?? safe(() => localStorage.getItem(KEY), null);
  if (saved) {
    try { await enter(saved); return; } catch { /* person gone: fall through to join */ }
  }
  await showJoin();
}
void start();
