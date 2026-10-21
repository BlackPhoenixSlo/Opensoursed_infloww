import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { bindQr, drawQr, exportSize, qrSize, qrSrc } from "./ofMirrorQr";

/** Settings > QR code: OF's own code (qrcode-svg, ecl H, 6px dots, logo or avatar, URL line), its switches, Download. */

const load = () => {
  document.documentElement.innerHTML = readFileSync(resolve(__dirname, "../public/of-mirror/pages/settings/qrcode.html"), "utf8");
  return document;
};
const flush = () => new Promise((r) => setTimeout(r, 0));
const url = () => document.getElementById("add_url_to_qrcode") as HTMLInputElement;
const avatar = () => document.getElementById("add_avatar_to_qrcode") as HTMLInputElement;
const download = () => document.querySelector<HTMLButtonElement>("button.m-profile-qrcode")!;
const img = () => document.querySelector<HTMLImageElement>(".b-qrcode img")!;
const svgOf = (src: string) => decodeURIComponent(escape(atob(src.replace(/^data:image\/svg\+xml;base64,/, ""))));
const toggle = (el: HTMLInputElement) => {
  el.checked = !el.checked;
  el.dispatchEvent(new Event("change", { bubbles: true }));
};
const unbinds: (() => void)[] = [];
beforeEach(() => localStorage.clear());
afterEach(() => unbinds.splice(0).forEach((u) => u()));

describe("OF's code", () => {
  it("is (modules + 8) dots of 6px, on the profile URL with ?qr=1", () => {
    const { size, code } = qrSize("yourmodel");
    expect(size).toBe((code.qrcode.modules.length + 8) * 6);
    expect(code.options.content).toBe("https://onlyfans.com/yourmodel?qr=1");
    expect(code.options.ecl).toBe("H");
  });

  it("draws a white square with OF's logo in the middle, and no URL line by default", () => {
    const { svg, width, height } = drawQr({ username: "yourmodel", avatar: null, showUrl: false });
    expect(height).toBe(width);
    expect(svg).toContain(`width="${width}" height="${width}"`);
    expect(svg).toContain('<rect width="66" height="66"');
    expect(svg).toContain('fill="#00aeef"');
    expect(svg).toContain('fill="#008ccf"');
    expect(svg).not.toContain("<text");
    expect(svg).not.toContain("<?xml");
  });

  it("with the URL: onlyfans.com/<username> under the code, the image taller by the line", () => {
    const { svg, width, height } = drawQr({ username: "yourmodel", avatar: null, showUrl: true });
    expect(svg).toMatch(/<text[^>]*text-anchor="middle"[^>]*>onlyfans\.com\/yourmodel<\/text>/);
    expect(svg).toContain("family=Roboto");
    expect(height).toBeGreaterThan(width);
  });

  it("shrinks the URL line to 48px less than the width", () => {
    const { svg, width } = drawQr({ username: "yourmodel", avatar: null, showUrl: true, measure: (_t, s) => s * 30 });
    const font = Number(/font-size="([\d.]+)"/.exec(svg)![1]);
    expect(font * 30).toBeCloseTo(width - 48, 5);
  });

  it("with the avatar: the image in a 54px circle instead of the logo", () => {
    const { svg } = drawQr({ username: "yourmodel", avatar: "data:image/png;base64,AAAA", showUrl: false });
    expect(svg).toContain('<circle r="27"');
    expect(svg).toContain('href="data:image/png;base64,AAAA"');
    expect(svg).not.toContain('fill="#00aeef"');
  });

  it("is well-formed XML in every variant (an <img> shows nothing otherwise)", () => {
    for (const showUrl of [false, true])
      for (const avatar of [null, "data:image/png;base64,AAAA&x"]) {
        const { svg } = drawQr({ username: "your_model", avatar, showUrl });
        const doc = new DOMParser().parseFromString(svg, "image/svg+xml");
        expect(doc.querySelector("parsererror")).toBeNull();
      }
  });

  it("exports 738px wide, in proportion", () => {
    expect(exportSize({ width: 246, height: 266 })).toEqual({ width: 738, height: 798 });
  });
});

describe("the page", () => {
  it("draws the model's code, the switches off by default, Download enabled", async () => {
    const d = load();
    unbinds.push(bindQr(d, { username: "yourmodel", avatar: "/api/img?u=a" }, () => Promise.resolve("data:image/png;base64,AAAA")));
    await flush();
    expect(img().alt).toBe("yourmodel");
    expect(svgOf(img().src)).toContain('fill="#00aeef"');
    expect([url().checked, avatar().checked]).toEqual([false, false]);
    expect([url().disabled, avatar().disabled, download().disabled]).toEqual([false, false, false]);
    for (const el of [url(), avatar(), download()]) expect(el.hasAttribute("data-oi-wired")).toBe(true);
  });

  it("the switches redraw and are kept in the browser", async () => {
    const d = load();
    unbinds.push(bindQr(d, { username: "yourmodel", avatar: "/api/img?u=a" }, () => Promise.resolve("data:image/png;base64,AAAA")));
    await flush();
    toggle(url());
    await flush();
    expect(svgOf(img().src)).toContain(">onlyfans.com/yourmodel</text>");
    toggle(avatar());
    await flush();
    expect(svgOf(img().src)).toContain('href="data:image/png;base64,AAAA"');
    unbinds.splice(0).forEach((u) => u());
    load();
    unbinds.push(bindQr(document, { username: "yourmodel", avatar: "/api/img?u=a" }, () => Promise.resolve("data:image/png;base64,AAAA")));
    expect([url().checked, avatar().checked]).toEqual([true, true]);
  });

  it("no avatar: Show avatar stays disabled", async () => {
    const d = load();
    unbinds.push(bindQr(d, { username: "yourmodel", avatar: null }));
    await flush();
    expect(avatar().disabled).toBe(true);
    expect(url().disabled).toBe(false);
  });

  it("the avatar fails to load: it turns off and is disabled, OF's logo is drawn", async () => {
    localStorage.setItem("of-mirror:QR_CODE_AVATAR", "true");
    const d = load();
    unbinds.push(bindQr(d, { username: "yourmodel", avatar: "/api/img?u=a" }, () => Promise.reject(new Error("404"))));
    await flush();
    await flush();
    expect(avatar().checked).toBe(false);
    expect(avatar().disabled).toBe(true);
    expect(svgOf(img().src)).toContain('fill="#00aeef"');
  });

  it("Download saves <username>.png", async () => {
    const d = load();
    const clicks: string[] = [];
    vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(function (this: HTMLAnchorElement) {
      clicks.push(this.download);
    });
    vi.spyOn(HTMLCanvasElement.prototype, "toDataURL").mockReturnValue("data:image/png;base64,AAAA");
    // jsdom loads no image: fire each one's load as the browser would.
    const real = Object.getOwnPropertyDescriptor(HTMLImageElement.prototype, "src")!;
    Object.defineProperty(HTMLImageElement.prototype, "src", {
      ...real,
      set(this: HTMLImageElement, v: string) {
        real.set!.call(this, v);
        setTimeout(() => this.onload?.(new Event("load")), 0);
      },
    });
    try {
      unbinds.push(bindQr(d, { username: "yourmodel", avatar: null }));
      await flush();
      download().click();
      await flush();
      expect(clicks).toEqual(["yourmodel.png"]);
    } finally {
      Object.defineProperty(HTMLImageElement.prototype, "src", real);
      vi.restoreAllMocks();
    }
  });

  it("OF's scan count above the code (\"QR Scans: <n>\"), none at 0 (OF hides it)", async () => {
    const d = load();
    unbinds.push(bindQr(d, { username: "yourmodel", scans: 0 }));
    expect(d.querySelector(".text-center")).toBeNull();
    unbinds.splice(0).forEach((u) => u());
    unbinds.push(bindQr(d, { username: "yourmodel", scans: 12 }));
    const p = d.querySelector(".b-qrcode")!.previousElementSibling as HTMLElement;
    expect(p.tagName).toBe("P");
    expect(p.className).toBe("text-center");
    expect(p.textContent!.trim()).toBe("QR Scans: 12");
    expect(d.querySelectorAll("p.text-center").length).toBe(1);
  });

  it("no model: the placeholder stays, the switches and Download are disabled", async () => {
    const d = load();
    const before = img().src;
    unbinds.push(bindQr(d, null));
    await flush();
    expect(img().src).toBe(before);
    expect([url().disabled, avatar().disabled, download().disabled]).toEqual([true, true, true]);
  });

  it("the base64 src decodes back to the SVG", () => {
    const { svg } = drawQr({ username: "yourmodel", avatar: null, showUrl: false });
    expect(svgOf(qrSrc(svg))).toBe(svg);
  });
});
