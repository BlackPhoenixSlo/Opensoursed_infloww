/**
 * Seam 2 of docs/spec/phase-04-composer-ppv-vault.md: `VaultPicker` rendered
 * directly with a Fan in scope. `@/lib/relay` is mocked by URL through the
 * Composer harness's relay mock, so the picker's real hooks run.
 */
import { afterEach, beforeEach, describe, expect, it, onTestFinished, vi } from "vitest";
import { act, cleanup, fireEvent, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import type { VaultMedia } from "@/lib/relay";
import type { FanVaultHistoryResp } from "@/hooks/useFanVaultHistory";
import { renderWithProviders } from "@/test-utils";
import { observerStub, relayGet, relayPost, resetComposerHarness, routeRelay } from "./composerTestHarness";
import { VaultPicker } from "./VaultPicker";
import { NOT_WIRED } from "./NotWired";

vi.mock("@/lib/relay", async (orig) =>
  (await import("./composerTestHarness")).mockRelayModule(await orig()));
// An owner session, as the Thread runs it: the chatter folder gate stays off.
vi.mock("@/contexts/UserContext", () => ({ useUser: () => ({ user: { username: "owner" } }) }));
vi.mock("@/contexts/ChatterContext", () => ({ useChatter: () => ({ chatter: null }) }));

/* ── the spec's fixtures (synthetic) ────────────────────────────────────── */

const MEDIA: VaultMedia[] = [
  { id: 7001, type: "photo", isReady: true, canView: true },
  { id: 7002, type: "video", isReady: true, canView: true, duration: 30 },
  { id: 7003, type: "video", isReady: true, canView: true, duration: 120 },
  { id: 7004, type: "video", isReady: true, canView: true, duration: 600 },
];

const FAN_HISTORY: FanVaultHistoryResp = {
  by_media: {
    // purchased
    "7001": {
      send_count: 1, last_sent_at: "2026-10-01T10:00:00Z", last_price_cents: 1500,
      was_purchased: true, last_purchase_at: "2026-10-01T11:00:00Z", total_paid_cents: 2500,
    },
    // sent free
    "7002": {
      send_count: 1, last_sent_at: "2026-10-02T10:00:00Z", last_price_cents: 0,
      was_purchased: false, last_purchase_at: null, total_paid_cents: 0,
    },
    // sent locked
    "7003": {
      send_count: 1, last_sent_at: "2026-10-03T10:00:00Z", last_price_cents: 2000,
      was_purchased: false, last_purchase_at: null, total_paid_cents: 0,
    },
  },
};

/** Every relay path the picker requests today (VaultPicker.tsx's hooks:
 *  useVaultCacheSummary, useVaultLists, useChatterFolderAccess,
 *  useVaultMedia, useMirrorItems + searchOf, useFanVaultHistory,
 *  useWallMedia, useVaultMediaStats). Anything else is a new endpoint. */
const ALLOWED_PATHS = new Set([
  "/admin/vault-ai/cache/summary",
  "/api/of/v2/vault/lists",
  "/chatter/me/folder-access",
  "/api/of/v2/vault/media",
  "/admin/vault-ai/items",
  "/admin/vault-ai/search-of",
  "/admin/vault/fan-history",
  "/admin/vault/wall-media",
  "/admin/vault/media-stats",
]);

const NEW_PLACEHOLDER = "Search hashtag, note or caption";
const TILE_HINT = "Click to select · double-click to attach";

/** The vault mirror's copy of the purchased photo, with its AI overlay:
 *  four tags (the card shows three) and a description (never the note). */
const MIRROR_PHOTO = {
  ...MEDIA[0],
  _ai: { description: "Sunset walk on the beach", tags: ["beach", "sunset", "bikini", "golden hour"] },
};

/** fan-history's reply; a test swaps it to hold the request pending. */
let fanHistoryReply: () => unknown;
/** The mirror's item count: above 0, the picker serves the grid from the
 *  mirror (`/admin/vault-ai/items`) instead of the live OnlyFans path. */
let mirrorCount: number;
/** The live vault page; a test swaps it for media with files. */
let mediaReply: VaultMedia[];

beforeEach(() => {
  resetComposerHarness();
  fanHistoryReply = () => FAN_HISTORY;
  mirrorCount = 0;
  mediaReply = MEDIA;
  vi.stubGlobal("IntersectionObserver", observerStub);
  routeRelay("/admin/vault-ai/cache/summary", () => ({ account_id: "acct-1", count: mirrorCount, running: false, last_run: null }));
  routeRelay("/api/of/v2/vault/lists", () => ({ list: [], hasMore: false }));
  routeRelay("/api/of/v2/vault/media", () => ({ list: mediaReply, hasMore: false }));
  routeRelay("/admin/vault/fan-history", () => fanHistoryReply());
  routeRelay("/admin/vault/wall-media", () => ({ media_ids: [], scanned_posts: 0, has_more: false }));
  routeRelay("/admin/vault-ai/items", () => ({ list: [MIRROR_PHOTO], hasMore: false, source: "mirror" }));
});

afterEach(() => {
  cleanup();
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

function renderPicker(fanId: number | null, onConfirm: (picked: VaultMedia[]) => void = () => {}) {
  return renderWithProviders(
    <VaultPicker
      open
      onClose={() => {}}
      accountId="acct-1"
      fanId={fanId}
      initialSelectedIds={[]}
      onConfirm={onConfirm}
    />,
  );
}

/** A card, by the media id its tooltip names ("photo · 7001 · …"). */
const card = (id: number) => screen.getByTitle(new RegExp(`· ${id} ·`));

/** The tooltips of every card on screen, in grid order. */
const cardTitles = () =>
  screen.getAllByRole("button").map((b) => b.title).filter((t) => t.endsWith(TILE_HINT));

/** The tooltips of the greyed cards. */
const greyedTitles = () =>
  screen.queryAllByTestId("vault-card-greyed").map((o) => o.closest("button")!.title);

/** The open "Media details" panel, and the four price history labels. */
const detailsPanel = () => screen.getByRole("dialog", { name: "Media details" });
const HISTORY_LABELS = ["Purchased", "Sent (free or paid)", "Unsent (free or paid)", "Posted in feed"];
/** The value written next to a label in "Media details". */
const detailsValue = (label: string) => within(detailsPanel()).getByText(label).nextElementSibling;

const requestedPaths = () =>
  [...relayGet.mock.calls, ...relayPost.mock.calls].map(([path]) => path);

describe("VaultPicker with a Fan in scope", () => {
  it("requests only the relay paths it requests today", async () => {
    renderPicker(42);
    // fan-history is the last request the picker makes (gated on the first
    // vault page landing), so once it is out every request is in.
    await waitFor(() =>
      expect(requestedPaths().some((p) => p.startsWith("/admin/vault/fan-history?"))).toBe(true));

    const unknown = requestedPaths()
      .map((p) => p.split("?")[0])
      .filter((p) => !ALLOWED_PATHS.has(p));
    expect(unknown).toEqual([]);
  });

  it("says the search covers hashtags, notes and captions, and sends query= after the debounce", async () => {
    const user = userEvent.setup();
    renderPicker(42);
    const search = screen.getByPlaceholderText(NEW_PLACEHOLDER);
    const searches = () =>
      requestedPaths().filter((p) => p.startsWith("/api/of/v2/vault/media?") && p.includes("query="));

    await user.type(search, "beach");
    // Debounced: no request per keystroke, then one for the whole term.
    expect(searches()).toEqual([]);
    await waitFor(() => expect(searches()).toEqual([expect.stringContaining("query=beach")]));
  });
});

describe("VaultPicker cards with a Fan in scope", () => {
  it("greys out the purchased and free-sent cards only, and none while fan-history is pending", async () => {
    fanHistoryReply = () => new Promise(() => {});
    const pending = renderPicker(42);
    await waitFor(() =>
      expect(requestedPaths().some((p) => p.startsWith("/admin/vault/fan-history?"))).toBe(true));
    expect(screen.getAllByTitle(TILE_HINT)).toHaveLength(4);
    expect(greyedTitles()).toEqual([]);
    pending.unmount();

    fanHistoryReply = () => FAN_HISTORY;
    renderPicker(42);
    await waitFor(() => expect(greyedTitles()).toHaveLength(2));
    expect(greyedTitles()).toEqual([
      expect.stringMatching(/^photo · 7001 · /),
      expect.stringMatching(/^video · 7002 · /),
    ]);
  });

  it("shows the last price on the purchased card's pill, and the total paid in its tooltip", async () => {
    renderPicker(42);
    await waitFor(() => expect(card(7001)).toBeInTheDocument());
    const purchased = card(7001);
    expect(purchased).toHaveTextContent(/\$15(?![.\d])/);
    expect(purchased).not.toHaveTextContent("$25");
    expect(purchased.title).toContain("$25");
  });

  it("keeps a greyed card selectable: confirming passes both picks in pick order", async () => {
    const user = userEvent.setup();
    const onConfirm = vi.fn();
    renderPicker(42, onConfirm);
    await waitFor(() => expect(greyedTitles()).toHaveLength(2));

    await user.click(card(7003));
    await user.click(card(7001));
    await user.click(screen.getByRole("button", { name: "Attach" }));

    expect(onConfirm).toHaveBeenCalledTimes(1);
    expect(onConfirm.mock.calls[0][0].map((m: VaultMedia) => m.id)).toEqual([7003, 7001]);
  });

  it("opens \"Media details\" from ⓘ and leaves the selection unchanged", async () => {
    const user = userEvent.setup();
    renderPicker(42);
    await waitFor(() => expect(greyedTitles()).toHaveLength(2));
    await user.click(card(7003));
    expect(screen.getByText("1 item selected")).toBeInTheDocument();

    await user.click(within(card(7001)).getByRole("button", { name: "Media details" }));
    expect(detailsPanel()).toBeInTheDocument();
    expect(screen.getByText("1 item selected")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Close media details" }));
    expect(screen.queryByRole("dialog", { name: "Media details" })).toBeNull();
    expect(screen.getByText("1 item selected")).toBeInTheDocument();
  });

  it("shows the four price history labels, \"—\" under Unsent and the total paid under Purchased", async () => {
    const user = userEvent.setup();
    renderPicker(42);
    await waitFor(() => expect(greyedTitles()).toHaveLength(2));
    await user.click(within(card(7001)).getByRole("button", { name: "Media details" }));

    const history = within(detailsPanel()).getByRole("region", { name: "Price history" });
    expect(within(history).getAllByRole("term").map((t) => t.textContent)).toEqual(HISTORY_LABELS);
    expect(detailsValue("Unsent (free or paid)")).toHaveTextContent(/^—$/);
    expect(detailsValue("Purchased")).toHaveTextContent(/ · \$25$/);
  });

  it("opens \"Media details\" at the price history from the price pill", async () => {
    const scrollIntoView = vi.fn();
    // jsdom has no scrollIntoView; the spy records which element was scrolled to.
    Object.defineProperty(HTMLElement.prototype, "scrollIntoView", { value: scrollIntoView, configurable: true });
    onTestFinished(() => { delete (HTMLElement.prototype as { scrollIntoView?: unknown }).scrollIntoView; });
    const user = userEvent.setup();
    renderPicker(42);
    await waitFor(() => expect(greyedTitles()).toHaveLength(2));

    // ⓘ opens at the top: nothing is scrolled to.
    await user.click(within(card(7001)).getByRole("button", { name: "Media details" }));
    expect(scrollIntoView).not.toHaveBeenCalled();
    await user.click(screen.getByRole("button", { name: "Close media details" }));

    await user.click(within(card(7001)).getByRole("button", { name: "$15" }));
    const history = within(detailsPanel()).getByRole("region", { name: "Price history" });
    expect(scrollIntoView).toHaveBeenCalledTimes(1);
    expect(scrollIntoView.mock.contexts[0]).toBe(history);
    expect(screen.getByText("No items selected")).toBeInTheDocument();
  });

  it("shows up to three of a mirror item's AI tags and an empty notes slot; live media shows no tags", async () => {
    const live = renderPicker(42);
    await waitFor(() => expect(greyedTitles()).toHaveLength(2));
    expect(screen.queryAllByRole("list", { name: "Tags" })).toEqual([]);
    live.unmount();

    mirrorCount = 1;
    renderPicker(42);
    await waitFor(() => expect(card(7001)).toBeInTheDocument());
    const photo = card(7001);
    const tags = within(photo).getByRole("list", { name: "Tags" });
    expect(within(tags).getAllByRole("listitem").map((t) => t.textContent)).toEqual(["beach", "sunset", "bikini"]);
    expect(within(photo).getByTestId("vault-card-notes")).toBeEmptyDOMElement();
    expect(photo).not.toHaveTextContent("Sunset walk on the beach");
  });

  it("narrows the loaded cards by length on the client, hiding non-videos", async () => {
    const user = userEvent.setup();
    renderPicker(42);
    await waitFor(() => expect(greyedTitles()).toHaveLength(2));
    const length = screen.getByRole("combobox", { name: "Filter by length" });
    expect([...length.querySelectorAll("option")].map((o) => o.textContent))
      .toEqual(["Any length", "Under 1 min", "1–5 min", "Over 5 min"]);
    const requests = requestedPaths().length;

    await user.selectOptions(length, "1–5 min");
    expect(cardTitles()).toEqual([expect.stringMatching(/^video · 7003 · /)]);
    await user.selectOptions(length, "Under 1 min");
    expect(cardTitles()).toEqual([expect.stringMatching(/^video · 7002 · /)]);
    // 7004 was never sent to this Fan, so its tooltip is the bare hint.
    await user.selectOptions(length, "Over 5 min");
    expect(cardTitles()).toEqual([TILE_HINT]);
    await user.selectOptions(length, "Any length");
    expect(cardTitles()).toHaveLength(4);
    expect(requestedPaths()).toHaveLength(requests);
  });

  it("puts a disabled \"not wired\" unsend on the cards already sent to this Fan only", async () => {
    const user = userEvent.setup();
    renderPicker(42);
    await waitFor(() => expect(greyedTitles()).toHaveLength(2));

    const unsends = screen.getAllByRole("button", { name: "Unsend" });
    expect(unsends.map((u) => u.closest("button")!.title)).toEqual([
      expect.stringMatching(/^photo · 7001 · /),
      expect.stringMatching(/^video · 7002 · /),
      expect.stringMatching(/^video · 7003 · /),
    ]);
    for (const u of unsends) {
      expect(u).toHaveAttribute("aria-disabled", "true");
      expect(u).toHaveAttribute("title", `not wired: ${NOT_WIRED.vaultUnsend}`);
    }
    await user.click(unsends[0]);
    expect(screen.getByText("No items selected")).toBeInTheDocument();
  });
});

describe("VaultPicker with no Fan", () => {
  it("keeps today's search placeholder and adds no overlay, ⓘ, length filter, unsend, tags or notes", async () => {
    renderPicker(null);
    expect(screen.queryByPlaceholderText(NEW_PLACEHOLDER)).toBeNull();
    expect(screen.getByPlaceholderText("Search vault…")).toBeInTheDocument();
    await waitFor(() => expect(screen.getAllByTitle(TILE_HINT)).toHaveLength(4));
    expect(greyedTitles()).toEqual([]);
    expect(screen.queryAllByRole("button", { name: "Media details" })).toEqual([]);
    expect(screen.queryByRole("combobox", { name: "Filter by length" })).toBeNull();
    expect(screen.queryAllByRole("button", { name: "Unsend" })).toEqual([]);
    expect(screen.queryAllByRole("list", { name: "Tags" })).toEqual([]);
    expect(screen.queryAllByTestId("vault-card-notes")).toEqual([]);
  });
});

/* ── hover enlarge, range select and keyboard (no Fan: every title is the hint) ── */

const HOVER_MEDIA: VaultMedia[] = [
  {
    id: 7101, type: "photo", isReady: true, canView: true,
    files: {
      thumb: { url: "https://cdn.example/7101-thumb.jpg" },
      preview: { url: "https://cdn.example/7101-preview.jpg" },
      full: { url: "https://cdn.example/7101-full.jpg" },
    },
  },
  {
    id: 7102, type: "video", isReady: true, canView: true, duration: 30,
    files: { thumb: { url: "https://cdn.example/7102-thumb.jpg" } },
    videoSources: { "240": "https://cdn.example/7102-240.mp4" },
  },
  {
    id: 7103, type: "photo", isReady: true, canView: true,
    files: { thumb: { url: "https://cdn.example/7103-thumb.jpg" } },
  },
];

/** The cards in grid order (with no Fan, every card's title is the hint). */
const tiles = () => screen.getAllByTitle(TILE_HINT);
const photoPreview = () => screen.queryByAltText("Photo preview");
const selectedText = () => screen.getByText(/items? selected$/).textContent;
const confirmedIds = (onConfirm: ReturnType<typeof vi.fn>) =>
  onConfirm.mock.calls[0][0].map((m: VaultMedia) => m.id);

async function renderLoaded(onConfirm: (picked: VaultMedia[]) => void = () => {}) {
  renderPicker(null, onConfirm);
  await waitFor(() => expect(tiles()).toHaveLength(mediaReply.length));
}

describe("VaultPicker hover preview", () => {
  it("enlarges a hovered photo with its preview url only after the dwell, and closes on leave", async () => {
    mediaReply = HOVER_MEDIA;
    await renderLoaded();
    vi.useFakeTimers();

    fireEvent.mouseEnter(tiles()[0]);
    act(() => { vi.advanceTimersByTime(399); });
    expect(photoPreview()).toBeNull();
    act(() => { vi.advanceTimersByTime(1); });
    expect(photoPreview()).not.toBeNull();
    expect(photoPreview()!.getAttribute("src")).toContain(encodeURIComponent("https://cdn.example/7101-preview.jpg"));

    fireEvent.mouseLeave(tiles()[0]);
    expect(photoPreview()).toBeNull();
  });

  it("falls back to the thumbnail, closes on scroll and on Esc, and never blocks a click", async () => {
    mediaReply = HOVER_MEDIA;
    await renderLoaded();
    vi.useFakeTimers();

    fireEvent.mouseEnter(tiles()[2]);
    act(() => { vi.advanceTimersByTime(400); });
    expect(photoPreview()!.getAttribute("src")).toContain(encodeURIComponent("https://cdn.example/7103-thumb.jpg"));
    fireEvent.click(tiles()[2]);
    expect(selectedText()).toBe("1 item selected");

    fireEvent.scroll(tiles()[2].closest(".overflow-y-auto")!);
    expect(photoPreview()).toBeNull();

    fireEvent.mouseLeave(tiles()[2]);
    fireEvent.mouseEnter(tiles()[0]);
    act(() => { vi.advanceTimersByTime(400); });
    expect(photoPreview()).not.toBeNull();
    fireEvent.keyDown(document, { key: "Escape" });
    expect(photoPreview()).toBeNull();
  });

  it("still plays the video storyboard after the dwell", async () => {
    vi.stubGlobal("fetch", vi.fn(() => Promise.resolve(new Response(null))));
    mediaReply = HOVER_MEDIA;
    await renderLoaded();
    vi.useFakeTimers();
    const scrubFrames = () => document.querySelectorAll('img[src^="/img/scrub?"]');

    fireEvent.mouseEnter(tiles()[1]);
    act(() => { vi.advanceTimersByTime(399); });
    expect(scrubFrames()).toHaveLength(0);
    act(() => { vi.advanceTimersByTime(1); });
    expect(scrubFrames()).toHaveLength(12);
    expect(photoPreview()).toBeNull();

    fireEvent.mouseLeave(tiles()[1]);
    expect(scrubFrames()).toHaveLength(0);
  });
});

describe("VaultPicker range select and keyboard", () => {
  it("says how to range-select and move", async () => {
    await renderLoaded();
    expect(screen.getByText(/Shift-click for a range · arrows to move/)).toBeInTheDocument();
  });

  it("shift-click selects every card between the anchor and the target", async () => {
    const user = userEvent.setup();
    const onConfirm = vi.fn();
    await renderLoaded(onConfirm);

    await user.click(tiles()[0]);
    await user.keyboard("{Shift>}");
    await user.click(tiles()[2]);
    await user.keyboard("{/Shift}");
    expect(selectedText()).toBe("3 items selected");
    await user.click(screen.getByRole("button", { name: "Attach" }));
    expect(confirmedIds(onConfirm)).toEqual([7001, 7002, 7003]);
  });

  it("shift-click adds the range to an existing selection", async () => {
    const user = userEvent.setup();
    const onConfirm = vi.fn();
    await renderLoaded(onConfirm);

    await user.click(tiles()[3]);
    await user.click(tiles()[0]);
    await user.keyboard("{Shift>}");
    await user.click(tiles()[2]);
    await user.keyboard("{/Shift}");
    expect(selectedText()).toBe("4 items selected");
    await user.click(screen.getByRole("button", { name: "Attach" }));
    expect(confirmedIds(onConfirm)).toEqual([7004, 7001, 7002, 7003]);
  });

  it("arrow keys move the focus ring and Space toggles the focused card", async () => {
    const user = userEvent.setup();
    await renderLoaded();

    await user.click(tiles()[0]);
    await user.keyboard("{ArrowRight}");
    expect(document.activeElement).toBe(tiles()[1]);
    expect(selectedText()).toBe("1 item selected");

    await user.keyboard(" ");
    expect(selectedText()).toBe("2 items selected");
    await user.keyboard(" ");
    expect(selectedText()).toBe("1 item selected");

    await user.keyboard("{ArrowLeft}");
    expect(document.activeElement).toBe(tiles()[0]);
  });

  it("Shift+arrow extends the range from the anchor", async () => {
    const user = userEvent.setup();
    await renderLoaded();

    await user.click(tiles()[1]);
    await user.keyboard("{Shift>}{ArrowRight}{ArrowRight}{/Shift}");
    expect(document.activeElement).toBe(tiles()[3]);
    expect(selectedText()).toBe("3 items selected");
  });

  it("Cmd+A and Ctrl+A select every loaded card", async () => {
    const user = userEvent.setup();
    await renderLoaded();

    act(() => tiles()[0].focus());
    await user.keyboard("{Meta>}a{/Meta}");
    expect(selectedText()).toBe("4 items selected");
    await user.click(tiles()[0]);
    await user.keyboard("{Control>}a{/Control}");
    expect(selectedText()).toBe("4 items selected");
  });

  it("Enter attaches the focused card when nothing is selected, else the selection", async () => {
    const user = userEvent.setup();
    const onConfirm = vi.fn();
    const first = renderPicker(null, onConfirm);
    await waitFor(() => expect(tiles()).toHaveLength(4));
    act(() => tiles()[2].focus());
    await user.keyboard("{Enter}");
    expect(onConfirm).toHaveBeenCalledTimes(1);
    expect(confirmedIds(onConfirm)).toEqual([7003]);
    first.unmount();

    const onConfirm2 = vi.fn();
    await renderLoaded(onConfirm2);
    await user.click(tiles()[0]);
    await user.keyboard("{ArrowRight}{Enter}");
    expect(onConfirm2).toHaveBeenCalledTimes(1);
    expect(confirmedIds(onConfirm2)).toEqual([7001]);
  });

  it("keys typed in the search input neither move the focus nor select", async () => {
    const user = userEvent.setup();
    const onConfirm = vi.fn();
    await renderLoaded(onConfirm);
    const search = screen.getByPlaceholderText("Search vault…");

    await user.click(search);
    await user.keyboard("{ArrowRight}{ArrowDown} {Meta>}a{/Meta}{Control>}a{/Control}{Enter}");
    expect(document.activeElement).toBe(search);
    expect(screen.getByText("No items selected")).toBeInTheDocument();
    expect(onConfirm).not.toHaveBeenCalled();
  });

  it("double-click still attaches the card", async () => {
    const user = userEvent.setup();
    const onConfirm = vi.fn();
    await renderLoaded(onConfirm);

    await user.dblClick(tiles()[1]);
    expect(onConfirm).toHaveBeenCalledTimes(1);
    expect(confirmedIds(onConfirm)).toEqual([7002]);
  });
});
