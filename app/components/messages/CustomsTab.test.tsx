/**
 * CustomsTab's pane, with the real component and the relay mocked: every
 * request is held until the test answers it, in the order the test picks.
 *
 *   • Read A then B, replies interleaved out of order: only B's render, and
 *     "Copy handoff" copies B's brief under B's username.
 *   • Close + reopen the same row: the first open's late replies are dropped.
 *   • Pull A then Pull B: each spinner clears only on its own pull; a pull
 *     answering ok=false re-reads nothing and says so on the row.
 *   • Pull A, then Read B before the rescrape answers: A does not reopen over
 *     B and no (paid) brief is asked for A.
 *   • Read A, Pull A, Hide A before the rescrape answers: A stays closed and
 *     no second (paid) brief is asked for A.
 *   • A failed order lookup shows (and Copy enables) before the thread lands.
 *   • A clipboard write that settles after close + reopen notes nothing.
 *   • Refresh after an owed fan tips again keeps his open pane and says it was
 *     read at the older tip.
 *   • A rejected clipboard write says so.
 *   • Two "Worth a look" rows for one fan are two rows, not one.
 *   • "try again" on a failed brief after Refresh moved the row's tip asks at
 *     the pane's tip time, not the row's new one.
 *   • Sent on a row mid-Pull: its ok rescrape reopens nothing and asks for no
 *     (paid) brief; another fan's Pull still reopens its row. Dismiss on one
 *     of a fan's review rows stops a Pull on his other one (the backend
 *     settles the fan).
 *   • Sent on the open row: while the clear POST is in flight the pane stays
 *     and Read / Pull are off; it closes once the POST succeeds, and a failed
 *     clear leaves row and pane as they were (no second brief).
 *   • Dismiss on one of a fan's review rows: Read / Pull are off on his OTHER
 *     row too while the POST runs (the backend settles the fan), and come back
 *     if it fails; another fan's row stays usable.
 */
import { act, fireEvent, render, screen, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const { relay } = vi.hoisted(() => ({ relay: { get: vi.fn(), post: vi.fn() } }));
vi.mock("@/lib/relay", () => ({ relay }));

import CustomsTab from "@/components/messages/CustomsTab";

const row = (fan_id: number, name: string, over: Record<string, unknown> = {}) => ({
  marked: true,
  account_id: "acc1",
  account_name: "Model",
  fan_id,
  display_name: name,
  of_username: name.toLowerCase(),
  tip_cents: 10000,
  order_count: 1,
  tipped_at: "2026-10-01T00:00:00Z",
  lifetime_spend_cents: 10000,
  chat_href: "#",
  ...over,
});

let customs: ReturnType<typeof row>[] = [];
/** Held replies per `<endpoint>:<fan>`, in the order they were asked. */
const pending = new Map<string, ((v: unknown) => void)[]>();
const defer = (k: string) =>
  new Promise((res) => pending.set(k, [...(pending.get(k) ?? []), res]));
const fanOf = (url: string) => new URLSearchParams(url.split("?")[1]).get("fan_id");

relay.get.mockImplementation((url: string) => {
  if (url === "/admin/customs") return Promise.resolve({ customs });
  if (url.startsWith("/admin/customs/context")) return defer(`ctx:${fanOf(url)}`);
  if (url.startsWith("/admin/customs/order")) return defer(`order:${fanOf(url)}`);
  return Promise.reject(new Error(`unexpected ${url}`));
});
/** Every POST body, in order. */
let posts: { url: string; body: Record<string, unknown> }[] = [];
relay.post.mockImplementation((url: string, body: { fan_id: number }) => {
  posts.push({ url, body });
  if (url === "/admin/customs/brief") return defer(`brief:${body.fan_id}`);
  if (url === "/admin/customs/clear") return defer(`clear:${body.fan_id}`);
  const m = url.match(/^\/admin\/messages\/acc1\/(\d+)\/rescrape-now$/);
  if (m) return defer(`rescrape:${m[1]}`);
  return Promise.reject(new Error(url));
});

/** Answer the `i`-th held request for `k`. */
async function settle(k: string, v: unknown, i = 0) {
  const res = pending.get(k)?.[i];
  if (!res) throw new Error(`no pending ${k}[${i}]`);
  await act(async () => res(v));
}
const ctxReply = (who: string) => ({
  messages: [{ message_id: 1, from_fan: true, text: `${who} thread`, at: null, is_tip: false, price_cents: 0 }],
});
const orderReply = (who: string) => ({
  lines: [{ message_id: 1, from_fan: true, is_tip: false, text: `${who} line`, at: null }],
  count: 1,
});
const briefReply = (who: string) => ({ ok: true, summary: `${who} brief` });
async function answerAll(fan: number, who: string, i = 0) {
  await settle(`ctx:${fan}`, ctxReply(who), i);
  await settle(`order:${fan}`, orderReply(who), i);
  await settle(`brief:${fan}`, briefReply(who), i);
}

const rowOf = async (name: string) => (await screen.findByText(name)).closest("tr")!;
const click = (el: HTMLElement) => act(async () => { fireEvent.click(el); });
const readBtn = (tr: HTMLElement) => within(tr).getByTitle("Read the conversation around this tip");
const pullBtn = (tr: HTMLElement) => within(tr).getByTitle("Re-fetch this chat from OnlyFans, then re-read it");
const sentBtn = (tr: HTMLElement) => within(tr).getByTitle(/^Mark delivered/);
const dismissBtn = (tr: HTMLElement) => within(tr).getByTitle(/^Nothing owed here/);
const copyBtn = () => screen.getByRole("button", { name: "Copy handoff" });

function mockClipboard(writeText: ReturnType<typeof vi.fn>) {
  Object.defineProperty(navigator, "clipboard", { value: { writeText }, configurable: true });
}

beforeEach(() => {
  pending.clear();
  posts = [];
  relay.get.mockClear();
  relay.post.mockClear();
  customs = [row(1, "Alice"), row(2, "Bob")];
});

describe("CustomsTab pane", () => {
  it("A then B, replies interleaved out of order: B's data only, Copy copies B", async () => {
    const writeText = vi.fn().mockResolvedValue(undefined);
    mockClipboard(writeText);
    render(<CustomsTab />);
    await click(readBtn(await rowOf("Alice")));
    await click(readBtn(await rowOf("Bob")));

    await settle("ctx:2", ctxReply("Bob"));
    await settle("brief:1", briefReply("Alice"));
    await settle("ctx:1", ctxReply("Alice"));
    await settle("order:2", orderReply("Bob"));
    // Brief still in flight: the copy would be a fallback, so it is not offered.
    expect(copyBtn()).toBeDisabled();
    await settle("order:1", orderReply("Alice"));
    await settle("brief:2", briefReply("Bob"));

    expect(screen.getByText("Bob brief")).toBeInTheDocument();
    expect(screen.getByText("Bob thread")).toBeInTheDocument();
    expect(screen.getByText("Bob line")).toBeInTheDocument();
    expect(screen.queryByText(/Alice (brief|thread|line)/)).toBeNull();

    expect(copyBtn()).toBeEnabled();
    await click(copyBtn());
    expect(writeText).toHaveBeenCalledTimes(1);
    const copied = writeText.mock.calls[0][0] as string;
    expect(copied).toContain("@bob");
    expect(copied).toContain("Bob brief");
    expect(copied).not.toContain("Alice");
    expect(copied).not.toContain("@alice");
    expect(screen.getByText("Copied")).toBeInTheDocument();
  });

  it("close + reopen the same row: the first open's late replies are dropped", async () => {
    render(<CustomsTab />);
    const alice = await rowOf("Alice");
    await click(readBtn(alice));
    await click(readBtn(alice)); // Hide
    expect(screen.queryByText("Reading…")).toBeNull();
    await click(readBtn(alice)); // Read again

    await answerAll(1, "Stale", 0);
    expect(screen.queryByText(/Stale/)).toBeNull();
    expect(screen.getByText("Reading…")).toBeInTheDocument();

    await answerAll(1, "Fresh", 1);
    expect(screen.getByText("Fresh brief")).toBeInTheDocument();
    expect(screen.getByText("Fresh thread")).toBeInTheDocument();
    expect(screen.queryByText(/Stale/)).toBeNull();
  });

  it("Pull A then Pull B: each spinner clears on its own pull; ok=false re-reads nothing", async () => {
    render(<CustomsTab />);
    const alice = await rowOf("Alice");
    const bob = await rowOf("Bob");
    await click(pullBtn(alice));
    await click(pullBtn(bob));
    expect(pullBtn(alice)).toHaveTextContent("…");
    expect(pullBtn(bob)).toHaveTextContent("…");

    await settle("rescrape:1", { ok: false, error: "boom" });
    expect(pullBtn(alice)).toHaveTextContent("Pull");
    expect(within(alice).getByText("Pull failed")).toHaveAttribute("title", "boom");
    expect(pullBtn(bob)).toHaveTextContent("…");
    // A failed pull opens nothing and asks for no (paid) brief.
    expect(pending.has("ctx:1")).toBe(false);
    expect(pending.has("brief:1")).toBe(false);

    await settle("rescrape:2", { ok: true });
    expect(screen.getByText("Reading…")).toBeInTheDocument();
    expect(pullBtn(bob)).toHaveTextContent("…");
    await answerAll(2, "Bob");
    expect(pullBtn(bob)).toHaveTextContent("Pull");
    expect(screen.getByText("Bob brief")).toBeInTheDocument();
  });

  it("Pull A, Read B during the rescrape: A does not reopen over B, no brief for A", async () => {
    render(<CustomsTab />);
    await click(pullBtn(await rowOf("Alice")));
    await click(readBtn(await rowOf("Bob")));
    await settle("rescrape:1", { ok: true });
    expect(pending.has("brief:1")).toBe(false);
    expect(pending.has("ctx:1")).toBe(false);
    expect(pullBtn(await rowOf("Alice"))).toHaveTextContent("Pull");
    await answerAll(2, "Bob");
    expect(screen.getByText("Bob brief")).toBeInTheDocument();
  });

  it("Read A, Pull A, Hide A during the rescrape: A stays closed, no second brief", async () => {
    render(<CustomsTab />);
    const alice = await rowOf("Alice");
    await click(readBtn(alice));
    await answerAll(1, "Alice");
    await click(pullBtn(alice));
    await click(readBtn(alice)); // Hide
    await settle("rescrape:1", { ok: true });
    expect(pullBtn(alice)).toHaveTextContent("Pull");
    expect(readBtn(alice)).toHaveTextContent("Read");
    expect(screen.queryByText("Reading…")).toBeNull();
    expect(pending.get("brief:1")).toHaveLength(1);
    expect(pending.get("ctx:1")).toHaveLength(1);
  });

  it("order lookup failed: the note and Copy show while the thread is still loading", async () => {
    render(<CustomsTab />);
    await click(readBtn(await rowOf("Alice")));
    await settle("brief:1", briefReply("Alice"));
    expect(copyBtn()).toBeDisabled();
    // Resolving with a rejected promise fails the held order lookup.
    await settle("order:1", Promise.reject(new Error("timeout")));
    expect(screen.getByText("Reading…")).toBeInTheDocument();
    expect(screen.getByText(/order lookup failed \(timeout\)/)).toBeInTheDocument();
    expect(copyBtn()).toBeEnabled();
  });

  it("a clipboard write that settles after close + reopen notes nothing in the new pane", async () => {
    let finish: () => void = () => {};
    mockClipboard(vi.fn(() => new Promise<void>((res) => { finish = res; })));
    render(<CustomsTab />);
    const alice = await rowOf("Alice");
    await click(readBtn(alice));
    await answerAll(1, "Alice");
    await click(copyBtn());
    await click(readBtn(alice)); // Hide
    await click(readBtn(alice)); // Read again
    await act(async () => finish());
    expect(screen.queryByText("Copied")).toBeNull();
  });

  it("Refresh after an owed fan tips again keeps his open pane and says it was read at the older tip", async () => {
    render(<CustomsTab />);
    await click(readBtn(await rowOf("Alice")));
    await answerAll(1, "Alice");
    expect(screen.queryByText(/He tipped again/)).toBeNull();
    customs = [row(1, "Alice", { tipped_at: "2026-10-09T00:00:00Z", tip_cents: 20000 }), row(2, "Bob")];
    await click(screen.getByRole("button", { name: "Refresh" }));
    expect(await screen.findByText("Alice brief")).toBeInTheDocument();
    expect(readBtn(await rowOf("Alice"))).toHaveTextContent("Hide");
    expect(screen.getByText(/He tipped again since this was read/)).toBeInTheDocument();
    expect(copyBtn()).toBeEnabled();
  });

  it("a rejected clipboard write is shown as a failure, not as Copied", async () => {
    mockClipboard(vi.fn().mockRejectedValue(new Error("not allowed")));
    render(<CustomsTab />);
    await click(readBtn(await rowOf("Alice")));
    await answerAll(1, "Alice");
    await click(copyBtn());
    expect(screen.getByText(/Copy blocked/)).toBeInTheDocument();
    expect(screen.queryByText("Copied")).toBeNull();
  });

  it("two review rows for one fan are two rows: Read opens the one clicked, Copy uses its total", async () => {
    const writeText = vi.fn().mockResolvedValue(undefined);
    mockClipboard(writeText);
    customs = [
      row(1, "Carl", { marked: false, tip_cents: 10000, tipped_at: "2026-10-01T00:00:00Z" }),
      row(1, "Carl", { marked: false, tip_cents: 25000, tipped_at: "2026-10-05T00:00:00Z" }),
    ];
    render(<CustomsTab />);
    const [first, second] = (await screen.findAllByText("Carl")).map((el) => el.closest("tr")!);
    await click(readBtn(second));
    expect(readBtn(second)).toHaveTextContent("Hide");
    expect(readBtn(first)).toHaveTextContent("Read");
    expect(screen.getAllByText("Reading…")).toHaveLength(1);

    await answerAll(1, "Carl");
    await click(copyBtn());
    const copied = writeText.mock.calls[0][0] as string;
    expect(copied).toContain("-total: $250");
    expect(copied).not.toContain("$100");
  });

  it("try again after Refresh moved his tip asks for the brief at the pane's tip time", async () => {
    render(<CustomsTab />);
    await click(readBtn(await rowOf("Alice")));
    await settle("ctx:1", ctxReply("Alice"));
    await settle("order:1", orderReply("Alice"));
    await settle("brief:1", { ok: false, reason: "busy" });
    customs = [row(1, "Alice", { tipped_at: "2026-10-09T00:00:00Z", tip_cents: 20000 }), row(2, "Bob")];
    await click(screen.getByRole("button", { name: "Refresh" }));
    expect(await screen.findByText(/He tipped again since this was read/)).toBeInTheDocument();
    await click(screen.getByRole("button", { name: "try again" }));
    const briefs = posts.filter((x) => x.url === "/admin/customs/brief");
    expect(briefs.map((x) => x.body.at)).toEqual(["2026-10-01T00:00:00Z", "2026-10-01T00:00:00Z"]);
  });

  it("Sent on A mid-Pull: A's ok rescrape reopens nothing and asks no brief", async () => {
    render(<CustomsTab />);
    await click(pullBtn(await rowOf("Alice")));
    await click(sentBtn(await rowOf("Alice")));
    await settle("clear:1", { ok: true });
    expect(screen.queryByText("Alice")).toBeNull();
    await settle("rescrape:1", { ok: true });
    expect(pending.has("brief:1")).toBe(false);
    expect(pending.has("ctx:1")).toBe(false);
    expect(pending.has("order:1")).toBe(false);
    expect(screen.queryByText("Reading…")).toBeNull();
    expect(posts.map((x) => x.url)).toEqual(["/admin/messages/acc1/1/rescrape-now", "/admin/customs/clear"]);
  });

  it("Sent on A while A and B pull: B's ok rescrape still reopens B", async () => {
    render(<CustomsTab />);
    await click(pullBtn(await rowOf("Alice")));
    await click(pullBtn(await rowOf("Bob")));
    await click(sentBtn(await rowOf("Alice")));
    await settle("clear:1", { ok: true });
    await settle("rescrape:1", { ok: true });
    await settle("rescrape:2", { ok: true });
    expect(pending.has("brief:1")).toBe(false);
    await answerAll(2, "Bob");
    expect(screen.getByText("Bob brief")).toBeInTheDocument();
    expect(readBtn(await rowOf("Bob"))).toHaveTextContent("Hide");
  });

  it("Dismiss on Carl's newer review row mid-Pull of his older one asks no brief", async () => {
    customs = [
      row(1, "Carl", { marked: false, tipped_at: "2026-10-01T00:00:00Z" }),
      row(1, "Carl", { marked: false, tipped_at: "2026-10-05T00:00:00Z" }),
    ];
    render(<CustomsTab />);
    const [k1, k2] = (await screen.findAllByText("Carl")).map((el) => el.closest("tr")!);
    await click(pullBtn(k1));
    await click(dismissBtn(k2));
    // K1's rescrape answers ok while the clear is still in flight.
    await settle("rescrape:1", { ok: true });
    expect(pending.has("brief:1")).toBe(false);
    expect(pending.has("ctx:1")).toBe(false);
    expect(pending.has("order:1")).toBe(false);
    await settle("clear:1", { ok: true });
    expect(screen.queryByText("Carl")).toBeNull();
    expect(pending.has("brief:1")).toBe(false);
  });

  it("Dismiss on Carl's K2: Read / Pull off on his K1 while it runs, back after it fails", async () => {
    customs = [
      row(1, "Carl", { marked: false, tipped_at: "2026-10-01T00:00:00Z" }),
      row(1, "Carl", { marked: false, tipped_at: "2026-10-05T00:00:00Z" }),
      row(2, "Dan", { marked: false }),
    ];
    render(<CustomsTab />);
    const [k1, k2] = (await screen.findAllByText("Carl")).map((el) => el.closest("tr")!);
    await click(dismissBtn(k2));
    expect(dismissBtn(k2)).toHaveTextContent("…");
    expect(dismissBtn(k1)).toHaveTextContent("Dismiss");
    for (const b of [readBtn(k1), pullBtn(k1), readBtn(k2), pullBtn(k2)]) expect(b).toBeDisabled();
    const dan = await rowOf("Dan");
    expect(readBtn(dan)).toBeEnabled();
    expect(pullBtn(dan)).toBeEnabled();
    // A click on K1 now asks nothing (no paid brief on a fan being settled).
    await click(readBtn(k1));
    await click(pullBtn(k1));
    expect(pending.has("brief:1")).toBe(false);
    expect(pending.has("rescrape:1")).toBe(false);
    await settle("clear:1", Promise.reject(new Error("502")));
    for (const b of [readBtn(k1), pullBtn(k1), readBtn(k2), pullBtn(k2)]) expect(b).toBeEnabled();
  });

  it("Sent on the open row: pane stays while the clear is in flight, closes once it succeeds", async () => {
    render(<CustomsTab />);
    const alice = await rowOf("Alice");
    await click(readBtn(alice));
    await answerAll(1, "Alice");
    await click(sentBtn(alice));
    expect(sentBtn(alice)).toHaveTextContent("…");
    expect(screen.getByText("Alice brief")).toBeInTheDocument();
    // Leaving the queue: no Read / Pull (a read would pay for a brief).
    expect(readBtn(alice)).toBeDisabled();
    expect(pullBtn(alice)).toBeDisabled();
    await settle("clear:1", { ok: true });
    expect(screen.queryByText("Alice")).toBeNull();
    expect(screen.queryByText(/Alice (brief|thread|line)/)).toBeNull();
    expect(screen.queryByRole("button", { name: "Copy handoff" })).toBeNull();
  });

  it("a failed clear leaves the row and its pane as they were, no second brief", async () => {
    render(<CustomsTab />);
    const alice = await rowOf("Alice");
    await click(readBtn(alice));
    await answerAll(1, "Alice");
    await click(sentBtn(alice));
    await settle("clear:1", Promise.reject(new Error("502")));
    expect(screen.getByText("502")).toBeInTheDocument();
    expect(sentBtn(await rowOf("Alice"))).toHaveTextContent("Sent");
    expect(readBtn(await rowOf("Alice"))).toHaveTextContent("Hide");
    expect(screen.getByText("Alice brief")).toBeInTheDocument();
    expect(copyBtn()).toBeEnabled();
    expect(pending.get("brief:1")).toHaveLength(1);
  });
});
