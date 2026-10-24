import type { Pt, Venue } from "./types";

export interface Bounds { minX: number; minY: number; maxX: number; maxY: number }

export function bounds(v: Venue): Bounds {
  let minX = Infinity, minY = Infinity, maxX = -Infinity, maxY = -Infinity;
  for (const z of v.zones) for (const [x, y] of z.polygon) {
    minX = Math.min(minX, x); maxX = Math.max(maxX, x);
    minY = Math.min(minY, y); maxY = Math.max(maxY, y);
  }
  return { minX, minY, maxX, maxY };
}

export function polygonArea(p: Pt[]): number {
  let s = 0;
  for (let i = 0; i < p.length; i++) {
    const [x1, y1] = p[i], [x2, y2] = p[(i + 1) % p.length];
    s += x1 * y2 - x2 * y1;
  }
  return Math.abs(s) / 2;
}

export function centroid(p: Pt[]): Pt {
  let a = 0, cx = 0, cy = 0;
  for (let i = 0; i < p.length; i++) {
    const [x1, y1] = p[i], [x2, y2] = p[(i + 1) % p.length];
    const c = x1 * y2 - x2 * y1;
    a += c; cx += (x1 + x2) * c; cy += (y1 + y2) * c;
  }
  if (Math.abs(a) < 1e-12) return [p.reduce((s, q) => s + q[0], 0) / p.length, p.reduce((s, q) => s + q[1], 0) / p.length];
  return [cx / (3 * a), cy / (3 * a)];
}

export function pointInPolygon(x: number, y: number, p: Pt[]): boolean {
  let inside = false;
  for (let i = 0, j = p.length - 1; i < p.length; j = i++) {
    const [xi, yi] = p[i], [xj, yj] = p[j];
    if ((yi > y) !== (yj > y) && x < ((xj - xi) * (y - yi)) / (yj - yi) + xi) inside = !inside;
  }
  return inside;
}

export class Transform {
  scale: number; private ox: number; private oy: number;
  private h: number;
  constructor(b: Bounds, w: number, h: number, pad = 28) {
    this.h = h;
    const bw = Math.max(b.maxX - b.minX, 1), bh = Math.max(b.maxY - b.minY, 1);
    this.scale = Math.min((w - 2 * pad) / bw, (h - 2 * pad) / bh);
    this.ox = pad + (w - 2 * pad - bw * this.scale) / 2 - b.minX * this.scale;
    this.oy = pad + (h - 2 * pad - bh * this.scale) / 2 - b.minY * this.scale;
  }
  /** World metres (y north) to canvas pixels (y down). */
  toScreen(x: number, y: number): Pt { return [x * this.scale + this.ox, this.h - (y * this.scale + this.oy)]; }
  toWorld(px: number, py: number): Pt { return [(px - this.ox) / this.scale, (this.h - py - this.oy) / this.scale]; }
}
