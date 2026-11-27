import { useState } from "react";
import { afterEach, beforeEach, describe, expect, it, vi, type Mock } from "vitest";
import { act, cleanup, fireEvent, screen, waitFor, within } from "@testing-library/react";

vi.mock("@/lib/relay", async (importOriginal) => {
  const real = await importOriginal<typeof import("@/lib/relay")>();
  return { ...real, relay: { get: vi.fn(), put: vi.fn(), post: vi.fn(), delete: vi.fn() } };
});

import { StartRemovalPopup, type OfferRead } from "@/components/leaks/StartRemovalPopup";
import type { RemovalOffer } from "@/components/leaks/removalOffer";
import { relay, RelayError } from "@/lib/relay";
import { renderWithProviders } from "@/test-utils";

const relayGet = relay.get as unknown as Mock;
const BRAND = "Example Removal";
const CONTACT = "https://removal.example/contact";
const OFFER: RemovalOffer = { brand: BRAND, contact_url: CONTACT, angle: "came_back", n: 1 };
const CUES = [
  { t_s: 3, kind: "google" }, { t_s: 9.5, kind: "google_images" }, { t_s: 16, kind: "mega" },
  { t_s: 22, kind: "forum" }, { t_s: 28, kind: "x" }, { t_s: 40, kind: "end" },
] as const;
const leak = (id: string, title: string, kind = "page") =>
  ({ leak_id: id, leak_site: "example-leaks.test", kind, title, pill: "live" as const, preview: null });
const READ: OfferRead = {
  offer: OFFER,
  preview_leak: null,
  video: { duration_s: 42, has_poster: true, cues: [...CUES] },
  scenes: {
    google: [leak("lk_0001", "miavale onlyfans leak"), leak("lk_0002", "mia.vale.x thread")],
    google_images: [leak("lk_0010", "mia vale images", "media")],
    mega: [], forum: [], x: [],
  },
  last_checked_at: "2026-11-27T04:05:00Z",
};

let media: Record<string, boolean> = {};
const realImage = globalThis.Image;
let probes = 0;

class ProbeImage {
  constructor() {
    probes += 1;
  }
}

beforeEach(() => {
  relayGet.mockReset();
  media = {};
  probes = 0;
  globalThis.Image = ProbeImage as unknown as typeof Image;
  window.matchMedia = ((q: string) => ({
    matches: !!media[q], media: q, addEventListener() {}, removeEventListener() {},
  })) as unknown as typeof window.matchMedia;
  window.localStorage.clear();
});
afterEach(() => {
  cleanup();
  globalThis.Image = realImage;
});

const open = async (read: OfferRead | Error = READ, onClose = vi.fn()) => {
  if (read instanceof Error) relayGet.mockRejectedValue(read);
  else relayGet.mockResolvedValue(read);
  renderWithProviders(<StartRemovalPopup creatorId="acc-a" offer={OFFER} onClose={onClose} />);
  const dialog = await screen.findByRole("dialog", { name: `Start removal with ${BRAND}` });
  if (!(read instanceof Error)) await within(dialog).findByRole("region", { name: "Results" });
  return { dialog, onClose };
};
const video = () => document.querySelector("video");
const overlay = () => document.querySelector<HTMLElement>("[data-overlay]");
const seek = async (t: number, event: "seeked" | "timeUpdate" = "seeked") => {
  const v = video()!;
  Object.defineProperty(v, "currentTime", { configurable: true, value: t });
  await act(async () => { fireEvent[event](v); });
};

describe("Start removal popup", () => {
  it("reads live with the Creator header and lays out video, results, then the contact link", async () => {
    const { dialog } = await open();
    expect(relayGet).toHaveBeenCalledWith("/admin/leaks/watches/acc-a/offer", { accountId: "acc-a" });
    const v = video()!;
    const results = within(dialog).getByRole("region", { name: "Results" });
    const link = within(dialog).getByRole("link", { name: `Contact ${BRAND}` });
    expect(v.compareDocumentPosition(results) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(results.compareDocumentPosition(link) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(link.getAttribute("href")).toBe(CONTACT);
    expect(within(results).getByText("1 leak came back in the last 30 days.")).toBeTruthy();
    expect(within(results).getByText(/^Google: 2 · example-leaks\.test — miavale onlyfans leak/)).toBeTruthy();
    expect(within(results).getByText(/^Last checked /)).toBeTruthy();
  });

  it("plays the generic take natively: no autoplay or loop, captions on, every src same-origin, no iframe", async () => {
    const { dialog } = await open();
    const v = video()!;
    expect(v.hasAttribute("controls")).toBe(true);
    expect(v.hasAttribute("autoplay")).toBe(false);
    expect(v.hasAttribute("loop")).toBe(false);
    expect(v.getAttribute("preload")).toBe("metadata");
    expect(v.hasAttribute("playsinline")).toBe(true);
    const track = v.querySelector("track")!;
    expect(track.getAttribute("kind")).toBe("captions");
    expect(track.hasAttribute("default")).toBe(true);
    expect(dialog.querySelector("iframe")).toBeNull();
    const srcs = [v.getAttribute("src"), v.getAttribute("poster"), track.getAttribute("src")];
    expect(srcs).toEqual([
      "/admin/leaks/offer-video/video?account_id=acc-a",
      "/admin/leaks/offer-video/poster?account_id=acc-a",
      "/admin/leaks/offer-video/captions?account_id=acc-a",
    ]);
    for (const el of dialog.querySelectorAll("[src],[href],[poster]")) {
      for (const a of ["src", "poster"]) {
        const val = el.getAttribute(a);
        if (val) expect(val.startsWith("/admin/leaks/offer-video/")).toBe(true);
      }
    }
  });

  it("the overlay is aria-hidden, over the video, and a seek moves the active scene", async () => {
    await open();
    const layer = overlay()!;
    expect(layer.getAttribute("aria-hidden")).toBe("true");
    expect(layer.dataset.layout).toBe("over");
    expect(layer.parentElement!.contains(video())).toBe(true);
    expect(layer.dataset.scene).toBe("none");
    await seek(4);
    expect(overlay()!.dataset.scene).toBe("google");
    expect(within(overlay()!).getByText("miavale onlyfans leak")).toBeTruthy();
    expect(within(overlay()!).queryByText("Preview · not removed")).toBeNull();
    await seek(7, "timeUpdate");
    expect(within(overlay()!).getAllByText("No longer available")).toHaveLength(2);
    expect(within(overlay()!).getByText("Preview · not removed")).toBeTruthy();
    await seek(17);
    expect(overlay()!.dataset.scene).toBe("mega");
    expect(within(overlay()!).getByText("None found here")).toBeTruthy();
    await seek(41);
    expect(overlay()!.dataset.scene).toBe("end");
    expect(within(overlay()!).getByText("1 leak came back in the last 30 days.")).toBeTruthy();
    await seek(3);
    expect(overlay()!.dataset.scene).toBe("google");
  });

  it("the images scene shows site and title cards and no <img> under SFW", async () => {
    window.localStorage.setItem("chatterly:blur-mode", "constant");
    const { dialog } = await open();
    await seek(10);
    expect(overlay()!.dataset.scene).toBe("google_images");
    expect(within(overlay()!).getByText("mia vale images")).toBeTruthy();
    expect(within(overlay()!).getByText("example-leaks.test")).toBeTruthy();
    expect(dialog.querySelector("img")).toBeNull();
  });

  it("swaps scenes with a fade only when motion is allowed", async () => {
    await open();
    await seek(4);
    expect(overlay()!.firstElementChild!.className).toMatch(/animate-/);
    cleanup();
    media = { "(prefers-reduced-motion: reduce)": true };
    await open();
    await seek(4);
    expect(overlay()!.firstElementChild!.className).not.toMatch(/animate-/);
  });

  it("at phone width the layer sits below the video and the popup is the full-height sheet", async () => {
    media = { "(max-width: 639px)": true };
    const { dialog } = await open();
    const layer = overlay()!;
    expect(layer.dataset.layout).toBe("below");
    expect(layer.parentElement!.contains(video())).toBe(true);
    expect(video()!.parentElement!.contains(layer)).toBe(false);
    expect(video()!.compareDocumentPosition(layer) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(dialog.className).toMatch(/max-sm:h-/);
  });

  it("with no cue table there is no overlay, only the results card", async () => {
    await open({ ...READ, video: { ...READ.video!, cues: null } });
    expect(video()).toBeTruthy();
    expect(overlay()).toBeNull();
    expect(screen.getByRole("region", { name: "Results" })).toBeTruthy();
  });

  it.each([
    ["no video", (async () => { await open({ ...READ, video: null }); })],
    ["a failed video", (async () => { await open(); await act(async () => { fireEvent.error(video()!); }); })],
    ["failed captions", (async () => {
      await open();
      await act(async () => { video()!.querySelector("track")!.dispatchEvent(new Event("error")); });
    })],
  ])("%s drops the player and keeps results and contact", async (_, run) => {
    await run();
    expect(video()).toBeNull();
    expect(overlay()).toBeNull();
    expect(screen.getByRole("region", { name: "Results" })).toBeTruthy();
    expect(screen.getByRole("link", { name: `Contact ${BRAND}` })).toBeTruthy();
  });

  it("the poster is left to the video element, never fetched a second time", async () => {
    await open();
    expect(video()!.getAttribute("poster")).toBe("/admin/leaks/offer-video/poster?account_id=acc-a");
    expect(probes).toBe(0);
  });

  it("no poster on the service sets none", async () => {
    await open({ ...READ, video: { ...READ.video!, has_poster: false } });
    expect(video()!.hasAttribute("poster")).toBe(false);
  });

  it("a 404 read closes the popup", async () => {
    const { onClose } = await open(new RelayError(404, { detail: "Not Found" }));
    await waitFor(() => expect(onClose).toHaveBeenCalled());
  });

  it.each([502, 503])("a %s keeps the popup with the contact from the card", async (status) => {
    const { dialog, onClose } = await open(new RelayError(status, { detail: "x" }));
    expect(await within(dialog).findByRole("alert")).toBeTruthy();
    expect(within(dialog).getByRole("link", { name: `Contact ${BRAND}` }).getAttribute("href")).toBe(CONTACT);
    expect(onClose).not.toHaveBeenCalled();
  });
});

function Harness() {
  const [on, setOn] = useState(false);
  return (
    <>
      <button type="button" onClick={() => setOn(true)}>Contact us to start removal</button>
      {on && <StartRemovalPopup creatorId="acc-a" offer={OFFER} onClose={() => setOn(false)} />}
    </>
  );
}

describe("popup focus", () => {
  it("traps focus inside, Escape closes, and focus returns to the CTA", async () => {
    relayGet.mockResolvedValue(READ);
    renderWithProviders(<Harness />);
    const cta = screen.getByRole("button", { name: "Contact us to start removal" });
    cta.focus();
    fireEvent.click(cta);
    const dialog = await screen.findByRole("dialog");
    await within(dialog).findByRole("region", { name: "Results" });
    expect(dialog.contains(document.activeElement)).toBe(true);
    const link = within(dialog).getByRole("link", { name: `Contact ${BRAND}` });
    link.focus();
    fireEvent.keyDown(document, { key: "Tab" });
    expect(dialog.contains(document.activeElement)).toBe(true);
    fireEvent.keyDown(document, { key: "Escape" });
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
    expect(document.activeElement).toBe(cta);
  });
});
