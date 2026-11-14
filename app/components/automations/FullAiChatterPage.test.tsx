/**
 * Full AI Chat: the settings column (five controls, Save / Roll back / JSON over the draft config, the persona block), the Test chat (two windows, one composer; POST /admin/full-ai/test/turn per side), the on/off switch over kind `full_ai_chat` (Shadow / Off) through the server's kind switch,
 * and today's Shadow Decision rows (GET /admin/full-ai/today): counts in Route order, then the newest rows.
 */
import { afterEach, beforeEach, describe, expect, it, vi, type Mock } from "vitest";
import { act, cleanup, fireEvent, screen, waitFor, within } from "@testing-library/react";
import type { QueryClient } from "@tanstack/react-query";

vi.mock("@/lib/relay", async (importOriginal) => {
  const mod = await importOriginal<typeof import("@/lib/relay")>();
  // Every verb mocked, so nothing here can reach a live relay.
  return {
    ...mod,
    relay: {
      ...mod.relay,
      get: vi.fn(), put: vi.fn(), post: vi.fn(), patch: vi.fn(),
      delete: vi.fn(), uploadFile: vi.fn(),
    },
  };
});
const accounts = vi.hoisted(() => ({ list: [{ id: "acc-a", nickname: "Creator A", has_session: true }] }));
vi.mock("@/hooks/useAccounts", () => ({
  useActiveAccounts: () => accounts.list,
  useAccounts: () => ({ isLoading: false }),
}));
vi.mock("@/contexts/EmployeeContext", () => ({ useEmployee: () => ({ current: null }) }));

import FullAiChatterPage from "@/components/automations/FullAiChatterPage";
import { fullAiConfigKey } from "@/hooks/useFullAiConfig";
import { relay, RelayError } from "@/lib/relay";
import { makeTestQueryClient, renderWithProviders } from "@/test-utils";

const relayGet = relay.get as unknown as Mock;
const relayPost = relay.post as unknown as Mock;

const rule = (is_enabled: boolean) => ({
  id: 9, account_id: "acc-a", name: "Full AI Chat", kind: "full_ai_chat", is_enabled,
  every_seconds: 86400, trigger: { every_seconds: 86400 }, payload: {},
  quiet_hours: null, created_at: null, last_run: null, next_due_at: null, has_pending_job: false,
});

const TODAY = {
  since: "2026-11-13T00:00:00Z",
  // Keys out of Route order, so the strip's order comes from the page, not the payload.
  counts: { no_send: 1, chat: 7, ai_dare: 2, sext: 6, make_right: 3, sell_now: 5, tease: 4 },
  jev_failed: 8,
  rows: [
    { id: 2, created_at: "2026-11-13T10:05:00Z", fan_id: "77", fan_name: "Garrett", route: "tease", heat: 3,
      row: "tease_price", jev_ms: 412, jev_failed: false },
    { id: 1, created_at: "2026-11-13T10:00:00Z", fan_id: "78", fan_name: null, route: "chat", heat: 1,
      row: "jev_failed", jev_ms: null, jev_failed: true },
  ],
};

const TEMPLATE = "Name: \nAge: \nFrom: \nPersonality: \nLikes: \nWon't do (hard limits): ";
const CONFIG = { version: 1, reply_speed: "0-2m", text_style: "girl", gifs: false, writers: ["euryale-v2.3"] };
const configBody = (over: Record<string, unknown> = {}) =>
  ({ checkpoint: CONFIG, previous: null, draft: CONFIG, rev: 3, errors: [], ...over });
/** The reads every mount answers: the Full AI config, the account config (Model info) and the LLM keys status. */
const baseGet = (p: string): unknown => {
  if (p.startsWith("/admin/full-ai/config")) return configBody();
  if (p.startsWith("/admin/account-config")) {
    return { account_id: "acc-a", config: { persona: "", model_notes: null }, model_notes_template: TEMPLATE };
  }
  if (p.startsWith("/admin/my-llm-keys")) {
    return { providers: { nanogpt: { set: true, hint: "••••n4n0" }, openrouter: { set: false, hint: "" } } };
  }
  return {};
};

let client: QueryClient;
beforeEach(() => {
  client = makeTestQueryClient();
  accounts.list = [{ id: "acc-a", nickname: "Creator A", has_session: true }];
  relayGet.mockReset();
  relayPost.mockReset();
  relayPost.mockResolvedValue({ action: "created" });
});
afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

const mount = (rules: unknown[], today: unknown = TODAY) => {
  relayGet.mockImplementation((path: string) => {
    const p = String(path);
    if (p.startsWith("/admin/automation-rules")) return Promise.resolve({ rules: rules.slice() });
    if (p.startsWith("/admin/full-ai/today")) return Promise.resolve(today);
    return Promise.resolve(baseGet(p));
  });
  renderWithProviders(<FullAiChatterPage />, client);
};
const settings = () => within(screen.getByRole("list", { name: "Settings" }));
const theSwitch = () => settings().getByRole("switch", { name: "Full AI Chat" }) as HTMLButtonElement;
const switchCalls = () => relayPost.mock.calls.filter((c) => String(c[0]) === "/admin/automation-rules/switch");

describe("Full AI Chat page", () => {
  it("reads Off with no rule and flips it to Shadow through the server switch", async () => {
    mount([]);
    await waitFor(() => expect(theSwitch().disabled).toBe(false));
    expect(theSwitch().getAttribute("aria-checked")).toBe("false");
    expect(settings().getByText("Off")).toBeTruthy();
    await act(async () => { fireEvent.click(theSwitch()); });
    await waitFor(() => expect(switchCalls().length).toBe(1));
    expect(switchCalls()[0][1]).toEqual({ account_id: "acc-a", kind: "full_ai_chat", enable: true });
    expect(relayPost).toHaveBeenCalledTimes(1);
  });

  it("reads Shadow from an enabled rule and switches it off", async () => {
    mount([rule(true)]);
    await waitFor(() => expect(theSwitch().getAttribute("aria-checked")).toBe("true"));
    expect(settings().getByText("Shadow")).toBeTruthy();
    await act(async () => { fireEvent.click(theSwitch()); });
    await waitFor(() => expect(switchCalls().length).toBe(1));
    expect(switchCalls()[0][1]).toEqual({ account_id: "acc-a", kind: "full_ai_chat", enable: false });
  });

  it("counts today's rows in Route order, Jev failures last, and reads the Creator's today", async () => {
    mount([rule(true)]);
    const strip = await screen.findByRole("list", { name: "Decisions per route" });
    await waitFor(() => expect(within(strip).getAllByRole("listitem")[0].textContent).toBe("Chat7"));
    expect(within(strip).getAllByRole("listitem").map((li) => li.textContent)).toEqual([
      "Chat7", "Sext6", "Sell now5", "Tease4", "Make right3", "AI dare2", "No send1", "Jev failed8",
    ]);
    expect(relayGet.mock.calls.some((c) => String(c[0]) === "/admin/full-ai/today?account_id=acc-a")).toBe(true);
  });

  it("shows the newest rows: Fan, Route, Heat, row and Jev latency or Jev failed", async () => {
    mount([rule(true)]);
    const rows = await screen.findAllByTestId("full-ai-row");
    expect(rows.length).toBe(2);
    const first = within(rows[0]).getAllByRole("cell").map((td) => td.textContent);
    expect(first.slice(1)).toEqual(["Garrett", "Tease", "3", "tease_price", "412 ms"]);
    const second = within(rows[1]).getAllByRole("cell").map((td) => td.textContent);
    expect(second.slice(1)).toEqual(["Fan 78", "Chat", "1", "jev_failed", "Jev failed"]);
  });

  it("shows the house no-Creator state and reads nothing with no live Creator", async () => {
    accounts.list = [];
    mount([]);
    expect(await screen.findByText("No creator with a live session")).toBeTruthy();
    expect(screen.queryByRole("switch", { name: "Full AI Chat" })).toBeNull();
    expect(relayGet).not.toHaveBeenCalled();
  });
});

// ── Test chat ────────────────────────────────────────────────────────────────────────────────────────────────────
type Body = { account_id: string; pair: string; side: "checkpoint" | "draft"; n: number; text: string };
const answer = (over: Record<string, unknown> = {}) => ({
  row_id: 11, route: "chat", heat: 2, route_row: "otherwise", dropped: [], parts: [{ text: "hey babe" }],
  writer: "euryale-v2.3", attempts: [{ writer: "euryale-v2.3", outcome: "ok", ms: 800 }], wait_s: 0,
  status: "sent", fan_info: {}, ...over,
});
/** A row as GET /admin/full-ai/test/session returns it (`full_ai_test.session_row`): no `dropped`. */
const sessionRow = (over: Record<string, unknown> = {}) =>
  Object.fromEntries(Object.entries(answer(over)).filter(([k]) => k !== "dropped"));
const PHONE = "(max-width: 639px)";
const turnCalls = () => relayPost.mock.calls.filter((c) => String(c[0]) === "/admin/full-ai/test/turn");

/** The page with the turn route answering per side (`bySide`), and the session read answering `session`. */
const mountChat = (
  bySide: Record<string, (b: Body) => unknown>,
  session: unknown = { rows: [] },
) => {
  relayPost.mockImplementation((path: string, body: Body) => {
    if (String(path) === "/admin/full-ai/test/turn") {
      try { return Promise.resolve(bySide[body.side](body)); } catch (e) { return Promise.reject(e); }
    }
    return Promise.resolve({ action: "created" });
  });
  relayGet.mockImplementation((path: string) => {
    const p = String(path);
    if (p.startsWith("/admin/automation-rules")) return Promise.resolve({ rules: [] });
    if (p.startsWith("/admin/full-ai/today")) return Promise.resolve(TODAY);
    if (p.startsWith("/admin/full-ai/test/session")) return Promise.resolve(session);
    return Promise.resolve(baseGet(p));
  });
  renderWithProviders(<FullAiChatterPage />, client);
};
const win = (name: "Checkpoint" | "Draft") => within(screen.getByRole("region", { name }));
const composer = () => screen.getByRole("textbox", { name: "Fan message" }) as HTMLTextAreaElement;
const sendBtn = () => screen.getByRole("button", { name: "Send" }) as HTMLButtonElement;
const say = async (text: string) => {
  fireEvent.change(composer(), { target: { value: text } });
  await act(async () => { fireEvent.click(sendBtn()); });
};
const skipWait = () => fireEvent.click(screen.getByRole("switch", { name: "Skip wait" }));

describe("Full AI Chat page › Test chat", () => {
  it("is titled Full AI Chat", async () => {
    mountChat({});
    expect(await screen.findByRole("heading", { name: "Full AI Chat" })).toBeTruthy();
  });

  it("one composer sends his line to both windows as two requests, checkpoint and draft, Turn 1 then 2", async () => {
    mountChat({ checkpoint: () => answer(), draft: () => answer({ parts: [{ text: "hi there" }] }) });
    await screen.findByRole("region", { name: "Checkpoint" });
    skipWait();
    await say("hey");
    await waitFor(() => expect(turnCalls().length).toBe(2));
    const bodies = turnCalls().map((c) => c[1] as Body).sort((a, b) => a.side.localeCompare(b.side));
    expect(bodies.map(({ account_id, side, n, text }) => ({ account_id, side, n, text }))).toEqual([
      { account_id: "acc-a", side: "checkpoint", n: 1, text: "hey" },
      { account_id: "acc-a", side: "draft", n: 1, text: "hey" },
    ]);
    expect(bodies[0].pair).toBe(bodies[1].pair);
    expect(await win("Checkpoint").findByText("hey babe")).toBeTruthy();
    expect(await win("Draft").findByText("hi there")).toBeTruthy();
    expect(win("Checkpoint").getByText("hey")).toBeTruthy();
    await waitFor(() => expect(sendBtn().disabled).toBe(true)); // the composer is empty again
    await say("you?");
    await waitFor(() => expect(turnCalls().length).toBe(4));
    expect(turnCalls().slice(2).map((c) => (c[1] as Body).n)).toEqual([2, 2]);
  });

  it("disables Send while a side is in flight and shows typing dots there", async () => {
    let finish: (v: unknown) => void = () => {};
    mountChat({ checkpoint: () => answer(), draft: () => new Promise((r) => { finish = r; }) });
    await screen.findByRole("region", { name: "Draft" });
    skipWait();
    await say("hey");
    expect(await win("Checkpoint").findByText("hey babe")).toBeTruthy();
    expect(win("Draft").getByRole("status", { name: "typing" })).toBeTruthy();
    fireEvent.change(composer(), { target: { value: "more" } });
    expect(sendBtn().disabled).toBe(true);
    await act(async () => { finish(answer({ parts: [{ text: "late one" }] })); });
    expect(await win("Draft").findByText("late one")).toBeTruthy();
    await waitFor(() => expect(sendBtn().disabled).toBe(false));
  });

  it("holds a reply back for its wait_s without skip-wait (typing dots, Send disabled)", async () => {
    mountChat({ checkpoint: () => answer({ wait_s: 90 }), draft: () => answer({ wait_s: 90 }) });
    await screen.findByRole("region", { name: "Checkpoint" });
    await say("hey");
    await waitFor(() => expect(turnCalls().length).toBe(2));
    await waitFor(() => expect(win("Checkpoint").getByRole("status", { name: "typing" })).toBeTruthy());
    expect(win("Checkpoint").queryByText("hey babe")).toBeNull();
    fireEvent.change(composer(), { target: { value: "more" } });
    expect(sendBtn().disabled).toBe(true);
    skipWait();
    expect(await win("Checkpoint").findByText("hey babe")).toBeTruthy();
  });

  it("reveals a reply when its wait is over, without skip-wait", async () => {
    mountChat({ checkpoint: () => answer({ wait_s: 0.05 }), draft: () => answer({ wait_s: 0.05 }) });
    await screen.findByRole("region", { name: "Checkpoint" });
    await say("hey");
    expect(await win("Checkpoint").findByText("hey babe")).toBeTruthy();
    expect(await win("Draft").findByText("hey babe")).toBeTruthy();
    await waitFor(() => expect(win("Draft").queryByRole("status", { name: "typing" })).toBeNull());
  });

  it("prints the reply line: Route, Heat, matched row, the Writer and how many fell before it", async () => {
    mountChat({
      checkpoint: () => answer(),
      draft: () => answer({ route: "sext", heat: 3, route_row: "sexual_now", writer: "hermes-4-405b",
        attempts: [{ writer: "euryale-v2.3", outcome: "http_503", ms: 120 },
          { writer: "hermes-4-405b", outcome: "ok", ms: 2100 }] }),
    });
    await screen.findByRole("region", { name: "Checkpoint" });
    skipWait();
    await say("hey");
    expect((await win("Checkpoint").findByTestId("reply-line")).textContent)
      .toBe("Route chat · Heat 2 · Row otherwise · Writer euryale-v2.3 · 0 fell before");
    expect((await win("Draft").findByTestId("reply-line")).textContent)
      .toBe("Route sext · Heat 3 · Row sexual_now · Writer hermes-4-405b · 1 fell before");
  });

  it("an all-failed Turn reads 'no reply: all writers failed' with each outcome; no_send reads promo / under 18", async () => {
    mountChat({
      checkpoint: () => answer({ status: "failed", parts: [], writer: null, attempts: [
        { writer: "euryale-v2.3", outcome: "http_503", ms: 100 }, { writer: "hermes-4-405b", outcome: "timeout", ms: 25000 },
        { writer: "glm-5.3-flash", outcome: "no_key", ms: 0 }, { writer: "deepseek-v4-flash", outcome: "empty", ms: 900 },
      ] }),
      draft: (b) => answer({ status: "no_send", route: "no_send", route_row: b.n === 1 ? "promo" : "says_under_18",
        parts: [], writer: null, attempts: [] }),
    });
    await screen.findByRole("region", { name: "Checkpoint" });
    skipWait();
    await say("check my page");
    expect(await win("Checkpoint").findByText("no reply: all writers failed")).toBeTruthy();
    expect(win("Checkpoint").getByText(
      "euryale-v2.3 http_503 · hermes-4-405b timeout · glm-5.3-flash no_key · deepseek-v4-flash empty")).toBeTruthy();
    expect(await win("Draft").findByText("no reply (promo)")).toBeTruthy();
    await waitFor(() => expect(sendBtn().disabled).toBe(true));
    await say("im 16");
    expect(await win("Draft").findByText("no reply (under 18)")).toBeTruthy();
  });

  it("the window header shows the facts the test Fan gave", async () => {
    mountChat({
      checkpoint: () => answer({ fan_info: { real_name: "Mike", his_age: "31", home_city: "Austin", fetishes: "" } }),
      draft: () => answer(),
    });
    await screen.findByRole("region", { name: "Checkpoint" });
    expect(win("Checkpoint").getByTestId("facts").textContent).toBe("No facts yet");
    skipWait();
    await say("im mike, 31, from austin");
    await waitFor(() => expect(win("Checkpoint").getByTestId("facts").textContent)
      .toBe("name Mike · age 31 · city Austin"));
    expect(win("Draft").getByTestId("facts").textContent).toBe("No facts yet");
  });

  it("renders a GIF part through the Giphy render", async () => {
    mountChat({ checkpoint: () => answer({ parts: [{ text: "lol" }, { gif: "abc123", tag: "cat_wink" }] }),
      draft: () => answer() });
    await screen.findByRole("region", { name: "Checkpoint" });
    skipWait();
    await say("hey");
    const img = await win("Checkpoint").findByRole("img", { name: "GIF cat_wink" });
    expect(img.getAttribute("src")).toContain("abc123");
  });

  it("a failed request keeps its Turn number on Retry; a 409 reloads that session", async () => {
    let draftCalls = 0;
    mountChat({
      checkpoint: () => answer(),
      draft: () => {
        draftCalls += 1;
        if (draftCalls === 1) throw new RelayError(503, {}, "relay 503");
        throw new RelayError(409, { row_id: 12 });
      },
    }, { rows: [
      { side: "checkpoint", n: 1, text: "hey", created_at: "2026-11-14T03:00:00Z", ...sessionRow({ parts: [{ text: "the other side" }] }) },
      { side: "draft", n: 1, text: "hey", created_at: "2026-11-14T03:00:01Z", ...sessionRow({ parts: [{ text: "from the reload" }], wait_s: null }) },
    ] });
    await screen.findByRole("region", { name: "Draft" });
    skipWait();
    await say("hey");
    await act(async () => { fireEvent.click(await win("Draft").findByRole("button", { name: "Retry" })); });
    expect(await win("Draft").findByText("from the reload")).toBeTruthy();
    const draftBodies = turnCalls().map((c) => c[1] as Body).filter((b) => b.side === "draft");
    expect(draftBodies.map((b) => b.n)).toEqual([1, 1]);
    const reload = relayGet.mock.calls.map((c) => String(c[0])).find((p) => p.startsWith("/admin/full-ai/test/session"));
    expect(reload).toBe(`/admin/full-ai/test/session?account_id=acc-a&pair=${encodeURIComponent(draftBodies[0].pair)}`);
  });

  it("New chat starts a fresh pair with empty windows", async () => {
    mountChat({ checkpoint: () => answer(), draft: () => answer() });
    await screen.findByRole("region", { name: "Checkpoint" });
    skipWait();
    await say("hey");
    expect(await win("Checkpoint").findByText("hey babe")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "New chat" }));
    expect(win("Checkpoint").queryByText("hey babe")).toBeNull();
    await say("again");
    await waitFor(() => expect(turnCalls().length).toBe(4));
    const pairs = turnCalls().map((c) => (c[1] as Body).pair);
    expect(pairs[2]).not.toBe(pairs[0]);
    expect(turnCalls().slice(2).map((c) => (c[1] as Body).n)).toEqual([1, 1]);
  });

  describe("on a phone held upright", () => {
    const real = window.matchMedia;
    beforeEach(() => {
      window.matchMedia = vi.fn((q: string) => ({
        matches: q === PHONE, media: q, addEventListener: () => {}, removeEventListener: () => {},
      })) as unknown as typeof window.matchMedia;
    });
    afterEach(() => { window.matchMedia = real; });

    it("shows the windows as Checkpoint / Draft tabs, one at a time", async () => {
      mountChat({ checkpoint: () => answer(), draft: () => answer({ parts: [{ text: "draft says hi" }] }) });
      const tabs = within(await screen.findByRole("tablist", { name: "Test chat windows" }));
      expect(tabs.getAllByRole("tab").map((t) => t.textContent)).toEqual(["Checkpoint", "Draft"]);
      expect(screen.getByRole("region", { name: "Checkpoint" })).toBeTruthy();
      expect(screen.queryByRole("region", { name: "Draft" })).toBeNull();
      skipWait();
      await say("hey");
      fireEvent.click(tabs.getByRole("tab", { name: "Draft" }));
      expect(await win("Draft").findByText("draft says hi")).toBeTruthy();
      expect(screen.queryByRole("region", { name: "Checkpoint" })).toBeNull();
    });

    it("desktop shows both windows and no tabs", async () => {
      window.matchMedia = real;
      mountChat({});
      expect(await screen.findByRole("region", { name: "Checkpoint" })).toBeTruthy();
      expect(screen.getByRole("region", { name: "Draft" })).toBeTruthy();
      expect(screen.queryByRole("tablist")).toBeNull();
    });
  });
});

// ── Settings column (ticket 39) ──────────────────────────────────────────────────────────────────────────────────
const relayPut = relay.put as unknown as Mock;
const putCalls = () => relayPut.mock.calls.filter((c) => String(c[0]) === "/admin/full-ai/config/draft");
const postsTo = (path: string) => relayPost.mock.calls.filter((c) => String(c[0]) === path);
const btn = (name: string) => screen.getByRole("button", { name }) as HTMLButtonElement;

/** The page with the config read answering `config` (a function: called per read), writes answered by `put` / `post`. */
const mountSettings = (
  config: unknown = configBody(),
  { put, post }: { put?: (b: Record<string, unknown>) => unknown; post?: (path: string, b: Record<string, unknown>) => unknown } = {},
) => {
  relayGet.mockImplementation((path: string) => {
    const p = String(path);
    if (p.startsWith("/admin/automation-rules")) return Promise.resolve({ rules: [] });
    if (p.startsWith("/admin/full-ai/today")) return Promise.resolve(TODAY);
    if (p.startsWith("/admin/full-ai/config")) return typeof config === "function" ? config() : Promise.resolve(config);
    return Promise.resolve(baseGet(p));
  });
  relayPut.mockImplementation((_path: string, b: Record<string, unknown>) => {
    try { return Promise.resolve(put ? put(b) : configBody({ draft: b.draft, rev: Number(b.rev) + 1 })); } catch (e) { return Promise.reject(e); }
  });
  relayPost.mockImplementation((path: string, b: Record<string, unknown>) => {
    try { return Promise.resolve(post ? post(String(path), b) : answer()); } catch (e) { return Promise.reject(e); }
  });
  renderWithProviders(<FullAiChatterPage />, client);
};
const loadedConfig = async () => waitFor(() => expect(settings().getByRole("switch", { name: "GIFs" }).hasAttribute("disabled")).toBe(false));

describe("Full AI Chat page › Settings", () => {
  beforeEach(() => { relayPut.mockReset(); });

  it("holds five controls: on/off, LLM keys, reply speed, text like a girl, GIFs; the config is read for this Creator", async () => {
    mountSettings();
    await loadedConfig();
    const items = settings().getAllByRole("listitem");
    expect(items.length).toBe(5);
    expect(within(items[0]).getByRole("switch", { name: "Full AI Chat" })).toBeTruthy();
    expect(within(items[1]).getByText("LLM keys")).toBeTruthy();
    const speed = within(items[2]).getByRole("radiogroup", { name: "Reply speed" });
    expect(within(speed).getAllByRole("radio").map((r) => [r.textContent, r.getAttribute("aria-checked")]))
      .toEqual([["0-2 min", "true"], ["0-15-60", "false"]]);
    expect(within(items[3]).getByRole("switch", { name: "Human style" }).getAttribute("aria-checked")).toBe("true");
    expect(within(items[4]).getByRole("switch", { name: "GIFs" }).getAttribute("aria-checked")).toBe("false");
    expect(relayGet.mock.calls.some((c) => String(c[0]) === "/admin/full-ai/config?account_id=acc-a")).toBe(true);
  });

  it("LLM keys shows whether NanoGPT and OpenRouter are set, never a value, and links to the keys form", async () => {
    mountSettings();
    const keys = within(settings().getAllByRole("listitem")[1]);
    expect(await keys.findByText("NanoGPT set")).toBeTruthy();
    expect(keys.getByText("OpenRouter not set")).toBeTruthy();
    expect(screen.queryByText(/n4n0/)).toBeNull();
    expect(keys.getByRole("link", { name: "Open keys form" }).getAttribute("href")).toBe("/settings/ai-keys");
  });

  it("a control stores the draft at once; Send waits ('Save draft first') until it is stored", async () => {
    let store: (v: unknown) => void = () => {};
    mountSettings(configBody(), { put: () => new Promise((r) => { store = r; }) });
    await loadedConfig();
    fireEvent.change(composer(), { target: { value: "hey" } });
    expect(sendBtn().disabled).toBe(false);
    await act(async () => { fireEvent.click(settings().getByRole("switch", { name: "GIFs" })); });
    expect(putCalls().length).toBe(1);
    expect(putCalls()[0][1]).toEqual({ account_id: "acc-a", draft: { ...CONFIG, gifs: true }, rev: 3 });
    expect(sendBtn().disabled).toBe(true);
    expect(screen.getByText("Save draft first")).toBeTruthy();
    await act(async () => { store(configBody({ draft: { ...CONFIG, gifs: true }, rev: 4 })); });
    await waitFor(() => expect(sendBtn().disabled).toBe(false));
    expect(screen.queryByText("Save draft first")).toBeNull();
    expect(settings().getByRole("switch", { name: "GIFs" }).getAttribute("aria-checked")).toBe("true");
    await act(async () => { fireEvent.click(within(settings().getByRole("radiogroup", { name: "Reply speed" })).getByRole("radio", { name: "0-15-60" })); });
    await waitFor(() => expect(putCalls().length).toBe(2));
    expect(putCalls()[1][1]).toEqual({ account_id: "acc-a", draft: { ...CONFIG, gifs: true, reply_speed: "0-15-60" }, rev: 4 });
  });

  it("a refused draft shows its field errors and keeps Send waiting", async () => {
    mountSettings(configBody(), { put: () => { throw new RelayError(422, { errors: ["text_style: must be one of girl, formal"] }); } });
    await loadedConfig();
    fireEvent.change(composer(), { target: { value: "hey" } });
    await act(async () => { fireEvent.click(settings().getByRole("switch", { name: "Human style" })); });
    expect(await screen.findByText("text_style: must be one of girl, formal")).toBeTruthy();
    expect(sendBtn().disabled).toBe(true);
    expect(screen.getByText("Save draft first")).toBeTruthy();
  });

  it("Save makes the draft the checkpoint, then Roll back swaps back; each disabled with nothing to do", async () => {
    const draft = { ...CONFIG, gifs: true };
    mountSettings(configBody({ draft }), {
      post: (path, b) => path === "/admin/full-ai/config/save"
        ? configBody({ checkpoint: draft, previous: CONFIG, draft, rev: Number(b.rev) + 1 })
        : configBody({ checkpoint: CONFIG, previous: draft, draft, rev: Number(b.rev) + 1 }),
    });
    await loadedConfig();
    expect(btn("Roll back").disabled).toBe(true);
    await waitFor(() => expect(btn("Save").disabled).toBe(false));
    await act(async () => { fireEvent.click(btn("Save")); });
    expect(postsTo("/admin/full-ai/config/save").map((c) => c[1])).toEqual([{ account_id: "acc-a", rev: 3 }]);
    await waitFor(() => expect(btn("Roll back").disabled).toBe(false));
    expect(btn("Save").disabled).toBe(true);
    await act(async () => { fireEvent.click(btn("Roll back")); });
    expect(postsTo("/admin/full-ai/config/rollback").map((c) => c[1])).toEqual([{ account_id: "acc-a", rev: 4 }]);
    await waitFor(() => expect(btn("Save").disabled).toBe(false)); // the draft differs from the restored checkpoint again
    await act(async () => { fireEvent.click(btn("Roll back")); });
    expect(postsTo("/admin/full-ai/config/rollback").map((c) => c[1])).toEqual([{ account_id: "acc-a", rev: 4 }, { account_id: "acc-a", rev: 5 }]);
  });

  it("a draft stored meanwhile elsewhere shows a reload message instead of overwriting; Reload reads it again", async () => {
    mountSettings(configBody({ draft: { ...CONFIG, gifs: true } }), {
      post: () => { throw new RelayError(409, { detail: "Someone saved this config meanwhile. Reload.", rev: 9 }); },
    });
    await loadedConfig();
    await waitFor(() => expect(btn("Save").disabled).toBe(false));
    await act(async () => { fireEvent.click(btn("Save")); });
    expect(await screen.findByText("Someone saved this config meanwhile. Reload.")).toBeTruthy();
    expect(btn("Save").disabled).toBe(true);
    expect(settings().getByRole("switch", { name: "GIFs" }).hasAttribute("disabled")).toBe(true);
    const reads = () => relayGet.mock.calls.filter((c) => String(c[0]).startsWith("/admin/full-ai/config")).length;
    const before = reads();
    await act(async () => { fireEvent.click(btn("Reload")); });
    await waitFor(() => expect(reads()).toBe(before + 1));
    await waitFor(() => expect(screen.queryByText("Someone saved this config meanwhile. Reload.")).toBeNull());
  });

  it("JSON opens the full draft in the raw JSON editor; a field error is shown, a good one stores and closes", async () => {
    let calls = 0;
    mountSettings(configBody(), {
      put: (b) => {
        calls += 1;
        if (calls === 1) throw new RelayError(422, { errors: ["writer_timeout_s: must be a number of seconds from 5 to 60"] });
        return configBody({ draft: b.draft, rev: 4 });
      },
    });
    await loadedConfig();
    fireEvent.click(btn("JSON"));
    const box = await screen.findByRole("textbox", { name: "Raw JSON" }) as HTMLTextAreaElement;
    expect(JSON.parse(box.value)).toEqual(CONFIG);
    fireEvent.change(box, { target: { value: JSON.stringify({ ...CONFIG, writer_timeout_s: 1 }) } });
    await act(async () => { fireEvent.click(within(screen.getByRole("dialog")).getByRole("button", { name: "Save" })); });
    expect(putCalls()[0][1]).toEqual({ account_id: "acc-a", draft: { ...CONFIG, writer_timeout_s: 1 }, rev: 3 });
    expect(await within(screen.getByRole("dialog")).findByText(/writer_timeout_s: must be a number of seconds from 5 to 60/)).toBeTruthy();
    fireEvent.change(box, { target: { value: JSON.stringify({ ...CONFIG, writer_timeout_s: 30 }) } });
    await act(async () => { fireEvent.click(within(screen.getByRole("dialog")).getByRole("button", { name: "Save" })); });
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
    expect(putCalls()[1][1]).toEqual({ account_id: "acc-a", draft: { ...CONFIG, writer_timeout_s: 30 }, rev: 3 });
  });

  it("Reload is the way back from a refused edit: it drops the edit and Send works again; also after a failed read", async () => {
    let reads = 0;
    const read = () => (++reads === 1 ? Promise.reject(new Error("relay down")) : Promise.resolve(configBody()));
    mountSettings(read, { put: () => { throw new RelayError(422, { errors: ["writer_timeout_s: must be a number of seconds from 5 to 60"] }); } });
    expect(await screen.findByText("Couldn't read the Full AI config: relay down")).toBeTruthy();
    await act(async () => { fireEvent.click(btn("Reload")); });
    await loadedConfig();
    expect(screen.queryByRole("button", { name: "Reload" })).toBeNull();
    fireEvent.click(btn("JSON"));
    const box = await screen.findByRole("textbox", { name: "Raw JSON" });
    fireEvent.change(box, { target: { value: JSON.stringify({ ...CONFIG, writer_timeout_s: 1 }) } });
    await act(async () => { fireEvent.click(within(screen.getByRole("dialog")).getByRole("button", { name: "Save" })); });
    await within(screen.getByRole("dialog")).findByText(/writer_timeout_s: must be a number/);
    fireEvent.click(within(screen.getByRole("dialog")).getByRole("button", { name: "Cancel" }));
    fireEvent.change(composer(), { target: { value: "hey" } });
    expect(sendBtn().disabled).toBe(true);
    await act(async () => { fireEvent.click(btn("Reload")); });
    await waitFor(() => expect(sendBtn().disabled).toBe(false));
    expect(screen.queryByText("Save draft first")).toBeNull();
    fireEvent.click(btn("JSON"));
    expect(JSON.parse((await screen.findByRole("textbox", { name: "Raw JSON" }) as HTMLTextAreaElement).value)).toEqual(CONFIG);
  });

  it("the persona block (Model info) sits here with 'not part of the checkpoint' next to its Save", async () => {
    mountSettings();
    expect(await screen.findByRole("textbox", { name: "Model info" })).toBeTruthy();
    expect(screen.getByRole("button", { name: "Make persona from the Creator's images" })).toBeTruthy();
    const save = btn("Save model info");
    expect(within(save.parentElement as HTMLElement)
      .getByText("Saves for every live chat on this Creator now (not part of the checkpoint)")).toBeTruthy();
  });
});

// ── An assistant Apply lands (ticket 57: Do mode invalidates `fullAiConfigKey`, the page refetches) ──────────────────
describe("Full AI Chat page › applied draft", () => {
  beforeEach(() => { relayPut.mockReset(); });
  const slower = { ...CONFIG, reply_speed: "0-15-60" };
  /** The config read answers rev 3 until `apply()` stores the slower draft as rev 4; then the assistant invalidates. */
  const mountApplied = (opts: Parameters<typeof mountSettings>[1] = {}) => {
    let body = configBody();
    mountSettings(() => Promise.resolve(body), opts);
    return async () => {
      body = configBody({ draft: slower, rev: 4 });
      await act(async () => { await client.invalidateQueries({ queryKey: fullAiConfigKey("acc-a") }); });
    };
  };
  const speed = () => within(settings().getByRole("radiogroup", { name: "Reply speed" }));
  const bar = () => screen.queryByRole("group", { name: "Draft changed elsewhere" });

  it("with no unsaved edit, the settings column and the Draft window header adopt it; the next draft write uses its rev", async () => {
    const apply = mountApplied();
    await loadedConfig();
    expect(win("Draft").getByText("Reply 0-2 min · Human style on · GIFs off")).toBeTruthy();
    await apply();
    await waitFor(() => expect(speed().getByRole("radio", { name: "0-15-60" }).getAttribute("aria-checked")).toBe("true"));
    expect(win("Draft").getByText("Reply 0-15-60 · Human style on · GIFs off")).toBeTruthy();
    expect(win("Checkpoint").getByText("Reply 0-2 min · Human style on · GIFs off")).toBeTruthy();
    expect(bar()).toBeNull();
    fireEvent.change(composer(), { target: { value: "hey" } });
    expect(sendBtn().disabled).toBe(false);
    expect(btn("Save").disabled).toBe(false);
    await act(async () => { fireEvent.click(settings().getByRole("switch", { name: "GIFs" })); });
    expect(putCalls()[0][1]).toEqual({ account_id: "acc-a", draft: { ...slower, gifs: true }, rev: 4 });
  });

  it("with an unsaved edit, raises Keep mine / Take theirs and keeps the page's draft; Send and Save off", async () => {
    const apply = mountApplied({ put: () => { throw new RelayError(422, { errors: ["gifs: bad"] }); } });
    await loadedConfig();
    await act(async () => { fireEvent.click(settings().getByRole("switch", { name: "GIFs" })); });
    await screen.findByText("gifs: bad");
    await apply();
    await waitFor(() => expect(bar()).toBeTruthy());
    expect(settings().getByRole("switch", { name: "GIFs" }).getAttribute("aria-checked")).toBe("true");
    expect(speed().getByRole("radio", { name: "0-2 min" }).getAttribute("aria-checked")).toBe("true");
    fireEvent.change(composer(), { target: { value: "hey" } });
    expect([sendBtn().disabled, btn("Save").disabled]).toEqual([true, true]);
    expect(screen.getByText("Keep mine or Take theirs first")).toBeTruthy();
    await act(async () => { fireEvent.click(btn("Take theirs")); });
    expect(bar()).toBeNull();
    expect(speed().getByRole("radio", { name: "0-15-60" }).getAttribute("aria-checked")).toBe("true");
    expect(settings().getByRole("switch", { name: "GIFs" }).getAttribute("aria-checked")).toBe("false");
    expect(sendBtn().disabled).toBe(false);
    expect(putCalls().length).toBe(1);   // the refused edit only: Take theirs writes nothing
  });

  it("Keep mine re-stores the page's draft on the applied rev", async () => {
    let calls = 0;
    const apply = mountApplied({
      put: (b) => {
        if (++calls === 1) throw new RelayError(422, { errors: ["gifs: bad"] });
        return configBody({ draft: b.draft, rev: Number(b.rev) + 1 });
      },
    });
    await loadedConfig();
    await act(async () => { fireEvent.click(settings().getByRole("switch", { name: "GIFs" })); });
    await screen.findByText("gifs: bad");
    await apply();
    await waitFor(() => expect(bar()).toBeTruthy());
    await act(async () => { fireEvent.click(btn("Keep mine")); });
    expect(putCalls()[1][1]).toEqual({ account_id: "acc-a", draft: { ...CONFIG, gifs: true }, rev: 4 });
    await waitFor(() => expect(bar()).toBeNull());
    fireEvent.change(composer(), { target: { value: "hey" } });
    await waitFor(() => expect(sendBtn().disabled).toBe(false));
    expect(settings().getByRole("switch", { name: "GIFs" }).getAttribute("aria-checked")).toBe("true");
  });

  it("an equal rev on refetch changes nothing", async () => {
    mountSettings();
    await loadedConfig();
    const reads = () => relayGet.mock.calls.filter((c) => String(c[0]).startsWith("/admin/full-ai/config")).length;
    const before = reads();
    await act(async () => { await client.invalidateQueries({ queryKey: fullAiConfigKey("acc-a") }); });
    expect(reads()).toBe(before + 1);
    expect(bar()).toBeNull();
    expect(speed().getByRole("radio", { name: "0-2 min" }).getAttribute("aria-checked")).toBe("true");
  });
});
