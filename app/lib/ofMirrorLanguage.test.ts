import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { bindLanguage, LANGUAGE_PAGE, LANGUAGES } from "./ofMirrorLanguage";

/** Settings > Display > Language: OF's list, one checked, kept in the browser (OF: client-only), Display's row label. */

const load = (page: string) => {
  document.documentElement.innerHTML = readFileSync(resolve(__dirname, `../public/of-mirror/pages/${page}.html`), "utf8");
  return document;
};
const radios = () => [...document.querySelectorAll<HTMLInputElement>("input[type=radio][id^='lang-']")];
const checked = () => radios().filter((r) => r.checked).map((r) => r.value);
const pick = (code: string) => {
  const r = document.getElementById(`lang-${code}`) as HTMLInputElement;
  r.checked = true;
  r.dispatchEvent(new Event("change", { bubbles: true }));
};
const row = () => document.querySelector("a[href$='/settings/display/language'] .b-menu-list__subtext")!;
const unbinds: (() => void)[] = [];
beforeEach(() => localStorage.clear());
afterEach(() => unbinds.splice(0).forEach((u) => u()));

describe("Language", () => {
  it("lists OF's languages, in OF's order, with OF's labels", () => {
    load(LANGUAGE_PAGE);
    expect(radios().map((r) => [r.value, r.labels?.[0]?.textContent])).toEqual(Object.entries(LANGUAGES));
  });

  it("English by default; a pick is the only one checked, and is kept", () => {
    const d = load(LANGUAGE_PAGE);
    unbinds.push(bindLanguage(d, LANGUAGE_PAGE));
    expect(checked()).toEqual(["en"]);
    for (const r of radios()) expect(r.hasAttribute("data-oi-wired")).toBe(true);
    pick("de");
    expect(checked()).toEqual(["de"]);
    unbinds.splice(0).forEach((u) => u());
    load(LANGUAGE_PAGE);
    unbinds.push(bindLanguage(document, LANGUAGE_PAGE));
    expect(checked()).toEqual(["de"]);
  });

  it("Display's Language row shows the pick's label", () => {
    localStorage.setItem("of-mirror:lang", "fr");
    const d = load("settings/display");
    bindLanguage(d, "settings/display");
    expect(row().textContent).toBe("French");
  });

  it("an unknown stored code falls back to English", () => {
    localStorage.setItem("of-mirror:lang", "xx");
    const d = load("settings/display");
    bindLanguage(d, "settings/display");
    expect(row().textContent).toBe("English");
  });
});
