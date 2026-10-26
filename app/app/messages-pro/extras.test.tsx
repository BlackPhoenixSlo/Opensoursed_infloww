/**
 * The extras audit: docs/spec/phase-07-ours-kept-marked.md, Testing
 * Decisions. The Messages Pro tree opens through the Deep link for one
 * fixture Creator and Fan. The Fan List, the Thread (ChatSurface)
 * and Fan insights render for real; the relay client is mocked by path
 * through the shared harness (`components/chat/composerTestHarness.tsx`), the
 * session contexts are stubbed as `page.render.test.tsx` stubs them, and the
 * browser APIs jsdom lacks are stubbed. Phase 0's `windowed.test.tsx`
 * exports no fixture, so this file writes its own.
 *
 * The reach routine opens one host at a time, so each labelled element is
 * attributed to the host that revealed it. Ticket 122 checks the spec's
 * assertions 1, 4, 7 and 9; ticket 123 the New menu host; ticket 124
 * assertions 2, 5 and 6 (Group chat) for
 * the Window header, Fan tabs, Fan List, Chat header and Kebab menu hosts;
 * ticket 125 runs them over the whole tree, the Composer and Fan insights
 * included.
 *
 * Fixture identifiers are invented (this repo mirrors to a public one).
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, screen, within } from "@testing-library/react";
import userEvent, { type UserEvent } from "@testing-library/user-event";

vi.mock("@/lib/relay", async (orig) =>
  (await import("@/components/chat/composerTestHarness")).mockRelayModule(await orig()));

// Assertion 6: the group-tab opener, spied on by module path. It answers as
// it does inside /group, so a click opens no window.
vi.mock("@/lib/groupChannel", async (orig) => ({
  ...(await orig<typeof import("@/lib/groupChannel")>()),
  openGroupTab: vi.fn(async () => ({ kind: "self" as const })),
}));

const router = vi.hoisted(() => ({
  push: vi.fn(), replace: vi.fn(), back: vi.fn(), forward: vi.fn(), prefetch: vi.fn(),
}));
vi.mock("next/navigation", () => ({
  useRouter: () => router,
  usePathname: () => "/",
  useSearchParams: () => new URLSearchParams(),
  useParams: () => ({}),
  redirect: vi.fn(),
  notFound: vi.fn(),
}));

// An owner signed in, no chatter, no Employee (as windowed.test.tsx stubs them).
vi.mock("@/contexts/UserContext", async (orig) => {
  const value = { user: { username: "owner" }, logout: vi.fn() };
  return { ...(await orig<typeof import("@/contexts/UserContext")>()), useUser: () => value, useOptionalUser: () => value };
});
vi.mock("@/contexts/ChatterContext", async (orig) => {
  const value = { chatter: null, logout: vi.fn() };
  return { ...(await orig<typeof import("@/contexts/ChatterContext")>()), useChatter: () => value, useOptionalChatter: () => value };
});
vi.mock("@/contexts/EmployeeContext", async (orig) => {
  const value = { current: null, hydrated: true, pickedId: null, clear: vi.fn() };
  return { ...(await orig<typeof import("@/contexts/EmployeeContext")>()), useEmployee: () => value };
});

import { ScopeProvider } from "@/contexts/ScopeContext";
import { renderWithProviders } from "@/test-utils";
import { resetRosterCountsModuleState } from "@/hooks/useRosterCounts";
import { observerStub, resetComposerHarness, routeRelay } from "@/components/chat/composerTestHarness";
import { openGroupTab } from "@/lib/groupChannel";
import { EXTRA_LABEL, EXTRAS, EXTRAS_OVERFLOW_LABEL, type ExtraName } from "@/lib/openinflowwwwExtras";
import DeepLinkPage from "./[accountId]/[fanId]/page";

/* ── fixtures: one Creator, one Fan ─────────────────────────────────────── */

const ACCOUNT_ID = "100000001";
const CREATOR = { id: 100000001, name: "Test Creator", username: "testcreator", avatar: null };
const FAN = { id: 200000001, name: "Fixture Fan One", username: "fixturefanone" };
const ago = (min: number) => new Date(Date.now() - min * 60_000).toISOString();
const ahead = (min: number) => new Date(Date.now() + min * 60_000).toISOString();
const fanUser = { ...FAN, avatar: null, customNickname: null, displayName: null };
const ACCOUNT = {
  id: ACCOUNT_ID, nickname: "Test Creator", name: "Test Creator", platform: "onlyfans",
  color: "#e8618c", has_session: true, session_dead_at: null, created_at: ago(43_200), last_used_at: ago(5),
};
const THREAD_TEXT = "Fixture thread opener";
/** Newest first, as OnlyFans answers. The Fan's last message is the Fan's
 *  own; before it, one incoming tip, whose Bubble action row must hold no
 *  Reward control (ticket 145's Tip reward, vetoed by the human 2026-10-15). */
const THREAD = [{
  id: 900000001, text: THREAD_TEXT, fromUser: fanUser, toUser: CREATOR,
  createdAt: ago(30), isFree: true, isOpened: true, isTip: false, price: 0,
  media: [], mediaCount: 0, isLiked: false, isPinned: false,
}, {
  id: 900000002, text: "Fixture tip", fromUser: fanUser, toUser: CREATOR,
  createdAt: ago(40), isFree: true, isOpened: true, isTip: true, price: 0,
  media: [], mediaCount: 0, isLiked: false, isPinned: false,
}];
const CHATS = [{
  withUser: fanUser,
  lastMessage: {
    id: 800000001, text: THREAD_TEXT, fromUser: fanUser, createdAt: ago(30),
    mediaCount: 0, isFree: true, isTip: false, isOpened: true,
  },
  hasUnread: false, unreadMessagesCount: 0, isOnline: false,
  canSendMessage: true, canNotSendReason: null, isMutedNotifications: false,
}];
/** FanRecord in lib/relay.ts, empty but for the identity fields. */
const FAN_RECORD = {
  account_id: ACCOUNT_ID, fan_id: FAN.id, of_username: FAN.username, of_display_name: FAN.name,
  custom_nickname: null, generated_nickname: null, real_name: null, his_age: null, home_country: null,
  home_city: null, hobbies: null, fetishes: null, self_description: null, description: null, notes: null,
  subscription_status: null, subscribed_at: null, language: null, language_source: null,
  avatar_url: null, tags: [], lifetime_spend_cents: 0, bought_amount: 0,
  last_message_received_at: ago(30), source: "test", is_followed: false, created_at: ago(43_200), updated_at: ago(30),
};
/** One direct queued send to the Fan (the Scheduled chip's queue). */
const DIRECT_QUEUED = {
  type: "chat", publishDateTime: ahead(120),
  entity: { id: 700000001, text: "Fixture queued send", price: 0, mediaCount: 0, media: [], userIds: [FAN.id] },
};
/** The server-scheduled job: a human's `scheduled_send`. */
const JOBS = [
  { job_id: 610000001, kind: "scheduled_send", fan_id: FAN.id, run_at: ahead(30), status: "pending", text: "Fixture timed message" },
];
/** One unsold PPV sent to the Fan. */
const UNSOLD_PPV = {
  id: 601000001, text: "Fixture unsold pitch", price: 15, isFree: false, isOpened: false, isFromQueue: false,
  mediaCount: 1, createdAt: ago(600),
  media: [{ id: 602000001, type: "photo", files: { thumb: { url: "https://cdn.test/u-thumb.jpg" } } }],
};
/** One vault media item. */
const VAULT_ITEM = {
  id: 910000001, type: "photo", createdAt: ago(1440), canView: true, hasError: false, isReady: true,
  files: { thumb: { url: "https://cdn.test/v-thumb.jpg" } },
};

/** The relay as the tree asks it, by path; anything else answers empty. */
function serveFixture() {
  routeRelay("/admin/accounts", () => ({ accounts: [ACCOUNT], active_account_id: ACCOUNT_ID }));
  routeRelay(`/api/of/v2/chats/${FAN.id}/messages`, () => ({ list: THREAD, hasMore: false }));
  routeRelay(`/api/of/v2/chats/${FAN.id}/media`, (path) =>
    ({ list: path.includes("purchased=1") ? [] : [UNSOLD_PPV], hasMore: false }));
  routeRelay("/api/of/v2/chats?", (path) => {
    const q = new URLSearchParams(path.split("?")[1]);
    const first = (q.get("offset") ?? "0") === "0" && !q.get("filter") && !q.get("query") && !q.get("list_id");
    return { list: first ? CHATS : [], hasMore: false };
  });
  routeRelay("/api/of/v2/users/list", () => ({ [String(FAN.id)]: fanUser }));
  routeRelay(`/api/of/v2/users/${FAN.id}`, () => fanUser);
  routeRelay("/api/of/v2/schedules", () => ({ list: [DIRECT_QUEUED] }));
  routeRelay("/api/of/v2/scheduled-sends", () => ({ list: JOBS }));
  routeRelay("/api/of/v2/vault/media", () => ({ list: [VAULT_ITEM], hasMore: false }));
  routeRelay(`/admin/fans/${ACCOUNT_ID}/${FAN.id}/ppv-history`, () => ({
    items: [], summary: { count: 0, max_cents: 0, avg_cents: 0, tips_cents: 0, messages_cents: 0, posts_cents: 0 },
  }));
  routeRelay(`/admin/fans/${ACCOUNT_ID}/${FAN.id}`, () => FAN_RECORD);
  // One error in the last 24h: the error badge hides at zero.
  routeRelay("/admin/errors", () => ({ count: 1, since_hours: 24, list: [] }));
  routeRelay("/", () => ({ list: [], items: [], rows: [], hasMore: false, next_cursor: null }));
}

/* ── jsdom gaps ─────────────────────────────────────────────────────────── */

function stubDesktop() {
  window.matchMedia = ((query: string) => {
    const min = /min-width:\s*(\d+)px/.exec(query);
    const max = /max-width:\s*(\d+)px/.exec(query);
    const matches = (!min || 1440 >= Number(min[1])) && (!max || 1440 <= Number(max[1])) && !!(min || max);
    return {
      matches, media: query, onchange: null,
      addEventListener: vi.fn(), removeEventListener: vi.fn(),
      addListener: vi.fn(), removeListener: vi.fn(), dispatchEvent: vi.fn(),
    };
  }) as unknown as typeof window.matchMedia;
}
class FakeEventSource {
  static CONNECTING = 0;
  static OPEN = 1;
  static CLOSED = 2;
  readyState = 0;
  onopen: unknown = null;
  onmessage: unknown = null;
  onerror: unknown = null;
  addEventListener() {}
  removeEventListener() {}
  close() {}
}
// For the whole file: a scope change schedules the SSE bus's reconnect
// (lib/events.ts setScope), which may fire after a case's teardown.
Object.defineProperty(globalThis, "EventSource", { value: FakeEventSource, configurable: true, writable: true });

beforeEach(() => {
  resetComposerHarness();
  resetRosterCountsModuleState();
  serveFixture();
  stubDesktop();
  vi.mocked(openGroupTab).mockClear();
  Element.prototype.scrollIntoView = vi.fn();
  vi.stubGlobal("IntersectionObserver", observerStub);
  vi.stubGlobal("ResizeObserver", observerStub);
});

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

/* ── render ─────────────────────────────────────────────────────────────── */

/** Messages Pro through the Deep link for the fixture Creator and Fan,
 *  waited to loaded state: the Thread, the Fan List row and the
 *  server-scheduled row. */
async function renderMessagesPro() {
  const url = `/messages-pro/${ACCOUNT_ID}/${FAN.id}`;
  window.history.replaceState(null, "", url);
  const value = { accountId: ACCOUNT_ID, fanId: String(FAN.id) };
  const params = Object.assign(Promise.resolve(value), { status: "fulfilled", value });
  renderWithProviders(
    <ScopeProvider>
      <DeepLinkPage params={params} />
    </ScopeProvider>,
  );
  expect((await screen.findAllByText(THREAD_TEXT)).length).toBeGreaterThan(0);
  await screen.findByText(/⏱ scheduled ·/);
}

/** Every Extras overflow trigger, in document order. */
const triggers = () => screen.queryAllByRole("button", { name: EXTRAS_OVERFLOW_LABEL });

/** Elements whose tooltip starts with "Inflowwww extra". */
const labelled = (root: ParentNode = document) =>
  [...root.querySelectorAll<HTMLElement>(`[title^="${EXTRA_LABEL}"]`)];

/** The labelled elements under `root` that hold no labelled element and
 *  show something (text or a control): the extras themselves, not a wrapper
 *  whose title only its items inherit, nor an empty labelled box. */
const labelledLeaves = (root: ParentNode) =>
  labelled(root).filter((el) => labelled(el).length === 0 &&
    (!!el.textContent?.trim() || !!el.querySelector("button, input, select, textarea, a, [role]")));

/** What an opened trigger reveals: the element its `aria-controls` names. */
function revealedBy(trigger: HTMLElement): HTMLElement {
  const id = trigger.getAttribute("aria-controls");
  const el = id ? document.getElementById(id) : null;
  if (!el) throw new Error("an open Extras overflow trigger names no revealed element");
  return el;
}

/** The Region an element (an extra, an Extras overflow trigger) sits in.
 *  Fan insights renders its pinned pane and its slide-over both (CSS picks
 *  one), so its extras show twice; the slide-over sits inside the Thread. */
function regionOf(el: HTMLElement): string {
  if (el.closest('[aria-label="Window header"]')) return "Window header";
  if (el.closest('[aria-label="Fan tabs"]')) return "Fan tabs";
  if (el.closest('[aria-label="Fan insights"]')) return "Fan insights";
  if (el.closest('[data-mp-pane="fan-list"]')) return "Fan List";
  if (el.closest("[data-composer-area]")) return "Composer";
  if (el.closest('[data-mp-pane="thread"] header')) return "Chat header";
  if (el.closest('[data-mp-pane="thread"]')) return "Message list";
  return "outside every Region";
}

/** Fan insights' pinned pane, the one a desktop shows: the audit reads Fan
 *  insights there, so the slide-over's copy is not counted twice. */
const pinnedInsights = () => document.querySelector<HTMLElement>('[data-mp-pane="insights"]');

/** One host of the reach routine: its name, and (for an Extras overflow) the
 *  element it revealed, which may hold extras. */
type Visit = { host: string; overflow: HTMLElement | null };

/** The Kebab menu, a plain box: found through its "Hide chats" row (as
 *  `ChatHeader.test.tsx` finds it). */
const kebabMenu = () => screen.getByRole("button", { name: /Hide chats/ }).parentElement!;

/** Waits for what a visit shows to load: the Scheduled chip's count (its
 *  old tooltip names it) and Fan insights' Fan record. */
async function settle({ host, overflow }: Visit) {
  const insights = pinnedInsights();
  if (host === "the Chat header Extras overflow") {
    await within(overflow!).findByRole("button", { name: /^Scheduled \d/ });
  } else if (host === "Fan insights, Insights tab") {
    await within(insights!).findByRole("region", { name: "Notes" });
  } else if (host === "Fan insights, Notes tab") {
    await within(insights!).findByRole("region", { name: "Creator notes" });
  }
}

/**
 * The reach routine: opens every host that can hold an extra, one at a time,
 * calling `visit` with each open (once it has loaded), then closes it. First
 * the page as loaded (no host open), then Fan insights on its Insights and
 * Notes tabs, then each "Inflowwww extras" trigger in turn, the Fan List's
 * New menu and sort menu and the Kebab, then the Chat header Extras overflow
 * through the Kebab's last row, "Inflowwww extras ▸" (ticket 140).
 */
async function reach(user: UserEvent, show: (v: Visit) => void | Promise<void>) {
  const visit = async (v: Visit) => { await settle(v); await show(v); };
  await visit({ host: "no host open", overflow: null });

  const insightsToggle = screen.getAllByRole("button", { name: "Fan insights" })
    .find((b) => !b.closest("aside"))!;
  await user.click(insightsToggle);
  const insights = await screen.findByRole("complementary", { name: "Fan insights" })
    .catch(() => screen.getByRole("dialog", { name: "Fan insights" }));
  const tabs = within(insights).getByRole("tablist", { name: "Fan insights tabs" });
  await visit({ host: "Fan insights, Insights tab", overflow: null });
  await user.click(within(tabs).getAllByRole("tab").find((t) => /Notes/.test(t.textContent ?? ""))!);
  await visit({ host: "Fan insights, Notes tab", overflow: null });
  await user.click(within(tabs).getAllByRole("tab").find((t) => /Insights/.test(t.textContent ?? ""))!);

  const all = triggers();
  for (let i = 0; i < all.length; i++) {
    const trigger = triggers()[i];
    await user.click(trigger);
    await visit({ host: `the ${regionOf(trigger)} Extras overflow`, overflow: revealedBy(trigger) });
    await user.click(trigger);
  }

  const newButton = screen.getByRole("button", { name: "New" });
  await user.click(newButton);
  await visit({ host: "New menu", overflow: null });
  await user.click(newButton);

  // The extra sort orders, in plain view since the Fan List lost its "+"
  // (ADR-0003 amended 2026-10-26).
  const sort = screen.getByRole("button", { name: /^Sort: / });
  await user.click(sort);
  await visit({ host: "Sort menu", overflow: null });
  await user.click(sort);

  const kebab = screen.getByRole("button", { name: "More actions" });
  await user.click(kebab);
  await visit({ host: "Kebab", overflow: null });
  const row = within(kebabMenu()).getByRole("button", { name: EXTRAS_OVERFLOW_LABEL });
  await user.click(row);
  await visit({ host: `the ${regionOf(row)} Extras overflow`, overflow: revealedBy(row) });
  // A pointer-down outside closes the submenu and the Kebab menu both.
  await user.click(document.body);
  expect(screen.queryByRole("button", { name: /Hide chats/ })).toBeNull();
}

/* ── assertion 4's table: each extra's pre-parity identity ──────────────── */

/** The Gap tables' Today column at `1387781`: a title or a visible text each
 *  extra carried before the parity work. Extras that were not in Messages Pro
 *  then (the ones Phases 4 and 5 hand over, but for the old Unsold PPVs
 *  heading) have none. "tooltip" marks the extra's own old
 *  tooltip, which assertion 5 reads as its tooltip's second line (ticket 124
 *  marks those of its Regions: `git show 1387781:app/components/chat/`
 *  `ChatList.tsx` :812-817 and :878, `ChatSurface.tsx` :942-944 and :1258,
 *  `ScheduledForChat.tsx` :55, and
 *  `git show 1387781:app/components/inbox/` `AccountRosterIcon.tsx` :226; ticket 125 the stepper's
 *  own title, `Composer.tsx` :634; Fan insights' extras had none of their
 *  own, `FanDrawer.tsx`). */
const OLD_IDENTITIES: ReadonlyArray<readonly [ExtraName, string, "tooltip"?]> = [
  ["Scheduled chip", "1 scheduled for this fan — click to view/cancel", "tooltip"],
  ["Owe reply", "↩ Owe reply"],
  ["Owe reply", "Chats where the fan sent the last message and we haven't replied", "tooltip"],
  ["Group chat", "Add to group chat tab", "tooltip"],
  ["All Models", "All models", "tooltip"],
  ["Generated profile note", "AI profile"],
  ["Persona claims", "Correct what this fan was told — this is what the prompt reads"],
  ["Mass exclude", "Add to MASSdmEXCLUDE"],
  ["Mark as unread", "Mark as unread"],
  ["Phone focus", "👁 focus"],
  ["Phone focus", "Focus mode — hide the AI status strip and header tools to give the conversation the full screen", "tooltip"],
  ["Phone focus", "Focus mode ON — AI status & header tools hidden for more thread space. Tap to turn off.", "tooltip"],
  ["Unsold PPVs", "Unsold PPVs sent"],
  ["Extra sort orders", "Amount spent"],
  ["Extra sort orders", "Spend + unread on top"],
  ["Extra sort orders", "Unread → owe-reply → idle, spend desc within each tier", "tooltip"],
  ["Extra sort orders", "Spend + recency"],
  ["Extra sort orders", "Spend × decay. Half-life: idle 1h, owe-reply 2h, unread 3h. Below $3 effective, unread wins.", "tooltip"],
];

/** An extra's old tooltips: its second line must be one of them. */
const oldTooltips = (name: string) =>
  OLD_IDENTITIES.filter(([n, , kind]) => n === name && kind === "tooltip").map(([, identity]) => identity);

/** Elements carrying `identity` as their title or as their whole text. */
function carriers(identity: string): HTMLElement[] {
  return [...document.body.querySelectorAll<HTMLElement>("*")].filter((el) =>
    el.getAttribute("title") === identity ||
    el.getAttribute("aria-label") === identity ||
    (el.childElementCount === 0 && el.textContent?.trim() === identity));
}

/** A readable name for where `el` sits. */
const where = (el: HTMLElement) =>
  `<${el.tagName.toLowerCase()}> "${(el.textContent ?? "").trim().slice(0, 40)}" in ${
    el.closest("[aria-label]")?.getAttribute("aria-label") ?? "the page"}`;

/* ── the top rows, the Fan List, the Chat header and the Kebab menu ────── */

/** The name on an extra's tooltip's first line, "Inflowwww extra — <name>"
 *  (the whole first line if it has another form). */
function extraNameOf(el: HTMLElement): string {
  const first = (el.getAttribute("title") ?? "").split("\n")[0];
  const prefix = `${EXTRA_LABEL} — `;
  return first.startsWith(prefix) ? first.slice(prefix.length) : first;
}

/** The catalogued names. */
const NAMES: ReadonlySet<string> = new Set(EXTRAS.map((e) => e.name));

/** The extras (labelled leaves other than a trigger) under `root`. */
const extrasIn = (root: ParentNode) =>
  labelledLeaves(root).filter((el) => el.getAttribute("title") !== EXTRAS_OVERFLOW_LABEL);

/** The extras one visit shows, each with its host. With no host open, every
 *  extra on the page, at its Region; on Fan insights' tabs, those in its
 *  pinned pane; then those an Extras overflow, the New menu, the sort menu
 *  or the Kebab reveals. */
function extrasOf({ host, overflow }: Visit): Array<[HTMLElement, string]> {
  const at = (root: ParentNode, as: string) => extrasIn(root).map((el) => [el, as] as [HTMLElement, string]);
  if (host === "no host open") return extrasIn(document).map((el) => [el, regionOf(el)]);
  if (host.startsWith("Fan insights, ")) return at(pinnedInsights()!, "Fan insights");
  const region = /^the (.+) Extras overflow$/.exec(host)?.[1];
  if (overflow && region) return at(overflow, `${region} overflow`);
  if (host === "New menu") return at(screen.getByRole("region", { name: "New" }), "New menu");
  if (host === "Sort menu") return at(screen.getByRole("region", { name: "Sort" }), "Fan List sort menu");
  if (host === "Kebab") return at(kebabMenu(), "Kebab");
  return [];
}

/* ── the audit ──────────────────────────────────────────────────────────── */

// The reach routine opens every host in turn: about 2s alone, over the 5s default under the full suite's parallel load.
describe("the extras audit", { timeout: 20_000 }, () => {
  it("1: no host open: no \"Inflowwww extras\" trigger shows, and only the Window header's All Models (TODO.md B2) and the Fan List's Priority chip (page-parity 07) and Owe reply chip (ADR-0003 amended 2026-10-26) have a tooltip starting with \"Inflowwww extra\"", async () => {
    await renderMessagesPro();
    // The Fan List's "+" was the last trigger in plain view; the Chat
    // header's is the Kebab's last row (ticket 140).
    expect(triggers()).toEqual([]);
    const allModels = screen.getByRole("button", { name: "All Models" });
    expect(allModels).toHaveAttribute("title", `${EXTRA_LABEL} — All Models\nAll models`);
    expect(regionOf(allModels)).toBe("Window header");
    const fanList = within(document.querySelector<HTMLElement>('[data-mp-pane="fan-list"]')!);
    const priority = fanList.getByRole("button", { name: "Priority" });
    expect(priority).toHaveAttribute("title", `${EXTRA_LABEL} — Priority chip`);
    expect(regionOf(priority)).toBe("Fan List");
    const oweReply = fanList.getByRole("button", { name: /^Owe reply\b/ });
    expect(oweReply).toHaveAttribute("title", `${EXTRA_LABEL} — Owe reply\nChats where the fan sent the last message and we haven't replied`);
    expect(regionOf(oweReply)).toBe("Fan List");
    expect(labelled().filter((el) => ![allModels, priority, oweReply].includes(el)).map(where)).toEqual([]);
  });

  it("4: no pre-parity identity shows outside an opened Extras overflow, through the whole reach routine, but for Fan insights' extras in Fan insights (its Insights blocks, ADR-0003 amended 2026-10-21) and the extra sort orders in the Fan List's sort menu (ADR-0003 amended 2026-10-26)", async () => {
    const user = userEvent.setup();
    await renderMessagesPro();
    const leaks: string[] = [];
    const hostsOf = (name: ExtraName) => EXTRAS.find((e) => e.name === name)!.hosts as readonly string[];
    const inFanInsights = (name: ExtraName, el: HTMLElement) =>
      (hostsOf(name).includes("Fan insights") && regionOf(el) === "Fan insights") ||
      (hostsOf(name).includes("Fan List sort menu") && !!el.closest('[aria-label="Sort"]'));
    await reach(user, ({ host, overflow }) => {
      for (const [name, identity] of OLD_IDENTITIES) {
        for (const el of carriers(identity)) {
          if (!overflow?.contains(el) && !inFanInsights(name, el)) leaks.push(`${name} ("${identity}") with ${host}: ${where(el)}`);
        }
      }
    });
    expect(leaks).toEqual([]);
  });

  it("7: every trigger reveals an extra (a labelled element holding no other) whose tooltip starts with \"Inflowwww extra\"; the Window header has no trigger (TODO.md B2)", async () => {
    const user = userEvent.setup();
    await renderMessagesPro();
    const empty: string[] = [];
    const opened: string[] = [];
    await reach(user, ({ host, overflow }) => {
      if (!overflow) return;
      opened.push(host);
      if (labelledLeaves(overflow).length === 0) empty.push(host);
    });
    // The routine reached a trigger in each Region that has an extra to show:
    // through the Kebab, the Chat header. The Composer has none since TODO.md
    // A2, Fan insights none since its extras became Insights blocks
    // (2026-10-21), the Fan List none since its extras are in plain view
    // (2026-10-26).
    expect([...new Set(opened)]).toEqual([
      "the Chat header Extras overflow",
    ]);
    expect(empty).toEqual([]);
    const windowHeader = screen.getByRole("region", { name: "Window header" });
    expect(within(windowHeader).queryAllByRole("button", { name: EXTRAS_OVERFLOW_LABEL })).toHaveLength(0);
  });

  it("the New menu host holds no labelled extra", async () => {
    const user = userEvent.setup();
    await renderMessagesPro();
    const found: Array<[string, string]> = [];
    await reach(user, ({ host }) => {
      if (host !== "New menu") return;
      const menu = screen.getByRole("region", { name: "New" });
      for (const el of labelledLeaves(menu)) found.push([extraNameOf(el), host]);
    });
    expect(found).toEqual([]);
  });

  it("2: after the reach routine, the (name, host) pairs of the extras of the whole tree equal the catalogue's", async () => {
    const user = userEvent.setup();
    await renderMessagesPro();
    const found: string[] = [];
    const names = new Set<string>();
    await reach(user, (v) => {
      for (const [el, host] of extrasOf(v)) {
        found.push(`${extraNameOf(el)} @ ${host}`);
        names.add(extraNameOf(el));
      }
    });
    const expected = EXTRAS.flatMap((e) => e.hosts.map((h) => `${e.name} @ ${h}`));
    expect(found.sort()).toEqual(expected.sort());
    // Every one of the thirteen catalogued extras is reached.
    expect([...names].sort()).toEqual([...NAMES].sort());
    expect(NAMES.size).toBe(13);
  });

  it("5: every labelled element but a trigger reads \"Inflowwww extra — <a catalogued name>\" on its first line, and each extra its old tooltip, where the old-identity table gives one, on its second", async () => {
    const user = userEvent.setup();
    await renderMessagesPro();
    const bad = new Set<string>();
    let seen = 0;
    await reach(user, (v) => {
      // Every labelled element on the page, a wrapper or a leaf.
      for (const el of labelled().filter((l) => l.title !== EXTRAS_OVERFLOW_LABEL)) {
        const name = extraNameOf(el);
        const [first, , ...more] = el.title.split("\n");
        if (!NAMES.has(name) || first !== `${EXTRA_LABEL} — ${name}` || more.length) {
          bad.add(`${regionOf(el)}: ${JSON.stringify(el.title)}`);
        }
      }
      const shown = extrasOf(v);
      seen += shown.length;
      for (const [el, host] of shown) {
        const name = extraNameOf(el);
        const second = el.title.split("\n")[1];
        const old = oldTooltips(name);
        if (old.length === 0 && second !== undefined) {
          bad.add(`${host}: ${name} had no old tooltip but reads a second line ${JSON.stringify(second)}`);
        }
        if (old.length && second !== undefined && !old.includes(second)) {
          bad.add(`${host}: ${name}'s second line ${JSON.stringify(second)} is not its old tooltip`);
        }
      }
      // At least one old tooltip of each extra the visit shows is some
      // element's second line (an old tooltip may depend on state).
      for (const name of new Set(shown.map(([el]) => extraNameOf(el)))) {
        const seconds = shown.filter(([el]) => extraNameOf(el) === name).map(([el]) => el.title.split("\n")[1]);
        const old = oldTooltips(name);
        if (old.length && !old.some((o) => seconds.includes(o))) {
          bad.add(`${v.host}: no ${name} carries one of its old tooltips`);
        }
      }
    });
    expect(seen).toBeGreaterThan(0);
    expect([...bad]).toEqual([]);
  });

  it("6: clicking each Group chat entry point calls the group-tab opener with the fixture Creator and Fan", async () => {
    const user = userEvent.setup();
    await renderMessagesPro();
    const opener = vi.mocked(openGroupTab);
    const clicked: string[] = [];
    await reach(user, async (v) => {
      for (const [el, host] of extrasOf(v)) {
        if (extraNameOf(el) !== "Group chat") continue;
        opener.mockClear();
        await user.click(el);
        expect(opener.mock.calls.map(([a, f]) => [a, String(f)])).toEqual([[ACCOUNT_ID, String(FAN.id)]]);
        clicked.push(host);
      }
    });
    const groupChat = EXTRAS.find((e) => e.name === "Group chat")!;
    expect(clicked.sort()).toEqual([...groupChat.hosts].sort());
  });

  it("the Fan's tip has no Reward control in its Bubble action row; the Tip reward button was vetoed by the human 2026-10-15", async () => {
    await renderMessagesPro();
    let line: HTMLElement | null = screen.getByText("Fixture tip");
    while (line && !within(line).queryByRole("group", { name: "Message actions" })) line = line.parentElement;
    const row = within(line!).getByRole("group", { name: "Message actions" });
    expect(within(row).getAllByRole("button").map((b) => b.getAttribute("aria-label")))
      .toEqual(["Pin", "Reply", "Like", "Translate"]);
    expect(screen.queryAllByRole("button", { name: /reward/i })).toEqual([]);
    expect(document.querySelectorAll('[title*="reward" i], [aria-label*="reward" i]')).toHaveLength(0);
  });

  it("9: the scheduled_send row shows with its cancel button", async () => {
    await renderMessagesPro();
    const timed = screen.getByText(/⏱ scheduled ·/).parentElement!;
    expect(within(timed).getByRole("button", { name: "cancel" })).toBeInTheDocument();
  });
});
