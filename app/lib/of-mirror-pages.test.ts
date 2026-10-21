import fs from "node:fs";
import path from "node:path";
import { describe, expect, it } from "vitest";
import { OF_MIRROR_SECTIONS } from "./of-mirror-pages";

const PAGES = path.join(process.cwd(), "public/of-mirror/pages") // vitest runs from app/;

const fileOf = (section: string, sub: string) => `${section}/${sub || "index"}.html`;

function filesUnder(dir: string, prefix = ""): string[] {
  return fs
    .readdirSync(dir, { withFileTypes: true })
    .flatMap((e) => (e.isDirectory() ? filesUnder(`${dir}/${e.name}`, `${prefix}${e.name}/`) : e.name.endsWith(".html") ? [`${prefix}${e.name}`] : []));
}

describe("OF_MIRROR_SECTIONS", () => {
  const listed = Object.entries(OF_MIRROR_SECTIONS).flatMap(([section, { pages }]) => Object.keys(pages).map((sub) => fileOf(section, sub)));

  it("has a file for every listed page", () => {
    expect(listed.filter((f) => !fs.existsSync(`${PAGES}/${f}`))).toEqual([]);
  });

  it("lists every page file", () => {
    expect(filesUnder(PAGES).filter((f) => !listed.includes(f))).toEqual([]);
  });

  it("lists each section's index page", () => {
    for (const [section, { index, pages }] of Object.entries(OF_MIRROR_SECTIONS)) expect(pages, section).toHaveProperty([index]);
  });
});
