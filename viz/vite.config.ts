import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { defineConfig, type Plugin } from "vite";

const repoRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const SHARED = ["venues", "runs", "scenarios"];

/** .json and .jsonl files under a folder, as paths relative to it (e.g. "generated/gen-7.json"). */
function listFiles(dir: string, prefix: string, depth = 0): string[] {
  if (!fs.existsSync(dir) || depth > 3) return [];
  const out: string[] = [];
  for (const e of fs.readdirSync(dir, { withFileTypes: true })) {
    if (e.isDirectory()) out.push(...listFiles(path.join(dir, e.name), `${prefix}${e.name}/`, depth + 1));
    else if (/\.(json|jsonl)$/.test(e.name)) out.push(prefix + e.name);
  }
  return out;
}

/** Dev only: serve the repo's venues/, runs/ and scenarios/ at /data so the viewer can load them. */
function crowdData(): Plugin {
  return {
    name: "crowd-data",
    configureServer(server) {
      server.middlewares.use("/data", (req: { url?: string }, res: any, next: () => void) => {
        const url = decodeURIComponent((req.url ?? "/").split("?")[0]);
        if (url === "/index.json") {
          const out: Record<string, string[]> = {};
          for (const d of SHARED) out[d] = listFiles(path.join(repoRoot, d), "").sort();
          res.setHeader("Content-Type", "application/json");
          res.end(JSON.stringify(out));
          return;
        }
        const rel = path.normalize(url).replace(/^[/\\]+/, "");
        const file = path.join(repoRoot, rel);
        const inside = path.relative(repoRoot, file);
        if (!SHARED.includes(rel.split(path.sep)[0]) || inside.startsWith("..") || path.isAbsolute(inside)) return next();
        if (!fs.existsSync(file) || fs.statSync(file).isDirectory()) {
          res.statusCode = 404;
          res.end("not found");
          return;
        }
        res.setHeader("Content-Type", "text/plain; charset=utf-8");
        fs.createReadStream(file).pipe(res);
      });
    },
  };
}

const pages = ["index", "viewer", "live", "app", "editor"];

export default defineConfig({
  plugins: [crowdData()],
  server: {
    port: 5173,
    // run `python -m crowd_server` next to `npm run dev` and the pages talk to it
    proxy: { "/api": "http://localhost:8000", "/ws": { target: "ws://localhost:8000", ws: true } },
  },
  build: {
    rollupOptions: {
      input: Object.fromEntries(pages.map((p) => [p, path.resolve(path.dirname(fileURLToPath(import.meta.url)), `${p}.html`)])),
    },
  },
});
