#!/usr/bin/env node

import { register } from "node:module";
import path from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

const APP = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../../app") + path.sep;

// Node strips the types; this hook only adds what tsconfig's paths and the bundler resolution do (the plugin barrel's noPlugins fallback, extensionless imports).
register(
  "data:text/javascript," +
    encodeURIComponent(`
import fs from "node:fs";
import { fileURLToPath, pathToFileURL } from "node:url";
const APP = ${JSON.stringify(APP)};
export async function resolve(s, c, next) {
  if (s.startsWith("@/lib/plugins.generated")) s = "@/lib/noPlugins";
  if (s.startsWith("@/")) s = pathToFileURL(APP + s.slice(2)).href;
  else if (s.startsWith(".") && c.parentURL?.startsWith("file:")) s = new URL(s, c.parentURL).href;
  if (s.startsWith("file:") && !/\\.[cm]?[jt]sx?$/.test(s))
    for (const ext of [".ts", "/index.ts"]) if (fs.existsSync(fileURLToPath(s + ext))) { s += ext; break; }
  return next(s, c);
}`),
);

const { routableFanslyPages } = await import(pathToFileURL(`${APP}lib/fansly-mirror-route.ts`).href);
const pages = process.argv.includes("--empty-table") ? routableFanslyPages({}) : routableFanslyPages();
console.log(JSON.stringify(pages));
