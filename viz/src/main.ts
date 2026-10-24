import { drawChart } from "./chart";
import { sampleAt, sum, topEntries } from "./interp";
import { detectKind, parseRun, parseVenue } from "./loader";
import { parseEdgeKey, RunView } from "./render";
import type { RunLog, Venue } from "./types";

const $ = <T extends HTMLElement>(id: string) => document.getElementById(id) as T;
const esc = (s: unknown) => String(s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]!);
const dark = () => matchMedia("(prefers-color-scheme: dark)").matches;
const fmt = (n: number) => Math.round(n).toLocaleString();
const mmss = (s: number) => `${Math.floor(s / 60)}:${String(Math.floor(s % 60)).padStart(2, "0")}`;

interface Slot { log: RunLog; name: string; view?: RunView; chart?: HTMLCanvasElement; live?: HTMLElement }
const app = { venue: null as Venue | null, slots: [] as Slot[], t: 0, playing: false, speed: 5, level: "all", labels: true, duration: 0, lastPanel: 0 };

function say(text: string | null): void {
  const el = $("msg");
  el.hidden = !text;
  el.textContent = text ?? "";
}

function ingest(name: string, text: string): void {
  try {
    const kind = detectKind(text);
    if (kind === "venue") app.venue = parseVenue(text);
    else if (kind === "run") app.slots.push({ log: parseRun(text), name });
    else throw new Error("not a venue file or a run log");
    say(null);
  } catch (e) {
    say(`Could not read ${name}: ${(e as Error).message}`);
  }
}

function zoneName(id: string): string {
  return app.venue?.zones.find((z) => z.id === id)?.name ?? id;
}
function edgeLabel(key: string): string {
  const { tid, from, to } = parseEdgeKey(key);
  const th = app.venue?.thresholds.find((t) => t.id === tid);
  return `${th?.name ?? tid}: ${zoneName(from)} to ${zoneName(to)}`;
}

function rebuild(): void {
  const views = $("views");
  views.querySelectorAll(".view").forEach((n) => n.remove());
  const empty = $("empty");
  const panel = $("panel");
  panel.innerHTML = "";
  if (!app.venue || !app.slots.length) {
    empty.hidden = false;
    (empty.firstElementChild as HTMLElement).textContent = !app.venue && app.slots.length
      ? "Run loaded. Now open the venue file it was run on (venues/*.json)."
      : app.venue
        ? "Venue loaded. Now open a run log (runs/*.jsonl)."
        : "Open a venue file (venues/*.json) and one or more run logs (runs/*.jsonl), or drop them here.";
    return;
  }
  empty.hidden = true;
  const venue = app.venue;
  const known = new Set(venue.zones.map((z) => z.id));
  const sel = $<HTMLSelectElement>("level");
  sel.innerHTML = `<option value="all">All</option>` + venue.levels.map((l) => `<option value="${esc(l.id)}">${esc(l.name ?? l.id)}</option>`).join("");
  sel.value = app.level = "all";

  app.slots.forEach((slot, i) => {
    const wrap = document.createElement("div");
    wrap.className = "view";
    wrap.innerHTML = `<canvas></canvas><button class="close" aria-label="Remove this run" title="Remove">×</button>`;
    views.appendChild(wrap);
    wrap.querySelector("button")!.addEventListener("click", () => { app.slots.splice(i, 1); rebuild(); });
    const canvas = wrap.querySelector("canvas")!;
    slot.view = new RunView(canvas, venue, slot.log);
    new ResizeObserver(() => slot.view?.resize()).observe(wrap);
    canvas.addEventListener("mousemove", (ev) => hover(slot, canvas, ev));
    canvas.addEventListener("mouseleave", () => { $("tip").hidden = true; });
    if (slot.log.venueId && slot.log.venueId !== venue.id) say(`Run ${slot.name} was made on venue "${slot.log.venueId}", but "${venue.id}" is loaded.`);
    const stray = Object.keys(slot.log.states[0]?.zones ?? {}).filter((z) => !known.has(z));
    if (stray.length) say(`Run ${slot.name} mentions zones that are not in this venue (${stray[0]}...).`);

    const card = document.createElement("section");
    card.className = "card";
    card.innerHTML = `<h3>${esc(slot.log.planner || slot.name)} <small>${esc(slot.log.scenario)}</small></h3><div class="live"></div>
      <canvas class="chart" aria-label="Active and queued people over time"></canvas>
      <div class="legend"><span><i style="background:var(--series-a)"></i>Still moving</span><span><i style="background:var(--series-b)"></i>Waiting in queues</span></div>`;
    panel.appendChild(card);
    slot.live = card.querySelector<HTMLElement>(".live")!;
    slot.chart = card.querySelector("canvas")!;
    slot.chart.addEventListener("click", (ev) => {
      const r = slot.chart!.getBoundingClientRect();
      seek(Math.max(0, Math.min(1, (ev.clientX - r.left - 34) / (r.width - 40))) * app.duration);
    });
  });

  const cmp = document.createElement("section");
  cmp.className = "card";
  cmp.id = "final";
  panel.appendChild(cmp);
  const key = document.createElement("section");
  key.className = "card key";
  key.innerHTML = `<h3>How to read the map</h3>
    <p><b>Zone colour</b>: people per m² against the zone's comfortable limit (pale = empty, dark red = at the limit).</p>
    <p><b>Dashed blue line</b>: people crossing a threshold, thicker means more. They are on their way, so they are not counted in a zone.</p>
    <p><b>Orange circle</b>: people queueing to cross a threshold.</p>
    <p><b>Red cross</b>: closed threshold. <b>Dashed outline</b>: upper level.</p>`;
  panel.appendChild(key);
  app.duration = Math.max(...app.slots.map((s) => s.log.duration));
  const range = $<HTMLInputElement>("range");
  range.max = String(app.duration);
  app.t = Math.min(app.t, app.duration);
  renderFinal();
  renderTicks();
  frame(performance.now());
}

const ROWS: [string, string, "low" | "high" | null][] = [
  ["arrived_share", "Arrived", "high"], ["travel_time_mean_s", "Mean travel (s)", "low"],
  ["travel_time_p95_s", "95th pct travel (s)", "low"], ["clearance_s", "Clearance (s)", "low"],
  ["groups_split_mean_share", "Groups split (mean)", "low"], ["groups_split_peak", "Groups split (peak)", "low"], ["stuck", "Stuck", "low"],
];
function renderFinal(): void {
  const el = $("final");
  const withM = app.slots.filter((s) => s.log.metrics);
  if (!withM.length) { el.hidden = true; return; }
  el.hidden = false;
  const head = withM.map((s) => `<th>${esc(s.log.planner || s.name)}<br><small>${esc(s.log.scenario)}</small></th>`).join("");
  const body = ROWS.map(([key, label, better]) => {
    const vals = withM.map((s) => s.log.metrics![key] as number | null);
    const nums = vals.filter((v): v is number => typeof v === "number");
    const best = nums.length > 1 && better ? (better === "low" ? Math.min(...nums) : Math.max(...nums)) : null;
    const cells = vals.map((v) => `<td class="${v !== null && v === best && new Set(nums).size > 1 ? "best" : ""}">${v === null || v === undefined ? "n/a" : key.includes("share") ? (v * 100).toFixed(1) + "%" : v}</td>`).join("");
    return `<tr><td>${label}</td>${cells}</tr>`;
  }).join("");
  el.innerHTML = `<h3>Final results</h3><table><thead><tr><th></th>${head}</tr></thead><tbody>${body}</tbody></table>`;
}

function renderTicks(): void {
  const ticks = $("ticks");
  ticks.innerHTML = "";
  const log = app.slots[0]?.log;
  if (!log || !app.duration) return;
  for (const ev of log.events) {
    const i = document.createElement("i");
    i.style.left = `${(ev.t_s / app.duration) * 100}%`;
    i.className = ev.type === "mode_change" ? "mode" : "";
    i.title = `${mmss(ev.t_s)} ${ev.type === "closure" ? `${ev.data.closed ? "closed" : "reopened"} ${ev.data.threshold}` : `mode: ${ev.data.mode}`}`;
    ticks.appendChild(i);
  }
}

function updateLive(): void {
  const yMax = Math.max(1, ...app.slots.flatMap((s) => s.log.states.map((st) => Math.max(st.active, sum(st.queues)))));
  for (const slot of app.slots) {
    const s = sampleAt(slot.log.states, app.t);
    const top = topEntries(s.queues, 4).map(([k, n]) => `<li>${fmt(n)} <small>${esc(edgeLabel(k))}</small></li>`).join("");
    slot.live!.innerHTML = `<dl><dt>Left the venue</dt><dd>${fmt(s.cleared)}</dd><dt>Still moving</dt><dd>${fmt(s.active)}</dd>
      <dt>Waiting in queues</dt><dd>${fmt(sum(s.queues))}</dd><dt>Groups split</dt><dd>${fmt(s.groups_split)}</dd></dl>
      ${top ? `<h4>Longest queues</h4><ol>${top}</ol>` : ""}`;
    drawChart(slot.chart!, slot.log, app.t, app.duration, yMax);
  }
}

function hover(slot: Slot, canvas: HTMLCanvasElement, ev: MouseEvent): void {
  const r = canvas.getBoundingClientRect();
  const z = slot.view!.zoneAt(ev.clientX - r.left, ev.clientY - r.top, app.level);
  const tip = $("tip");
  if (!z) { tip.hidden = true; return; }
  const info = slot.view!.info.get(z.id)!;
  const n = slot.view!.stateAt(app.t).zones[z.id] ?? 0;
  tip.hidden = false;
  tip.style.left = `${ev.clientX + 14}px`;
  tip.style.top = `${ev.clientY + 14}px`;
  tip.innerHTML = `<b>${esc(z.name ?? z.id)}</b> (${esc(z.kind)})<br>${fmt(n)} people<br>${(n / info.area).toFixed(2)} per m², limit ${info.maxDensity.toFixed(1)}<br>${fmt(info.area)} m²`;
}

function seek(t: number): void {
  app.t = Math.max(0, Math.min(app.duration, t));
  $<HTMLInputElement>("range").value = String(app.t);
  updateLive();
}

function frame(now: number): void {
  const dt = Math.min(0.1, (now - (frame as unknown as { last?: number }).last! || 0) / 1000);
  (frame as unknown as { last?: number }).last = now;
  if (app.playing && app.duration) {
    app.t += dt * app.speed;
    if (app.t >= app.duration) { app.t = app.duration; app.playing = false; $("play").textContent = "Play"; }
    $<HTMLInputElement>("range").value = String(app.t);
  }
  for (const slot of app.slots) slot.view?.draw(app.t, { level: app.level, labels: app.labels, dark: dark(), wall: now / 1000 });
  $("clock").textContent = `${mmss(app.t)} / ${mmss(app.duration)}`;
  if (now - app.lastPanel > 100) { app.lastPanel = now; if (app.slots.length) updateLive(); }
  requestAnimationFrame(frame);
}

async function loadFiles(files: FileList | File[]): Promise<void> {
  for (const f of Array.from(files)) ingest(f.name, await f.text());
  rebuild();
}

async function fetchText(url: string): Promise<string> {
  const r = await fetch(url);
  if (!r.ok) throw new Error(`${url}: ${r.status}`);
  return r.text();
}

async function initRepo(): Promise<void> {
  let index: Record<string, string[]>;
  try { index = JSON.parse(await fetchText("/data/index.json")); } catch { return; }
  $("repoLoad").hidden = false;
  const opts = (names: string[]) => names.map((n) => `<option>${esc(n)}</option>`).join("");
  $("repoVenue").innerHTML = opts(index.venues.filter((n) => n.endsWith(".json")));
  $("repoRun").innerHTML = opts(index.runs.filter((n) => n.endsWith(".jsonl")));
  $("repoAdd").addEventListener("click", async () => {
    try {
      const run = $<HTMLSelectElement>("repoRun").value;
      const text = run ? await fetchText(`/data/runs/${run}`) : "";
      if (!app.venue) {
        // pick the venue file the run was made on (file name is the venue id), else the dropdown
        const id = text ? parseRun(text).venueId : "";
        const match = index.venues.find((n) => n.split("/").pop() === `${id}.json`);
        ingest("venue", await fetchText(`/data/venues/${match ?? $<HTMLSelectElement>("repoVenue").value}`));
      }
      if (text) ingest(run, text);
    } catch (e) { say((e as Error).message); }
    rebuild();
  });
  const q = new URLSearchParams(location.search);
  for (const k of ["venue", "run", "run2", "run3"]) if (q.get(k)?.includes("..")) return;
  try {
    if (q.get("venue")) ingest("venue", await fetchText(`/data/venues/${q.get("venue")}`));
    for (const key of ["run", "run2", "run3"]) if (q.get(key)) ingest(q.get(key)!, await fetchText(`/data/runs/${q.get(key)}`));
    rebuild();
  } catch (e) { say((e as Error).message); }
}

$<HTMLInputElement>("files").addEventListener("change", (e) => loadFiles((e.target as HTMLInputElement).files!));
$("play").addEventListener("click", () => {
  if (!app.duration) return;
  if (app.t >= app.duration) seek(0);
  app.playing = !app.playing;
  $("play").textContent = app.playing ? "Pause" : "Play";
});
$<HTMLSelectElement>("speed").addEventListener("change", (e) => { app.speed = Number((e.target as HTMLSelectElement).value); });
$<HTMLInputElement>("range").addEventListener("input", (e) => seek(Number((e.target as HTMLInputElement).value)));
$<HTMLSelectElement>("level").addEventListener("change", (e) => { app.level = (e.target as HTMLSelectElement).value; });
$<HTMLInputElement>("labels").addEventListener("change", (e) => { app.labels = (e.target as HTMLInputElement).checked; });
window.addEventListener("dragover", (e) => e.preventDefault());
window.addEventListener("drop", (e) => { e.preventDefault(); if (e.dataTransfer?.files.length) void loadFiles(e.dataTransfer.files); });
window.addEventListener("keydown", (e) => {
  if ((e.target as HTMLElement).tagName === "SELECT") return;
  if (e.key === " ") { e.preventDefault(); $("play").click(); }
  if (e.key === "ArrowRight") seek(app.t + (e.shiftKey ? 30 : 5));
  if (e.key === "ArrowLeft") seek(app.t - (e.shiftKey ? 30 : 5));
});
requestAnimationFrame(frame);
void initRepo();
