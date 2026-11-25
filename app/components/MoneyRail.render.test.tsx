import { afterEach, beforeAll, beforeEach, describe, expect, it, vi } from "vitest";
import { act, cleanup, screen, waitFor } from "@testing-library/react";
import { focusManager } from "@tanstack/react-query";

const { relayGet, route, accounts } = vi.hoisted(() => ({
  relayGet: vi.fn(),
  route: { pathname: "/messages-pro" },
  accounts: [
    { id: "1001", nickname: "ava" },
    { id: "1002", nickname: "mia" },
  ],
}));

vi.mock("next/navigation", () => ({
  usePathname: () => route.pathname,
  useRouter: () => ({ push: vi.fn(), replace: vi.fn(), prefetch: vi.fn() }),
  useSearchParams: () => new URLSearchParams(),
  useParams: () => ({}),
}));

vi.mock("@/lib/relay", () => ({
  relay: { get: (...args: unknown[]) => relayGet(...args) },
  RelayError: class RelayError extends Error {
    constructor(public status: number, public body: unknown) { super(`relay ${status}`); }
  },
  proxyImage: () => "",
}));

vi.mock("@/hooks/useAccounts", () => ({
  useActiveAccounts: () => accounts,
}));

import { renderWithProviders } from "@/test-utils";
import {
  DEFAULT_SETTINGS,
  SETTINGS_KEY,
  writeSettings,
  type NotificationItem,
  type RailSettings,
} from "@/lib/moneyRailStorage";
import { holdLease } from "@/lib/viewLease";
import { armRead, resetReadGate } from "@/lib/ofReadGate";
import { APP_OPEN_WARM_FALLBACK_MS } from "@/lib/viewLease";
import { SELECTED_SOURCE } from "@/lib/viewLeaseState";
import { MoneyRail, MoneyRailRestoreButton } from "./MoneyRail";

const OF_NOTIFICATIONS = "/api/of/v2/users/notifications";
const OF_MONEY = "/api/of/v2/users/notifications/money";
const OF_CHAT_DETAIL = "/api/of/v2/chats/";

const FANOUT = accounts.length * 2;

function callsTo(prefix: string): string[] {
  return relayGet.mock.calls.map((c) => String(c[0])).filter((p) => p.startsWith(prefix));
}

function listReads(aid?: string): string[] {
  return relayGet.mock.calls.flatMap((c) => {
    const [path, ctx] = [String(c[0]), c[1] as { accountId?: string } | undefined];
    if (!path.startsWith(OF_NOTIFICATIONS) || (aid && ctx?.accountId !== aid)) return [];
    const q = new URLSearchParams(path.split("?")[1] ?? "");
    const types = path.startsWith(OF_MONEY) ? (q.get("types") ?? "").split(",") : [q.get("type") ?? ""];
    return types.map((t) => `${ctx?.accountId}:${t}`);
  });
}

function notif(id: number, name: string, amount: string): NotificationItem {
  return {
    id,
    type: "purchase",
    text: `${name} has purchased your message for $${amount}!`,
    createdAt: "2026-08-25T10:00:00.000Z",
    user: { id: 9000 + id, name },
  };
}

const ROWS: Record<string, NotificationItem[]> = {
  "1001:purchases": [notif(1, "Jim", "25.22"), notif(2, "Dana", "144.00"), notif(3, "Joe", "12.00")],
};

function seedRelay(): void {
  relayGet.mockImplementation((path: string, opts?: { accountId?: string }) => {
    if (path.startsWith(OF_MONEY)) {
      const types = (new URLSearchParams(path.split("?")[1] ?? "").get("types") ?? "").split(",");
      return Promise.resolve(Object.fromEntries(types.map((t) => [t, { list: ROWS[`${opts?.accountId}:${t}`] ?? [] }])));
    }
    if (path.startsWith(OF_NOTIFICATIONS)) {
      const type = new URLSearchParams(path.split("?")[1] ?? "").get("type") ?? "";
      return Promise.resolve({ list: ROWS[`${opts?.accountId}:${type}`] ?? [] });
    }
    if (path.startsWith(OF_CHAT_DETAIL)) return Promise.resolve({});
    return Promise.resolve({ by_msg_id: {} });
  });
}

async function flush(): Promise<void> {
  await act(async () => {
    await new Promise((r) => setTimeout(r, 0));
  });
}

beforeAll(async () => {
  seedRelay();
  writeSettings(DEFAULT_SETTINGS);
  route.pathname = "/messages-pro";
  renderWithProviders(<MoneyRail />);
  await screen.findByTitle("Expand");
  cleanup();
});

let release: () => void = () => {};
beforeEach(() => {
  window.localStorage.clear();
  relayGet.mockReset();
  seedRelay();
  route.pathname = "/messages-pro";
  writeSettings(DEFAULT_SETTINGS);
  resetReadGate();
  release = holdLease("test", accounts.map((a) => a.id));
});

afterEach(() => {
  cleanup();
  release();
});

describe("MoneyRail surface gate", () => {
  it("issues no requests at all on a surface it is not shown on", async () => {
    route.pathname = "/stats";
    const { container } = renderWithProviders(<MoneyRail />);
    await flush();

    expect(relayGet).not.toHaveBeenCalled();
    expect(container).toBeEmptyDOMElement();
  });

  it("fans out within one turn on a surface it IS shown on", async () => {
    route.pathname = "/messages-pro";
    renderWithProviders(<MoneyRail />);
    await flush();

    expect(listReads()).toHaveLength(FANOUT);
    expect(callsTo(OF_MONEY)).toEqual(accounts.map(() => `${OF_MONEY}?types=purchases%2Ctip&limit=20&offset=0`));
    expect(await screen.findByText("Jim")).toBeInTheDocument();
    await waitFor(() => expect(callsTo(OF_CHAT_DETAIL)).not.toHaveLength(0));
  });

  it("keeps rendering smallRows while COLLAPSED on a visible surface", async () => {
    writeSettings({ ...DEFAULT_SETTINGS, smallRows: 2 });
    route.pathname = "/messages-pro";
    const { container } = renderWithProviders(<MoneyRail />);

    expect(await screen.findByTitle("Expand")).toBeInTheDocument();
    expect(listReads()).toHaveLength(FANOUT);
    const body = await waitFor(() => {
      const el = container.querySelector<HTMLElement>(".overflow-y-auto");
      expect(el).not.toBeNull();
      return el!;
    });
    expect(body.style.maxHeight).toBe("136px");
    expect(screen.getByText("Jim")).toBeInTheDocument();
    expect(screen.getByText("Joe")).toBeInTheDocument();
  });

  it("rides a client-side nav between two visible surfaces, then leaves", async () => {
    route.pathname = "/messages-pro";
    const { rerender, container } = renderWithProviders(<MoneyRail />);
    expect(await screen.findByText("Jim")).toBeInTheDocument();
    const fetched = listReads().length;

    route.pathname = "/group";
    await act(async () => {
      rerender(<MoneyRail />);
    });
    expect(screen.getByText("Jim")).toBeInTheDocument();
    expect(listReads()).toHaveLength(fetched);

    route.pathname = "/stats";
    await act(async () => {
      rerender(<MoneyRail />);
    });
    expect(container).toBeEmptyDOMElement();
  });

  it("mounts and fetches when the surface is ticked on AFTER mount", async () => {
    route.pathname = "/stats";
    renderWithProviders(<MoneyRail />);
    await flush();
    expect(relayGet).not.toHaveBeenCalled();

    await act(async () => {
      writeSettings({ ...DEFAULT_SETTINGS, surfaces: null });
      await new Promise((r) => setTimeout(r, 0));
    });

    await waitFor(() => expect(listReads()).toHaveLength(FANOUT));
    expect(await screen.findByText("Jim")).toBeInTheDocument();
  });
});

describe("MoneyRailRestoreButton", () => {
  const LABEL = /rail is hidden here/i;

  it("offers the way back only where the rail is actually hidden", async () => {
    route.pathname = "/stats";
    const hidden = renderWithProviders(<MoneyRailRestoreButton />);
    expect(await screen.findByText(LABEL)).toBeInTheDocument();
    hidden.unmount();

    route.pathname = "/messages-pro";
    const { container } = renderWithProviders(<MoneyRailRestoreButton />);
    await flush();
    expect(container).toBeEmptyDOMElement();
  });

  it("follows a hide performed in ANOTHER tab", async () => {
    route.pathname = "/messages-pro";
    renderWithProviders(<MoneyRailRestoreButton />);
    await flush();
    expect(screen.queryByText(LABEL)).toBeNull();

    await act(async () => {
      const next: RailSettings = { ...DEFAULT_SETTINGS, surfaces: ["group"] };
      window.localStorage.setItem(SETTINGS_KEY, JSON.stringify(next));
      window.dispatchEvent(new StorageEvent("storage", { key: SETTINGS_KEY }));
    });

    expect(await screen.findByText(LABEL)).toBeInTheDocument();
  });
});

describe("MoneyRail OF call budget", () => {
  afterEach(() => {
    vi.restoreAllMocks();
    focusManager.setFocused(undefined);
  });

  async function hideAndReturn(): Promise<void> {
    await act(async () => { focusManager.setFocused(false); });
    await act(async () => { focusManager.setFocused(true); });
    await flush();
  }

  it("a tab return re-reads OF's lists only once they are stale, then once", async () => {
    renderWithProviders(<MoneyRail />);
    await flush();
    expect(listReads()).toHaveLength(FANOUT);

    await hideAndReturn();
    expect(listReads()).toHaveLength(FANOUT);

    const later = Date.now() + 5 * 60_000 + 1;
    vi.spyOn(Date, "now").mockReturnValue(later);
    await hideAndReturn();
    await waitFor(() => expect(listReads()).toHaveLength(2 * FANOUT));
  });
});

describe("MoneyRail lease gate", () => {
  afterEach(() => {
    vi.restoreAllMocks();
    focusManager.setFocused(undefined);
  });

  const listsOf = (aid: string) => listReads(aid);

  it("an unleased Creator reads nothing until its creator_warmed, then once, with no focus re-read", async () => {
    release();
    renderWithProviders(<MoneyRail />);
    await flush();
    expect(listReads()).toHaveLength(0);

    await act(async () => { armRead("1001"); });
    await flush();
    expect(listsOf("1001")).toHaveLength(2);
    expect(listsOf("1002")).toHaveLength(0);

    vi.spyOn(Date, "now").mockReturnValue(Date.now() + 10 * 60_000);
    await act(async () => { focusManager.setFocused(false); });
    await act(async () => { focusManager.setFocused(true); });
    await flush();
    expect(listReads()).toHaveLength(2);
  });

  it("an unleased Creator whose warm never came reads at the fallback deadline after the load", async () => {
    release();
    resetReadGate(Date.now() - APP_OPEN_WARM_FALLBACK_MS);
    renderWithProviders(<MoneyRail />);
    await flush();
    await flush();
    expect(listReads()).toHaveLength(FANOUT);
  });

  it("a lease gain refetches a list older than 30 s, not a fresher one", async () => {
    release();
    armRead("1001");
    armRead("1002");
    renderWithProviders(<MoneyRail />);
    await flush();
    expect(listReads()).toHaveLength(FANOUT);

    const t0 = Date.now();
    const off1 = holdLease("chat", ["1001"]);
    await flush();
    expect(listReads()).toHaveLength(FANOUT);

    vi.spyOn(Date, "now").mockReturnValue(t0 + 31_000);
    const off2 = holdLease("strip", ["1002"]);
    await flush();
    expect(listsOf("1002")).toHaveLength(4);
    expect(listsOf("1001")).toHaveLength(2);
    off1();
    off2();
  });

  it("a selection refetches its stale lists even if already leased", async () => {
    renderWithProviders(<MoneyRail />);
    await flush();
    expect(listReads()).toHaveLength(FANOUT);
    vi.spyOn(Date, "now").mockReturnValue(Date.now() + 31_000);
    const off = holdLease(SELECTED_SOURCE, ["1002"]);
    await flush();
    expect(listsOf("1002")).toHaveLength(4);
    expect(listsOf("1001")).toHaveLength(2);
    off();
  });

  it("a Dead-session Creator issues no query, leased or not", async () => {
    const dead = { id: "1003", nickname: "gone", session_dead_at: "2026-11-01T00:00:00Z" };
    (accounts as { id: string; nickname: string }[]).push(dead);
    const off = holdLease("strip", ["1003"]);
    try {
      renderWithProviders(<MoneyRail />);
      await flush();
      expect(listReads()).toHaveLength(FANOUT);
      expect(listsOf("1003")).toHaveLength(0);
    } finally {
      off();
      accounts.pop();
    }
  });
});
