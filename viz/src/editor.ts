import { api, dark, esc } from "./api";
import { bounds, centroid, pointInPolygon, polygonArea } from "./geom";
import type { Pt } from "./types";

type Tool = "select" | "rect" | "poly" | "gate" | "dest" | "del";
interface Zone { id: string; name?: string; level: string; kind: string; polygon: Pt[]; capacity?: { max_density_pp_m2?: number }; step_free?: boolean }
interface Gate { id: string; name?: string; kind: string; from_zone: string; to_zone: string; segment: [Pt, Pt]; width_m: number; one_way?: boolean; closable?: boolean; step_free?: boolean }
interface Dest { id: string; name?: string; kind: string; zone: string; safe?: boolean; at?: Pt }
interface Venue {
  schema_version: string; id: string; name?: string; units: "metres";
  levels: { id: string; name?: string; elevation_m: number }[];
  zones: Zone[]; thresholds: Gate[]; destinations: Dest[];
  pathways?: { id: string; zones: string[] }[]; sensor_sites?: { id: string; covers?: { kind: string; id: string }[]; threshold?: string }[];
  [k: string]: unknown;
}
type Sel = { kind: "zone" | "gate" | "dest"; id: string } | null;

const ZONE_KINDS = ["open_area", "corridor", "stage_front", "concourse", "queue", "seating", "assembly_point", "restricted"];
const GATE_KINDS = ["opening", "gate", "door", "stairs", "ramp", "barrier_gap"];
const DEST_KINDS = ["exit", "entry", "stage", "food", "toilets", "medical", "meeting_point", "assembly_point"];
const HUE: Record<string, number> = { open_area: 200, corridor: 40, stage_front: 330, concourse: 160, queue: 20, seating: 270, assembly_point: 120, restricted: 0 };

const $ = <T extends HTMLElement>(id: string) => document.getElementById(id) as T;
const cv = $("cv") as HTMLCanvasElement;

const blank = (): Venue => ({
  schema_version: "0.1.0", id: "my-venue", name: "My venue", units: "metres",
  levels: [{ id: "ground", name: "Ground", elevation_m: 0 }], zones: [], thresholds: [], destinations: [], pathways: [], sensor_sites: [],
});

let venue: Venue = blank();
let tool: Tool = "select";
let sel: Sel = null;
let level = "ground";
let snap = true;
let draft: Pt[] = [];
let rubber: Pt | null = null;
let drag: { mode: "vertex" | "end" | "zone" | "dest" | "pan" | "rect" | "gate"; start: Pt; px: [number, number]; idx?: number; orig?: unknown; to?: Pt } | null = null;
let errors: string[] | null = null;
let view = { scale: 8, ox: 40, oy: 40 };   // px per metre, and screen offset of world (0,0)
const undo: string[] = [], redo: string[] = [];

// ---------------------------------------------------------------- helpers
const toScreen = (p: Pt): [number, number] => [p[0] * view.scale + view.ox, cv.clientHeight - (p[1] * view.scale + view.oy)];
const toWorld = (x: number, y: number): Pt => [(x - view.ox) / view.scale, (cv.clientHeight - y - view.oy) / view.scale];
const r1 = (n: number) => Math.round(n * 10) / 10;

function say(t: string | null, bad = true): void {
  const el = $("msg");
  el.hidden = !t;
  el.textContent = t ?? "";
  el.style.background = bad ? "" : "color-mix(in srgb, #2e8b57 16%, var(--surface))";
  el.style.borderColor = bad ? "" : "#2e8b57";
}
function slug(s: string): string { return s.toLowerCase().replace(/[^a-z0-9_-]+/g, "_").replace(/^[^a-z0-9]+/, "") || "item"; }
function uid(base: string, taken: string[]): string {
  let i = 1, id = `${slug(base)}_${i}`;
  while (taken.includes(id)) id = `${slug(base)}_${++i}`;
  return id;
}
function commit(): void {
  undo.push(JSON.stringify(venue));
  if (undo.length > 100) undo.shift();
  redo.length = 0;
  errors = null;
  refreshPanel();
}
function restore(from: string[], to: string[]): void {
  const s = from.pop();
  if (!s) return;
  to.push(JSON.stringify(venue));
  venue = JSON.parse(s);
  sel = null;
  fixLevel();
  refreshPanel();
}
function fixLevel(): void {
  if (!venue.levels.some((l) => l.id === level)) level = venue.levels[0].id;
  $("level").innerHTML = venue.levels.map((l) => `<option value="${esc(l.id)}" ${l.id === level ? "selected" : ""}>${esc(l.name ?? l.id)}</option>`).join("");
}
function allVertices(): Pt[] { return venue.zones.filter((z) => z.level === level).flatMap((z) => z.polygon); }
function snapPt(sx: number, sy: number, force = false): Pt {
  const w = toWorld(sx, sy);
  if (!snap && !force) return [r1(w[0]), r1(w[1])];
  let best: Pt | null = null, bd = 10;
  for (const v of allVertices()) {
    const [x, y] = toScreen(v), d = Math.hypot(x - sx, y - sy);
    if (d < bd) { bd = d; best = v; }
  }
  if (best) return [best[0], best[1]];
  return [Math.round(w[0]), Math.round(w[1])];
}
function zoneAtPoint(p: Pt, lvl?: string): Zone | undefined {
  return venue.zones.filter((z) => (!lvl || z.level === lvl) && pointInPolygon(p[0], p[1], z.polygon))
    .sort((a, b) => polygonArea(a.polygon) - polygonArea(b.polygon))[0];
}
function segDist(p: Pt, a: Pt, b: Pt): number {
  const dx = b[0] - a[0], dy = b[1] - a[1], l2 = dx * dx + dy * dy || 1;
  const f = Math.max(0, Math.min(1, ((p[0] - a[0]) * dx + (p[1] - a[1]) * dy) / l2));
  return Math.hypot(p[0] - (a[0] + f * dx), p[1] - (a[1] + f * dy));
}
function destPos(d: Dest): Pt | undefined {
  if (d.at) return d.at;
  const z = venue.zones.find((q) => q.id === d.zone);
  return z ? centroid(z.polygon) : undefined;
}
function hit(sx: number, sy: number): Sel {
  const p = toWorld(sx, sy), tol = 8 / view.scale;
  for (const d of venue.destinations) {
    const q = destPos(d), z = venue.zones.find((zz) => zz.id === d.zone);
    if (q && z?.level === level && Math.hypot(q[0] - p[0], q[1] - p[1]) < 10 / view.scale) return { kind: "dest", id: d.id };
  }
  for (const g of venue.thresholds) {
    const a = venue.zones.find((z) => z.id === g.from_zone), b = venue.zones.find((z) => z.id === g.to_zone);
    if ((a?.level === level || b?.level === level) && segDist(p, g.segment[0], g.segment[1]) < tol) return { kind: "gate", id: g.id };
  }
  const z = zoneAtPoint(p, level);
  return z ? { kind: "zone", id: z.id } : null;
}

// ---------------------------------------------------------------- edit operations
function addZone(poly: Pt[]): void {
  if (poly.length < 3 || polygonArea(poly) < 1) { say("A zone needs at least three corners and some area."); return; }
  const n = venue.zones.length + 1;
  const id = uid("zone", venue.zones.map((z) => z.id));
  venue.zones.push({ id, name: `Zone ${n}`, level, kind: "open_area", polygon: poly.map((p) => [p[0], p[1]] as Pt) });
  sel = { kind: "zone", id };
  say(null);
  commit();
}
function addGate(a: Pt, b: Pt): void {
  const len = Math.hypot(b[0] - a[0], b[1] - a[1]);
  if (len < 0.5) return;
  const m: Pt = [(a[0] + b[0]) / 2, (a[1] + b[1]) / 2];
  const nx = -(b[1] - a[1]) / len, ny = (b[0] - a[0]) / len, off = 0.6;
  const z1 = zoneAtPoint([m[0] + nx * off, m[1] + ny * off], level);
  const z2 = zoneAtPoint([m[0] - nx * off, m[1] - ny * off], level);
  if (!z1 || !z2 || z1.id === z2.id) { say("A gate has to sit on the shared edge of two different zones. Draw it along that edge."); return; }
  const id = uid("gate", venue.thresholds.map((t) => t.id));
  venue.thresholds.push({ id, name: `Gate ${venue.thresholds.length + 1}`, kind: "opening", from_zone: z1.id, to_zone: z2.id, segment: [a, b], width_m: r1(len) });
  sel = { kind: "gate", id };
  say(null);
  commit();
}
function addDest(p: Pt): void {
  const z = zoneAtPoint(p, level);
  if (!z) { say("Click inside a zone to place it."); return; }
  const kind = ($("destKind") as HTMLSelectElement).value;
  const id = uid(kind, venue.destinations.map((d) => d.id));
  venue.destinations.push({ id, name: `${kind.replace("_", " ")} ${venue.destinations.length + 1}`, kind, zone: z.id, at: p, ...(kind === "exit" || kind === "assembly_point" ? { safe: true } : {}) });
  sel = { kind: "dest", id };
  say(null);
  commit();
}
function remove(s: NonNullable<Sel>): void {
  if (s.kind === "zone") {
    venue.zones = venue.zones.filter((z) => z.id !== s.id);
    venue.thresholds = venue.thresholds.filter((t) => t.from_zone !== s.id && t.to_zone !== s.id);
    venue.destinations = venue.destinations.filter((d) => d.zone !== s.id);
    venue.pathways = (venue.pathways ?? []).filter((p) => !p.zones.includes(s.id));
    const gone = new Set(venue.thresholds.map((t) => t.id));
    venue.sensor_sites = (venue.sensor_sites ?? []).filter((x) => (!x.covers || x.covers.every((c) => c.kind !== "zone" || c.id !== s.id)) && (!x.threshold || gone.has(x.threshold)));
  } else if (s.kind === "gate") {
    venue.thresholds = venue.thresholds.filter((t) => t.id !== s.id);
    venue.sensor_sites = (venue.sensor_sites ?? []).filter((x) => x.threshold !== s.id);
  } else venue.destinations = venue.destinations.filter((d) => d.id !== s.id);
  sel = null;
  commit();
}
function retarget(g: Gate): void {
  const a = g.segment[0], b = g.segment[1], len = Math.hypot(b[0] - a[0], b[1] - a[1]) || 1;
  const m: Pt = [(a[0] + b[0]) / 2, (a[1] + b[1]) / 2], nx = -(b[1] - a[1]) / len, ny = (b[0] - a[0]) / len;
  const z1 = zoneAtPoint([m[0] + nx * 0.6, m[1] + ny * 0.6]), z2 = zoneAtPoint([m[0] - nx * 0.6, m[1] - ny * 0.6]);
  if (z1 && z2 && z1.id !== z2.id) { g.from_zone = z1.id; g.to_zone = z2.id; }
}

// ---------------------------------------------------------------- drawing
function fitView(): void {
  const w = cv.clientWidth, h = cv.clientHeight;
  if (!venue.zones.length) { view = { scale: Math.min(w / 140, h / 90), ox: 20, oy: 20 }; return; }
  const b = bounds({ zones: venue.zones } as never);
  const pad = 40, bw = Math.max(b.maxX - b.minX, 1), bh = Math.max(b.maxY - b.minY, 1);
  const s = Math.min((w - 2 * pad) / bw, (h - 2 * pad) / bh);
  view = { scale: s, ox: pad - b.minX * s + (w - 2 * pad - bw * s) / 2, oy: pad - b.minY * s + (h - 2 * pad - bh * s) / 2 };
}
function css(n: string): string { return getComputedStyle(document.documentElement).getPropertyValue(n).trim(); }

function draw(): void {
  const w = cv.clientWidth, h = cv.clientHeight, dpr = devicePixelRatio || 1;
  if (cv.width !== Math.round(w * dpr) || cv.height !== Math.round(h * dpr)) { cv.width = Math.round(w * dpr); cv.height = Math.round(h * dpr); }
  const ctx = cv.getContext("2d")!;
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  ctx.fillStyle = css("--map-bg"); ctx.fillRect(0, 0, w, h);
  // grid
  const step = view.scale * 10 < 24 ? 50 : 10;
  const [x0, y1] = toWorld(0, 0), [x1, y0] = toWorld(w, h);
  ctx.lineWidth = 1;
  for (let x = Math.floor(x0 / step) * step; x <= x1; x += step) {
    const sx = toScreen([x, 0])[0];
    ctx.strokeStyle = x % (step * 5) === 0 ? css("--line") : `color-mix(in srgb, ${css("--line")} 40%, transparent)`;
    ctx.beginPath(); ctx.moveTo(sx, 0); ctx.lineTo(sx, h); ctx.stroke();
  }
  for (let y = Math.floor(y0 / step) * step; y <= y1; y += step) {
    const sy = toScreen([0, y])[1];
    ctx.strokeStyle = y % (step * 5) === 0 ? css("--line") : `color-mix(in srgb, ${css("--line")} 40%, transparent)`;
    ctx.beginPath(); ctx.moveTo(0, sy); ctx.lineTo(w, sy); ctx.stroke();
  }
  const d = dark();
  const path = (poly: Pt[]) => { ctx.beginPath(); poly.forEach((p, i) => { const [x, y] = toScreen(p); if (i) ctx.lineTo(x, y); else ctx.moveTo(x, y); }); ctx.closePath(); };
  // zones: other levels faint
  for (const z of [...venue.zones].sort((a, b) => Number(a.level === level) - Number(b.level === level))) {
    const here = z.level === level;
    path(z.polygon);
    ctx.fillStyle = `hsla(${HUE[z.kind] ?? 200}, ${d ? 35 : 55}%, ${d ? 28 : 82}%, ${here ? 0.85 : 0.18})`;
    ctx.fill();
    ctx.strokeStyle = sel?.kind === "zone" && sel.id === z.id ? css("--accent") : css("--line");
    ctx.lineWidth = sel?.kind === "zone" && sel.id === z.id ? 3 : 1.5;
    ctx.stroke();
    if (here) {
      const [cx, cy] = toScreen(centroid(z.polygon));
      ctx.fillStyle = css("--text"); ctx.font = "600 12px system-ui, sans-serif"; ctx.textAlign = "center"; ctx.textBaseline = "middle";
      ctx.fillText(z.name ?? z.id, cx, cy);
      ctx.font = "11px system-ui, sans-serif"; ctx.fillStyle = css("--muted");
      ctx.fillText(`${Math.round(polygonArea(z.polygon)).toLocaleString()} m²`, cx, cy + 14);
    }
  }
  // vertex handles for selected zone
  if (sel?.kind === "zone") {
    const z = venue.zones.find((q) => q.id === sel!.id);
    z?.polygon.forEach((p) => { const [x, y] = toScreen(p); ctx.fillStyle = "#fff"; ctx.strokeStyle = css("--accent"); ctx.lineWidth = 2; ctx.beginPath(); ctx.arc(x, y, 5, 0, 7); ctx.fill(); ctx.stroke(); });
  }
  // gates
  for (const g of venue.thresholds) {
    const a = venue.zones.find((z) => z.id === g.from_zone), b = venue.zones.find((z) => z.id === g.to_zone);
    if (a?.level !== level && b?.level !== level) continue;
    const [p, q] = g.segment.map(toScreen);
    const on = sel?.kind === "gate" && sel.id === g.id;
    ctx.strokeStyle = on ? css("--accent") : g.kind === "stairs" || g.kind === "ramp" ? "#8a5cd0" : css("--queue");
    ctx.lineWidth = Math.max(4, Math.min(12, g.width_m * view.scale * 0.3)); ctx.lineCap = "round";
    ctx.beginPath(); ctx.moveTo(p[0], p[1]); ctx.lineTo(q[0], q[1]); ctx.stroke();
    if (on) for (const e of [p, q]) { ctx.fillStyle = "#fff"; ctx.strokeStyle = css("--accent"); ctx.lineWidth = 2; ctx.beginPath(); ctx.arc(e[0], e[1], 5, 0, 7); ctx.fill(); ctx.stroke(); }
  }
  // destinations
  for (const dd of venue.destinations) {
    const pos = destPos(dd), z = venue.zones.find((q) => q.id === dd.zone);
    if (!pos || z?.level !== level) continue;
    const [x, y] = toScreen(pos), on = sel?.kind === "dest" && sel.id === dd.id;
    ctx.fillStyle = dd.safe ? "#2e8b57" : css("--accent"); ctx.strokeStyle = on ? css("--text") : "#fff"; ctx.lineWidth = on ? 3 : 2;
    ctx.beginPath(); ctx.arc(x, y, 9, 0, 7); ctx.fill(); ctx.stroke();
    ctx.fillStyle = "#fff"; ctx.font = "700 10px system-ui, sans-serif"; ctx.textAlign = "center"; ctx.textBaseline = "middle";
    ctx.fillText(dd.kind[0].toUpperCase(), x, y);
  }
  // in-progress shapes
  ctx.strokeStyle = css("--accent"); ctx.lineWidth = 2; ctx.setLineDash([6, 4]);
  if (draft.length) {
    ctx.beginPath(); draft.forEach((p, i) => { const [x, y] = toScreen(p); if (i) ctx.lineTo(x, y); else ctx.moveTo(x, y); });
    if (rubber) { const [x, y] = toScreen(rubber); ctx.lineTo(x, y); }
    ctx.stroke();
    draft.forEach((p) => { const [x, y] = toScreen(p); ctx.fillStyle = css("--accent"); ctx.beginPath(); ctx.arc(x, y, 4, 0, 7); ctx.fill(); });
  }
  if (drag?.mode === "rect" && drag.to) {
    const a = toScreen(drag.start), b = toScreen(drag.to);
    ctx.strokeRect(Math.min(a[0], b[0]), Math.min(a[1], b[1]), Math.abs(a[0] - b[0]), Math.abs(a[1] - b[1]));
  }
  if (drag?.mode === "gate" && drag.to) {
    const a = toScreen(drag.start), b = toScreen(drag.to);
    ctx.beginPath(); ctx.moveTo(a[0], a[1]); ctx.lineTo(b[0], b[1]); ctx.stroke();
  }
  ctx.setLineDash([]);
  requestAnimationFrame(draw);
}

// ---------------------------------------------------------------- pointer
function pos(e: PointerEvent | MouseEvent): [number, number] {
  const r = cv.getBoundingClientRect();
  return [e.clientX - r.left, e.clientY - r.top];
}
cv.addEventListener("pointerdown", (e) => {
  cv.focus();
  cv.setPointerCapture(e.pointerId);
  const [sx, sy] = pos(e);
  const w = snapPt(sx, sy);
  if (e.button === 1 || e.button === 2 || (e.button === 0 && e.shiftKey && tool === "select")) { drag = { mode: "pan", start: w, px: [sx, sy] }; return; }
  if (tool === "rect") { drag = { mode: "rect", start: w, px: [sx, sy], to: w }; return; }
  if (tool === "gate") { drag = { mode: "gate", start: w, px: [sx, sy], to: w }; return; }
  if (tool === "poly") {
    if (draft.length >= 3) {
      const [fx, fy] = toScreen(draft[0]);
      if (Math.hypot(fx - sx, fy - sy) < 10) { addZone(draft); draft = []; rubber = null; return; }
    }
    draft.push(w);
    return;
  }
  if (tool === "dest") { addDest(snapPt(sx, sy, false)); return; }
  const h = hit(sx, sy);
  if (tool === "del") { if (h) remove(h); return; }
  // select tool: handles first
  if (sel?.kind === "zone") {
    const z = venue.zones.find((q) => q.id === sel!.id)!;
    const i = z.polygon.findIndex((p) => { const [x, y] = toScreen(p); return Math.hypot(x - sx, y - sy) < 9; });
    if (i >= 0) { drag = { mode: "vertex", start: w, px: [sx, sy], idx: i, orig: JSON.stringify(venue) }; return; }
  }
  if (sel?.kind === "gate") {
    const g = venue.thresholds.find((q) => q.id === sel!.id)!;
    const i = g.segment.findIndex((p) => { const [x, y] = toScreen(p); return Math.hypot(x - sx, y - sy) < 9; });
    if (i >= 0) { drag = { mode: "end", start: w, px: [sx, sy], idx: i, orig: JSON.stringify(venue) }; return; }
  }
  sel = h;
  refreshPanel();
  if (h?.kind === "zone") drag = { mode: "zone", start: toWorld(sx, sy), px: [sx, sy], orig: JSON.stringify(venue) };
  else if (h?.kind === "dest") drag = { mode: "dest", start: w, px: [sx, sy], orig: JSON.stringify(venue) };
  else drag = { mode: "pan", start: w, px: [sx, sy] };
});
cv.addEventListener("pointermove", (e) => {
  const [sx, sy] = pos(e);
  const w = snapPt(sx, sy);
  $("coord").textContent = `${w[0].toFixed(1)}, ${w[1].toFixed(1)} m`;
  if (tool === "poly" && draft.length) rubber = w;
  if (!drag) return;
  if (drag.mode === "pan") { view.ox += sx - drag.px[0]; view.oy -= sy - drag.px[1]; drag.px = [sx, sy]; return; }
  if (drag.mode === "rect" || drag.mode === "gate") { drag.to = w; return; }
  if (drag.mode === "vertex" && sel?.kind === "zone") venue.zones.find((z) => z.id === sel!.id)!.polygon[drag.idx!] = w;
  else if (drag.mode === "end" && sel?.kind === "gate") {
    const g = venue.thresholds.find((t) => t.id === sel!.id)!;
    g.segment[drag.idx!] = w;
    g.width_m = r1(Math.hypot(g.segment[1][0] - g.segment[0][0], g.segment[1][1] - g.segment[0][1]));
  } else if (drag.mode === "zone" && sel?.kind === "zone") {
    const cur = toWorld(sx, sy), dx = r1(cur[0] - drag.start[0]), dy = r1(cur[1] - drag.start[1]);
    const orig = JSON.parse(drag.orig as string) as Venue;
    const zo = orig.zones.find((z) => z.id === sel!.id)!;
    venue.zones.find((z) => z.id === sel!.id)!.polygon = zo.polygon.map((p) => [r1(p[0] + dx), r1(p[1] + dy)] as Pt);
  } else if (drag.mode === "dest" && sel?.kind === "dest") {
    const d = venue.destinations.find((q) => q.id === sel!.id)!;
    d.at = w;
    const z = zoneAtPoint(w, level);
    if (z) d.zone = z.id;
  }
});
cv.addEventListener("pointerup", () => {
  if (!drag) return;
  const d = drag;
  drag = null;
  if (d.mode === "rect" && d.to) {
    const [a, b] = [d.start, d.to];
    addZone([[a[0], a[1]], [b[0], a[1]], [b[0], b[1]], [a[0], b[1]]] as Pt[]);
  } else if (d.mode === "gate" && d.to) addGate(d.start, d.to);
  else if (d.mode === "end" && sel?.kind === "gate") { retarget(venue.thresholds.find((t) => t.id === sel!.id)!); commit(); }
  else if (d.mode === "vertex" || d.mode === "zone" || d.mode === "dest") {
    if (JSON.stringify(venue) !== d.orig) { undo.push(d.orig as string); redo.length = 0; errors = null; refreshPanel(); }
  }
});
cv.addEventListener("dblclick", () => { if (tool === "poly" && draft.length >= 3) { addZone(draft); draft = []; rubber = null; } });
cv.addEventListener("contextmenu", (e) => e.preventDefault());
cv.addEventListener("wheel", (e) => {
  e.preventDefault();
  const [sx, sy] = pos(e), before = toWorld(sx, sy), f = Math.exp(-e.deltaY * 0.0015);
  view.scale = Math.max(0.5, Math.min(80, view.scale * f));
  view.ox = sx - before[0] * view.scale;
  view.oy = cv.clientHeight - sy - before[1] * view.scale;
}, { passive: false });
cv.addEventListener("keydown", (e) => {
  const k = e.key;
  if (k === "Enter" && tool === "poly" && draft.length >= 3) { addZone(draft); draft = []; rubber = null; }
  else if (k === "Escape") { draft = []; rubber = null; sel = null; refreshPanel(); }
  else if ((k === "Delete" || k === "Backspace") && sel) remove(sel);
  else if ((e.ctrlKey || e.metaKey) && k.toLowerCase() === "z") { e.preventDefault(); restore(undo, redo); }
  else if ((e.ctrlKey || e.metaKey) && k.toLowerCase() === "y") { e.preventDefault(); restore(redo, undo); }
  else if (!e.ctrlKey && !e.metaKey) {
    const t = ({ v: "select", r: "rect", p: "poly", g: "gate", d: "dest", x: "del" } as Record<string, Tool>)[k.toLowerCase()];
    if (t) setTool(t);
  }
});

function setTool(t: Tool): void {
  tool = t; draft = []; rubber = null;
  document.querySelectorAll<HTMLElement>("#tools button").forEach((b) => b.classList.toggle("on", b.dataset.tool === t));
  cv.style.cursor = t === "select" ? "default" : "crosshair";
}

// ---------------------------------------------------------------- panel
function opt(list: string[], cur: string): string { return list.map((o) => `<option ${o === cur ? "selected" : ""}>${esc(o)}</option>`).join(""); }

function refreshPanel(): void {
  const p = $("panel");
  let html = `<div class="card"><h3>Venue</h3>
    <label>Name<input type="text" data-v="name" value="${esc(venue.name ?? "")}"></label>
    <label>Id (lowercase letters, digits, - _)<input type="text" data-v="id" value="${esc(venue.id)}"></label>
    <h4>Levels</h4>
    ${venue.levels.map((l, i) => `<div class="levelrow"><input type="text" data-l="${i}:name" value="${esc(l.name ?? l.id)}"><input type="number" data-l="${i}:elev" value="${l.elevation_m}" title="elevation in metres"></div>`).join("")}
    <button id="addLevel" class="btn alt small" type="button">Add level</button>
    <p class="muted small">${venue.zones.length} zones, ${venue.thresholds.length} gates, ${venue.destinations.length} places</p></div>`;
  if (sel?.kind === "zone") {
    const z = venue.zones.find((q) => q.id === sel!.id);
    if (z) html += `<div class="card"><h3>Zone</h3>
      <label>Name<input type="text" data-z="name" value="${esc(z.name ?? "")}"></label>
      <label>Kind<select data-z="kind">${opt(ZONE_KINDS, z.kind)}</select></label>
      <label>Level<select data-z="level">${venue.levels.map((l) => `<option value="${esc(l.id)}" ${l.id === z.level ? "selected" : ""}>${esc(l.name ?? l.id)}</option>`).join("")}</select></label>
      <label>Max density (people per m², optional)<input type="number" step="0.1" min="0.1" data-z="dens" value="${z.capacity?.max_density_pp_m2 ?? ""}"></label>
      <label class="inline"><input type="checkbox" data-z="sf" ${z.step_free === false ? "" : "checked"}> Step free</label>
      <p class="muted small">${Math.round(polygonArea(z.polygon)).toLocaleString()} m² · id ${esc(z.id)}</p></div>`;
  } else if (sel?.kind === "gate") {
    const g = venue.thresholds.find((q) => q.id === sel!.id);
    if (g) html += `<div class="card"><h3>Gate</h3>
      <label>Name<input type="text" data-g="name" value="${esc(g.name ?? "")}"></label>
      <label>Kind<select data-g="kind">${opt(GATE_KINDS, g.kind)}</select></label>
      <label>Width (m)<input type="number" step="0.5" min="0.5" data-g="width" value="${g.width_m}"></label>
      <label class="inline"><input type="checkbox" data-g="one" ${g.one_way ? "checked" : ""}> One way (from → to)</label>
      <label class="inline"><input type="checkbox" data-g="closable" ${g.closable === false ? "" : "checked"}> Can be closed</label>
      <label class="inline"><input type="checkbox" data-g="sf" ${g.step_free === false ? "" : "checked"}> Step free</label>
      <p class="muted small">${esc(zn(g.from_zone))} → ${esc(zn(g.to_zone))} <button id="swap" class="btn alt small" type="button">Swap</button></p></div>`;
  } else if (sel?.kind === "dest") {
    const d = venue.destinations.find((q) => q.id === sel!.id);
    if (d) html += `<div class="card"><h3>Place</h3>
      <label>Name<input type="text" data-d="name" value="${esc(d.name ?? "")}"></label>
      <label>Kind<select data-d="kind">${opt(DEST_KINDS, d.kind)}</select></label>
      <label class="inline"><input type="checkbox" data-d="safe" ${d.safe ? "checked" : ""}> Safe place (evacuation target)</label>
      <p class="muted small">In ${esc(zn(d.zone))}</p></div>`;
  }
  html += `<div class="card"><h3>Check</h3>${errors === null ? `<p class="muted small">Press Check to validate the venue.</p>` : errors.length ? `<ul class="errs">${errors.map((x) => `<li>${esc(x)}</li>`).join("")}</ul>` : `<p class="ok">Valid. Ready to save.</p>`}</div>
    <div class="card key"><h3>Drawing</h3><p>Rectangle or Polygon to draw zones, then Gate: drag along the edge two zones share. Place adds exits, food, toilets and so on. Scroll to zoom, right-drag to pan, Ctrl+Z to undo.</p></div>`;
  p.innerHTML = html;
}
const zn = (id: string) => venue.zones.find((z) => z.id === id)?.name ?? id;

$("panel").addEventListener("change", (e) => {
  const t = e.target as HTMLInputElement;
  const ds = t.dataset;
  const val = t.type === "checkbox" ? t.checked : t.value;
  if (ds.v === "name") venue.name = String(val);
  else if (ds.v === "id") venue.id = String(val).trim();
  else if (ds.l) {
    const [i, f] = ds.l.split(":"); const l = venue.levels[Number(i)];
    if (f === "name") l.name = String(val); else l.elevation_m = Number(val) || 0;
  } else if (ds.z && sel?.kind === "zone") {
    const z = venue.zones.find((q) => q.id === sel!.id)!;
    if (ds.z === "name") z.name = String(val);
    else if (ds.z === "kind") z.kind = String(val);
    else if (ds.z === "level") z.level = String(val);
    else if (ds.z === "sf") z.step_free = Boolean(val);
    else if (ds.z === "dens") { const n = Number(val); if (val === "" || !(n > 0)) delete z.capacity; else z.capacity = { max_density_pp_m2: n }; }
  } else if (ds.g && sel?.kind === "gate") {
    const g = venue.thresholds.find((q) => q.id === sel!.id)!;
    if (ds.g === "name") g.name = String(val);
    else if (ds.g === "kind") g.kind = String(val);
    else if (ds.g === "width") g.width_m = Math.max(0.5, Number(val) || g.width_m);
    else if (ds.g === "one") g.one_way = Boolean(val);
    else if (ds.g === "closable") g.closable = Boolean(val);
    else if (ds.g === "sf") g.step_free = Boolean(val);
  } else if (ds.d && sel?.kind === "dest") {
    const d = venue.destinations.find((q) => q.id === sel!.id)!;
    if (ds.d === "name") d.name = String(val);
    else if (ds.d === "kind") d.kind = String(val);
    else if (ds.d === "safe") d.safe = Boolean(val);
  }
  fixLevel();
  commit();
});
$("panel").addEventListener("click", (e) => {
  const id = (e.target as HTMLElement).id;
  if (id === "addLevel") {
    const n = venue.levels.length;
    venue.levels.push({ id: uid("level", venue.levels.map((l) => l.id)), name: `Level ${n + 1}`, elevation_m: n * 4 });
    fixLevel(); commit();
  } else if (id === "swap" && sel?.kind === "gate") {
    const g = venue.thresholds.find((q) => q.id === sel!.id)!;
    [g.from_zone, g.to_zone] = [g.to_zone, g.from_zone];
    commit();
  }
});

// ---------------------------------------------------------------- toolbar and server
function download(name: string, text: string): void {
  const a = document.createElement("a");
  a.href = URL.createObjectURL(new Blob([text], { type: "application/json" }));
  a.download = name; a.click();
  setTimeout(() => URL.revokeObjectURL(a.href), 1000);
}
function clean(): Venue {
  // the schema does not know the editor's helper field "at" for a destination's exact spot, so drop it
  const v = JSON.parse(JSON.stringify(venue)) as Venue;
  v.destinations.forEach((d) => { delete d.at; });
  if (!v.pathways?.length) delete v.pathways;
  if (!v.sensor_sites?.length) delete v.sensor_sites;
  return v;
}
async function check(): Promise<boolean> {
  try {
    const r = await api<{ errors: string[] }>("/api/venues/validate", clean());
    errors = r.errors; refreshPanel();
    return r.errors.length === 0;
  } catch (e) { say(`Could not check: ${(e as Error).message}`); return false; }
}
async function save(): Promise<boolean> {
  try {
    await api("/api/venues", clean());
    errors = []; refreshPanel();
    say(`Saved as "${venue.id}". It now appears in the control room's venue list.`, false);
    await fillOpen();
    return true;
  } catch (e) {
    errors = (e as Error).message.split("; "); refreshPanel();
    say("Not saved: fix the problems listed on the right.");
    return false;
  }
}
async function fillOpen(): Promise<void> {
  try {
    const vs = await api<{ id: string; name: string; source: string }[]>("/api/venues");
    $("open").innerHTML = `<option value="">Open venue…</option>` + vs.map((v) => `<option value="${esc(v.id)}">${esc(v.name)} (${v.source})</option>`).join("");
  } catch { /* server not running: editor still works offline */ }
}
function load(v: Venue, name?: string): void {
  v.units ??= "metres";
  v.destinations ??= []; v.thresholds ??= []; v.zones ??= [];
  venue = v; sel = null; draft = []; undo.length = 0; redo.length = 0; errors = null;
  level = v.levels?.[0]?.id ?? "ground";
  if (!v.levels?.length) v.levels = [{ id: "ground", name: "Ground", elevation_m: 0 }];
  fixLevel(); fitView(); refreshPanel();
  if (name) say(`Opened ${name}.`, false);
}

$("tools").addEventListener("click", (e) => { const b = (e.target as HTMLElement).closest("button"); if (b) setTool(b.dataset.tool as Tool); });
$("destKind").innerHTML = DEST_KINDS.map((k) => `<option>${k}</option>`).join("");
($("snap") as HTMLInputElement).onchange = (e) => { snap = (e.target as HTMLInputElement).checked; };
$("level").onchange = (e) => { level = (e.target as HTMLSelectElement).value; sel = null; refreshPanel(); };
$("undo").onclick = () => restore(undo, redo);
$("redo").onclick = () => restore(redo, undo);
$("export").onclick = () => download(`${venue.id}.json`, JSON.stringify(clean(), null, 2));
$("validate").onclick = () => void check().then((ok) => say(ok ? "The venue is valid." : "There are problems, listed on the right.", ok));
$("save").onclick = () => void save();
$("try").onclick = async () => {
  if (!(await save())) return;
  try {
    await api("/api/session", { venue: venue.id, scenario: "auto-egress", planner: "adaptive", total: 3000, speed: 10 });
    location.href = "/live.html";
  } catch (e) { say(`Saved, but could not start a session: ${(e as Error).message}`); }
};
($("open") as HTMLSelectElement).onchange = async (e) => {
  const id = (e.target as HTMLSelectElement).value;
  if (!id) return;
  try { load(await api<Venue>(`/api/venues/${encodeURIComponent(id)}`), id); } catch (err) { say((err as Error).message); }
  (e.target as HTMLSelectElement).value = "";
};
($("import") as HTMLInputElement).onchange = async (e) => {
  const f = (e.target as HTMLInputElement).files?.[0];
  if (!f) return;
  try { load(JSON.parse(await f.text()) as Venue, f.name); } catch { say("That file is not valid JSON."); }
  (e.target as HTMLInputElement).value = "";
};
new ResizeObserver(() => { /* canvas resizes on next frame */ }).observe($("map"));
addEventListener("beforeunload", (e) => { if (undo.length) e.preventDefault(); });

fixLevel(); fitView(); refreshPanel(); void fillOpen(); requestAnimationFrame(draw);
