import { beforeEach, describe, expect, it } from "vitest";

import { amountFrom, anchorFor, clampToViewport, lastOutboundOf, replyStateOf } from "./MoneyRail";
import { distinctPayers, mergeMoneyRows, payerIdOf, type MergedItem } from "./useMoneyRailFeed";
import { initialRailDock, railDockReducer, type RailDockState } from "./useRailDock";
import type { CachedNotification } from "@/lib/notifSettings";
import type { OFChatItem } from "@/lib/relay";
import type { AttributionResponse } from "@/hooks/useChatAttribution";

const ACCOUNT = "5551";
const ME = 5551;
const FAN = 999;

/** Attribution for the newest outbound row. `kind` null = a human chatter. */
function attrib(messageId: number, kind: string | null): AttributionResponse {
  return {
    by_msg_id: {
      [String(messageId)]: {
        employee_id: kind ? null : 7,
        display_name: kind ? "Automation" : "jack",
        automation_kind: kind,
        sender_name: null,
        color: null,
      },
    },
  };
}

function chat(over: Partial<OFChatItem>): OFChatItem {
  return { withUser: { id: FAN }, ...over } as OFChatItem;
}

/** Freshly fetched /chats/{id}: real ids, real receipt, but up to 60s old. */
function detailWith(lastMsg: {
  id: number;
  text: string;
  from: number;
  at: string;
}, lastReadMessageId?: number): OFChatItem {
  return chat({
    lastMessage: {
      id: lastMsg.id,
      text: lastMsg.text,
      fromUser: { id: lastMsg.from },
      createdAt: lastMsg.at,
    },
    lastReadMessageId,
  });
}

describe("replyStateOf", () => {
  it("shows ✓✓ seen when the fan's read receipt reaches our last message", () => {
    const st = replyStateOf(
      detailWith({ id: 100, text: "<p>u liked it huh</p>", from: ME, at: "2026-07-12T09:18:00Z" }, 100),
      null,
      ACCOUNT,
    );
    expect(st).toMatchObject({ text: "u liked it huh", outbound: true, seen: true, stale: false });
  });

  it("shows a plain ✓ when the receipt is behind our last message", () => {
    const st = replyStateOf(
      detailWith({ id: 101, text: "ok", from: ME, at: "2026-07-12T09:35:00Z" }, 100),
      null,
      ACCOUNT,
    );
    expect(st).toMatchObject({ outbound: true, seen: false });
  });

  it("marks the fan as owed a reply when they spoke last", () => {
    const st = replyStateOf(
      detailWith({ id: 102, text: "Made me hard", from: FAN, at: "2026-07-12T09:23:00Z" }),
      null,
      ACCOUNT,
    );
    // outbound=false is what paints the orange "awaiting your reply" dot.
    expect(st).toMatchObject({ outbound: false, seen: false, unread: false });
  });

  it("uses the optimistic chat-list row when a chatter has just replied", () => {
    // The regression: sending patches the chat-list row with the new TEXT but
    // reuses the previous lastMessage.id (useSendMessage). Preferring the
    // 60s-stale detail fetch here reverted the row to the fan's old message.
    const detail = detailWith(
      { id: 102, text: "Made me hard", from: FAN, at: "2026-07-12T09:23:00Z" },
      102,
    );
    const optimistic = chat({
      lastMessage: {
        id: 102, // stale id — the send hasn't been reconciled yet
        text: "ok",
        fromUser: { id: ME },
        createdAt: "2026-07-12T09:35:00Z",
      },
      lastReadMessageId: 102,
      unreadMessagesCount: 0,
    });
    const st = replyStateOf(detail, optimistic, ACCOUNT);
    expect(st?.text).toBe("ok");
    expect(st?.outbound).toBe(true);
    // The dot must clear: we spoke last, so nobody owes the fan a reply.
    // And we must NOT claim "seen" off the stale id (lastRead 102 >= id 102)
    // — the fan cannot have read a message sent one second ago.
    expect(st?.seen).toBe(false);
    expect(st?.stale).toBe(true);
  });

  it("prefers an SSE-delivered inbound over a stale detail fetch", () => {
    const detail = detailWith({ id: 200, text: "you around?", from: ME, at: "2026-07-12T10:00:00Z" }, 200);
    const live = chat({
      lastMessage: {
        id: 201,
        text: "yeah just got home",
        fromUser: { id: FAN },
        createdAt: "2026-07-12T10:05:00Z",
      },
      lastReadMessageId: 200,
      unreadMessagesCount: 1,
    });
    expect(replyStateOf(detail, live, ACCOUNT)).toMatchObject({
      text: "yeah just got home",
      outbound: false,
      unread: true,
      stale: true,
    });
  });

  it("keeps the trustworthy detail row when both sources agree on time", () => {
    const at = "2026-07-12T09:18:00Z";
    const detail = detailWith({ id: 100, text: "hey", from: ME, at }, 100);
    const cached = chat({
      lastMessage: { id: 0, text: "hey", fromUser: { id: ME }, createdAt: at },
    });
    expect(replyStateOf(detail, cached, ACCOUNT)).toMatchObject({ seen: true, stale: false });
  });

  it("falls back to media count when the last message has no text", () => {
    const st = replyStateOf(
      chat({ lastMessage: { id: 5, text: "", fromUser: { id: ME }, createdAt: "2026-07-12T09:00:00Z", mediaCount: 3 } }),
      null,
      ACCOUNT,
    );
    expect(st?.text).toBe("(3 media)");
  });

  it("returns null for an empty thread", () => {
    expect(replyStateOf(chat({}), null, ACCOUNT)).toBeNull();
    expect(replyStateOf(null, null, ACCOUNT)).toBeNull();
  });
});

describe("replyStateOf — a bot reply doesn't discharge the thread", () => {
  const aiSent = detailWith(
    { id: 300, text: "<p>mm tell me more baby</p>", from: ME, at: "2026-07-12T09:40:00Z" },
    300,
  );

  it("keeps the dot lit when the last message came from an automation", () => {
    const st = replyStateOf(aiSent, null, ACCOUNT, lastOutboundOf(attrib(300, "welcome_chatter_for_info")));
    expect(st).toMatchObject({ outbound: true, byBot: true, seen: true });
  });

  it("clears the dot when a human chatter sent the last message", () => {
    const st = replyStateOf(aiSent, null, ACCOUNT, lastOutboundOf(attrib(300, null)));
    expect(st?.byBot).toBe(false);
  });

  it("does not blame the bot when the attribution row is for an OLDER message", () => {
    // The chatter just replied (id 301); our DB still only knows the AI's 300.
    // Claiming byBot here would flash an orange dot at someone who just replied.
    const st = replyStateOf(
      detailWith({ id: 301, text: "ok", from: ME, at: "2026-07-12T09:41:00Z" }, 300),
      null,
      ACCOUNT,
      lastOutboundOf(attrib(300, "welcome_chatter_for_info")),
    );
    expect(st?.byBot).toBe(false);
  });

  it("stays silent about the sender while the send is still optimistic", () => {
    const detail = detailWith(
      { id: 300, text: "mm tell me more baby", from: ME, at: "2026-07-12T09:40:00Z" },
      300,
    );
    const optimistic = chat({
      lastMessage: { id: 300, text: "ok", fromUser: { id: ME }, createdAt: "2026-07-12T09:45:00Z" },
      lastReadMessageId: 300,
    });
    const st = replyStateOf(detail, optimistic, ACCOUNT, lastOutboundOf(attrib(300, "welcome_chatter_for_info")));
    // The stale optimistic id collides with the AI's real id — without the
    // `stale` guard this would keep the AI's dot on the chatter's own reply.
    expect(st).toMatchObject({ text: "ok", outbound: true, byBot: false, seen: false, stale: true });
  });

  it("has no opinion when attribution is missing entirely", () => {
    expect(lastOutboundOf(undefined)).toBeNull();
    expect(replyStateOf(aiSent, null, ACCOUNT, null)?.byBot).toBe(false);
  });
});


describe("anchorFor", () => {
  const VH = 800;

  it("pins to the bottom when the panel sits in the lower half", () => {
    // Dropped near the bottom → expanding must grow UP, so the bottom edge is
    // the one that stays put.
    expect(anchorFor(700, 68, VH)).toBe("bottom");
  });

  it("pins to the top when the panel sits in the upper half", () => {
    expect(anchorFor(20, 68, VH)).toBe("top");
  });

  it("decides on the panel's centre, not its top edge", () => {
    // Top edge is above the midpoint (390 < 400) but the centre is below it,
    // so this belongs to the bottom half.
    expect(anchorFor(390, 200, VH)).toBe("bottom");
  });
});

describe("clampToViewport", () => {
  beforeEach(() => {
    Object.defineProperty(window, "innerWidth", { value: 1000, writable: true, configurable: true });
    Object.defineProperty(window, "innerHeight", { value: 800, writable: true, configurable: true });
  });

  it("leaves an in-bounds position alone", () => {
    expect(clampToViewport(300, 200, 420)).toEqual({ x: 300, y: 200 });
  });

  it("pulls the panel back inside when it would hang off the edges", () => {
    // 1000 - 290 = 710 is the furthest left the panel can sit.
    expect(clampToViewport(9999, 9999, 420)).toEqual({ x: 710, y: 720 });
    expect(clampToViewport(-50, -50, 420)).toEqual({ x: 0, y: 0 });
  });

  it("always leaves the header grabbable, even for a tall panel", () => {
    // y is capped at innerHeight - 80 regardless of panel height, so the drag
    // handle can never be scrolled off the bottom where it can't be grabbed.
    expect(clampToViewport(0, 5000, 420).y).toBe(720);
  });

  it("re-anchors a spot saved from a bigger window", () => {
    Object.defineProperty(window, "innerWidth", { value: 500, writable: true, configurable: true });
    Object.defineProperty(window, "innerHeight", { value: 400, writable: true, configurable: true });
    expect(clampToViewport(900, 700, 68)).toEqual({ x: 210, y: 332 });
  });
});


describe("amountFrom: the Buys & tips amount chip in the house price format", () => {
  it("drops OF's .00, keeps real cents, adds commas", () => {
    expect(amountFrom("Noah R. sent you a $40.00 tip!")).toBe("$40");
    expect(amountFrom("Jim has purchased your message for $25.22!")).toBe("$25.22");
    expect(amountFrom("Ann tipped $1,250.00")).toBe("$1,250");
    expect(amountFrom("no money here")).toBeNull();
  });
});

describe("mergeMoneyRows", () => {
  const at = (min: number) => new Date(Date.UTC(2026, 9, 31, 12, min)).toISOString();
  const hist = (id: string, min: number, type: string, typeKey: CachedNotification["typeKey"] = null): CachedNotification =>
    ({ id, accountId: "a", type, typeKey, user: { id: 1 }, text: `h${id}`, createdAt: at(min) });
  const ids = (rows: MergedItem[]) => rows.map((m) => `${m.accountId}:${m.n.id}:${m.typeKey}:${m.n.text ?? ""}`);

  it.each([
    ["feed row beats the history row with the same aid:id",
      [{ aid: "a", type: "tip" as const, rows: [{ id: 1, text: "feed", createdAt: at(1) }] }],
      { a: [hist("1", 5, "tip")] }, ["a"], ["a:1:tip:feed"]],
    ["same id on another account is not a dupe",
      [{ aid: "b", type: "tip" as const, rows: [{ id: 1, text: "feed", createdAt: at(1) }] }],
      { a: [hist("1", 5, "tip")] }, ["a", "b"], ["a:1:tip:h1", "b:1:tip:feed"]],
    ["history: money only, typeKey else mapped from type",
      [], { a: [hist("1", 1, "message", "message"), hist("2", 2, "tip"), hist("3", 3, "x", "purchases"), hist("4", 4, "favorited")] },
      ["a"], ["a:3:purchases:h3", "a:2:tip:h2"]],
    ["history only for the picked accounts",
      [], { a: [hist("1", 1, "tip")], z: [hist("2", 2, "tip")] }, ["a"], ["a:1:tip:h1"]],
    ["newest first; undated rows last; ties keep list order",
      [{ aid: "a", type: "purchases" as const, rows: [{ id: 1, createdAt: at(1) }, { id: 2 }, { id: 3, createdAt: at(9) }] },
       { aid: "a", type: "tip" as const, rows: [{ id: 4, createdAt: at(1) }] }],
      {}, ["a"], ["a:3:purchases:", "a:1:purchases:", "a:4:tip:", "a:2:purchases:"]],
    ["unloaded lists contribute nothing",
      [{ aid: "a", type: "tip" as const, rows: undefined }], {}, ["a"], []],
  ])("%s", (_l, lists, history, aids, want) => {
    expect(ids(mergeMoneyRows(lists, history, aids))).toEqual(want);
  });

  it("caps at 50, keeping the newest", () => {
    const rows = Array.from({ length: 60 }, (_, i) => ({ id: i, createdAt: at(i) }));
    const out = mergeMoneyRows([{ aid: "a", type: "tip", rows }], {}, ["a"]);
    expect(out).toHaveLength(50);
    expect(out[0].n.id).toBe(59);
    expect(out[49].n.id).toBe(10);
  });
});

describe("payerIdOf / distinctPayers", () => {
  const row = (accountId: string, user?: { id?: number | string }, fromUser?: { id?: number | string }): MergedItem =>
    ({ n: { user, fromUser } as MergedItem["n"], accountId, typeKey: "tip", ts: 0 });

  it.each([
    [row("a", { id: 1 }, { id: 2 }), 1],
    [row("a", {}, { id: 2 }), 2],
    [row("a"), undefined],
  ])("payerIdOf %#", (m, want) => {
    expect(payerIdOf(m)).toBe(want);
  });

  const rows = [
    row("a", { id: 1 }), row("a", {}, { id: 1 }), row("b", { id: 1 }), row("a"), row("a", { id: 0 }),
    row("a", { id: 2 }), row("a", { id: 3 }),
  ];
  it.each([
    // [cap, expected] — order kept, one per account × fan, payerless rows skipped
    [undefined, ["a:1", "b:1", "a:2", "a:3"]],
    [2, ["a:1", "b:1"]],
    [3, ["a:1", "b:1", "a:2"]],
  ])("cap %s", (cap, want) => {
    expect(distinctPayers(rows, cap).map((p) => `${p.accountId}:${p.fanId}`)).toEqual(want);
  });
});

describe("railDockReducer", () => {
  const placed = (over: Partial<RailDockState["dock"]> = {}): RailDockState => ({
    ...initialRailDock, mounted: true, viewportH: 800,
    dock: { open: false, x: 100, y: 100, anchor: "top", ...over },
  });

  it("load sets the dock and the viewport and mounts, without a save", () => {
    const dock = { open: true, x: 5, y: 6, anchor: "bottom" as const };
    expect(railDockReducer(initialRailDock, { type: "load", dock, viewportH: 700 }))
      .toEqual({ dock, viewportH: 700, mounted: true, saves: 0 });
  });

  it.each([
    // [label, action, expected dock, saves]
    ["dragMove clamps, pins to the top, and never saves",
      { type: "dragMove", x: 9999, y: -5, panelH: 420, viewportW: 1000, viewportH: 800 } as const,
      { open: false, x: 710, y: 0, anchor: "top" }, 0],
    ["drop in the lower half re-anchors to the bottom and saves",
      { type: "drop", rect: { top: 700, bottom: 768, height: 68 }, viewportH: 800 } as const,
      { open: false, x: 100, y: 32, anchor: "bottom" }, 1],
    ["drop in the upper half keeps the top",
      { type: "drop", rect: { top: 20, bottom: 88, height: 68 }, viewportH: 800 } as const,
      { open: false, x: 100, y: 20, anchor: "top" }, 1],
    ["an unmeasurable drop still saves the dock as it is",
      { type: "drop", rect: null, viewportH: 800 } as const,
      { open: false, x: 100, y: 100, anchor: "top" }, 1],
    ["toggle flips open and saves",
      { type: "toggle" } as const,
      { open: true, x: 100, y: 100, anchor: "top" }, 1],
  ])("%s", (_l, action, dock, saves) => {
    expect(railDockReducer(placed(), action)).toMatchObject({ dock, saves });
  });

  it.each([
    // [label, start, action, expected dock, viewportH, saves]
    ["a top-anchored dock pulled back on screen, saved",
      placed({ x: 900, y: 700 }), { type: "resize", viewportW: 500, viewportH: 400, panelH: 68 } as const,
      { x: 210, y: 332, anchor: "top" }, 400, 1],
    ["bottom-anchored: clamped in top-space, re-expressed from the bottom",
      placed({ x: 0, y: 500, anchor: "bottom" }), { type: "resize", viewportW: 1000, viewportH: 400, panelH: 68 } as const,
      { x: 0, y: 332, anchor: "bottom" }, 400, 1],
    ["in bounds: only the viewport changes, no save",
      placed(), { type: "resize", viewportW: 1000, viewportH: 600, panelH: 68 } as const,
      { x: 100, y: 100 }, 600, 0],
    ["never-dragged (no x/y): only the viewport, no save",
      { ...placed(), dock: { open: false, x: null, y: null, anchor: "bottom" } } as RailDockState,
      { type: "resize", viewportW: 300, viewportH: 300, panelH: 68 } as const,
      { x: null, y: null }, 300, 0],
  ])("resize: %s", (_l, start, action, dock, viewportH, saves) => {
    expect(railDockReducer(start, action)).toMatchObject({ dock, viewportH, saves });
  });

  it("a resize that changes nothing keeps the same state (no re-render)", () => {
    const s = placed();
    expect(railDockReducer(s, { type: "resize", viewportW: 1000, viewportH: 800, panelH: 68 })).toBe(s);
  });
});
