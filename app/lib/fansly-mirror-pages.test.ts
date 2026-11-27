import fs from "node:fs";
import path from "node:path";
import { describe, expect, it } from "vitest";
import { FANSLY_MIRROR_SECTIONS } from "./fansly-mirror-pages";

const PAGES = path.join(process.cwd(), "public/fansly-mirror/pages");
const absent = !fs.existsSync(PAGES);

const fileOf = (section: string, sub: string) => `${section}/${sub || "index"}.html`;

function filesUnder(dir: string, prefix = ""): string[] {
  return fs
    .readdirSync(dir, { withFileTypes: true })
    .flatMap((e) => (e.isDirectory() ? filesUnder(`${dir}/${e.name}`, `${prefix}${e.name}/`) : e.name.endsWith(".html") ? [`${prefix}${e.name}`] : []));
}

describe("FANSLY_MIRROR_SECTIONS", () => {
  const listed = Object.entries(FANSLY_MIRROR_SECTIONS).flatMap(([section, { pages }]) => Object.keys(pages).map((sub) => fileOf(section, sub)));

  it.skipIf(absent)("has a file for every listed page", () => {
    expect(listed.filter((f) => !fs.existsSync(`${PAGES}/${f}`))).toEqual([]);
  });

  it.skipIf(absent)("lists every page file", () => {
    expect(filesUnder(PAGES).filter((f) => !listed.includes(f))).toEqual([]);
  });

  it.skipIf(absent)("lists each section's index page", () => {
    for (const [section, { index, pages }] of Object.entries(FANSLY_MIRROR_SECTIONS)) expect(pages, section).toHaveProperty([index]);
  });
});
