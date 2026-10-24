import { api, dark, esc, socket, type Guidance, type JoinInfo, type LiveMsg } from "./api";
import { RunView } from "./render";
import type { RunLog, Venue } from "./types";

const $ = <T extends HTMLElement>(id: string) => document.getElementById(id) as T;
const KEY = "crowd.guest";
interface Saved { code: string; pid: string; token: string }
const safe = <T>(f: () => T, d: T): T => { try { return f(); } catch { return d; } };

let venue: Venue | null = null;
let view: RunView | null = null;
let pid: string | null = null;
let code = "";
let token = "";
let info: JoinInfo | null = null;
let watchId: number | null = null;
let lastSend = 0;
let tapMode = false;
const gh = () => ({ "X-Guest-Token": token });
const jb = () => `/api/join/${encodeURIComponent(code)}`;
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

function setLoc(text: string, bad = false): void {
  const el = $("locStatus");
  el.textContent = text;
  el.classList.toggle("err", bad);
}

async function sendPosition(body: Record<string, unknown>): Promise<void> {
  if (!pid || !pid.startsWith("guest-")) return;
  try {
    const r = await api<{ status: string; zone: string | null; off_venue_m: number }>(`${jb()}/guest/${encodeURIComponent(pid)}/position`, body, "POST", gh());
    if (r.status === "inaccurate") setLoc("Location too vague here. Move to a clearer spot or tap the map.", true);
    else if (r.status === "off_venue") setLoc(`You look to be ${Math.round(r.off_venue_m)} m outside the venue.`, true);
    else setLoc(r.zone ? `Located: ${zoneName(r.zone)}` : "Locating…");
  } catch (e) { setLoc((e as Error).message, true); }
}

function startLocation(): void {
  if (watchId !== null || !("geolocation" in navigator)) { if (!("geolocation" in navigator)) setLoc("This phone cannot share its location here. Tap the map instead.", true); return; }
  setLoc("Locating…");
  watchId = navigator.geolocation.watchPosition((p) => {
    const now = Date.now();
    if (now - lastSend < 2000) return;
    lastSend = now;
    void sendPosition({ lat: p.coords.latitude, lon: p.coords.longitude, accuracy_m: p.coords.accuracy });
  }, (e) => {
    if (e.code === 1) {
      setLoc("Location permission was denied. Tap the map instead.", true);
      stopLocation(false);
    } else setLoc("No location fix right now. Still trying.", true);
  }, { enableHighAccuracy: true, maximumAge: 2000, timeout: 20000 });
  ($("useLoc") as HTMLInputElement).checked = true;
}

function stopLocation(report = true): void {
  if (watchId !== null) navigator.geolocation.clearWatch(watchId);
  watchId = null;
  ($("useLoc") as HTMLInputElement).checked = false;
  if (report && pid) void api(`${jb()}/guest/${encodeURIComponent(pid)}/mode`, { external: false }, "POST", gh()).catch(() => {});
  if (report) setLoc("Location off. Moving as the simulation says.");
}

async function enter(saved: Saved): Promise<void> {
  code = saved.code; pid = saved.pid; token = saved.token;
  const guest = pid.startsWith("guest-");
  const hdr = guest ? gh() : undefined;
  const first = await api<Guidance>(`${jb()}/guest/${encodeURIComponent(pid)}/guidance`, undefined, "GET", hdr);
  info = await api<JoinInfo>(jb());
  venue = await api<Venue>(`${jb()}/venue`);
  safe(() => localStorage.setItem(KEY, JSON.stringify(saved)), undefined);
  history.replaceState(null, "", `?s=${encodeURIComponent(code)}`);
  log.venueId = venue.id;
  view = new RunView($("cv") as HTMLCanvasElement, venue, log);
  new ResizeObserver(() => view?.resize()).observe($("map"));
  g = first;
  $("destRow").hidden = !guest;
  $("locCard").hidden = !guest;
  $("eventName").textContent = info.name;
  const hasGps = info.has_anchor && "geolocation" in navigator;
  ($("useLocRow") as HTMLElement).hidden = !hasGps;
  setLoc(hasGps ? "Off. Turn on to use your real position." : "Tap the map where you are to update your position.");
  if (guest) {
    const sel = $("dest") as HTMLSelectElement;
    sel.innerHTML = `<option value="nearest_safe">Nearest safe exit</option>` +
      info.destinations.map((d) => `<option value="${esc(d.id)}">${esc(d.name)}</option>`).join("");
    sel.value = first.destination;
    sel.onchange = () => void api(`${jb()}/guest/${encodeURIComponent(pid!)}/destination`, { destination: sel.value }, "POST", gh()).catch(() => {});
  }
  stops.forEach((s) => s());
  stops = [
    socket(`/ws/join/${encodeURIComponent(code)}/guide/${encodeURIComponent(pid)}${guest ? `?token=${encodeURIComponent(token)}` : ""}`, (m) => { g = m; render(); }),
    socket(`/ws/join/${encodeURIComponent(code)}/live`, (m) => { if (m.type === "state") live = m; }),
  ];
  show("main");
  render();
}

function leave(): void {
  stops.forEach((s) => s());
  stops = [];
  if (watchId !== null) stopLocation(false);
  if (pid?.startsWith("guest-")) void api(`${jb()}/guest/${encodeURIComponent(pid)}`, undefined, "DELETE", gh()).catch(() => {});
  pid = null; token = "";
  safe(() => localStorage.removeItem(KEY), undefined);
  history.replaceState(null, "", location.pathname);
  $("banner").hidden = true;
  void showJoin();
}

async function findEvent(c: string): Promise<void> {
  const err = $("joinErr");
  err.hidden = true;
  try {
    info = await api<JoinInfo>(`/api/join/${encodeURIComponent(c.trim())}`);
    code = info.id;
    $("step1").hidden = true;
    $("step2").hidden = false;
    $("evTitle").textContent = info.name;
    $("where").innerHTML = info.zones.map((z) => `<option value="${esc(z.id)}">${esc(z.name)}</option>`).join("");
    $("to").innerHTML = `<option value="nearest_safe">Nearest safe exit</option>` +
      info.destinations.map((d) => `<option value="${esc(d.id)}">${esc(d.name)}</option>`).join("");
    const demo = $("demoBox");
    demo.hidden = !info.demo_people;
    if (info.demo_people) {
      venue = await api<Venue>(`${jb()}/venue`);
      const people = await api<{ id: string; group_size: number; zone: string }[]>(`${jb()}/people?limit=6`);
      $("people").innerHTML = people.map((p) =>
        `<li><button data-pid="${esc(p.id)}" type="button">${esc(p.id)} · ${esc(zoneName(p.zone))}${p.group_size > 1 ? ` · group of ${p.group_size}` : ""}</button></li>`).join("");
    }
  } catch (e) {
    err.hidden = false;
    err.textContent = (e as Error).message;
  }
}

async function showJoin(): Promise<void> {
  show("join");
  $("step1").hidden = false;
  $("step2").hidden = true;
  const want = new URLSearchParams(location.search).get("s");
  if (want) { ($("codeIn") as HTMLInputElement).value = want.toUpperCase(); await findEvent(want); }
}

function wire(): void {
  $("find").onclick = () => void findEvent(($("codeIn") as HTMLInputElement).value);
  ($("codeIn") as HTMLInputElement).addEventListener("keydown", (e) => { if (e.key === "Enter") $("find").click(); });
  $("back").onclick = () => { $("step1").hidden = false; $("step2").hidden = true; };
  $("joinBtn").onclick = async () => {
    try {
      const r = await api<{ person_id: string; token: string }>(`${jb()}/guest`, {
        zone: ($("where") as HTMLSelectElement).value, destination: ($("to") as HTMLSelectElement).value });
      await enter({ code, pid: r.person_id, token: r.token });
    } catch (e) { $("joinErr").hidden = false; $("joinErr").textContent = (e as Error).message; }
  };
  $("people").addEventListener("click", async (e) => {
    const id = (e.target as HTMLElement).closest("button")?.dataset.pid;
    if (!id) return;
    try { await enter({ code, pid: id, token: "" }); } catch (err) { $("joinErr").hidden = false; $("joinErr").textContent = (err as Error).message; }
  });
  $("leave").onclick = leave;
  $("useLoc").addEventListener("change", (e) => (e.target as HTMLInputElement).checked ? startLocation() : stopLocation());
  $("tapBtn").onclick = () => {
    tapMode = !tapMode;
    $("tapBtn").textContent = tapMode ? "Tap the map now" : "Set my position on the map";
    $("tapBtn").classList.toggle("on", tapMode);
  };
  $("cv").addEventListener("click", (e) => {
    if (!tapMode || !view || !pid?.startsWith("guest-")) return;
    const r = ($("cv") as HTMLCanvasElement).getBoundingClientRect();
    const [x, y] = view.tr.toWorld(e.clientX - r.left, e.clientY - r.top);
    const z = view.zoneAt(e.clientX - r.left, e.clientY - r.top, "all");
    if (!z) { setLoc("Tap inside a zone.", true); return; }
    tapMode = false;
    $("tapBtn").textContent = "Set my position on the map";
    $("tapBtn").classList.remove("on");
    if (watchId !== null) stopLocation(false);
    void sendPosition({ x, y, accuracy_m: 1 });
  });
}

async function start(): Promise<void> {
  wire();
  requestAnimationFrame(frame);
  if (import.meta.env.PROD && "serviceWorker" in navigator) navigator.serviceWorker.register("/sw.js").catch(() => {});
  const want = new URLSearchParams(location.search).get("s")?.toUpperCase();
  const saved = safe<Saved | null>(() => JSON.parse(localStorage.getItem(KEY) ?? "null"), null);
  if (saved && (!want || want === saved.code.toUpperCase())) {
    try { await enter(saved); return; } catch { safe(() => localStorage.removeItem(KEY), undefined); }
  }
  await showJoin();
}
void start();
