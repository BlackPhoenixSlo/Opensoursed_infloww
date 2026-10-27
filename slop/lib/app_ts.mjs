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
      out = out.replace(rx, () => { n += 1; return rep; });
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
try {
  // stdin read as a stream: a sync read of a large piped input fails with EAGAIN.
  const chunks = [];
  for await (const c of process.stdin) chunks.push(c);
  const input = JSON.parse(Buffer.concat(chunks).toString("utf8"));
  const { run } = await import(pathToFileURL(path.resolve(script)).href);
  const out = await run((p) => server.ssrLoadModule(p), input);
  await new Promise((done) => process.stdout.write(JSON.stringify({ out, hits, files }), done));
} finally {
  await server.close();
}
