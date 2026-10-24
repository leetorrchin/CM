import type { NumMap, ZoneState } from "./types";

export function lerpMap(a: NumMap, b: NumMap, f: number): NumMap {
  const out: NumMap = {};
  for (const k of new Set([...Object.keys(a), ...Object.keys(b)])) {
    const va = a[k] ?? 0;
    const v = va + ((b[k] ?? 0) - va) * f;
    if (v > 0.01) out[k] = v;
  }
  return out;
}

/** State at time t: counts are interpolated between samples, mode and closures step. */
export function sampleAt(states: ZoneState[], t: number): ZoneState {
  const first = states[0], last = states[states.length - 1];
  if (t <= first.t_s) return first;
  if (t >= last.t_s) return last;
  let lo = 0, hi = states.length - 1;
  while (hi - lo > 1) {
    const mid = (lo + hi) >> 1;
    if (states[mid].t_s <= t) lo = mid; else hi = mid;
  }
  const a = states[lo], b = states[hi];
  const f = (t - a.t_s) / (b.t_s - a.t_s);
  return {
    t_s: t, mode: a.mode, closed: a.closed,
    zones: lerpMap(a.zones, b.zones, f),
    transit: lerpMap(a.transit, b.transit, f),
    queues: lerpMap(a.queues, b.queues, f),
    cleared: a.cleared + (b.cleared - a.cleared) * f,
    active: a.active + (b.active - a.active) * f,
    groups_split: a.groups_split + (b.groups_split - a.groups_split) * f,
  };
}

export function topEntries(m: NumMap, n: number): [string, number][] {
  return Object.entries(m).sort((x, y) => y[1] - x[1]).slice(0, n);
}

export function sum(m: NumMap): number {
  let s = 0;
  for (const v of Object.values(m)) s += v;
  return s;
}
