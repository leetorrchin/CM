import type { RunLog } from "./types";
import { sum } from "./interp";

function css(name: string): string {
  return getComputedStyle(document.documentElement).getPropertyValue(name).trim();
}

/** Two lines over time (people still moving, people waiting in queues) with a cursor at t. */
export function drawChart(canvas: HTMLCanvasElement, run: RunLog, t: number, tMax: number, yMax: number): void {
  const dpr = window.devicePixelRatio || 1;
  const r = canvas.getBoundingClientRect();
  const w = r.width, h = r.height;
  if (canvas.width !== Math.round(w * dpr)) { canvas.width = Math.round(w * dpr); canvas.height = Math.round(h * dpr); }
  const ctx = canvas.getContext("2d")!;
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  ctx.clearRect(0, 0, w, h);
  const padL = 34, padR = 6, padT = 6, padB = 16;
  const X = (s: number) => padL + (s / tMax) * (w - padL - padR);
  const Y = (v: number) => h - padB - (v / yMax) * (h - padT - padB);
  ctx.strokeStyle = css("--line"); ctx.lineWidth = 1;
  ctx.beginPath(); ctx.moveTo(padL, h - padB); ctx.lineTo(w - padR, h - padB); ctx.moveTo(padL, padT); ctx.lineTo(padL, h - padB); ctx.stroke();
  ctx.fillStyle = css("--muted"); ctx.font = "10px system-ui, sans-serif";
  ctx.textAlign = "right"; ctx.textBaseline = "middle";
  ctx.fillText(Math.round(yMax).toLocaleString(), padL - 4, padT + 4);
  ctx.fillText("0", padL - 4, h - padB);
  ctx.textAlign = "center"; ctx.textBaseline = "top";
  ctx.fillText(`${Math.round(tMax)} s`, w - padR - 14, h - padB + 2);

  const series: [string, (s: RunLog["states"][number]) => number][] = [
    [css("--series-a"), (s) => s.active],
    [css("--series-b"), (s) => sum(s.queues)],
  ];
  for (const [color, f] of series) {
    ctx.strokeStyle = color; ctx.lineWidth = 1.75; ctx.beginPath();
    run.states.forEach((s, i) => { const x = X(s.t_s), y = Y(f(s)); if (i) ctx.lineTo(x, y); else ctx.moveTo(x, y); });
    ctx.stroke();
  }
  ctx.strokeStyle = css("--text"); ctx.lineWidth = 1;
  ctx.beginPath(); ctx.moveTo(X(t), padT); ctx.lineTo(X(t), h - padB); ctx.stroke();
}
