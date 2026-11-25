import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { ReactElement } from "react";

import {
  DEFAULT_NOTIF_SETTINGS,
  readNotifHistory,
  type NotifSettings,
} from "@/lib/notifSettings";

let mockSettings: NotifSettings;
let mockAccountId: string | null;
let mockActive: { id: string; platform?: "onlyfans" | "fansly" | null; has_session: boolean }[];
type Handler = (env: unknown, rawType?: string) => void;
let handlers: Map<string, Set<Handler>>;
let mockSession: { user: object | null; chatter: object | null };
let mockRelayGet: ReturnType<typeof vi.fn>;
let mockRelayPost: ReturnType<typeof vi.fn> = vi.fn();
let mockPushLive = false;
let pushNotice: ((raw: unknown) => boolean) | null = null;
const mockPlayAlertOnce = vi.fn();
const mockOsNotify = vi.fn(async () => {});

function settingsWith(over: {
  toastMessage: boolean;
  bubbleMessage: boolean;
}): NotifSettings {
  return {
    ...DEFAULT_NOTIF_SETTINGS,
    enabled: true,
    osPing: false,
    toast: { ...DEFAULT_NOTIF_SETTINGS.toast, subscribed: true, message: over.toastMessage },
    bubble: { ...DEFAULT_NOTIF_SETTINGS.bubble, message: over.bubbleMessage },
  };
}

async function loadComponent(
  { realAccounts = false }: { realAccounts?: boolean } = {},
): Promise<() => ReactElement> {
  vi.resetModules();
  handlers = new Map();

  vi.doMock("@/lib/events", () => ({
    eventBus: {
      on(type: string, fn: Handler) {
        let set = handlers.get(type);
        if (!set) {
          set = new Set();
          handlers.set(type, set);
        }
        set.add(fn);
        return () => set!.delete(fn);
      },
    },
  }));

  vi.doMock("@/hooks/useDeferredMount", () => ({
    useDeferredMount: () => true,
  }));

  vi.doMock("@/hooks/useNotificationSettings", () => ({
    useNotificationSettings: () => ({ settings: mockSettings }),
  }));

  vi.doMock("@/contexts/ScopeContext", () => ({
    useScope: () => ({ accountId: mockAccountId }),
  }));

  if (realAccounts) vi.doUnmock("@/hooks/useAccounts");
  else {
    vi.doMock("@/hooks/useAccounts", () => ({
      useActiveAccounts: () => mockActive,
    }));
  }

  vi.doMock("@/lib/relay", () => ({
    proxyImage: (url: string | null | undefined) => url ?? null,
    relay: { get: mockRelayGet, post: mockRelayPost },
    RelayError: class extends Error {},
  }));

  vi.doMock("@/contexts/UserContext", () => ({
    useOptionalUser: () => (mockSession.user ? { user: mockSession.user } : null),
    useUser: () => ({ user: { user_id: "owner-1" } }),
  }));
  vi.doMock("@/contexts/ChatterContext", () => ({
    useOptionalChatter: () => (mockSession.chatter ? { chatter: mockSession.chatter } : null),
    useChatter: () => ({ chatter: null }),
  }));

  vi.doMock("@/lib/webPush", () => ({
    isPushLive: () => mockPushLive,
    pushSupported: () => false,
    primePush: async () => {},
    syncPush: () => {},
    listenPushNotices: (fn: (raw: unknown) => boolean) => {
      pushNotice = fn;
      return () => { if (pushNotice === fn) pushNotice = null; };
    },
  }));
  vi.doMock("@/lib/alertSounds", async (orig) => ({
    ...(await orig<typeof import("@/lib/alertSounds")>()),
    playAlertOnce: mockPlayAlertOnce,
  }));
  vi.doMock("@/lib/osNotify", () => ({ osNotify: mockOsNotify, hasShellNotify: () => false }));

  const mod = await import("@/components/NotificationToaster");
  const Toaster = () => <mod.NotificationToaster />;
  return Toaster;
}

function fire(type: string, env: unknown) {
  const set = handlers.get(type);
  if (!set || set.size === 0) {
    throw new Error(`no handler registered for "${type}" — effect didn't subscribe`);
  }
  act(() => {
    for (const fn of set) fn(env);
  });
}

function renderToaster(Comp: () => ReactElement) {
  const qc = new QueryClient({
    defaultOptions: { queries: { retry: false, gcTime: 0, staleTime: 0 } },
  });
  return { ...render(<QueryClientProvider client={qc}><Comp /></QueryClientProvider>), qc };
}

function findToastByText(container: HTMLElement, text: string): HTMLElement | null {
  const cards = Array.from(
    container.querySelectorAll<HTMLElement>("div.bg-panel"),
  );
  return cards.find((c) => c.textContent?.includes(text)) ?? null;
}

beforeEach(() => {
  window.localStorage.clear();
  mockSettings = settingsWith({ toastMessage: true, bubbleMessage: false });
  mockAccountId = "100";
  mockActive = [];
  mockSession = { user: null, chatter: null };
  mockPushLive = false;
  pushNotice = null;
  mockRelayGet = vi.fn(async (path: string) => {
    throw new Error(`unmocked GET ${path}`);
  });
});

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
  vi.resetModules();
  vi.useRealTimers();
});

describe("NotificationToaster — inbound api2_chat_message bubble", () => {
  it("case 1: inbound + toast.message + bubble.message → toast with accent-ring bubble", async () => {
    mockAccountId = "100";
    mockSettings = settingsWith({ toastMessage: true, bubbleMessage: true });
    const Comp = await loadComponent();
    const { container } = renderToaster(Comp);

    fire("api2_chat_message", {
      __account_id: "100",
      api2_chat_message: { id: 1001, text: "hey from case1", fromUser: { id: 777, name: "Flinty" } },
    });

    const card = findToastByText(container, "hey from case1");
    expect(card).not.toBeNull();
    expect(card!.className).toContain("ring-accent");
    expect(card!.className).not.toContain("ring-border");
    expect(card!.textContent).toContain("Flinty");
  });

  it("case 2: inbound + toast.message + NO bubble → plain toast (ring-border, not ring-accent)", async () => {
    mockAccountId = "101";
    mockSettings = settingsWith({ toastMessage: true, bubbleMessage: false });
    const Comp = await loadComponent();
    const { container } = renderToaster(Comp);

    fire("api2_chat_message", {
      __account_id: "101",
      api2_chat_message: { id: 1002, text: "plain case2", fromUser: { id: 778, name: "Plainy" } },
    });

    const card = findToastByText(container, "plain case2");
    expect(card).not.toBeNull();
    expect(card!.className).toContain("ring-border");
    expect(card!.className).toContain("ring-1");
    expect(card!.className).not.toContain("ring-accent");
  });

  it("case 3: outbound echo (fromUser.id === account, with __fan_id) → NO toast", async () => {
    mockAccountId = "102";
    mockSettings = settingsWith({ toastMessage: true, bubbleMessage: true });
    const Comp = await loadComponent();
    const { container } = renderToaster(Comp);

    fire("api2_chat_message", {
      __account_id: "102",
      __fan_id: 779,
      api2_chat_message: { id: 1003, text: "outbound case3", fromUser: { id: 102, name: "Me" } },
    });

    expect(findToastByText(container, "outbound case3")).toBeNull();
    expect(container.querySelector("div.bg-panel")).toBeNull();
  });

  it("case 4: toast.message:false → NO toast, but history still mirrored", async () => {
    mockAccountId = "103";
    mockSettings = settingsWith({ toastMessage: false, bubbleMessage: true });
    const Comp = await loadComponent();
    const { container } = renderToaster(Comp);

    fire("api2_chat_message", {
      __account_id: "103",
      api2_chat_message: { id: 1004, text: "history case4", fromUser: { id: 780, name: "Histy" } },
    });

    expect(findToastByText(container, "history case4")).toBeNull();
    expect(container.querySelector("div.bg-panel")).toBeNull();

    const hist = readNotifHistory();
    const entries = hist["103"] ?? [];
    const entry = entries.find((e) => e.id === "m1004");
    expect(entry).toBeTruthy();
    expect(entry!.text).toContain("history case4");
    expect(entry!.typeKey).toBe("message");
    expect(window.localStorage.getItem("chatterly:notif-history:v1")).toContain("m1004");
  });

  it("chat_responded marks that fan's message history as answered, by whom", async () => {
    mockAccountId = "107";
    const Comp = await loadComponent();
    renderToaster(Comp);

    fire("api2_chat_message", {
      __account_id: "107",
      api2_chat_message: { id: 1070, text: "anyone?", fromUser: { id: 790, name: "Waity" } },
    });
    fire("api2_chat_message", {
      __account_id: "107",
      api2_chat_message: { id: 1071, text: "me too", fromUser: { id: 791, name: "Other" } },
    });
    fire("chat_responded", { __account_id: "107", chat_responded: { fan_id: 790, by: "Kingsley" } });

    const byId = Object.fromEntries((readNotifHistory()["107"] ?? []).map((e) => [e.id, e.respondedBy]));
    expect(byId).toEqual({ m1070: "Kingsley", m1071: undefined });
  });

  it("case 5: out-of-scope account (__account_id not in targetIds) → NO toast", async () => {
    mockAccountId = "104";
    mockSettings = settingsWith({ toastMessage: true, bubbleMessage: true });
    const Comp = await loadComponent();
    const { container } = renderToaster(Comp);

    fire("api2_chat_message", {
      __account_id: "999",
      api2_chat_message: { id: 1005, text: "scope case5", fromUser: { id: 781, name: "Stranger" } },
    });

    expect(findToastByText(container, "scope case5")).toBeNull();
    expect(container.querySelector("div.bg-panel")).toBeNull();
    const hist = readNotifHistory();
    expect(hist["104"]).toBeUndefined();
  });

  it("case 6: empty text + mediaCount>0 → toast text contains 'Sent you media'", async () => {
    mockAccountId = "105";
    mockSettings = settingsWith({ toastMessage: true, bubbleMessage: false });
    const Comp = await loadComponent();
    const { container } = renderToaster(Comp);

    fire("api2_chat_message", {
      __account_id: "105",
      api2_chat_message: { id: 1006, text: "", mediaCount: 2, fromUser: { id: 782, name: "Media" } },
    });

    const card = findToastByText(container, "Sent you media");
    expect(card).not.toBeNull();
    expect(card!.textContent).toContain("Media");
  });
});

describe("NotificationToaster — tip/purchase toast href carries ?refresh=media", () => {
  function fireOfToast(aid: string, toast: Record<string, unknown>) {
    fire("toasts", { __account_id: aid, toasts: [toast] });
  }

  function findChatAnchor(container: HTMLElement, fanId: number): HTMLAnchorElement | null {
    const anchors = Array.from(container.querySelectorAll<HTMLAnchorElement>("a"));
    return anchors.find((a) => a.getAttribute("href")?.includes(`/${fanId}`)) ?? null;
  }

  it("tip toast → href ends with ?refresh=media", async () => {
    mockAccountId = "300";
    const Comp = await loadComponent();
    const { container } = renderToaster(Comp);

    fireOfToast("300", {
      id: 9001,
      type: "tip",
      text: "tipped you $10",
      data: { relatedUser: { id: 555, name: "Tipper" } },
    });

    const a = findChatAnchor(container, 555);
    expect(a).not.toBeNull();
    expect(a!.getAttribute("href")).toBe("/messages-pro/300/555?refresh=media&fanTab=Tipper");
    expect(a!.getAttribute("target")).toBeNull();
  });

  it("a click opens the Fan tab: in place inside Messages Pro, else in the Messages Pro window", async () => {
    mockAccountId = "303";
    const Comp = await loadComponent();
    const { container } = renderToaster(Comp);
    const link = await import("@/lib/notificationLink");
    const open = vi.spyOn(window, "open").mockReturnValue(null);
    try {
      fireOfToast("303", { id: 9004, type: "subscribed", text: "subscribed", data: { relatedUser: { id: 558, name: "Ann" } } });
      const inPage = vi.fn();
      const unregister = link.setFanTabOpener(inPage);
      fireEvent.click(findChatAnchor(container, 558)!);
      expect(inPage).toHaveBeenCalledWith({ accountId: "303", fanId: 558, name: "Ann" }, { refresh: false });
      expect(open).not.toHaveBeenCalled();
      expect(container.querySelector('a[href*="/558"]')).toBeNull();

      unregister();
      fireOfToast("303", { id: 9005, type: "subscribed", text: "subscribed", data: { relatedUser: { id: 559, name: "Bo" } } });
      fireEvent.click(findChatAnchor(container, 559)!);
      expect(inPage).toHaveBeenCalledTimes(1);
      expect(open).toHaveBeenCalledWith("", "messages-pro", expect.any(String));
    } finally {
      open.mockRestore();
    }
  });

  it("purchase toast (paided_message) → href ends with ?refresh=media", async () => {
    mockAccountId = "301";
    const Comp = await loadComponent();
    const { container } = renderToaster(Comp);

    fireOfToast("301", {
      id: 9002,
      type: "paided_message",
      text: "unlocked your message",
      data: { relatedUser: { id: 556, name: "Buyer" } },
    });

    const a = findChatAnchor(container, 556);
    expect(a).not.toBeNull();
    expect(a!.getAttribute("href")).toBe("/messages-pro/301/556?refresh=media&fanTab=Buyer");
  });

  it("subscribed toast → plain href, no refresh flag", async () => {
    mockAccountId = "302";
    const Comp = await loadComponent();
    const { container } = renderToaster(Comp);

    fireOfToast("302", {
      id: 9003,
      type: "subscribed",
      text: "subscribed to you",
      data: { relatedUser: { id: 557, name: "Newsub" } },
    });

    const a = findChatAnchor(container, 557);
    expect(a).not.toBeNull();
    expect(a!.getAttribute("href")).toBe("/messages-pro/302/557?fanTab=Newsub");
  });
});

const RECENT_OF_TS = new Date(Date.now() - 60_000).toISOString()
  .replace("Z", "+00:00");
// Never pin a date in a purchase fixture: appendNotifHistory prunes rows older than 7 days, silently.
const RECENT_OF_TS_UTC = new Date(Date.parse(RECENT_OF_TS)).toISOString();

describe("NotificationToaster — arrivals seed the money lists, never refetch them", () => {
  function spyInvalidate() {
    return vi.spyOn(QueryClient.prototype, "invalidateQueries")
      .mockImplementation(() => Promise.resolve());
  }
  const refetchedNotifList = (spy: ReturnType<typeof spyInvalidate>) => spy.mock.calls.some(
    ([arg]) => JSON.stringify((arg as { queryKey?: unknown })?.queryKey ?? null).startsWith('["notif-list"'),
  );
  const OLD_ROW = { id: 1, type: "tip", text: "older", createdAt: "2026-01-01T00:00:00.000Z" };

  it("toasts lane: muted tip → no toast, recorded, seeded into the cached tip list, no refetch", async () => {
    mockAccountId = "700";
    mockSettings = { ...DEFAULT_NOTIF_SETTINGS, enabled: false };
    const spy = spyInvalidate();
    try {
      const Comp = await loadComponent();
      const { container, qc } = renderToaster(Comp);
      qc.setQueryData(["notif-list", "700", "tip"], [OLD_ROW]);

      fire("toasts", {
        __account_id: "700",
        toasts: [{
          id: 7001, type: "tip", text: "tipped you $10",
          data: { relatedUser: { id: 771, name: "Muted" } },
        }],
      });

      expect(container.querySelector("div.bg-panel")).toBeNull();
      expect(readNotifHistory()["700"]?.length).toBe(1);
      const list = qc.getQueryData<{ id: unknown; user?: { id?: unknown } }[]>(["notif-list", "700", "tip"]);
      expect(list?.map((r) => String(r.id))).toEqual(["7001", "1"]);
      expect(list?.[0]?.user?.id).toBe(771);
      expect(refetchedNotifList(spy)).toBe(false);
    } finally {
      spy.mockRestore();
    }
  });

  it("purchase lane: muted PPV unlock → recorded, seeded into the cached purchases list, no refetch", async () => {
    mockAccountId = "701";
    mockSettings = { ...DEFAULT_NOTIF_SETTINGS, enabled: false };
    const spy = spyInvalidate();
    try {
      const Comp = await loadComponent();
      const { qc } = renderToaster(Comp);
      qc.setQueryData(["notif-list", "701", "purchases"], [OLD_ROW]);

      fire("purchase_notified", {
        __account_id: "701",
        purchase_notified: {
          notif_id: "7002", fan_id: 772, message_id: 9, amount_cents: 500,
          created_at: RECENT_OF_TS, name: "Quiet",
        },
      });

      expect(readNotifHistory()["701"]?.length).toBe(1);
      const list = qc.getQueryData<{ id: unknown; text?: string; createdAt?: string }[]>(
        ["notif-list", "701", "purchases"]);
      expect(list?.[0]).toMatchObject({ id: "7002", text: "Unlocked your PPV — $5", createdAt: RECENT_OF_TS_UTC });
      expect(list).toHaveLength(2);
      expect(refetchedNotifList(spy)).toBe(false);
    } finally {
      spy.mockRestore();
    }
  });

  it("a list never fetched stays unfetched; a pinged DM refetches nothing", async () => {
    mockAccountId = "702";
    const spy = spyInvalidate();
    try {
      const Comp = await loadComponent();
      const { qc } = renderToaster(Comp);

      fire("toasts", {
        __account_id: "702",
        toasts: [{ id: 7003, type: "tip", text: "tipped you $5", data: { relatedUser: { id: 773 } } }],
      });
      fire("api2_chat_message", {
        __account_id: "702",
        api2_chat_message: { id: 7004, text: "hi", fromUser: { id: 773, name: "Dm" } },
      });

      expect(qc.getQueryData(["notif-list", "702", "tip"])).toBeUndefined();
      expect(readNotifHistory()["702"]?.length).toBe(2);
      expect(refetchedNotifList(spy)).toBe(false);
    } finally {
      spy.mockRestore();
    }
  });
});

describe("NotificationToaster — another accessible Creator's money, in a tab scoped to one", () => {
  const OLD_ROW = { id: 1, type: "tip", text: "older", createdAt: "2026-01-01T00:00:00.000Z" };
  const active = (...ids: string[]) => ids.map((id) => ({ id, platform: "onlyfans" as const, has_session: true }));

  it("toasts lane: a tip → no toast, recorded, seeded into the cached tip list", async () => {
    mockAccountId = "710";
    mockActive = active("710", "711");
    mockSettings = { ...DEFAULT_NOTIF_SETTINGS, enabled: true, osPing: false };
    const Comp = await loadComponent();
    const { container, qc } = renderToaster(Comp);
    qc.setQueryData(["notif-list", "711", "tip"], [OLD_ROW]);

    fire("toasts", {
      __account_id: "711",
      toasts: [{ id: 7101, type: "tip", text: "tipped you $10", data: { relatedUser: { id: 781, name: "Away" } } }],
    });

    expect(container.querySelector("div.bg-panel")).toBeNull();
    expect(readNotifHistory()["711"]?.map((e) => e.id)).toEqual(["7101"]);
    const list = qc.getQueryData<{ id: unknown }[]>(["notif-list", "711", "tip"]);
    expect(list?.map((r) => String(r.id))).toEqual(["7101", "1"]);
    expect(mockPlayAlertOnce).not.toHaveBeenCalled();
  });

  it("toasts lane: not money, or named by @username only → nothing recorded, nothing read", async () => {
    mockAccountId = "712";
    mockActive = active("712", "713");
    const Comp = await loadComponent();
    const { container } = renderToaster(Comp);

    fire("toasts", { __account_id: "713", toasts: [{ id: 7131, type: "favorited", text: "liked", data: { relatedUser: { id: 782 } } }] });
    fire("toasts", { __account_id: "713", toasts: [{ id: 7132, type: "tip", text: "tipped you $3", data: { relatedUser: { username: "u7132" } } }] });

    expect(container.querySelector("div.bg-panel")).toBeNull();
    expect(readNotifHistory()["713"]?.map((e) => e.id)).toEqual(["7132"]);
    expect(mockRelayGet).not.toHaveBeenCalled();
  });

  it("purchase lane: a PPV unlock → no toast, recorded, seeded into the cached purchases list", async () => {
    mockAccountId = "714";
    mockActive = active("714", "715");
    mockSettings = { ...DEFAULT_NOTIF_SETTINGS, enabled: true, osPing: false };
    const Comp = await loadComponent();
    const { container, qc } = renderToaster(Comp);
    qc.setQueryData(["notif-list", "715", "purchases"], [OLD_ROW]);

    fire("purchase_notified", {
      __account_id: "715",
      purchase_notified: { notif_id: "7151", fan_id: 783, message_id: 9, amount_cents: 500, created_at: RECENT_OF_TS, name: "Away" },
    });

    expect(container.querySelector("div.bg-panel")).toBeNull();
    expect(readNotifHistory()["715"]?.map((e) => e.id)).toEqual(["7151"]);
    expect(qc.getQueryData<{ id: unknown }[]>(["notif-list", "715", "purchases"])?.map((r) => String(r.id)))
      .toEqual(["7151", "1"]);
  });
});

describe("NotificationToaster — per-platform switches", () => {
  const tip = (aid: string, id: number) => fire("toasts", {
    __account_id: aid,
    toasts: [{ id, type: "tip", text: "tipped you $10", data: { relatedUser: { id: 781, name: "Plat" } } }],
  });

  it("a platform switched off pings nothing for its accounts, history still recorded", async () => {
    mockAccountId = null;
    mockActive = [
      { id: "710", platform: "fansly", has_session: true },
      { id: "711", platform: null, has_session: true },
    ];
    mockSettings = { ...DEFAULT_NOTIF_SETTINGS, osPing: false, platforms: { onlyfans: true, fansly: false } };
    const Comp = await loadComponent();
    const { container } = renderToaster(Comp);

    tip("710", 7101);
    expect(container.querySelector("div.bg-panel")).toBeNull();
    expect(readNotifHistory()["710"]?.length).toBe(1);

    tip("711", 7111);
    expect(container.querySelector("div.bg-panel")).not.toBeNull();
  });

  it("OnlyFans switched off mutes an account with no platform set", async () => {
    mockAccountId = null;
    mockActive = [{ id: "712", has_session: true }];
    mockSettings = { ...DEFAULT_NOTIF_SETTINGS, osPing: false, platforms: { onlyfans: false, fansly: true } };
    const Comp = await loadComponent();
    const { container } = renderToaster(Comp);

    tip("712", 7121);
    expect(container.querySelector("div.bg-panel")).toBeNull();
    expect(readNotifHistory()["712"]?.length).toBe(1);
  });

  it("OnlyFans switched off mutes an in-scope account missing from the active list", async () => {
    mockAccountId = "713";
    mockActive = [];
    mockSettings = { ...DEFAULT_NOTIF_SETTINGS, osPing: false, platforms: { onlyfans: false, fansly: true } };
    const Comp = await loadComponent();
    const { container } = renderToaster(Comp);

    tip("713", 7131);
    expect(container.querySelector("div.bg-panel")).toBeNull();
    expect(readNotifHistory()["713"]?.length).toBe(1);
  });
});

// The ping must carry OF's real notif id verbatim: the rail/bell dedupe on it, so a prefixed id double-lists the sale.
describe("NotificationToaster — purchase_notified PPV unlock", () => {
  function settingsForPurchases(on: boolean): NotifSettings {
    return {
      ...DEFAULT_NOTIF_SETTINGS,
      enabled: true,
      osPing: false,
      toast: { ...DEFAULT_NOTIF_SETTINGS.toast, purchases: on },
      bubble: { ...DEFAULT_NOTIF_SETTINGS.bubble, purchases: false },
    };
  }

  function fireBuy(aid: string, p: Record<string, unknown>) {
    fire("purchase_notified", { __account_id: aid, purchase_notified: p });
  }

  const unlock = (over: Record<string, unknown> = {}) => ({
    notif_id: "117301756206",
    fan_id: 4242,
    message_id: 10491720677794,
    amount_cents: 820,
    created_at: RECENT_OF_TS,
    name: "Daniel",
    ...over,
  });

  it("PPV unlock → money toast with the dollar amount + ?refresh=media href", async () => {
    mockAccountId = "400";
    mockSettings = settingsForPurchases(true);
    const Comp = await loadComponent();
    const { container } = renderToaster(Comp);

    fireBuy("400", unlock());

    expect(findToastByText(container, "Unlocked your PPV — $8.20")).not.toBeNull();
    const a = container.querySelector<HTMLAnchorElement>('a[href*="4242"]');
    expect(a!.getAttribute("href")).toBe("/messages-pro/400/4242?refresh=media&fanTab=Daniel");
  });

  it("history id is OF's notification id verbatim, so the feed row dedupes", async () => {
    mockAccountId = "401";
    mockSettings = settingsForPurchases(true);
    const Comp = await loadComponent();
    renderToaster(Comp);

    fireBuy("401", unlock({ notif_id: "117301756206" }));

    const [row] = readNotifHistory()["401"] ?? [];
    expect(row?.id).toBe("117301756206");
    expect(row?.typeKey).toBe("purchases");
    expect(row?.createdAt).toBe(RECENT_OF_TS_UTC);
    expect(row?.user?.name).toBe("Daniel");
  });

  it("history is mirrored even with the purchases toast muted (rail must not go deaf)", async () => {
    mockAccountId = "402";
    mockSettings = settingsForPurchases(false);
    const Comp = await loadComponent();
    const { container } = renderToaster(Comp);

    fireBuy("402", unlock({ notif_id: "222" }));

    expect(findToastByText(container, "Unlocked your PPV — $8.20")).toBeNull();
    expect(readNotifHistory()["402"]?.length).toBe(1);
  });

  it("a re-announce of the same notification is deduped", async () => {
    mockAccountId = "403";
    mockSettings = settingsForPurchases(true);
    const Comp = await loadComponent();
    renderToaster(Comp);

    fireBuy("403", unlock({ notif_id: "333" }));
    fireBuy("403", unlock({ notif_id: "333" }));

    expect(readNotifHistory()["403"]?.length).toBe(1);
  });

  it("two different purchases by the same fan both land", async () => {
    mockAccountId = "404";
    mockSettings = settingsForPurchases(true);
    const Comp = await loadComponent();
    renderToaster(Comp);

    fireBuy("404", unlock({ notif_id: "444", fan_id: 90 }));
    fireBuy("404", unlock({ notif_id: "445", fan_id: 90, amount_cents: 1500 }));

    expect(readNotifHistory()["404"]?.length).toBe(2);
  });

  it("an out-of-scope account never pings", async () => {
    mockAccountId = "405";
    mockSettings = settingsForPurchases(true);
    const Comp = await loadComponent();
    const { container } = renderToaster(Comp);

    fireBuy("999", unlock({ notif_id: "555" }));

    expect(container.querySelector("div.bg-panel")).toBeNull();
    expect(readNotifHistory()["999"]).toBeUndefined();
  });

  it("a payload with no notification id is ignored — it could not dedupe", async () => {
    mockAccountId = "406";
    mockSettings = settingsForPurchases(true);
    const Comp = await loadComponent();
    const { container } = renderToaster(Comp);

    fireBuy("406", unlock({ notif_id: undefined }));

    expect(container.querySelector("div.bg-panel")).toBeNull();
    expect(readNotifHistory()["406"]).toBeUndefined();
  });
});


describe("NotificationToaster — the clock-in reminder", () => {
  const REMINDER = {
    shift_id: 3, occurrence_start: "2026-10-14T15:00:00Z", occurrence_end: "2026-10-14T19:00:00Z",
    tz: "UTC", account_id: "1000001",
  };
  const TEXT = "Your shift on creator_one has started.";
  let reminder: typeof REMINDER | null;
  let clockReason: string | null;

  beforeEach(() => {
    mockSession = { user: null, chatter: { chatter_id: "c-1", username: "chatter_one" } };
    reminder = REMINDER;
    clockReason = null;
    mockRelayPost = vi.fn(async (path: string) => {
      if (path !== "/admin/shifts/clock-in") throw new Error(`unmocked POST ${path}`);
      return { clock_event_id: 9, employee_id: 41, account_id: null, shift_id: 3,
               in_utc: "2026-10-14T15:01:00Z", out_utc: null, close_reason: null };
    });
    mockRelayGet = vi.fn(async (path: string) => {
      if (path === "/admin/shifts/clock-status") {
        return { can_clock: true, reason: clockReason, open: null, last_closed: null,
                 auto_clock_out_minutes: 10, server_now: "2026-10-14T15:01:00Z" };
      }
      if (path !== "/admin/shifts/me") throw new Error(`unmocked GET ${path}`);
      return {
        accounts: [{ account_id: "1000001", display_name: "creator_one", time_tracking_enabled: true,
                     clock_in_reminder: true }],
        occurrences: [REMINDER], open_clocks: [], reminder,
      };
    });
  });

  async function renderReminder() {
    const Comp = await loadComponent();
    const qc = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: 0, staleTime: 0 } } });
    const utils = render(<QueryClientProvider client={qc}><Comp /></QueryClientProvider>);
    const poll = () => act(async () => { await qc.refetchQueries({ queryKey: ["shifts", "me"] }); });
    return { ...utils, poll };
  }

  it("a chatter gets one toast per occurrence, across polls and a reload", async () => {
    const { poll, unmount } = await renderReminder();
    expect(await screen.findByText(TEXT)).toBeInTheDocument();
    await poll();
    await poll();
    expect(screen.getAllByText(TEXT)).toHaveLength(1);
    expect(mockRelayGet.mock.calls.filter(([p]) => p === "/admin/shifts/me").length).toBeGreaterThanOrEqual(3);

    unmount();
    const before = mockRelayGet.mock.calls.length;
    const again = await renderReminder();
    await again.poll();
    await waitFor(() => expect(mockRelayGet.mock.calls.length).toBeGreaterThan(before));
    await act(async () => { await new Promise((r) => setTimeout(r, 20)); });
    expect(screen.queryByText(TEXT)).toBeNull();

    reminder = { ...REMINDER, occurrence_start: "2026-10-15T15:00:00Z", occurrence_end: "2026-10-15T19:00:00Z" };
    await again.poll();
    expect(await screen.findByText(TEXT)).toBeInTheDocument();
  });

  it("two chatters sharing a browser are each reminded of the same occurrence", async () => {
    const first = await renderReminder();
    expect(await screen.findByText(TEXT)).toBeInTheDocument();
    first.unmount();

    mockSession = { user: null, chatter: { chatter_id: "c-2", username: "chatter_two" } };
    await renderReminder();
    expect(await screen.findByText(TEXT)).toBeInTheDocument();
  });

  it("its Clock in action clocks in at once on the agency-wide clock and says so", async () => {
    await renderReminder();
    await screen.findByText(TEXT);
    await waitFor(() => expect(mockRelayGet).toHaveBeenCalledWith("/admin/shifts/clock-status"));
    fireEvent.click(screen.getByRole("button", { name: "Clock in" }));
    expect(await screen.findByText("Clock in successful")).toBeInTheDocument();
    expect(mockRelayPost.mock.calls).toEqual([["/admin/shifts/clock-in", {}]]);
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(screen.queryByText(TEXT)).toBeNull();
  });

  it("its Clock in action opens the clock dialog for a chatter in two Agencies", async () => {
    clockReason = "pick_creator";
    await renderReminder();
    await screen.findByText(TEXT);
    await waitFor(() => expect(mockRelayGet).toHaveBeenCalledWith("/admin/shifts/clock-status"));
    await act(async () => { await new Promise((r) => setTimeout(r, 20)); });
    fireEvent.click(screen.getByRole("button", { name: "Clock in" }));
    expect(await screen.findByRole("dialog", { name: "Clock in and out" })).toBeInTheDocument();
    expect(mockRelayPost).not.toHaveBeenCalled();
  });

  it("no reminder from the Relay, no toast", async () => {
    reminder = null;
    const { poll } = await renderReminder();
    await poll();
    expect(mockRelayGet).toHaveBeenCalledWith("/admin/shifts/me");
    expect(screen.queryByText(TEXT)).toBeNull();
  });

  it("an owner session never reads the chatter's shifts", async () => {
    mockSession = { user: { user_id: "owner-1" }, chatter: { username: "chatter_one" } };
    await renderReminder();
    await act(async () => { await Promise.resolve(); });
    expect(mockRelayGet).not.toHaveBeenCalled();
    expect(screen.queryByText(TEXT)).toBeNull();
  });
});

describe("NotificationToaster — platform switcher", () => {
  it("an OnlyFans DM still toasts while the shell is in Fansly mode", async () => {
    mockAccountId = null;
    mockSettings = settingsWith({ toastMessage: true, bubbleMessage: false });
    window.localStorage.setItem("chatterly:platform", "fansly");
    mockRelayGet = vi.fn(async (path: string) => {
      if (path === "/admin/accounts") {
        return {
          active_account_id: null,
          accounts: [
            { id: "of-200", nickname: "OF model", has_session: true, platform: "onlyfans" },
            { id: "fy-200", nickname: "Fansly model", has_session: true, platform: "fansly" },
          ],
        };
      }
      throw new Error(`unmocked GET ${path}`);
    });
    const Comp = await loadComponent({ realAccounts: true });
    const { container } = renderToaster(Comp);

    await waitFor(() => {
      fire("api2_chat_message", {
        __account_id: "of-200",
        api2_chat_message: { id: 2001, text: "of dm in fansly mode", fromUser: { id: 790, name: "OfFan" } },
      });
      expect(findToastByText(container, "of dm in fansly mode")).not.toBeNull();
    });
  });
});

describe("NotificationToaster — Web Push", () => {
  const dm = (id: number, text: string) => ({
    __account_id: "900",
    api2_chat_message: { id, text, fromUser: { id: 777, name: "Pushy" } },
  });
  const notice = (id: number, text: string) => ({
    v: 1, tag: `900:m${id}`, title: "Pushy", body: text,
    href: "/messages-pro/900/777?fanTab=Pushy", type: "message", account_id: "900",
  });
  const count = (c: HTMLElement, text: string) =>
    Array.from(c.querySelectorAll("div.bg-panel")).filter((d) => d.textContent?.includes(text)).length;

  beforeEach(() => {
    mockAccountId = "900";
    mockSettings = { ...settingsWith({ toastMessage: true, bubbleMessage: false }), osPing: true };
    window.localStorage.setItem("chatterly:notif-settings:v1", JSON.stringify(mockSettings));
  });

  it.each([
    [false, 1],
    [true, 0],
  ])("unfocused tab, push live=%s → in-page OS pings: %i", async (live, pings) => {
    mockPushLive = live;
    const focus = vi.spyOn(document, "hasFocus").mockReturnValue(false);
    try {
      const Comp = await loadComponent();
      const { container } = renderToaster(Comp);
      fire("api2_chat_message", dm(9001, "ping me"));
      expect(count(container, "ping me")).toBe(1);
      expect(mockOsNotify).toHaveBeenCalledTimes(pings);
    } finally {
      focus.mockRestore();
    }
  });

  function offer(raw: unknown): boolean {
    if (!pushNotice) throw new Error("no push-notice listener");
    let took = false;
    act(() => { took = pushNotice!(raw); });
    return took;
  }

  it("the SW's push-notice after the lane's frame → one toast, still acked (no OS notification)", async () => {
    const Comp = await loadComponent();
    const { container } = renderToaster(Comp);
    fire("api2_chat_message", dm(9002, "lane first"));
    expect(offer(notice(9002, "lane first"))).toBe(true);
    expect(count(container, "lane first")).toBe(1);
  });

  it("the push-notice before a sale's frame (idle mode's replay) → one toast; the frame still plays the sale sound, keyed once", async () => {
    mockSettings = { ...mockSettings, sounds: { ...mockSettings.sounds, sale: { on: true, sound: "s12" } } };
    const Comp = await loadComponent();
    const { container } = renderToaster(Comp);
    const ppv = { v: 1, tag: "900:9060", title: "Buyer", body: "Unlocked your PPV — $5", type: "purchases", account_id: "900", href: "/messages-pro/900/778?refresh=media&fanTab=Buyer" };
    expect(offer(ppv)).toBe(true);
    expect(mockPlayAlertOnce).not.toHaveBeenCalled();
    const buy = { __account_id: "900", purchase_notified: { notif_id: "9060", fan_id: 778, amount_cents: 500, name: "Buyer" } };
    fire("purchase_notified", buy);
    fire("purchase_notified", buy);
    expect(count(container, "Unlocked your PPV")).toBe(1);
    expect(mockPlayAlertOnce.mock.calls).toEqual([["900:9060", "s12"]]);
  });

  it("sale sound ignores a replayed old purchase and plays a fresh purchase once", async () => {
    mockSettings = { ...mockSettings, sounds: { ...mockSettings.sounds, sale: { on: true, sound: "s12" } } };
    renderToaster(await loadComponent());
    const buy = (notif_id: string, created_at: string) => ({
      __account_id: "900", purchase_notified: { notif_id, fan_id: 778, amount_cents: 500, created_at },
    });
    fire("purchase_notified", buy("9061", new Date(Date.now() - 45 * 60_000).toISOString()));
    expect(mockPlayAlertOnce).not.toHaveBeenCalled();
    const fresh = buy("9062", new Date().toISOString());
    fire("purchase_notified", fresh);
    fire("purchase_notified", fresh);
    expect(mockPlayAlertOnce.mock.calls).toEqual([["900:9062", "s12"]]);
  });

  it("sale sound: a tip plays it, a DM does not", async () => {
    mockSettings = { ...mockSettings, sounds: { ...mockSettings.sounds, sale: { on: true, sound: "s3" } } };
    const Comp = await loadComponent();
    renderToaster(Comp);
    fire("api2_chat_message", dm(9070, "just a dm"));
    expect(mockPlayAlertOnce).not.toHaveBeenCalled();
    fire("toasts", { __account_id: "900", toasts: [{ id: 9071, type: "tip", text: "tipped you $10", data: { relatedUser: { id: 779, name: "Tipper" } } }] });
    expect(mockPlayAlertOnce.mock.calls).toEqual([["900:9071", "s3"]]);
  });

  it("sale sound off by the master switch → silent tip", async () => {
    mockSettings = { ...mockSettings, enabled: false, sounds: { ...mockSettings.sounds, sale: { on: true, sound: "s3" } } };
    const Comp = await loadComponent();
    renderToaster(Comp);
    fire("toasts", { __account_id: "900", toasts: [{ id: 9072, type: "tip", text: "tipped you $10", data: { relatedUser: { id: 779, name: "Tipper" } } }] });
    expect(mockPlayAlertOnce).not.toHaveBeenCalled();
  });

  it("the push-notice before the lane's frame → the bell's history row is the lane's (avatar, username, OF's time), not the push's", async () => {
    const Comp = await loadComponent();
    renderToaster(Comp);
    expect(offer(notice(9005, "rich row"))).toBe(true);
    expect(readNotifHistory()["900"] ?? []).toEqual([]);
    fire("api2_chat_message", {
      __account_id: "900",
      api2_chat_message: {
        id: 9005, text: "rich row", createdAt: RECENT_OF_TS,
        fromUser: { id: 777, name: "Pushy", username: "pushy_u", avatar: "https://cdn.example/a.jpg" },
      },
    });
    const rows = readNotifHistory()["900"] ?? [];
    expect(rows).toHaveLength(1);
    expect(rows[0]).toMatchObject({
      id: "m9005",
      user: { id: 777, name: "Pushy", username: "pushy_u", avatar: "https://cdn.example/a.jpg" },
      createdAt: RECENT_OF_TS_UTC,
    });
  });

  it("the push-notice before a money frame → one toast; the frame still seeds the rail's list", async () => {
    const Comp = await loadComponent();
    const { container, qc } = renderToaster(Comp);
    qc.setQueryData(["notif-list", "900", "purchases"], [{ id: 1, type: "purchases", text: "older", createdAt: "2026-01-01T00:00:00.000Z" }]);
    const ppv = { v: 1, tag: "900:9050", title: "Buyer", body: "Unlocked your PPV — $5", type: "purchases", account_id: "900", href: "/messages-pro/900/778?refresh=media&fanTab=Buyer" };
    expect(offer(ppv)).toBe(true);
    fire("purchase_notified", {
      __account_id: "900",
      purchase_notified: { notif_id: "9050", fan_id: 778, amount_cents: 500, name: "Buyer" },
    });
    expect(count(container, "Unlocked your PPV")).toBe(1);
    const list = qc.getQueryData<{ id: unknown }[]>(["notif-list", "900", "purchases"]);
    expect(list?.map((r) => String(r.id))).toEqual(["9050", "1"]);
  });

  it("a notice for a Creator out of this page's scope → no toast, not acked (the worker shows it)", async () => {
    const Comp = await loadComponent();
    const { container } = renderToaster(Comp);
    expect(offer({ ...notice(9004, "elsewhere"), tag: "901:m9004", account_id: "901" })).toBe(false);
    expect(count(container, "elsewhere")).toBe(0);
  });
});
