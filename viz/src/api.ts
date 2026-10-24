import type { Venue, ZoneState } from "./types";

export async function api<T = unknown>(path: string, body?: unknown, method?: string): Promise<T> {
  const r = await fetch(path, {
    method: method ?? (body === undefined ? "GET" : "POST"),
    headers: body === undefined ? undefined : { "Content-Type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  if (!r.ok) {
    let msg = r.statusText;
    try {
      const j = await r.json();
      const d = j.detail;
      msg = typeof d === "string" ? d : d?.errors ? d.errors.join("; ") : JSON.stringify(d);
    } catch { /* keep status text */ }
    throw new Error(msg);
  }
  return r.json() as Promise<T>;
}

export interface LiveMsg extends ZoneState {
  type: "state";
  planner: string; speed: number; paused: boolean; people: number; scenario: string; venue: string;
  queue_switches: number; redirected: number;
}

export interface Guidance {
  person_id: string; state: string; zone: string; mode: string; destination: string; group_size: number;
  following: boolean; t_s: number; closed: string[]; arrived?: boolean; error?: string;
  next_threshold?: string; next_zone?: string; queue_ahead?: number; waited_s?: number;
  crossing?: string; from_zone?: string; to_zone?: string;
}

/** WebSocket that reconnects on its own. */
export function socket(path: string, onMsg: (m: any) => void, onStatus?: (up: boolean) => void): () => void {
  let ws: WebSocket | null = null, stopped = false, timer: number | undefined;
  const open = () => {
    const proto = location.protocol === "https:" ? "wss" : "ws";
    ws = new WebSocket(`${proto}://${location.host}${path}`);
    ws.onopen = () => onStatus?.(true);
    ws.onmessage = (e) => { try { onMsg(JSON.parse(e.data)); } catch { /* ignore bad frame */ } };
    ws.onclose = () => { onStatus?.(false); if (!stopped) timer = window.setTimeout(open, 1500); };
  };
  open();
  return () => { stopped = true; clearTimeout(timer); ws?.close(); };
}

export const getVenue = (id: string) => api<Venue>(`/api/venues/${encodeURIComponent(id)}`);
export const esc = (s: unknown) => String(s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]!);
export const mmss = (s: number) => `${Math.floor(s / 60)}:${String(Math.floor(s % 60)).padStart(2, "0")}`;
export const dark = () => matchMedia("(prefers-color-scheme: dark)").matches;
