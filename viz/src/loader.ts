import type { RunEvent, RunLog, Venue, ZoneState } from "./types";

/** Is this text a venue file (one JSON object with zones) or a run log (JSON Lines)? */
export function detectKind(text: string): "venue" | "run" | "unknown" {
  const trimmed = text.trim();
  if (!trimmed) return "unknown";
  try {
    const obj = JSON.parse(trimmed);
    if (obj && Array.isArray(obj.zones) && Array.isArray(obj.thresholds)) return "venue";
    if (obj && typeof obj.seq === "number" && typeof obj.type === "string") return "run";
  } catch {
    /* multiple lines: fall through */
  }
  const first = trimmed.split("\n", 1)[0];
  try {
    const obj = JSON.parse(first);
    if (obj && typeof obj.seq === "number" && typeof obj.type === "string") return "run";
  } catch {
    /* not json */
  }
  return "unknown";
}

export function parseVenue(text: string): Venue {
  const v = JSON.parse(text);
  if (!Array.isArray(v.zones) || !Array.isArray(v.thresholds)) throw new Error("not a venue file");
  return v as Venue;
}

export function parseRun(text: string): RunLog {
  const states: ZoneState[] = [];
  const events: RunEvent[] = [];
  let t0: number | null = null;
  let runId = "run", planner = "", scenario = "", venueId = "";
  let metrics: Record<string, unknown> | null = null;
  let lastT = 0;
  const tOf = (iso: string) => (t0 === null ? 0 : (Date.parse(iso) - t0) / 1000);

  for (const line of text.split("\n")) {
    if (!line.trim()) continue;
    const rec = JSON.parse(line);
    const data = rec.data ?? {};
    if (rec.type === "run_start") {
      t0 = Date.parse(rec.timestamp);
      runId = rec.run_id;
      planner = String(data.planner ?? "");
      scenario = String(data.scenario ?? "");
      venueId = String(data.venue ?? "");
    } else if (rec.type === "zone_state") {
      const s: ZoneState = {
        t_s: data.t_s, mode: data.mode, zones: data.zones ?? {}, transit: data.transit ?? {},
        queues: data.queues ?? {}, cleared: data.cleared ?? 0, active: data.active ?? 0,
        groups_split: data.groups_split ?? 0, closed: data.closed ?? [],
      };
      states.push(s);
      lastT = Math.max(lastT, s.t_s);
    } else if (rec.type === "metric") {
      metrics = data;
    } else if (rec.type === "mode_change" || rec.type === "closure") {
      events.push({ t_s: tOf(rec.timestamp), type: rec.type, data });
    }
  }
  if (!states.length) throw new Error("run log has no zone_state records");
  return { runId, venueId, planner, scenario, states, events, metrics, duration: lastT };
}
