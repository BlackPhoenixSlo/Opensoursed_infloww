#!/usr/bin/env node

import fs from "node:fs";
import { createRequire } from "node:module";
import path from "node:path";
import { fileURLToPath } from "node:url";

import { needlesOf, peopleOf, textKinds } from "../fansly-mirror/kinds.mjs";
import { dropNotCaptured } from "../fansly-mirror/not-captured.mjs";
import { peopleReOf } from "../fansly-mirror/scrub.mjs";

const REPO = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../..");
const { JSDOM, VirtualConsole } = createRequire(path.join(REPO, "app/package.json"))("jsdom");
const fail = (msg) => {
  console.error(`fansly-mirror-check kinds: ${msg}`);
  process.exit(1);
};
const arg = (name) => {
  const i = process.argv.indexOf(name);
  return i > 0 && process.argv[i + 1] ? path.resolve(process.argv[i + 1]) : fail(`${name} <path> is required`);
};
const capture = arg("--capture");
const manifest = JSON.parse(fs.readFileSync(path.join(capture, "manifest.json"), "utf8"));
const plan = JSON.parse(fs.readFileSync(arg("--plan"), "utf8"));
if (!Array.isArray(manifest?.identities) || !manifest.identities.length) fail("manifest identities is not a list");

const parentOf = new Map(plan.map((p) => [p.id, p.parent]));
const { entries } = dropNotCaptured(manifest.entries, (id) => parentOf.get(id), () => false, fail);
const docs = entries.map((entry) => ({ entry, dom: new JSDOM(fs.readFileSync(path.resolve(capture, entry.file), "utf8"), { virtualConsole: new VirtualConsole() }) }));
const needles = needlesOf(manifest.identities);
const people = peopleReOf(peopleOf(docs, needles));

const hits = [];
for (const { where, text } of JSON.parse(fs.readFileSync(0, "utf8"))) {
  const kinds = new Set();
  textKinds(String(text), kinds, { build: null, needles, people, readable: true });
  if (kinds.size) hits.push({ where, kinds: [...kinds] });
}
console.log(JSON.stringify(hits));
