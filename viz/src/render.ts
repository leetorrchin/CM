import { bounds, centroid, polygonArea, pointInPolygon, Transform } from "./geom";
import { densityColor } from "./colors";
import { sampleAt } from "./interp";
import type { Pt, RunLog, Threshold, Venue, Zone, ZoneState } from "./types";

// Same placeholder as core/src/crowd_core/config.py DEFAULT_MAX_DENSITY_PP_M2.
const DEFAULT_MAX_DENSITY = 3.0;

export interface DrawOptions {
  level: string; labels: boolean; dark: boolean; wall: number;
  /** Drawn on top of the map, before the heading. */
  overlay?: (ctx: CanvasRenderingContext2D, view: RunView) => void;
  heading?: boolean;
  /** Show people counts in zones (default true). */
  numbers?: boolean;
}

interface ZoneInfo { z: Zone; area: number; cen: Pt; maxDensity: number }

function css(name: string): string {
  return getComputedStyle(document.documentElement).getPropertyValue(name).trim();
}

/** Shorten text with an ellipsis so it fits in `max` pixels. */
function fit(ctx: CanvasRenderingContext2D, s: string, max: number): string {
  if (ctx.measureText(s).width <= max) return s;
  while (s.length > 1 && ctx.measureText(s + "…").width > max) s = s.slice(0, -1);
  return s + "…";
}

export function parseEdgeKey(key: string): { tid: string; from: string; to: string } {
  const i = key.indexOf(":");
  const [from, to] = key.slice(i + 1).split("->");
  return { tid: key.slice(0, i), from, to };
}

export class RunView {
  info = new Map<string, ZoneInfo>();
  private elevation = new Map<string, number>();
  /** People in or walking through each zone at the last draw (waiting plus half of each crossing). */
  lastCounts: Record<string, number> = {};
  tr: Transform;
  private w = 0;
  private h = 0;

  constructor(public canvas: HTMLCanvasElement, public venue: Venue, public run: RunLog) {
    for (const z of venue.zones) {
      const area = polygonArea(z.polygon);
      const cap = z.capacity ?? {};
      const maxDensity = cap.max_density_pp_m2 ?? (cap.max_people ? cap.max_people / area : DEFAULT_MAX_DENSITY);
      this.info.set(z.id, { z, area, cen: centroid(z.polygon), maxDensity });
    }
    for (const l of venue.levels) this.elevation.set(l.id, l.elevation_m);
    this.tr = new Transform(bounds(venue), 1, 1);
    this.resize();
  }

  resize(): void {
    const r = this.canvas.getBoundingClientRect();
    const dpr = window.devicePixelRatio || 1;
    this.w = Math.max(200, r.width);
    this.h = Math.max(200, r.height);
    this.canvas.width = Math.round(this.w * dpr);
    this.canvas.height = Math.round(this.h * dpr);
    this.tr = new Transform(bounds(this.venue), this.w, this.h);
  }

  stateAt(t: number): ZoneState { return sampleAt(this.run.states, t); }

  private visible(z: Zone, level: string): boolean { return level === "all" || z.level === level; }

  zoneAt(px: number, py: number, level: string): Zone | undefined {
    const [x, y] = this.tr.toWorld(px, py);
    for (const { z } of this.info.values()) {
      if (this.visible(z, level) && pointInPolygon(x, y, z.polygon)) return z;
    }
    return undefined;
  }

  /** Nearest threshold within `max` pixels of a screen point. */
  thresholdAt(px: number, py: number, level: string, max = 14): Threshold | undefined {
    let best: Threshold | undefined, bd = max;
    for (const th of this.venue.thresholds) {
      const a = this.info.get(th.from_zone)?.z, b = this.info.get(th.to_zone)?.z;
      if (!a || !b || !(this.visible(a, level) && this.visible(b, level))) continue;
      const [p, q] = th.segment.map((pt) => this.tr.toScreen(pt[0], pt[1]));
      const dx = q[0] - p[0], dy = q[1] - p[1], l2 = dx * dx + dy * dy || 1;
      const f = Math.max(0, Math.min(1, ((px - p[0]) * dx + (py - p[1]) * dy) / l2));
      const d = Math.hypot(px - (p[0] + f * dx), py - (p[1] + f * dy));
      if (d < bd) { bd = d; best = th; }
    }
    return best;
  }

  draw(t: number, o: DrawOptions): void {
    const ctx = this.canvas.getContext("2d")!;
    const dpr = window.devicePixelRatio || 1;
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.fillStyle = css("--map-bg");
    ctx.fillRect(0, 0, this.w, this.h);
    const s = this.stateAt(t);
    // In this model people only count as "in a zone" while waiting, so also share those crossing a
    // threshold between the two zones it joins. Otherwise a moving crowd looks like an empty venue.
    const cnt: Record<string, number> = { ...s.zones };
    for (const [key, n] of Object.entries(s.transit)) {
      const { from, to } = parseEdgeKey(key);
      cnt[from] = (cnt[from] ?? 0) + n / 2;
      cnt[to] = (cnt[to] ?? 0) + n / 2;
    }
    this.lastCounts = cnt;
    const line = css("--line"), text = css("--text"), muted = css("--muted");

    // zones
    for (const { z, area, maxDensity } of this.info.values()) {
      if (!this.visible(z, o.level)) continue;
      const n = cnt[z.id] ?? 0;
      ctx.beginPath();
      z.polygon.forEach((p, i) => {
        const [x, y] = this.tr.toScreen(p[0], p[1]);
        if (i) ctx.lineTo(x, y); else ctx.moveTo(x, y);
      });
      ctx.closePath();
      ctx.fillStyle = densityColor(n / area / maxDensity, o.dark);
      ctx.fill();
      ctx.strokeStyle = line;
      ctx.lineWidth = 1.5;
      ctx.setLineDash((this.elevation.get(z.level) ?? 0) > 0 ? [5, 4] : []);
      ctx.stroke();
      ctx.setLineDash([]);
    }
    // zone labels
    ctx.textAlign = "center";
    ctx.textBaseline = "middle";
    for (const { z, cen } of this.info.values()) {
      if (!this.visible(z, o.level)) continue;
      const xs = z.polygon.map((p) => this.tr.toScreen(p[0], p[1])[0]);
      const wpx = Math.max(...xs) - Math.min(...xs);
      if (wpx < (o.labels ? 40 : 56)) continue;
      const [cx, cy] = this.tr.toScreen(cen[0], cen[1]);
      ctx.fillStyle = text;
      ctx.font = "600 12px system-ui, sans-serif";
      const n = Math.round(cnt[z.id] ?? 0);
      if (o.labels) {
        const name = fit(ctx, z.name ?? z.id, wpx - 10);
        ctx.fillText(name, cx, cy - 8);
        if (o.numbers !== false) {
          ctx.font = "12px system-ui, sans-serif";
          ctx.fillText(n.toLocaleString(), cx, cy + 8);
        }
      } else if (o.numbers !== false) {
        ctx.fillText(n.toLocaleString(), cx, cy);
      }
    }

    // thresholds
    const closed = new Set(s.closed);
    const mids = new Map<string, Pt>();
    for (const th of this.venue.thresholds) {
      const a = this.info.get(th.from_zone)!.z, b = this.info.get(th.to_zone)!.z;
      if (!(this.visible(a, o.level) && this.visible(b, o.level))) continue;
      const [p, q] = th.segment.map((pt) => this.tr.toScreen(pt[0], pt[1]));
      const isClosed = closed.has(th.id);
      ctx.strokeStyle = isClosed ? css("--bad") : muted;
      ctx.lineWidth = Math.max(3, Math.min(12, th.width_m * this.tr.scale * 0.6));
      ctx.lineCap = "round";
      ctx.beginPath(); ctx.moveTo(p[0], p[1]); ctx.lineTo(q[0], q[1]); ctx.stroke();
      const mid: Pt = [(p[0] + q[0]) / 2, (p[1] + q[1]) / 2];
      mids.set(th.id, mid);
      if (isClosed) {
        ctx.strokeStyle = css("--bad"); ctx.lineWidth = 3;
        ctx.beginPath();
        ctx.moveTo(mid[0] - 7, mid[1] - 7); ctx.lineTo(mid[0] + 7, mid[1] + 7);
        ctx.moveTo(mid[0] + 7, mid[1] - 7); ctx.lineTo(mid[0] - 7, mid[1] + 7);
        ctx.stroke();
      }
    }

    // people in transit: marching dashed lines through the threshold
    ctx.strokeStyle = css("--flow");
    for (const [key, n] of Object.entries(s.transit)) {
      const { tid, from, to } = parseEdgeKey(key);
      const mid = mids.get(tid), a = this.info.get(from), b = this.info.get(to);
      if (!mid || !a || !b || n < 1) continue;
      const pa = this.tr.toScreen(a.cen[0], a.cen[1]), pb = this.tr.toScreen(b.cen[0], b.cen[1]);
      ctx.globalAlpha = 0.6;
      ctx.lineWidth = Math.min(14, 1.5 + 0.3 * Math.sqrt(n));
      ctx.setLineDash([7, 7]);
      ctx.lineDashOffset = -o.wall * 28;
      ctx.beginPath(); ctx.moveTo(pa[0], pa[1]); ctx.lineTo(mid[0], mid[1]); ctx.lineTo(pb[0], pb[1]); ctx.stroke();
      ctx.setLineDash([]);
      ctx.globalAlpha = 1;
    }

    // queues: a bubble on the waiting side of the threshold
    for (const [key, n] of Object.entries(s.queues)) {
      const { tid, from } = parseEdgeKey(key);
      const mid = mids.get(tid), a = this.info.get(from);
      if (!mid || !a || n < 1) continue;
      const pa = this.tr.toScreen(a.cen[0], a.cen[1]);
      const dx = pa[0] - mid[0], dy = pa[1] - mid[1], d = Math.hypot(dx, dy) || 1;
      const r = Math.min(30, 7 + 1.4 * Math.sqrt(n));
      const cx = mid[0] + (dx / d) * (r + 6), cy = mid[1] + (dy / d) * (r + 6);
      ctx.fillStyle = css("--queue");
      ctx.globalAlpha = 0.88;
      ctx.beginPath(); ctx.arc(cx, cy, r, 0, Math.PI * 2); ctx.fill();
      ctx.globalAlpha = 1;
      ctx.fillStyle = css("--on-queue");
      ctx.font = "600 11px system-ui, sans-serif";
      ctx.fillText(Math.round(n).toLocaleString(), cx, cy);
    }

    o.overlay?.(ctx, this);
    if (o.heading === false) return;
    // heading
    ctx.textAlign = "left";
    ctx.textBaseline = "top";
    ctx.fillStyle = text;
    ctx.font = "600 13px system-ui, sans-serif";
    ctx.fillText(`${this.run.planner || this.run.runId}  ·  ${this.run.scenario}`, 12, 10);
    ctx.font = "12px system-ui, sans-serif";
    ctx.fillStyle = muted;
    ctx.fillText(`t = ${Math.round(t)} s  ·  mode: ${s.mode}`, 12, 28);
  }
}
