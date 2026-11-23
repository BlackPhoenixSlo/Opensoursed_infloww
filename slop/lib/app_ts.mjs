// The app's own TypeScript in node, for checks that rest on client logic in a run
// without a browser (lib/app_ts.py). Loads app modules through vite's SSR loader (the
// app's `@/` alias, TypeScript stripped, node_modules as they are), then runs a
// scenario's script against them:
//
//   node slop/lib/app_ts.mjs <app dir> <script.mjs> <cache dir>  < input.json  > output.json
//
// The script exports `run(load, input)`; `load("/lib/x.ts")` is the module. The run's
// client fault (env SLOP_TS_REWRITES: [[regex, replacement], ...], lib/faults.py
// `browser=`) rewrites each app module as vite hands it over, as actors/ui.py does to
// the JS the browser loads; the output counts each rewrite's matches and the modules
// they hit. Prints {out, hits, files}.
import { realpathSync } from "node:fs";
import path from "node:path";
import { createInterface } from "node:readline";
import { pathToFileURL } from "node:url";

const [app, script, cacheDir] = process.argv.slice(2);
const appDir = realpathSync(app);
// vite is vitest's dependency (pnpm: next to vitest in its store folder).
const vite = path.join(path.dirname(realpathSync(path.join(appDir, "node_modules/vitest/package.json"))),
  "..", "vite", "dist/node/index.js");
const { createServer } = await import(pathToFileURL(vite).href);

const rewrites = JSON.parse(process.env.SLOP_TS_REWRITES || "[]").map(([rx, rep]) => [rx, new RegExp(rx, "g"), rep]);
const hits = Object.fromEntries(rewrites.map(([rx]) => [rx, 0]));
const files = {};
const fault = {
  name: "slop-client-fault",
  enforce: "post",
  transform(code, id) {
    const file = id.split("?")[0];
    if (!rewrites.length || !file.startsWith(appDir + path.sep) || file.includes(`${path.sep}node_modules${path.sep}`)) {
      return null;
    }
    let out = code;
    for (const [key, rx, rep] of rewrites) {
      let n = 0;
      // The replacement is Python's (lib/faults.py, as actors/ui.py applies it): `\1` is a group.
      out = out.replace(rx, (...m) => { n += 1; return rep.replace(/\\(\d+)/g, (_, i) => m[+i] ?? ""); });
      if (n) {
        hits[key] += n;
        const rel = path.relative(appDir, file);
        files[rel] = (files[rel] || 0) + n;
      }
    }
    return out === code ? null : { code: out, map: null };
  },
};

const server = await createServer({
  root: appDir, configFile: false, logLevel: "error", cacheDir,
  resolve: { alias: { "@": appDir } },
  plugins: [fault],
  server: { middlewareMode: true, hmr: false, watch: null },
  appType: "custom",
  optimizeDeps: { noDiscovery: true, include: [] },
});
const print = (s) => new Promise((done) => process.stdout.write(s, done));
try {
  const { run } = await import(pathToFileURL(path.resolve(script)).href);
  const load = (p) => server.ssrLoadModule(p);
  if (process.env.SLOP_TS_LINES === "1") {
    // A session (lib/app_ts.py `session`): one JSON input per stdin line, one answer line each, in order.
    for await (const line of createInterface({ input: process.stdin, crlfDelay: Infinity })) {
      if (!line) continue;
      try {
        await print(JSON.stringify({ out: await run(load, JSON.parse(line)), hits, files }) + "\n");
      } catch (e) {
        await print(JSON.stringify({ error: String(e?.stack || e) }) + "\n");
      }
    }
  } else {
    // stdin read as a stream: a sync read of a large piped input fails with EAGAIN.
    const chunks = [];
    for await (const c of process.stdin) chunks.push(c);
    await print(JSON.stringify({ out: await run(load, JSON.parse(Buffer.concat(chunks).toString("utf8"))), hits, files }));
  }
} finally {
  await server.close();
}
