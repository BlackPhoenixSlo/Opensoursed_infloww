/**
 * Fan insights (`FanDrawer`) — the edits an Employee can make today, pinned
 * before the Phase 5 restyle moves them. Each check asserts at the mocked
 * module boundary (`update.mutate` for our mirror, `relay.put` for the
 * OnlyFans write-through), so a later ticket may change how a test reaches a
 * control without changing what it asserts.
 *
 * Rendered the same way as `fanDrawerEditFreshness.test.tsx`: a query client,
 * the data hooks mocked at their module boundary, the cached OnlyFans profile
 * seeded.
 */
import { afterAll, afterEach, beforeAll, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactNode } from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

const { relayGet, relayPut } = vi.hoisted(() => ({ relayGet: vi.fn(), relayPut: vi.fn() }));
vi.mock("@/lib/relay", async (orig) => ({
  SALARY_FREQUENCIES: (await orig<typeof import("@/lib/relay")>()).SALARY_FREQUENCIES,
  relay: { get: relayGet, post: vi.fn(), put: relayPut, patch: vi.fn(), del: vi.fn() },
  proxyImage: (u: string) => u,
  proxyScrubFrame: (u: string) => u,
}));

const { update, fan } = vi.hoisted(() => ({
  update: { mutate: vi.fn(), isPending: false },
  fan: {
    current: {} as {
      id: number; tags: string[]; custom_nickname: string | null; notes: string | null;
      language: string | null; language_source: string | null;
      home_city?: string | null; home_country?: string | null; local_timezone?: string | null;
      salary?: string | null; last_pay_date?: string | null;
      last_message_received_at?: string | null;
    },
  },
}));
vi.mock("@/hooks/useFan", () => ({
  useFan: () => ({ data: fan.current, isLoading: false, update }),
}));
vi.mock("@/hooks/useAccounts", () => ({ useAccountLabel: () => "acct-a" }));
vi.mock("@/hooks/useMassExclude", () => ({
  useMassExclude: () => ({ isOn: false, isLoading: false, toggle: vi.fn() }),
}));
vi.mock("@/hooks/useLastPurchases", () => ({
  useFanActivity: () => ({ lastPurchase: new Map(), recentSpend: new Map() }),
}));
// One purchased PPV with one photo when `sales.seeded`; none otherwise.
// `sales.items`, when set, replaces the ledger items outright, and
// `sales.summary`, when set, replaces the relay's max and average, and
// `sales.placeholder` marks the page as the previous query's placeholder.
// One unsold PPV in the unsold gallery read when `sales.unsold`.
const { sales } = vi.hoisted(() => ({
  sales: {
    seeded: false, unsold: false, items: null as unknown[] | null,
    summary: null as { max_cents: number; avg_cents: number } | null,
    placeholder: false,
  },
}));
const SALE = {
  transaction_id: 1, message_id: 501, price_cents: 1000, net_cents: null, fee_cents: null,
  vat_cents: null, purchased_at: "2026-01-02T03:04:05Z", sent_at: null,
  sent_by_employee_id: null, employee_name: null, employee_color: null,
};
const SALE_MEDIA = {
  id: 501, text: "", price: 10, isFree: false, isOpened: true, isFromQueue: false, mediaCount: 1,
  createdAt: "2026-01-02T03:04:05Z",
  media: [{ id: 9, type: "photo", files: { full: { url: "https://cdn.test/full.jpg" }, thumb: { url: "https://cdn.test/thumb.jpg" } } }],
};
const UNSOLD_MEDIA = {
  id: 601, text: "unsold pitch", price: 15, isFree: false, isOpened: false, isFromQueue: false, mediaCount: 1,
  createdAt: "2026-01-05T03:04:05Z",
  media: [{ id: 12, type: "photo", files: { full: { url: "https://cdn.test/u-full.jpg" }, thumb: { url: "https://cdn.test/u-thumb.jpg" } } }],
};
// Records each `useFanPpvHistory(accountId, fanId, limit)` call.
const { historyArgs } = vi.hoisted(() => ({ historyArgs: vi.fn() }));
vi.mock("@/hooks/useFanPpvHistory", () => ({
  useFanPpvHistory: (...args: unknown[]) => (historyArgs(...args), {
    data: { items: sales.items ?? (sales.seeded ? [SALE] : []), summary: sales.summary ?? { max_cents: sales.seeded ? 1000 : 0, avg_cents: 0 } },
    isLoading: false,
    isPlaceholderData: sales.placeholder,
  }),
}));
vi.mock("@/hooks/useFanChatMedia", () => ({
  useFanChatMedia: (_a: string, _f: number, opts: { purchased: boolean }) => ({
    data: {
      pages: opts.purchased
        ? (sales.seeded ? [{ list: [SALE_MEDIA] }] : [])
        : (sales.unsold ? [{ list: [UNSOLD_MEDIA] }] : []),
    },
    isLoading: false, fetchNextPage: vi.fn(), hasNextPage: false,
  }),
}));
// `useFanInsights`' figures when `insights.current` is set; none (a sparse Fan) otherwise.
const { insights } = vi.hoisted(() => ({ insights: { current: undefined as unknown } }));
vi.mock("@/hooks/useFanInsights", () => ({
  useFanInsights: () => ({ data: insights.current }),
}));
vi.mock("./PersonaClaims",() => ({ PersonaClaims: () => "Persona claims" }));

import { FanDrawer } from "./FanDrawer";

const CHAT = {
  withUser: { id: 7, name: "Fan Seven", username: "fan7", avatar: null, displayName: "", notice: "" },
} as never;

let qc: QueryClient;

/** The viewport the `matchMedia` stub answers for. Installed once for the
 *  whole suite (restored in `afterAll`); a case only flips `viewport.wide`. */
const viewport = { wide: false };
const realMatchMedia = window.matchMedia;
beforeAll(() => {
  window.matchMedia = ((query: string) => ({
    matches: query === "(min-width: 1024px)" && viewport.wide,
    media: query, onchange: null,
    addEventListener: () => {}, removeEventListener: () => {},
    addListener: () => {}, removeListener: () => {}, dispatchEvent: () => false,
  })) as unknown as typeof window.matchMedia;
});
afterAll(() => { window.matchMedia = realMatchMedia; });

/** Renders Fan insights for fan 7 on acct-a with the OF profile cached.
 *  `layout` picks the render site: the slide-over, the pinned column, or
 *  both together the way the Thread mounts them, sharing one `onClose`. */
function renderInsights({
  layout = "slide-over", onClose = vi.fn(), sub, lists, location, lastSeen, onComposeWith,
}: {
  layout?: "slide-over" | "pinned" | "both"; onClose?: () => void;
  /** OF's `lastSeen` on the cached profile; absent on a sparse Fan. */
  lastSeen?: string;
  /** The Composer's compose callback; absent leaves Fan insights read-only. */
  onComposeWith?: (t: unknown) => void;
  /** OF's `subscribedOnData` on the cached profile; absent on a sparse Fan. */
  sub?: Record<string, unknown>;
  /** OF's `listsStates` on the cached profile; absent on a sparse Fan. */
  lists?: { id: number; type: string; name: string; hasUser: boolean }[];
  /** `home_city` / `home_country` on our Fan record; absent on a sparse Fan. */
  location?: { home_city?: string; home_country?: string; local_timezone?: string };
} = {}) {
  qc.setQueryData(["of-user", "acct-a", 7, "full"], {
    id: 7, displayName: "Old Nick", notice: "old note",
    ...(sub ? { subscribedOnData: sub } : {}), ...(lists ? { listsStates: lists } : {}),
    ...(lastSeen ? { lastSeen } : {}),
  });
  if (location) fan.current = { ...fan.current, ...location };
  function Wrap({ children }: { children: ReactNode }) {
    return (
      <QueryClientProvider client={qc}>
        {children}
      </QueryClientProvider>
    );
  }
  return render(
    <>
      {layout !== "pinned" && (
        <FanDrawer open onClose={onClose} accountId="acct-a" fanId={7} chat={CHAT} onComposeWith={onComposeWith} />
      )}
      {layout !== "slide-over" && (
        <FanDrawer pinned open onClose={onClose} accountId="acct-a" fanId={7} chat={CHAT} onComposeWith={onComposeWith} />
      )}
    </>,
    { wrapper: Wrap },
  );
}

beforeEach(() => {
  viewport.wide = false;
  sales.seeded = false;
  sales.unsold = false;
  sales.items = null;
  sales.summary = null;
  sales.placeholder = false;
  insights.current = undefined;
  historyArgs.mockClear();
  qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  fan.current = { id: 7, tags: ["vip"], custom_nickname: null, notes: null, language: null, language_source: null };
  update.mutate.mockReset();
  relayGet.mockReset();
  // The pre-edit re-read hands back the same profile that was cached.
  relayGet.mockImplementation((path: string) =>
    Promise.resolve(String(path).includes("/users/")
      ? { id: 7, displayName: "Old Nick", notice: "old note" }
      : {}),
  );
  relayPut.mockReset();
  relayPut.mockResolvedValue({});
});
afterEach(() => { cleanup(); qc.clear(); window.localStorage.clear(); });

const nick = () => screen.getByPlaceholderText("Fan Seven") as HTMLInputElement;
const notes = () => screen.getByPlaceholderText(/loves bondage/) as HTMLTextAreaElement;
const tags = () => screen.getByPlaceholderText("whale, EU, kink:feet") as HTMLInputElement;

describe("Fan insights avatar", () => {
  it("loads OF's signed avatar through the relay's /img for the chat's account", () => {
    const chat = { withUser: { id: 7, name: "Fan Seven", username: "fan7", avatar: "https://cdn.example.invalid/av.jpg" } } as never;
    const { container } = render(
      <QueryClientProvider client={qc}>
        <FanDrawer open onClose={vi.fn()} accountId="acct-a" fanId={7} chat={chat} />
      </QueryClientProvider>,
    );
    const src = container.querySelector("img")!.getAttribute("src")!;
    expect(src.startsWith("/img?")).toBe(true);
    const q = new URLSearchParams(src.slice("/img?".length));
    expect(q.get("u")).toBe("https://cdn.example.invalid/av.jpg");
    expect(q.get("account_id")).toBe("acct-a");
  });
});

describe("Fan insights edits", () => {
  it("leaving the Nickname saves the custom nickname to our mirror and writes it to OnlyFans", async () => {
    const user = userEvent.setup();
    renderInsights();
    await waitFor(() => expect(nick().value).toBe("Old Nick"));

    await user.clear(nick());
    await user.type(nick(), "New Nick");
    await user.tab();

    expect(update.mutate).toHaveBeenCalledWith({ custom_nickname: "New Nick" });
    expect(relayPut).toHaveBeenCalledWith(
      "/api/of/v2/subscriptions/7/custom-name",
      { name: "New Nick" },
      { accountId: "acct-a" },
    );
  });

  it("leaving Fan notes saves the notes to our mirror and writes them to OnlyFans", async () => {
    const user = userEvent.setup();
    renderInsights();
    await waitFor(() => expect(notes().value).toBe("old note"));

    await user.clear(notes());
    await user.type(notes(), "new note");
    await user.tab();

    expect(update.mutate).toHaveBeenCalledWith({ notes: "new note" });
    expect(relayPut).toHaveBeenCalledWith(
      "/api/of/v2/subscriptions/7/note",
      { note: "new note" },
      { accountId: "acct-a" },
    );
  });

  it("leaving Tags saves the tags", async () => {
    const user = userEvent.setup();
    renderInsights();
    await waitFor(() => expect(tags().value).toBe("vip"));

    await user.clear(tags());
    await user.type(tags(), "vip, whale");
    await user.tab();

    expect(update.mutate).toHaveBeenCalledWith({ tags: ["vip", "whale"] });
  });

  it("leaving Birthday saves an MM-DD day, clears on empty, and drops anything else", async () => {
    const user = userEvent.setup();
    renderInsights();
    const birthday = () => screen.getByRole("textbox", { name: "Birthday" }) as HTMLInputElement;

    await user.type(birthday(), "13-40");
    await user.tab();
    expect(update.mutate).not.toHaveBeenCalled();
    expect(birthday().value).toBe("");

    await user.type(birthday(), "02-29");
    await user.tab();
    expect(update.mutate).toHaveBeenCalledWith({ birthday: "02-29" });
  });

  it("leaving Salary and Last pay date saves them, empty clears; choosing a Salary frequency saves it", async () => {
    const user = userEvent.setup();
    fan.current = { ...fan.current, salary: "$3k", last_pay_date: "2026-10-01" };
    renderInsights();
    const salary = screen.getByRole("textbox", { name: "Salary" }) as HTMLInputElement;
    expect(salary.value).toBe("$3k");

    await user.clear(salary);
    await user.type(salary, "$4k / month");
    await user.tab();
    expect(update.mutate).toHaveBeenCalledWith({ salary: "$4k / month" });

    await user.selectOptions(screen.getByRole("combobox", { name: "Salary frequency" }), "Bi-weekly");
    expect(update.mutate).toHaveBeenCalledWith({ salary_frequency: "biweekly" });

    const payDate = screen.getByLabelText("Last pay date") as HTMLInputElement;
    expect(payDate.value).toBe("2026-10-01");
    await user.clear(payDate);
    await user.tab();
    expect(update.mutate).toHaveBeenCalledWith({ last_pay_date: null });
  });

  it("Local time shows the wall clock in the fan's resolved zone, the zone as its tooltip", () => {
    renderInsights({ location: { home_city: "Chicago", local_timezone: "America/Chicago" } });
    expect(screen.getByTitle("America/Chicago").textContent).toBe(
      new Date().toLocaleTimeString([], { timeZone: "America/Chicago", hour: "numeric", minute: "2-digit" }));
  });

  it("changing Language saves the language", async () => {
    const user = userEvent.setup();
    renderInsights();

    await user.selectOptions(screen.getByRole("combobox", { name: "Language" }), "Deutsch");

    expect(update.mutate).toHaveBeenCalledWith({ language: "de" });
  });

  it("shows 'Saved locally, but OnlyFans rejected…' under the content when an OnlyFans write fails", async () => {
    const user = userEvent.setup();
    const warn = vi.spyOn(console, "warn").mockImplementation(() => {});
    try {
      relayPut.mockRejectedValue(new Error("rejected by OF"));
      renderInsights();
      await waitFor(() => expect(nick().value).toBe("Old Nick"));

      await user.clear(nick());
      await user.type(nick(), "New Nick");
      await user.tab();

      expect(await screen.findByText(/^Saved locally, but OnlyFans rejected/)).toBeTruthy();
    } finally {
      warn.mockRestore();
    }
  });
});

describe("Fan insights closing", () => {
  it("the slide-over is a dialog named Fan insights that × and Esc each close below 1024px", async () => {
    const user = userEvent.setup();
    const onClose = vi.fn();
    sales.seeded = true;
    renderInsights({ layout: "slide-over", onClose });
    const dialog = screen.getByRole("dialog", { name: "Fan insights" });

    await user.click(within(dialog).getByRole("button", { name: "Close" }));
    expect(onClose).toHaveBeenCalledTimes(1);

    // An open lightbox owns Esc: the first press closes it, the next the sheet.
    // The purchased media sit on the Sales tab.
    await user.click(within(dialog).getByRole("tab", { name: "Sales" }));
    await user.click(within(dialog).getByRole("button", { name: "Click to preview" }));
    await user.keyboard("{Escape}");
    expect(screen.queryByRole("button", { name: "Close preview" })).toBeNull();
    expect(onClose).toHaveBeenCalledTimes(1);

    await user.keyboard("{Escape}");
    expect(onClose).toHaveBeenCalledTimes(2);
  });

  it("a swipe right on the slide-over or its backdrop closes it; a swipe left, the pinned column and 1024px+ do not", () => {
    const onClose = vi.fn();
    const swipe = (el: Element, x0: number, x1: number) => {
      fireEvent.touchStart(el, { touches: [{ clientX: x0, clientY: 300 }], changedTouches: [{ clientX: x0, clientY: 300 }] });
      fireEvent.touchMove(el, { touches: [{ clientX: x1, clientY: 300 }], changedTouches: [{ clientX: x1, clientY: 300 }] });
      fireEvent.touchEnd(el, { touches: [], changedTouches: [{ clientX: x1, clientY: 300 }] });
    };
    const { unmount } = renderInsights({ layout: "slide-over", onClose });
    const dialog = screen.getByRole("dialog", { name: "Fan insights" });
    swipe(dialog, 300, 150);
    expect(onClose).not.toHaveBeenCalled();
    swipe(dialog, 150, 300);
    expect(onClose).toHaveBeenCalledTimes(1);
    swipe(dialog.previousElementSibling!, 20, 200);            // the backdrop
    expect(onClose).toHaveBeenCalledTimes(2);
    unmount();

    renderInsights({ layout: "pinned", onClose });
    swipe(screen.getByRole("complementary", { name: "Fan insights" }), 150, 300);
    expect(onClose).toHaveBeenCalledTimes(2);
    cleanup();

    viewport.wide = true;
    renderInsights({ layout: "slide-over", onClose });
    swipe(screen.getByRole("dialog", { name: "Fan insights" }), 150, 300);
    expect(onClose).toHaveBeenCalledTimes(2);
  });

  it("the pinned column is the Fan insights landmark, not a dialog, and ignores Esc", async () => {
    const user = userEvent.setup();
    const onClose = vi.fn();
    renderInsights({ layout: "pinned", onClose });

    expect(screen.getByRole("complementary", { name: "Fan insights" })).toBeTruthy();
    expect(screen.queryByRole("dialog")).toBeNull();

    await user.keyboard("{Escape}");
    expect(onClose).not.toHaveBeenCalled();
  });

  it("from 1024px Esc closes neither the hidden slide-over nor the pinned column, and closes only an open lightbox", async () => {
    const user = userEvent.setup();
    const onClose = vi.fn();
    viewport.wide = true;
    sales.seeded = true;
    renderInsights({ layout: "both", onClose });
    screen.getByRole("dialog", { name: "Fan insights" });

    await user.keyboard("{Escape}");
    expect(onClose).not.toHaveBeenCalled();

    const pinned = screen.getByRole("complementary", { name: "Fan insights" });
    await user.click(within(pinned).getByRole("tab", { name: "Sales" }));
    await user.click(within(pinned).getByRole("button", { name: "Click to preview" }));
    expect(screen.getByRole("button", { name: "Close preview" })).toBeTruthy();

    await user.keyboard("{Escape}");
    expect(screen.queryByRole("button", { name: "Close preview" })).toBeNull();
    expect(onClose).not.toHaveBeenCalled();
  });
});

describe("Fan insights head, tabs and Extras overflow", () => {
  it("the tab bar reads Insights, Sales, Notes with Insights selected, and the head follows the tab", async () => {
    const user = userEvent.setup();
    const onClose = vi.fn();
    renderInsights({ onClose });
    const pane = screen.getByRole("dialog", { name: "Fan insights" });

    const tabs = within(pane).getAllByRole("tab");
    expect(tabs.map((t) => t.textContent)).toEqual(["Insights", "Sales", "Notes"]);
    expect(tabs.map((t) => t.getAttribute("aria-selected"))).toEqual(["true", "false", "false"]);
    expect(within(pane).getByRole("heading", { name: "Fan insights" })).toBeTruthy();

    await user.click(within(pane).getByRole("tab", { name: "Sales" }));
    expect(within(pane).getByRole("tab", { name: "Sales" }).getAttribute("aria-selected")).toBe("true");
    expect(within(pane).getByRole("heading", { name: "Sales" })).toBeTruthy();
    expect(within(pane).queryByRole("heading", { name: "Fan insights" })).toBeNull();

    await user.click(within(pane).getByRole("tab", { name: "Notes" }));
    expect(within(pane).getByRole("heading", { name: "Notes" })).toBeTruthy();

    // × sits in the head and still closes the pane (no render site hides it since ticket 07).
    await user.click(within(pane).getByRole("button", { name: "Close" }));
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it("text typed into Fan notes is still there after switching to Sales and back", async () => {
    const user = userEvent.setup();
    renderInsights();
    await waitFor(() => expect(notes().value).toBe("old note"));

    await user.clear(notes());
    await user.type(notes(), "draft note");
    await user.click(screen.getByRole("tab", { name: "Sales" }));

    // Leaving the field saved it on the way to the tab, and only the Sales tab renders.
    expect(update.mutate).toHaveBeenCalledWith({ notes: "draft note" });
    expect(screen.queryByPlaceholderText(/loves bondage/)).toBeNull();

    await user.click(screen.getByRole("tab", { name: "Insights" }));
    expect(notes().value).toBe("draft note");
  });

  it("the Fan block shows the Fan's name, @username and Creator · id as the Fan identity extra, and the extra Fan stats are gone", () => {
    renderInsights({ lastSeen: new Date().toISOString(), sub: { status: "active", postsSumm: 42 } });
    const pane = screen.getByRole("dialog", { name: "Fan insights" });
    const block = within(pane).getByRole("region", { name: "Fan" });

    expect(within(block).getByText("Old Nick")).toBeTruthy();
    expect(within(block).getByText("@fan7")).toBeTruthy();
    expect(within(block).getByText("acct-a · id 7")).toBeTruthy();
    expect(within(block).getByTitle("Inflowwww extra — Fan identity")).toBeTruthy();
    for (const gone of ["Last message in", "Last seen", "Subscribed at", "Renewed at", "Expires", "Expired", "Posts"]) {
      expect(within(pane).queryByText(gone)).toBeNull();
    }
    // The head's "+" is no Extras overflow any more.
    expect(screen.queryByRole("button", { name: "Inflowwww extras" })).toBeNull();
  });

  it("the Mass exclude block holds the one MASSdmEXCLUDE switch, for every mass send", () => {
    renderInsights();
    const block = screen.getByRole("region", { name: "Mass exclude" });
    expect(within(block).getAllByRole("switch")).toHaveLength(1);
    expect(within(block).getByRole("switch", { name: /MASSdmEXCLUDE/ })).toBeTruthy();
    expect(within(block).getByText("Never include in any mass send.")).toBeTruthy();
    expect(within(block).queryByText(/MASSppvEXCLUDE/)).toBeNull();
  });

  it("Send to chat on an unsold PPV in the Unsold PPVs block hands it to the Composer through the compose callback", async () => {
    const user = userEvent.setup();
    const onComposeWith = vi.fn();
    sales.unsold = true;
    renderInsights({ onComposeWith });

    const block = screen.getByRole("region", { name: "Unsold PPVs sent" });
    expect(within(block).getByText("unsold pitch")).toBeTruthy();
    await user.click(within(block).getByRole("button", { name: "Send to chat" }));

    expect(onComposeWith).toHaveBeenCalledTimes(1);
    expect(onComposeWith).toHaveBeenCalledWith(expect.objectContaining({
      source: "of", text: "unsold pitch", price: 15, mediaCount: 1,
      media: [expect.objectContaining({ id: 12, type: "photo" })],
    }));
  });

  it("the Unsold PPVs block shows with none, saying so", () => {
    renderInsights();
    const block = screen.getByRole("region", { name: "Unsold PPVs sent" });
    expect(within(block).getByText("No unsold PPVs sent.")).toBeTruthy();
    expect(within(block).getByTitle("Inflowwww extra — Unsold PPVs")).toBeTruthy();
  });
});

/** A block's rows as [term, value] pairs, in page order. */
/** The saved block layout's key, and a saved layout with every block shown
 *  (Organization metrics is removed by default). */
const LAYOUT_KEY = "chatterly:fan-insights-blocks:v2";
const showEveryBlock = () => window.localStorage.setItem(LAYOUT_KEY, JSON.stringify({ order: [], hidden: [] }));

function rowsOf(block: HTMLElement): [string, string][] {
  const terms = within(block).getAllByRole("term");
  const values = within(block).getAllByRole("definition");
  return terms.map((t, i) => [t.textContent ?? "", values[i]?.textContent ?? ""]);
}

describe("Fan insights blocks", () => {
  it("a block's chevron collapses its rows and flips aria-expanded, then expands it again; the grip moves the block", async () => {
    const user = userEvent.setup();
    renderInsights();
    const block = screen.getByRole("region", { name: "Subscription" });
    expect(within(block).getAllByRole("term")).toHaveLength(4);

    const collapse = within(block).getByRole("button", { name: "Collapse Subscription" });
    expect(collapse.getAttribute("aria-expanded")).toBe("true");
    await user.click(collapse);

    const expand = within(block).getByRole("button", { name: "Expand Subscription" });
    expect(expand.getAttribute("aria-expanded")).toBe("false");
    expect(within(block).queryAllByRole("term")).toHaveLength(0);
    expect(within(block).queryByText("Auto-renewal")).toBeNull();
    // Only this block collapsed.
    expect(rowsOf(screen.getByRole("region", { name: "Spending behavior" }))).toHaveLength(5);

    await user.click(expand);
    expect(within(block).getByRole("button", { name: "Collapse Subscription" }).getAttribute("aria-expanded")).toBe("true");
    expect(within(block).getAllByRole("term")).toHaveLength(4);

    expect(within(block).getByRole("button", { name: "Move Subscription" })).toBeTruthy();
    expect(within(block).queryByTitle("not wired")).toBeNull();
  });

  it("Insights blocks read in the selling order with Organization metrics removed; shown, a sparse Fan's metrics read —; Subscription's rows in order", () => {
    renderInsights();
    let pane = screen.getByRole("dialog", { name: "Fan insights" });

    expect(within(pane).getAllByRole("heading", { level: 3 }).map((h) => h.textContent))
      .toEqual(BLOCK_ORDER);
    expect(within(pane).queryByRole("region", { name: "Organization metrics" })).toBeNull();
    expect(rowsOf(within(pane).getByRole("region", { name: "Subscription" })).map(([k]) => k))
      .toEqual(["Status", "Cost", "Duration", "Auto-renewal"]);
    // The stats grid no longer repeats them.
    expect(within(pane).queryByText("Sub status")).toBeNull();
    expect(within(pane).queryByText("Sub price")).toBeNull();
    cleanup();

    showEveryBlock();
    renderInsights();
    pane = screen.getByRole("dialog", { name: "Fan insights" });
    expect(rowsOf(within(pane).getByRole("region", { name: "Organization metrics" })))
      .toEqual([["Spending power", "—"], ["Chargeback risk", "—"]]);
  });

  it("with insights loaded, Spending power and Chargeback risk show their labels, and the risk's share is its tooltip", () => {
    insights.current = {
      spending_power: { label: "Top 5%", spend_30d_cents: 5000, population: 25 },
      chargeback_risk: { label: "Medium", pct: 50, paid_cents: 10000, reversed_cents: 5000 },
      ppv_recent: { count: 0, bought: 0, buy_rate_pct: null, highest_cents: null, lowest_cents: null },
    };
    showEveryBlock();
    renderInsights();
    const block = screen.getByRole("region", { name: "Organization metrics" });
    expect(rowsOf(block)).toEqual([["Spending power", "Top 5%"], ["Chargeback risk", "Medium"]]);
    expect(within(block).getByTitle(/^50% of his payments/)).toBeTruthy();
  });

  it("Auto-renewal reads On, Off and — for an active, a set-to-expire and an unknown status; Duration shows the seeded duration", () => {
    const cases: [Record<string, unknown> | undefined, string[]][] = [
      [{ status: "active", price: 9.99, duration: "3 months" },
        ["Active", "$9.99", "3 months", "On"]],
      [{ status: "Set to Expire", price: 4.5, duration: "1 month" },
        ["Won't renew", "$4.50", "1 month", "Off"]],
      [undefined, ["—", "—", "—", "—"]],
    ];
    for (const [sub, values] of cases) {
      renderInsights({ sub });
      const block = screen.getByRole("region", { name: "Subscription" });
      expect(rowsOf(block)).toEqual([
        ["Status", values[0]], ["Cost", values[1]], ["Duration", values[2]], ["Auto-renewal", values[3]],
      ]);
      cleanup();
      qc.clear();
    }
  });
});

describe("Fan insights Spending behavior", () => {
  it("Spending behavior follows the Fan block, with Total spend, Last spend, PPV, Tip and Highest spend, and Total spend shows the seeded value", () => {
    renderInsights({ sub: { totalSumm: 123.45, messagesSumm: 40, tipsSumm: 12 } });
    const pane = screen.getByRole("dialog", { name: "Fan insights" });

    expect(within(pane).getAllByRole("heading", { level: 3 }).map((h) => h.textContent).slice(0, 3))
      .toEqual(["Fan", "Spending behavior", "Unsold PPVs sent"]);
    const rows = rowsOf(within(pane).getByRole("region", { name: "Spending behavior" }));
    expect(rows.map(([k]) => k)).toEqual(["Total spend", "Last spend", "PPV", "Tip", "Highest spend"]);
    expect(rows[0]).toEqual(["Total spend", "$123"]);
    expect(rows[2][1]).toMatch(/^\$40 Total/);
    expect(rows[3][1]).toMatch(/^\$12 Total/);
    // A 1px rule splits Total spend from Last spend (page-parity 07 FI1).
    expect(within(pane).getByText("Last spend", { selector: "dt" }).parentElement).toHaveClass("border-l", "border-border");
    // The stats grid and the strip no longer repeat them.
    for (const gone of ["Lifetime spend", "Tips", "Messages", "Last purchase"]) {
      expect(within(pane).queryByText(gone)).toBeNull();
    }
  });

  it("on a sparse Fan, Last spend and Tip's Avg read —", () => {
    renderInsights();
    const block = screen.getByRole("region", { name: "Spending behavior" });

    const rows = rowsOf(block);
    expect(rows[1]).toEqual(["Last spend", "—"]);
    const tip = within(block).getAllByRole("definition")[3];
    expect(within(tip).getByText(/Avg$/).textContent).toBe("— Avg");
  });

  it("with no purchase-history items, Highest spend and PPV Avg read —, never $0", () => {
    renderInsights();
    const block = screen.getByRole("region", { name: "Spending behavior" });

    const rows = rowsOf(block);
    expect(rows.map(([k]) => k)).toEqual(["Total spend", "Last spend", "PPV", "Tip", "Highest spend"]);
    expect(rows[4]).toEqual(["Highest spend", "—"]);
    const ppv = within(block).getAllByRole("definition")[2];
    expect(within(ppv).getByText(/Avg$/).textContent).toBe("— Avg");
  });

  it("with a part-filled page, Highest spend and PPV Avg show the page's highest and average price; with a full page, both read —", () => {
    // Two purchases, $12.50 and $5.00: highest $12.50, average $8.75.
    sales.items = [purchase(1, 1250, "2026-03-04T12:00:00Z"), purchase(2, 500, "2026-03-01T12:00:00Z")];
    sales.summary = { max_cents: 1250, avg_cents: 875 };
    renderInsights();
    let block = screen.getByRole("region", { name: "Spending behavior" });
    expect(rowsOf(block)[4]).toEqual(["Highest spend", "$12.50"]);
    expect(within(within(block).getAllByRole("definition")[2]).getByText(/Avg$/).textContent).toBe("$8.75 Avg");
    // Today's Max and Avg have left the Purchases over time label.
    expect(within(block).queryByText(/^(Max|Avg)$/)).toBeNull();
    cleanup();
    qc.clear();

    // A full page (12 of the default 12) may hide older purchases, so neither figure is shown.
    sales.items = Array.from({ length: 12 }, (_, i) => purchase(i + 1, 100 * (i + 1), "2026-02-01T12:00:00Z"));
    sales.summary = { max_cents: 1200, avg_cents: 650 };
    renderInsights();
    block = screen.getByRole("region", { name: "Spending behavior" });
    expect(rowsOf(block)[4]).toEqual(["Highest spend", "—"]);
    expect(within(within(block).getAllByRole("definition")[2]).getByText(/Avg$/).textContent).toBe("— Avg");
  });

  it("while the shown page is the previous query's placeholder (Load more or another Fan in flight), Highest spend and PPV Avg read —", () => {
    sales.items = [purchase(1, 1250, "2026-03-04T12:00:00Z"), purchase(2, 500, "2026-03-01T12:00:00Z")];
    sales.summary = { max_cents: 1250, avg_cents: 875 };
    sales.placeholder = true;
    renderInsights();
    const block = screen.getByRole("region", { name: "Spending behavior" });

    expect(rowsOf(block)[4]).toEqual(["Highest spend", "—"]);
    expect(within(within(block).getAllByRole("definition")[2]).getByText(/Avg$/).textContent).toBe("— Avg");
  });
});

/** A ledger item bought for `cents` at `at` (null: no purchase time). */
function purchase(id: number, cents: number, at: string | null) {
  return { ...SALE, transaction_id: id, message_id: null, price_cents: cents, purchased_at: at };
}

/** The chart's bars, each titled "<range>: <gross>", as their gross amounts. */
function bucketsOf(chart: HTMLElement): string[] {
  return within(chart).getAllByTitle(/: \$/).map((b) => b.getAttribute("title")!.split(": ").pop()!);
}

describe("Fan insights Purchases over time", () => {
  it("seeded purchases draw 12 gross buckets from the first purchase to now, and with no purchases the empty text shows", () => {
    vi.useFakeTimers({ toFake: ["Date"] });
    try {
      // First purchase to now is 12 days, so each bucket is one day.
      vi.setSystemTime(new Date("2026-01-13T00:00:00Z"));
      sales.items = [
        purchase(1, 1000, "2026-01-01T00:00:00Z"), // the first purchase: bucket 0
        purchase(2, 500, "2026-01-01T12:00:00Z"),  // bucket 0
        purchase(3, 2500, "2026-01-06T00:30:00"),  // a tz-naive UTC stamp: bucket 5
        purchase(4, 700, "2026-01-12T23:00:00Z"),  // bucket 11
        purchase(5, 300, "2026-01-13T00:00:00Z"),  // exactly now: clamped into bucket 11
        purchase(6, 900, null),                    // no purchase time: skipped
      ];
      renderInsights();
      const block = screen.getByRole("region", { name: "Spending behavior" });
      const chart = within(block).getByRole("img", { name: "Purchases over time" });

      expect(bucketsOf(chart)).toEqual([
        "$15", "$0", "$0", "$0", "$0", "$25",
        "$0", "$0", "$0", "$0", "$0", "$10",
      ]);
      expect(within(block).getByText("peak $25")).toBeTruthy();
      expect(within(block).getByText("now")).toBeTruthy();
      cleanup();
      qc.clear();

      sales.items = [];
      renderInsights();
      const empty = screen.getByRole("region", { name: "Spending behavior" });
      expect(within(empty).getByText("Purchases over time")).toBeTruthy();
      expect(within(empty).getByText("No PPV purchases yet.")).toBeTruthy();
      expect(within(empty).queryByRole("img", { name: "Purchases over time" })).toBeNull();
    } finally {
      vi.useRealTimers();
    }
  });

  it("Full history ↗ selects the Sales tab, whose first block is Purchases over time", async () => {
    const user = userEvent.setup();
    sales.seeded = true;
    renderInsights();
    const pane = screen.getByRole("dialog", { name: "Fan insights" });

    await user.click(within(pane).getByRole("button", { name: "Full history ↗" }));

    expect(within(pane).getByRole("tab", { name: "Sales" }).getAttribute("aria-selected")).toBe("true");
    expect(within(pane).getByRole("heading", { name: "Sales" })).toBeTruthy();
    const first = within(within(pane).getByRole("tabpanel")).getAllByRole("region")[0];
    expect(within(first).getByRole("heading", { level: 3 }).textContent).toBe("Purchases over time");
    expect(bucketsOf(within(first).getByRole("img", { name: "Purchases over time" }))).toHaveLength(12);
  });
});

describe("Fan insights Sales tab", () => {
  it("a seeded purchase shows its date, gross, net and sender in the Sales table, and Buy rate, Highest and Lowest price read —", async () => {
    const user = userEvent.setup();
    sales.items = [
      { ...purchase(1, 1250, "2026-03-04T12:00:00Z"), net_cents: 1000, employee_name: "Fixture Chatter" },
      purchase(2, 500, "2026-03-01T12:00:00Z"),
    ];
    renderInsights();
    await user.click(screen.getByRole("tab", { name: "Sales" }));
    const block = screen.getByRole("region", { name: "Sales" });

    expect(rowsOf(block)).toEqual([["Buy rate", "—"], ["Highest price", "—"], ["Lowest price", "—"]]);
    const table = within(block).getByRole("table");
    expect(within(table).getAllByRole("columnheader").map((h) => h.textContent))
      .toEqual(["Date", "Gross", "Net", "Sent by"]);
    const [, seeded, bare] = within(table).getAllByRole("row");
    expect(within(seeded).getAllByRole("cell").map((c) => c.textContent))
      .toEqual(["Mar 4", "$12.50", "$10", "Fixture Chatter"]);
    expect(within(bare).getAllByRole("cell").map((c) => c.textContent))
      .toEqual(["Mar 1", "$5", "—", "—"]);
  });

  it("with insights loaded, Buy rate shows the share of recent PPVs bought, with Highest and Lowest price", async () => {
    const user = userEvent.setup();
    insights.current = {
      spending_power: { label: "Bottom", spend_30d_cents: 0, population: 25 },
      chargeback_risk: { label: null, pct: null, paid_cents: 0, reversed_cents: 0 },
      ppv_recent: { count: 30, bought: 10, buy_rate_pct: 33, highest_cents: 3400, lowest_cents: 500 },
    };
    renderInsights();
    await user.click(screen.getByRole("tab", { name: "Sales" }));
    const block = screen.getByRole("region", { name: "Sales" });

    expect(rowsOf(block)).toEqual([["Buy rate", "33%"], ["Highest price", "$34"], ["Lowest price", "$5"]]);
    expect(within(block).getByTitle("10 of the last 30 PPVs bought")).toBeTruthy();
  });

  it("↻ invalidates the same query families as before: chat media, purchase history, last purchases, the OF profile and our fan row", async () => {
    const user = userEvent.setup();
    sales.seeded = true;
    renderInsights();
    await user.click(screen.getByRole("tab", { name: "Sales" }));
    const invalidate = vi.spyOn(qc, "invalidateQueries");

    await user.click(within(screen.getByRole("region", { name: "Sales" })).getByRole("button", { name: "Refresh gallery" }));

    expect(invalidate.mock.calls.map(([f]) => f)).toEqual([
      { queryKey: ["fan-chat-media", "acct-a", 7], exact: false },
      { queryKey: ["fan-ppv-history", "acct-a", 7], exact: false },
      { queryKey: ["last-purchases", "acct-a"] },
      { queryKey: ["of-user", "acct-a", 7] },
      { queryKey: ["fan", "acct-a", 7] },
    ]);
  });

  it("Load more asks the purchase history for 32 items", async () => {
    const user = userEvent.setup();
    sales.items = Array.from({ length: 12 }, (_, i) =>
      purchase(i + 1, 100 * (i + 1), `2026-02-${String(i + 1).padStart(2, "0")}T12:00:00Z`));
    renderInsights();
    await user.click(screen.getByRole("tab", { name: "Sales" }));
    expect(historyArgs).toHaveBeenLastCalledWith("acct-a", 7, 12);
    const block = screen.getByRole("region", { name: "Sales" });

    await user.click(within(block).getByRole("button", { name: "Show 9 more" }));
    await user.click(within(block).getByRole("button", { name: "Load more from server" }));

    expect(historyArgs).toHaveBeenLastCalledWith("acct-a", 7, 32);
  });
});

describe("Fan insights Profile, Lists and Notes", () => {
  it("Insights blocks run Spending behavior to Notes, Profile's rows run Nickname to Last pay date, and a sparse Fan's Birthday is empty and Source and Local time read —", () => {
    renderInsights();
    const pane = screen.getByRole("dialog", { name: "Fan insights" });

    // The six-heading order is pinned by the Insights-blocks test above.
    const profile = within(pane).getByRole("region", { name: "Profile" });
    const rows = rowsOf(profile);
    expect(rows.map(([k]) => k)).toEqual([
      "Nickname", "Tags", "Language", "Birthday", "Source", "Local time", "Salary", "Salary frequency", "Last pay date",
    ]);
    expect(rows[4]).toEqual(["Source", "—"]);
    expect(rows[5]).toEqual(["Local time", "—"]);
    // Birthday is ours (OF has none): an empty MM-DD field for a sparse Fan.
    const birthday = within(profile).getByRole("textbox", { name: "Birthday" }) as HTMLInputElement;
    expect(birthday.value).toBe("");
    expect(birthday.placeholder).toBe("MM-DD");
    // The Nickname input keeps its name, and its sync hint is the ⓘ's tooltip.
    expect(within(profile).getByRole("textbox", { name: "Nickname" })).toBe(nick());
    expect(within(profile).getByRole("img", { name: "info" })).toBeTruthy();
    expect(within(profile).getByTitle(/^Synced with OnlyFans/)).toBeTruthy();
    // Fan notes moved into its own block; the uppercase form labels are gone.
    expect(within(within(pane).getByRole("region", { name: "Notes" })).getByRole("textbox", { name: "Fan notes" }))
      .toBe(notes());
    expect(within(pane).queryByText("Custom nickname")).toBeNull();
  });

  const locationCases: [string, { home_city?: string; home_country?: string } | undefined, string][] = [
    ["city, country when both are seeded", { home_city: "Testville", home_country: "Fakeland" }, "Testville, Fakeland"],
    ["the one known part alone", { home_country: "Fakeland" }, "Fakeland"],
    ["— when neither is known", undefined, "—"],
  ];
  it.each(locationCases)("Location shows %s", (_label, location, shown) => {
    renderInsights({ location });
    const profile = screen.getByRole("region", { name: "Profile" });
    expect(within(profile).getByRole("group", { name: "Location" }).textContent).toBe(shown);
  });

  it("Lists shows one chip for each OF list the Fan is on", () => {
    renderInsights({
      lists: [
        { id: 1, type: "fans", name: "Fans", hasUser: true },
        { id: 2, type: "following", name: "Following", hasUser: false },
        { id: 3, type: "bookmarks", name: "Bookmarks", hasUser: true },
      ],
    });
    const lists = screen.getByRole("region", { name: "Lists" });
    expect(within(lists).getAllByRole("listitem").map((c) => c.textContent)).toEqual(["Fans", "Bookmarks"]);
  });

  it("Lists reads — when the Fan is on no list", () => {
    renderInsights();
    const empty = screen.getByRole("region", { name: "Lists" });
    expect(within(empty).queryAllByRole("listitem")).toHaveLength(0);
    expect(within(empty).getByText("—")).toBeTruthy();
  });
});

describe("Fan insights Notes tab", () => {
  const extraOf = (el: HTMLElement, name: string) => el.closest(`[title="Inflowwww extra — ${name}"]`);
  const cancelChip = () => screen.queryByTitle("Cancel the AI offer and take over");

  it("the Notes tab opens with a Creator notes block that reads —", async () => {
    const user = userEvent.setup();
    renderInsights();
    await user.click(screen.getByRole("tab", { name: "Notes" }));
    const pane = screen.getByRole("dialog", { name: "Fan insights" });

    expect(within(pane).getAllByRole("heading", { level: 3 })[0].textContent).toBe("Creator notes");
    const creator = within(pane).getByRole("region", { name: "Creator notes" });
    expect(within(creator).getByText("—")).toBeTruthy();
  });

  it("AI profile then Persona claims follow Creator notes, each titled Inflowwww extra; no AI seller chip", async () => {
    const user = userEvent.setup();
    renderInsights();
    // The AI seller chip went with the legacy selling engine.
    expect(cancelChip()).toBeNull();
    await user.click(screen.getByRole("tab", { name: "Notes" }));
    const creator = screen.getByRole("region", { name: "Creator notes" });
    const profile = screen.getByText("AI profile");
    const claims = screen.getByText("Persona claims");
    for (const [el, name] of [[profile, "Generated profile note"], [claims, "Persona claims"]] as const) {
      expect(extraOf(el, name)).not.toBeNull();
      expect(creator.compareDocumentPosition(el) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    }
    expect(profile.compareDocumentPosition(claims) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  });
});

/** The Insights blocks' headings in their default order (Organization metrics
 *  is removed by default, so last and absent). */
const BLOCK_ORDER = [
  "Fan", "Spending behavior", "Unsold PPVs sent", "Notes", "Mass exclude",
  "Subscription", "Profile", "Lists",
];

const headings = (pane: HTMLElement) =>
  within(pane).getAllByRole("heading", { level: 3 }).map((h) => h.textContent);

describe("Fan insights block layout", () => {
  it("× removes a block; the head's + lists it and adds it back at its old place", async () => {
    const user = userEvent.setup();
    renderInsights();
    const pane = screen.getByRole("dialog", { name: "Fan insights" });

    await user.click(within(pane).getByRole("button", { name: "Remove Subscription" }));
    await user.click(within(pane).getByRole("button", { name: "Remove Unsold PPVs sent" }));
    expect(headings(pane)).toEqual(BLOCK_ORDER.filter((h) => h !== "Subscription" && h !== "Unsold PPVs sent"));

    await user.click(within(pane).getByRole("button", { name: "Add block" }));
    const menu = within(pane).getByRole("menu", { name: "Add block" });
    expect(within(menu).getAllByRole("menuitem").map((m) => m.textContent))
      .toEqual(["Unsold PPVs sent", "Subscription", "Organization metrics"]);
    await user.click(within(menu).getByRole("menuitem", { name: "Subscription" }));

    expect(within(pane).queryByRole("menu")).toBeNull();
    expect(headings(pane)).toEqual(BLOCK_ORDER.filter((h) => h !== "Unsold PPVs sent"));
  });

  it("Organization metrics starts removed: the head's + lists only it, and adds it back last; then every block is shown", async () => {
    const user = userEvent.setup();
    renderInsights();
    const pane = screen.getByRole("dialog", { name: "Fan insights" });

    await user.click(within(pane).getByRole("button", { name: "Add block" }));
    const menu = within(pane).getByRole("menu", { name: "Add block" });
    expect(within(menu).getAllByRole("menuitem").map((m) => m.textContent)).toEqual(["Organization metrics"]);
    await user.click(within(menu).getByRole("menuitem", { name: "Organization metrics" }));
    expect(headings(pane)).toEqual([...BLOCK_ORDER, "Organization metrics"]);

    await user.click(within(pane).getByRole("button", { name: "Add block" }));
    expect(within(pane).getByRole("menu", { name: "Add block" }).textContent).toBe("Every block is shown");
  });

  it("the grip moves a block with ↑/↓ and by drag and drop", async () => {
    const user = userEvent.setup();
    renderInsights();
    const pane = screen.getByRole("dialog", { name: "Fan insights" });

    within(pane).getByRole("button", { name: "Move Spending behavior" }).focus();
    await user.keyboard("{ArrowDown}");
    expect(headings(pane).slice(0, 3)).toEqual(["Fan", "Unsold PPVs sent", "Spending behavior"]);

    // Drag the Mass exclude block onto the first block.
    const grip = within(pane).getByRole("button", { name: "Move Mass exclude" });
    const first = within(pane).getByRole("region", { name: "Fan" });
    fireEvent.dragStart(grip, { dataTransfer: { setData: () => {}, setDragImage: () => {} } });
    fireEvent.dragOver(first, { dataTransfer: {} });
    fireEvent.drop(first, { dataTransfer: {} });
    expect(headings(pane).slice(0, 4)).toEqual(["Mass exclude", "Fan", "Unsold PPVs sent", "Spending behavior"]);
    // The removed Organization metrics keeps its slot, so it stays removed.
    expect(headings(pane)).not.toContain("Organization metrics");
  });

  it("the layout is saved: a later Fan insights opens with it, and its twin follows at once", async () => {
    const user = userEvent.setup();
    renderInsights({ layout: "both" });
    const [slideOver, pinned] = [
      screen.getByRole("dialog", { name: "Fan insights" }),
      screen.getByRole("complementary", { name: "Fan insights" }),
    ];
    await user.click(within(slideOver).getByRole("button", { name: "Remove Lists" }));
    expect(headings(pinned)).not.toContain("Lists");
    cleanup();

    renderInsights();
    expect(headings(screen.getByRole("dialog", { name: "Fan insights" }))).toEqual(BLOCK_ORDER.filter((h) => h !== "Lists"));
  });

  it("a layout saved before a block existed shows that block, after the saved ones", () => {
    window.localStorage.setItem(LAYOUT_KEY, JSON.stringify({
      order: ["notes", "spending", "org", "subscription", "profile", "lists", "gone-block"], hidden: ["profile"],
    }));
    renderInsights();
    expect(headings(screen.getByRole("dialog", { name: "Fan insights" }))).toEqual([
      "Notes", "Spending behavior", "Organization metrics", "Subscription", "Lists", "Fan", "Unsold PPVs sent", "Mass exclude",
    ]);
  });

  it("a layout saved under the first key is reset once: the new defaults apply", () => {
    window.localStorage.setItem("chatterly:fan-insights-blocks", JSON.stringify({
      order: ["spending", "org", "subscription", "profile", "lists", "notes", "fan", "massExclude", "unsoldPpvs"], hidden: [],
    }));
    renderInsights();
    expect(headings(screen.getByRole("dialog", { name: "Fan insights" }))).toEqual(BLOCK_ORDER);
  });
});
