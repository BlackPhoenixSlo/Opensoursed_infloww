import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";
import { bindTooltips, tipTarget, tooltipPage } from "./ofMirrorTooltip";

const load = (p: string) => {
  document.documentElement.innerHTML = readFileSync(resolve(__dirname, `../public/of-mirror/pages/${p}.html`), "utf8");
  return document;
};
const tip = () => document.querySelector("[data-oi-tooltip] .tooltip-inner")?.textContent ?? null;
const hover = (el: Element) => el.dispatchEvent(new MouseEvent("mouseover", { bubbles: true }));
const leave = (el: Element) => el.dispatchEvent(new MouseEvent("mouseout", { bubbles: true }));

describe("OF's hover text (v-tooltip: aria-label on has-tooltip)", () => {
  it("only on Statistics and Statements pages", () => {
    expect(tooltipPage("statistics/statements/disputes")).toBe(true);
    expect(tooltipPage("statements/earnings")).toBe(true);
    expect(tooltipPage("home/index")).toBe(false);
  });

  it("Chargeback ratio and Pending balance: their OF text in OF's tooltip markup; leaving hides it", () => {
    const doc = load("statistics/statements/disputes");
    bindTooltips(doc);
    const ratio = doc.querySelector(".m-statistics-alert .has-tooltip")!;
    hover(ratio.querySelector("svg") ?? ratio);
    expect(tip()).toMatch(/^Chargebacks happen when a user contacts their payment card company/);
    expect(doc.querySelector("[data-oi-tooltip]")!.className).toBe("tooltip vue-tooltip-theme");
    expect(doc.querySelector("[data-oi-tooltip]")!.getAttribute("x-placement")).toMatch(/^(top|bottom)$/);
    leave(ratio);
    expect(tip()).toBeNull();
    const pending = doc.querySelector(".b-statements-balances__label .has-tooltip")!;
    pending.dispatchEvent(new FocusEvent("focusin", { bubbles: true }));
    expect(tip()).toMatch(/^Your balance is processed on a 7 day rolling basis/);
    pending.dispatchEvent(new KeyboardEvent("keydown", { key: "Escape", bubbles: true }));
    expect(tip()).toBeNull();
  });

  it("Unsend's \"i\" shows its text; the disabled Unsend and search (their own title) show none", () => {
    const doc = load("statistics/engagement/messages");
    bindTooltips(doc);
    const row = doc.querySelector("tr[data-oi-template]")!;
    const info = row.querySelector(".b-top-statistic__btns .has-tooltip")!;
    expect(tipTarget(info)).toBe(info);
    hover(info);
    expect(tip()).toBe("This will delete this message for all recipients who did not purchase the content in this message.");
    expect(tipTarget(row.querySelector(".b-top-statistic__btns button"))).toBeNull();
    expect(tipTarget(doc.querySelector(".m-search-btn"))).toBeNull();
  });

  it("a status tip with no text (a pending earning OF gives no days for) shows none", () => {
    const doc = load("statistics/statements/earnings");
    const status = doc.querySelector(".b-table__status-tip")!;
    expect(tipTarget(status)).toBe(status);
    status.removeAttribute("aria-label");
    expect(tipTarget(status)).toBeNull();
  });
});
