import { describe, expect, it } from "vitest";
import { detectKind, parseRun } from "./loader";
import { lerpMap, sampleAt } from "./interp";
import { centroid, pointInPolygon, polygonArea, Transform } from "./geom";
import { densityColor } from "./colors";
import { parseEdgeKey } from "./render";

const rec = (seq: number, type: string, data: object, ts = "2026-11-14T22:00:00.000+11:00") =>
  JSON.stringify({ schema_version: "0.1.0", run_id: "r", seq, timestamp: ts, type, data });
const state = (t: number, n: number) => ({ t_s: t, mode: "egress", zones: { a: n }, transit: {}, queues: { "t:a->b": n }, cleared: t, active: 100 - t, groups_split: 0, closed: [] });

describe("loader", () => {
  const log = [
    rec(0, "run_start", { venue: "v", scenario: "s", planner: "p" }),
    rec(1, "zone_state", state(0, 10)),
    rec(2, "closure", { threshold: "t", closed: true }, "2026-11-14T22:00:30.000+11:00"),
    rec(3, "zone_state", state(10, 20)),
    rec(4, "metric", { scope: "final", clearance_s: 12 }),
  ].join("\n");
  it("detects kinds", () => {
    expect(detectKind(log)).toBe("run");
    expect(detectKind('{"zones":[],"thresholds":[]}')).toBe("venue");
    expect(detectKind("hello")).toBe("unknown");
  });
  it("parses a run", () => {
    const r = parseRun(log);
    expect(r.states).toHaveLength(2);
    expect(r.duration).toBe(10);
    expect(r.events[0]).toMatchObject({ type: "closure", t_s: 30 });
    expect(r.metrics).toMatchObject({ clearance_s: 12 });
    expect(r.planner).toBe("p");
  });
  it("rejects a run with no states", () => {
    expect(() => parseRun(rec(0, "run_start", {}))).toThrow();
  });
});

describe("interp", () => {
  it("interpolates counts and steps mode", () => {
    const s = sampleAt([state(0, 10), state(10, 20)], 5);
    expect(s.zones.a).toBeCloseTo(15);
    expect(s.cleared).toBeCloseTo(5);
    expect(sampleAt([state(0, 10), state(10, 20)], 99).zones.a).toBe(20);
    expect(sampleAt([state(0, 10), state(10, 20)], -3).zones.a).toBe(10);
  });
  it("handles keys on one side only", () => {
    expect(lerpMap({ x: 10 }, {}, 0.5)).toEqual({ x: 5 });
    expect(lerpMap({}, { y: 4 }, 0.5)).toEqual({ y: 2 });
  });
});

describe("geometry", () => {
  const sq: [number, number][] = [[0, 0], [10, 0], [10, 10], [0, 10]];
  it("area, centroid, containment", () => {
    expect(polygonArea(sq)).toBe(100);
    expect(centroid(sq)).toEqual([5, 5]);
    expect(pointInPolygon(5, 5, sq)).toBe(true);
    expect(pointInPolygon(15, 5, sq)).toBe(false);
  });
  it("transform round-trips and flips y", () => {
    const t = new Transform({ minX: 0, minY: 0, maxX: 100, maxY: 50 }, 400, 300);
    const [px, py] = t.toScreen(20, 10);
    const [x, y] = t.toWorld(px, py);
    expect(x).toBeCloseTo(20); expect(y).toBeCloseTo(10);
    expect(t.toScreen(0, 50)[1]).toBeLessThan(t.toScreen(0, 0)[1]);
  });
});

describe("misc", () => {
  it("colours are valid and differ", () => {
    expect(densityColor(0, false)).toMatch(/^rgb\(/);
    expect(densityColor(0, false)).not.toBe(densityColor(1, false));
    expect(densityColor(9, true)).toBe(densityColor(1.25, true));
    expect(densityColor(0.2, false)).not.toBe(densityColor(0, false));
  });
  it("parses edge keys", () => {
    expect(parseEdgeKey("t_field_exit:main_field->lane")).toEqual({ tid: "t_field_exit", from: "main_field", to: "lane" });
  });
});
