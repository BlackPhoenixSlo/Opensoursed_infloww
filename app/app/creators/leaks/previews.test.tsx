import { afterEach, beforeEach, describe, expect, it, vi, type Mock } from "vitest";
import { act, cleanup, fireEvent, screen, waitFor, within } from "@testing-library/react";

const url = vi.hoisted(() => {
  const listeners = new Set<() => void>();
  return {
    subscribe: (cb: () => void) => { listeners.add(cb); return () => listeners.delete(cb); },
    go: (to: string) => { window.history.replaceState({}, "", to); listeners.forEach((cb) => cb()); },
  };
});
const replace = vi.fn((to: string) => url.go(to));
vi.mock("next/navigation", async () => {
  const { useSyncExternalStore } = await import("react");
  return {
    useRouter: () => ({ replace, push: vi.fn(), back: vi.fn(), forward: vi.fn(), prefetch: vi.fn() }),
    usePathname: () => "/creators/leaks",
    useSearchParams: () => new URLSearchParams(useSyncExternalStore(url.subscribe, () => window.location.search)),
  };
});

vi.mock("@/lib/relay", async (importOriginal) => {
  const real = await importOriginal<typeof import("@/lib/relay")>();
  return { ...real, relay: { get: vi.fn(), put: vi.fn(), post: vi.fn(), delete: vi.fn() } };
});

let flags: { fansly_manager: boolean; leak_tracker: boolean } | undefined;
vi.mock("@/components/shell/useFlags", () => ({ useFlags: () => flags }));
let scopeAccount: string | null = null;
vi.mock("@/contexts/ScopeContext", () => ({ useScope: () => ({ accountId: scopeAccount }) }));
const ACCOUNTS = [{ id: "acc-a", nickname: "Creator A" }, { id: "acc-b", nickname: "Creator B" }, { id: "acc-c", nickname: "Creator C" }];
vi.mock("@/hooks/useAccounts", () => ({ useActiveAccounts: () => ACCOUNTS }));
vi.mock("@/hooks/useEmployeeKey", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/hooks/useEmployeeKey")>()),
  useEmployeeKey: () => null,
}));

import Page from "@/app/creators/leaks/page";
import { RETRY_MS } from "@/components/leaks/leakPreview";
import { setBlurMode } from "@/hooks/useBlurMode";
import { relay } from "@/lib/relay";
import { renderWithProviders } from "@/test-utils";
import { type Answer, asAll, CREATOR_LEAKS, drill, MERGED, NO_LEAKS, row, serve, setup } from "./leakPageHarness";

const relayGet = relay.get as unknown as Mock;

beforeEach(() => {
  flags = { fansly_manager: false, leak_tracker: true };
  relayGet.mockReset();
  replace.mockClear();
  scopeAccount = null;
  window.history.replaceState({}, "", "/creators/leaks");
});
afterEach(() => cleanup());

describe("/creators/leaks Google previews", () => {
  const MEDIA_LEAK = CREATOR_LEAKS.find((l: { preview: unknown }) => l.preview);
  const OTHER = { ...MEDIA_LEAK, leak_id: "lk_0006", title: "someone else entirely", url: "https://pics.example-leaks.test/other",
    preview: { vertical: "images", seen_at: "2026-11-26T04:00:00Z" } };
  const TWO = [...CREATOR_LEAKS, OTHER];
  const SHOWN = [MEDIA_LEAK, OTHER];
  const PREVIEW = "/admin/leaks/watches/acc-a?preview=1";
  const thumb = (id: string, account = "acc-a") => `/admin/leaks/watches/${account}/leaks/${id}/thumb`;
  const grid = (name = "Creator A") => screen.findByRole("list", { name: `${name} Google previews` });
  const tile = (list: HTMLElement, id: string) => list.querySelector(`[data-tile="${id}"]`) as HTMLElement;
  const unblur = (t: HTMLElement) => within(t).queryByRole("button", { name: /^Unblur preview: / });
  const blurred = (t: HTMLElement) => t.querySelector("img")!.className.includes("blur-md");
  const google = (routes: Record<string, Answer> = {}, s = setup({ key: "set" })) => {
    window.history.replaceState({}, "", "/creators/leaks?open=acc-a&view=google");
    serve(s, { "/admin/leaks/roster": MERGED, "/admin/leaks/watches/acc-a": drill(TWO), [PREVIEW]: drill(SHOWN), ...routes });
  };

  afterEach(() => act(() => setBlurMode("off")));

  it("?view=google opens the Google view on load, newest seen first, each tile blurred under an Unblur button", async () => {
    google();
    const { container } = renderWithProviders(<Page />);
    const list = await grid();
    expect(within(list).getAllByRole("listitem").map((li) => li.dataset.tile)).toEqual(["lk_0005", "lk_0006"]);
    expect(screen.getByRole("radio", { name: "Google" }).getAttribute("aria-checked")).toBe("true");
    const t = tile(list, "lk_0005");
    const img = t.querySelector("img")!;
    expect([img.getAttribute("src"), img.getAttribute("alt"), img.getAttribute("loading")]).toEqual([thumb("lk_0005"), "Google preview", "lazy"]);
    expect(blurred(t)).toBe(true);
    expect(unblur(t)!.getAttribute("aria-pressed")).toBe("false");
    expect(unblur(t)!.getAttribute("aria-label")).toBe(`Unblur preview: ${MEDIA_LEAK.title}`);
    expect(relayGet).toHaveBeenCalledWith(PREVIEW, { accountId: null });
    expect(t.textContent).toContain("Seen in Google Images · 27 Nov");
    expect(t.querySelector('[data-pill="not_checked"]')).toBeTruthy();
    const link = within(t).getByRole("link");
    expect([link.getAttribute("href"), link.getAttribute("target"), link.getAttribute("rel")])
      .toEqual([MEDIA_LEAK.url, "_blank", "noreferrer noopener"]);
    expect(link.textContent).toContain("example-leaks.test");
    expect(img.closest("a")).toBeNull();
    expect(container.querySelector("[data-leak]")).toBeNull();
  });

  it("a click unblurs only that tile, a second click blurs it, and the image never navigates", async () => {
    google();
    renderWithProviders(<Page />);
    const list = await grid();
    const [a, b] = [tile(list, "lk_0005"), tile(list, "lk_0006")];
    const calls = replace.mock.calls.length;
    fireEvent.click(unblur(a)!);
    expect([blurred(a), blurred(b)]).toEqual([false, true]);
    expect(unblur(a)!.getAttribute("aria-pressed")).toBe("true");
    expect(unblur(a)!.getAttribute("aria-label")).toBe(`Unblur preview: ${MEDIA_LEAK.title}`);
    expect(unblur(b)!.getAttribute("aria-pressed")).toBe("false");
    fireEvent.click(unblur(a)!);
    expect(blurred(a)).toBe(true);
    expect(replace.mock.calls.length).toBe(calls);
  });

  it("a wrong-person tile still says the image may be unrelated, in its accessible name too", async () => {
    google();
    renderWithProviders(<Page />);
    const list = await grid();
    const wrong = within(list).getByRole("listitem", { name: "someone else entirely · Google preview · image may be unrelated" });
    expect(wrong.textContent).toContain("Google preview · image may be unrelated");
  });

  it("SFW on draws a placeholder with no image and no button, and turning it off starts blurred again", async () => {
    google();
    const { container } = renderWithProviders(<Page />);
    let list = await grid();
    fireEvent.click(unblur(tile(list, "lk_0005"))!);
    act(() => setBlurMode("hover"));
    list = await grid();
    expect(container.querySelector("img")).toBeNull();
    expect(within(list).queryAllByRole("button")).toEqual([]);
    expect(list.querySelectorAll('[data-thumb="placeholder"]')).toHaveLength(2);
    act(() => setBlurMode("off"));
    list = await grid();
    expect([blurred(tile(list, "lk_0005")), blurred(tile(list, "lk_0006"))]).toEqual([true, true]);
  });

  it("a Creator or Agency change blurs every tile again", async () => {
    google({ "/admin/leaks/watches/acc-c": drill(TWO), "/admin/leaks/watches/acc-c?preview=1": drill(SHOWN) });
    const { rerender } = renderWithProviders(<Page />);
    fireEvent.click(unblur(tile(await grid(), "lk_0005"))!);
    fireEvent.click(row("Creator C")!);
    let list = await grid("Creator C");
    expect(blurred(tile(list, "lk_0005"))).toBe(true);
    fireEvent.click(unblur(tile(list, "lk_0005"))!);
    expect(blurred(tile(list, "lk_0005"))).toBe(false);
    scopeAccount = "acc-b";
    rerender(<Page />);
    await waitFor(() => expect(relayGet).toHaveBeenCalledWith("/admin/leaks/watches/acc-c?preview=1", { accountId: "acc-b" }));
    list = await grid("Creator C");
    expect(blurred(tile(list, "lk_0005"))).toBe(true);
    expect(tile(list, "lk_0005").querySelector("img")!.getAttribute("src")).toBe(`${thumb("lk_0005", "acc-c")}?account_id=acc-b`);
  });

  it("a failed thumb retries once, then reads Preview unavailable, keeps the pill and moves focus to the link", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    try {
      google();
      renderWithProviders(<Page />);
      const list = await grid();
      const t = tile(list, "lk_0005");
      const first = t.querySelector("img")!;
      fireEvent.error(first);
      expect(first.className).toContain("invisible");
      act(() => vi.advanceTimersByTime(RETRY_MS));
      const second = t.querySelector("img")!;
      expect([second === first, second.className.includes("invisible"), second.getAttribute("src")]).toEqual([false, false, thumb("lk_0005")]);
      unblur(t)!.focus();
      fireEvent.error(second);
      expect(t.querySelector("img")).toBeNull();
      expect(t.textContent).toContain("Preview unavailable");
      expect(t.querySelector('[data-pill="not_checked"]')).toBeTruthy();
      expect(document.activeElement).toBe(within(t).getByRole("link"));
      expect(blurred(tile(list, "lk_0006"))).toBe(true);
    } finally {
      vi.useRealTimers();
    }
  });

  it("the switch flips List and Google in the URL and keeps focus", async () => {
    window.history.replaceState({}, "", "/creators/leaks?open=acc-a");
    serve(setup({ key: "set" }), { "/admin/leaks/roster": MERGED, "/admin/leaks/watches/acc-a": drill(TWO), [PREVIEW]: drill(SHOWN) });
    const { container } = renderWithProviders(<Page />);
    await screen.findByRole("list", { name: "Creator A Leaks" });
    expect(relayGet.mock.calls.some(([p]) => p === PREVIEW)).toBe(false);
    expect(container.querySelector("img")).toBeNull();
    const radio = screen.getByRole("radio", { name: "Google" });
    radio.focus();
    fireEvent.click(radio);
    expect(replace).toHaveBeenLastCalledWith("/creators/leaks?open=acc-a&view=google", { scroll: false });
    await grid();
    expect(document.activeElement).toBe(screen.getByRole("radio", { name: "Google" }));
    fireEvent.click(screen.getByRole("radio", { name: "List" }));
    expect(replace).toHaveBeenLastCalledWith("/creators/leaks?open=acc-a", { scroll: false });
    await screen.findByRole("list", { name: "Creator A Leaks" });
  });

  it("leaving a Creator for All Models clears the view, so the next Creator opens in List", async () => {
    google();
    renderWithProviders(<Page />);
    await grid();
    fireEvent.click(screen.getByTestId("of-all-creators-row"));
    expect(replace).toHaveBeenLastCalledWith("/creators/leaks", { scroll: false });
    fireEvent.click(row("Creator A")!);
    expect(replace).toHaveBeenLastCalledWith("/creators/leaks?open=acc-a", { scroll: false });
    await screen.findByRole("list", { name: "Creator A Leaks" });
  });

  it("with no preview yet the Google view says so", async () => {
    google({ [PREVIEW]: drill([]) });
    renderWithProviders(<Page />);
    expect(await screen.findByText("No Google previews for this Creator yet.")).toBeTruthy();
  });

  it("an empty first preview page with more to come shows Load more, not the empty line, and page 2 fills the grid", async () => {
    google({ [PREVIEW]: drill([], "c2"), [`${PREVIEW}&cursor=c2`]: drill(SHOWN) });
    renderWithProviders(<Page />);
    const more = await screen.findByRole("button", { name: "Load more" });
    expect(screen.queryByText("No Google previews for this Creator yet.")).toBeNull();
    fireEvent.click(more);
    const list = await grid();
    expect(within(list).getAllByRole("listitem").map((li) => li.dataset.tile)).toEqual(["lk_0005", "lk_0006"]);
    expect(screen.queryByRole("button", { name: "Load more" })).toBeNull();
  });

  it("previews off: text tiles with the Kind icon, no image, and no strip request", async () => {
    const off = CREATOR_LEAKS.map((l: object) => ({ ...l, preview: null }));
    google({ "/admin/leaks/watches/acc-a": drill(off) }, setup({ key: "set", previews: false }));
    const { container } = renderWithProviders(<Page />);
    const list = await grid();
    const t = tile(list, "lk_0005");
    expect(container.querySelector("img")).toBeNull();
    expect(t.querySelector('[data-thumb="placeholder"] svg')).toBeTruthy();
    expect(t.textContent).toContain("image may be unrelated");
    fireEvent.click(screen.getByTestId("of-all-creators-row"));
    await screen.findByRole("region", { name: "All Models" });
    expect(relayGet.mock.calls.some(([p]) => String(p).includes("preview=1"))).toBe(false);
    expect(screen.queryByRole("region", { name: "Seen in Google Images" })).toBeNull();
  });

  it("All Models shows the strip with Creator names, and a tile opens that Creator's Google view", async () => {
    serve(setup({ key: "set" }), {
      "/admin/leaks/roster": MERGED, "/admin/leaks/all?preview=1": asAll("leaks_preview_only"),
      "/admin/leaks/watches/acc-a": drill(TWO), [PREVIEW]: drill(SHOWN),
    });
    renderWithProviders(<Page />);
    const strip = await screen.findByRole("region", { name: "Seen in Google Images" });
    const t = strip.querySelector('[data-tile="lk_0005"]') as HTMLElement;
    expect(blurred(t)).toBe(true);
    expect(t.querySelector("img")!.getAttribute("src")).toBe(thumb("lk_0005"));
    expect(t.textContent).toContain("Google preview · image may be unrelated");
    fireEvent.click(unblur(t)!);
    expect(blurred(t)).toBe(false);
    fireEvent.click(within(t).getByRole("button", { name: "Creator A" }));
    expect(replace).toHaveBeenLastCalledWith("/creators/leaks?open=acc-a&view=google", { scroll: false });
    expect(blurred(tile(await grid(), "lk_0005"))).toBe(true);
  });

  it("the strip hides when empty, and SFW on draws it with no image", async () => {
    serve(setup({ key: "set" }), { "/admin/leaks/roster": MERGED, "/admin/leaks/all?preview=1": NO_LEAKS });
    renderWithProviders(<Page />);
    await screen.findByRole("region", { name: "All Models" });
    await waitFor(() => expect(relayGet).toHaveBeenCalledWith("/admin/leaks/all?preview=1", { accountId: null }));
    expect(screen.queryByRole("region", { name: "Seen in Google Images" })).toBeNull();
    cleanup();
    act(() => setBlurMode("constant"));
    serve(setup({ key: "set" }), { "/admin/leaks/roster": MERGED, "/admin/leaks/all?preview=1": asAll("leaks_preview_only") });
    const { container } = renderWithProviders(<Page />);
    const strip = await screen.findByRole("region", { name: "Seen in Google Images" });
    expect(strip.querySelector('[data-thumb="placeholder"]')).toBeTruthy();
    expect(container.querySelector("img")).toBeNull();
  });
});
