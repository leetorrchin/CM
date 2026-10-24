import type { Venue, ZoneState } from "./types";

const TOKEN_KEY = "crowd.token";
export const getToken = (): string => { try { return localStorage.getItem(TOKEN_KEY) ?? ""; } catch { return ""; } };
export const setToken = (t: string): void => { try { t ? localStorage.setItem(TOKEN_KEY, t) : localStorage.removeItem(TOKEN_KEY); } catch { /* storage blocked */ } };

/** Send the person to the login page, coming back here afterwards. */
export function toLogin(): void {
  setToken("");
  if (location.pathname.endsWith("/login.html")) return;
  location.href = `/login.html?next=${encodeURIComponent(location.pathname + location.search)}`;
}
export function logout(): void { setToken(""); location.href = "/login.html"; }

export async function api<T = unknown>(path: string, body?: unknown, method?: string, extra?: Record<string, string>): Promise<T> {
  const headers: Record<string, string> = { ...(extra ?? {}) };
  if (body !== undefined) headers["Content-Type"] = "application/json";
  const tok = getToken();
  if (tok && !headers.Authorization) headers.Authorization = `Bearer ${tok}`;
  const r = await fetch(path, {
    method: method ?? (body === undefined ? "GET" : "POST"),
    headers,
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  if (r.status === 401 && !path.startsWith("/api/join/") && path !== "/api/login") { toLogin(); throw new Error("Login required"); }
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

export interface SessionInfo {
  id: string; name: string; venue: string; scenario: string; planner: string; speed: number; paused: boolean;
  people: number; mode: string; t_s: number; active: number; cleared: number; guests: number;
  demo_people: boolean; recording: boolean;
}

export interface LiveMsg extends ZoneState {
  type: "state"; id?: string; name?: string; guests?: number; demo_people?: boolean; recording?: boolean;
  planner: string; speed: number; paused: boolean; people: number; scenario: string; venue: string;
  queue_switches: number; redirected: number;
}

export interface Guidance {
  person_id: string; state: string; zone: string; mode: string; destination: string; group_size: number;
  following: boolean; t_s: number; closed: string[]; arrived?: boolean; error?: string;
  next_threshold?: string; next_zone?: string; queue_ahead?: number; waited_s?: number;
  crossing?: string; from_zone?: string; to_zone?: string;
}

export interface JoinInfo {
  id: string; name: string; venue: string; venue_name: string; mode: string; demo_people: boolean; has_anchor: boolean;
  zones: { id: string; name: string; kind: string; level: string }[];
  destinations: { id: string; name: string; kind: string }[];
}

/** WebSocket that reconnects on its own. */
export function socket(path: string, onMsg: (m: any) => void, onStatus?: (up: boolean) => void): () => void {
  let ws: WebSocket | null = null, stopped = false, timer: number | undefined;
  const open = () => {
    const proto = location.protocol === "https:" ? "wss" : "ws";
    const tok = getToken();
    const url = tok && !path.startsWith("/ws/join/") ? `${path}${path.includes("?") ? "&" : "?"}token=${encodeURIComponent(tok)}` : path;
    ws = new WebSocket(`${proto}://${location.host}${url}`);
    ws.onopen = () => onStatus?.(true);
    ws.onmessage = (e) => { try { onMsg(JSON.parse(e.data)); } catch { /* ignore bad frame */ } };
    ws.onclose = (e) => {
      onStatus?.(false);
      if (e.code === 4401) { toLogin(); return; }
      if (!stopped) timer = window.setTimeout(open, 1500);
    };
  };
  open();
  return () => { stopped = true; clearTimeout(timer); ws?.close(); };
}

export const getVenue = (id: string) => api<Venue>(`/api/venues/${encodeURIComponent(id)}`);
export const esc = (s: unknown) => String(s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]!);
export const mmss = (s: number) => `${Math.floor(s / 60)}:${String(Math.floor(s % 60)).padStart(2, "0")}`;
export const dark = () => matchMedia("(prefers-color-scheme: dark)").matches;
