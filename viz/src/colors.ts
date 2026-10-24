/** Sequential scale for density relative to a zone's comfortable maximum (0 = empty, 1 = at limit). */
const STOPS_LIGHT = ["#eef2f4", "#f7e7a6", "#f4b05a", "#e0603f", "#9b1d4a"];
const STOPS_DARK = ["#1d2630", "#4d4a2c", "#8f5f26", "#c4472f", "#e0457b"];

function hexToRgb(h: string): [number, number, number] {
  return [parseInt(h.slice(1, 3), 16), parseInt(h.slice(3, 5), 16), parseInt(h.slice(5, 7), 16)];
}

export function densityColor(ratio: number, dark: boolean): string {
  const stops = dark ? STOPS_DARK : STOPS_LIGHT;
  // Square-root scaling so moderately busy zones are still visible next to empty ones.
  const r = Math.sqrt(Math.max(0, Math.min(1.25, ratio)) / 1.25) * (stops.length - 1);
  const i = Math.min(stops.length - 2, Math.floor(r)), f = r - i;
  const a = hexToRgb(stops[i]), b = hexToRgb(stops[i + 1]);
  const c = a.map((v, k) => Math.round(v + (b[k] - v) * f));
  return `rgb(${c[0]},${c[1]},${c[2]})`;
}
