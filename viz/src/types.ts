// Hand-written for now. Later these will be generated from ../schemas.
export type Pt = [number, number];

export interface Zone {
  id: string;
  name?: string;
  level: string;
  kind: string;
  polygon: Pt[];
  capacity?: { max_density_pp_m2?: number; max_people?: number };
}
export interface Threshold {
  id: string;
  name?: string;
  kind: string;
  from_zone: string;
  to_zone: string;
  segment: [Pt, Pt];
  width_m: number;
  one_way?: boolean;
}
export interface Venue {
  id: string;
  name?: string;
  levels: { id: string; name?: string; elevation_m: number }[];
  zones: Zone[];
  thresholds: Threshold[];
}

export type NumMap = Record<string, number>;
export interface ZoneState {
  t_s: number;
  mode: string;
  zones: NumMap;
  transit: NumMap;
  queues: NumMap;
  cleared: number;
  active: number;
  groups_split: number;
  closed: string[];
}
export interface RunEvent {
  t_s: number;
  type: string;
  data: Record<string, unknown>;
}
export interface RunLog {
  runId: string;
  venueId: string;
  planner: string;
  scenario: string;
  states: ZoneState[];
  events: RunEvent[];
  metrics: Record<string, unknown> | null;
  duration: number;
}
