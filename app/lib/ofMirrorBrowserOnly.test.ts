import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it, vi } from "vitest";
import { ACCOUNT, bindBrowserOnly, MAILTO, PASSWORD, PHONE, revealed, SUPPORT } from "./ofMirrorBrowserOnly";
import { NOT_YET } from "./ofMirrorWrites";

const page = (p: string) => {
  const html = readFileSync(resolve(__dirname, `../public/of-mirror/pages/${p}.html`), "utf8");
  return new DOMParser().parseFromString(html, "text/html");
};
const reveals = (d: Document) => [...d.querySelectorAll<HTMLButtonElement>("#content button[aria-label='Reveal password']")];
const fieldOf = (b: Element) => b.closest(".v-input")!.querySelector("input")!;
const cancel = (d: Document) => [...d.querySelectorAll<HTMLButtonElement>("#content form button")].find((b) => b.textContent?.trim() === "Cancel")!;
const support = (d: Document) => [...d.querySelectorAll<HTMLAnchorElement>("#content a")].filter((a) => a.textContent?.trim() === SUPPORT);

describe("revealed", () => {
  it.each([["password", "text"], ["text", "password"]])("%s -> %s", (from, to) => expect(revealed(from)).toBe(to));
});

describe("bindBrowserOnly", () => {
  it("Reveal password flips its own field both ways, title kept, and undoes", () => {
    const d = page(PASSWORD);
    const undo = bindBrowserOnly(d, PASSWORD, vi.fn());
    const bs = reveals(d);
    expect(bs).toHaveLength(3);
    for (const b of bs) {
      expect([b.disabled, b.title, b.hasAttribute("data-oi-wired")]).toEqual([false, NOT_YET, true]);
      b.click();
      expect([fieldOf(b).type, b.getAttribute("aria-checked")]).toEqual(["text", "true"]);
      expect(bs.filter((o) => o !== b).every((o) => fieldOf(o).type === "password")).toBe(true);
      b.click();
      expect([fieldOf(b).type, b.getAttribute("aria-checked")]).toEqual(["password", "false"]);
    }
    bs[0].click();
    undo();
    for (const b of bs) expect([b.disabled, b.hasAttribute("data-oi-wired"), fieldOf(b).type]).toEqual([true, false, "password"]);
  });

  it("leaves Save, Forgot password? and the fields as captured", () => {
    const d = page(PASSWORD);
    bindBrowserOnly(d, PASSWORD, vi.fn());
    const rest = [...d.querySelectorAll<HTMLInputElement | HTMLButtonElement>("#content form input, #content form button:not([aria-label='Reveal password'])")];
    expect(rest.length).toBe(5);
    for (const el of rest) expect([el.disabled, el.title]).toEqual([true, NOT_YET]);
  });

  it("phone Cancel goes to Account; SAVE stays disabled", () => {
    const d = page(PHONE);
    const navigate = vi.fn();
    const undo = bindBrowserOnly(d, PHONE, navigate);
    const c = cancel(d);
    expect([c.disabled, c.title]).toEqual([false, NOT_YET]);
    c.click();
    expect(navigate).toHaveBeenCalledExactlyOnceWith(ACCOUNT);
    expect([...d.querySelectorAll<HTMLButtonElement>("#content button[type='submit']")].every((b) => b.disabled)).toBe(true);
    undo();
    expect(c.disabled).toBe(true);
  });

  it.each(["bank/dac7/edit", "settings/account/delete"])("%s's support link mails support, title kept, and undoes", (p) => {
    const d = page(p);
    const [before] = support(d);
    expect(before.getAttribute("href")).toBe("#");
    const undo = bindBrowserOnly(d, p, vi.fn());
    const as = support(d);
    expect(as).toHaveLength(1);
    expect([as[0].getAttribute("href"), as[0].title, as[0].hasAttribute("aria-disabled")]).toEqual([MAILTO, NOT_YET, false]);
    undo();
    expect([as[0].getAttribute("href"), as[0].getAttribute("aria-disabled")]).toEqual(["#", "true"]);
  });

  it("touches nothing on another page (a Bank page's cards stay Not-yet)", () => {
    const d = page("bank/payments");
    const before = d.body.innerHTML;
    bindBrowserOnly(d, "bank/payments", vi.fn());
    expect(d.body.innerHTML).toBe(before);
  });
});
