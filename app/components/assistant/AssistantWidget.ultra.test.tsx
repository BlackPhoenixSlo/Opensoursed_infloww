/**
 * The help bot's Ultra mode (components/ultra/UltraPanel): owner-only tick, request → POST /admin/ultra/plans,
 * then the plan followed by polling GET …/{id}: planning → card → OK (the shown hash) → running → done; the pick
 * card's Send these; server refusals shown as written; a reload resumes the open plan.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { act, cleanup, fireEvent, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

const { relayPost, relayGet, signedIn } = vi.hoisted(() => ({
  relayPost: vi.fn(),
  relayGet: vi.fn(),
  signedIn: { user: { username: "owner" } as { username: string } | null },
}));

vi.mock("@/lib/relay", () => {
  class RelayError extends Error {
    status: number;
    body: unknown;
    constructor(status: number, body: unknown, message?: string) {
      super(message || `relay ${status}`);
      this.status = status;
      this.body = body;
    }
  }
  return {
    RelayError,
    relay: { post: (...a: unknown[]) => relayPost(...a), get: (...a: unknown[]) => relayGet(...a), put: vi.fn() },
    relayFile: vi.fn(),
  };
});
vi.mock("next/navigation", () => ({ usePathname: () => "/", useRouter: () => ({ push: vi.fn() }) }));
vi.mock("next/link", () => ({
  default: ({ href, children, ...rest }: { href: string; children: React.ReactNode }) => <a {...rest} href={href}>{children}</a>,
}));
vi.mock("@/contexts/ScopeContext", () => ({ useScope: () => ({ accountId: "1001" }) }));
vi.mock("@/contexts/EmployeeContext", () => ({ useEmployee: () => ({ current: { id: 7 } }) }));
vi.mock("@/hooks/useAccounts", () => ({
  useAccounts: () => ({ data: { accounts: [{ id: "1001", nickname: "Ava", has_session: true, is_active: true }] },
    isSuccess: true, dataUpdatedAt: 1 }),
}));
vi.mock("@/contexts/UserContext", () => ({ useOptionalUser: () => (signedIn.user ? { user: signedIn.user } : null) }));

import { RelayError } from "@/lib/relay";
import { renderWithProviders } from "@/test-utils";
import { PageCreatorProvider } from "@/contexts/PageCreatorContext";
import { AssistantProvider, AssistantWidget } from "./AssistantWidget";
import { ULTRA_KEY, ULTRA_PLAN_KEY } from "@/components/ultra/UltraPanel";
import type { PlanStatus, PlanView, StepStatus } from "@/components/ultra/ultraRunReducer";

const SHA = "c".repeat(64);
const TEXT = "new set just dropped, open it for $12 💋";
const plan = (status: PlanStatus, over: Partial<PlanView> = {}): PlanView => ({
  id: "p1", status, summary: "Mass the new set", sha256: SHA,
  card: [
    { id: "pick", tool: "judge", effect: "judge", title: "AI pick", rows: [["Question", "best 2"], ["Picks", "2"]] },
    { id: "mass", tool: "mass_send", effect: "send", title: "Mass message", text: TEXT,
      rows: [["Creator", "Ava"], ["Audience", "all fans"], ["Price", "$12.00"]] },
  ],
  step_states: [{ id: "pick", state: "pending" }, { id: "mass", state: "pending" }],
  created_at: "2026-11-14T10:00:00Z", expires_at: "2099-01-01T00:00:00Z", approved_at: null, finished_at: null, ...over,
});
const planning = plan("planning", {
  sha256: "", card: [], step_states: [], summary: "", expires_at: null,
  planning: { turns: 2, max_turns: 25, last_tool: "vault search" },
});
const cands = [21, 22, 23].map((id) => ({ id, type: "photo", thumb: `/admin/vault-ai/thumb?media_id=${id}`, description: `pic ${id}` }));
const waiting: StepStatus = { id: "pick", state: "needs_you", question: "Which 2 for the mass?", pick_n: 2, candidates: cands, picks: [22] };

/** What GET /admin/ultra/plans/p1 answers now. */
let current: () => Promise<PlanView>;

async function openPanel() {
  renderWithProviders(<PageCreatorProvider><AssistantProvider><AssistantWidget /></AssistantProvider></PageCreatorProvider>);
  const bubble = await screen.findByRole("button", { name: "Help assistant" });
  // The open dock is kept per browser: a "reload" finds it open already.
  if (bubble.getAttribute("aria-expanded") !== "true") await userEvent.click(bubble);
}
/** Fire the plan poll: flush pending effects first so its interval is set. */
async function poll(ms: number) {
  await act(async () => {});
  act(() => { vi.advanceTimersByTime(ms); });
}
const note = () => screen.getByRole("status");
const button = (name: string | RegExp) => screen.getByRole("button", { name });

// Only the plan poll's interval is faked (RTL's waitFor polls on setInterval too: wait on the DOM, not on storage).
beforeEach(() => {
  vi.useFakeTimers({ toFake: ["setInterval", "clearInterval"] });
  relayPost.mockReset();
  relayGet.mockReset();
  current = async () => plan("awaiting_ok");
  relayGet.mockImplementation((path: string) =>
    path.startsWith("/admin/ultra/plans/") ? current() : Promise.resolve({ count: 0, since_hours: 24, list: [] }));
  signedIn.user = { username: "owner" };
  window.localStorage.clear();
});
afterEach(() => {
  cleanup();
  vi.useRealTimers();
});

describe("Ultra mode in the help bot", () => {
  it("a chatter never sees the tick, even with it stored", async () => {
    signedIn.user = null;
    window.localStorage.setItem(ULTRA_KEY, "1");
    await openPanel();
    expect(screen.getByPlaceholderText("Ask a question…")).toBeInTheDocument();
    expect(screen.queryByLabelText("Ultra mode")).toBeNull();
    expect(document.querySelector("[data-ultra]")).toBeNull();
  });

  it("an owner ticks it: the panel turns Ultra, the tick is kept per browser, unticking goes back", async () => {
    await openPanel();
    fireEvent.click(screen.getByLabelText("Ultra mode"));
    expect(document.querySelector("[data-ultra]")).not.toBeNull();
    expect(screen.getByPlaceholderText("What should Ultra do?")).toBeInTheDocument();
    expect(window.localStorage.getItem(ULTRA_KEY)).toBe("1");
    fireEvent.click(screen.getByLabelText("Ultra mode"));
    expect(screen.getByPlaceholderText("Ask a question…")).toBeInTheDocument();
    expect(window.localStorage.getItem(ULTRA_KEY)).toBe("0");
  });

  it("request → planning → card → OK with the shown hash → running → done, then New request", async () => {
    window.localStorage.setItem(ULTRA_KEY, "1");
    await openPanel();
    expect(button("Plan it")).toBeDisabled();
    relayPost.mockResolvedValueOnce(planning);
    current = async () => planning;
    fireEvent.change(screen.getByPlaceholderText("What should Ultra do?"), { target: { value: "  mass the new set  " } });
    fireEvent.click(button("Plan it"));
    await waitFor(() => expect(note()).toHaveTextContent("Planning… turn 2 of 25 · last: vault search."));
    expect(relayPost).toHaveBeenCalledWith("/admin/ultra/plans", { request: "mass the new set" });
    expect(window.localStorage.getItem(ULTRA_PLAN_KEY)).toBe("p1");
    expect(button("Stop planning")).toBeEnabled();
    expect(screen.queryByRole("button", { name: /^OK/ })).toBeNull();

    current = async () => plan("awaiting_ok");
    await poll(1500);
    await screen.findByRole("button", { name: "OK, run 2 steps" });
    const mass = document.querySelector('[data-step="mass"]') as HTMLElement;
    expect(mass.querySelector("[data-step-text]")).toHaveTextContent(TEXT);
    expect(within(mass).getByText("$12.00")).toBeInTheDocument();
    expect(mass.querySelector("[data-step-num]")).toHaveTextContent("2.");

    const running = plan("running", { step_states: [{ id: "pick", state: "started" }, { id: "mass", state: "pending" }] });
    relayPost.mockResolvedValueOnce(running);
    current = async () => running;  // the OK is read again at once
    fireEvent.click(button("OK, run 2 steps"));
    await waitFor(() => expect(screen.getByRole("img", { name: "Running" })).toBeInTheDocument());
    expect(relayPost).toHaveBeenLastCalledWith("/admin/ultra/plans/p1/ok", { sha256: SHA }, undefined, expect.any(AbortSignal));
    expect(button("Cancel the rest")).toBeEnabled();

    current = async () => plan("done", { step_states: [
      { id: "pick", state: "done", result: { ids: [21, 22] }, picked_by: "ai" },
      { id: "mass", state: "done", result: { id: 4242 }, open_url: "/mass/4242" },
    ] });
    await poll(2000);
    await screen.findByRole("button", { name: "New request" });
    expect(screen.queryByRole("img", { name: "Running" })).toBeNull();
    expect(mass).toHaveTextContent("OnlyFans id: 4242");
    expect(within(mass).getByRole("link", { name: "Open in the app" })).toHaveAttribute("href", "/mass/4242");
    expect(document.querySelector('[data-step="pick"] [data-step-picks]')).toHaveTextContent("Picked by the AI: 21, 22");

    const gets = relayGet.mock.calls.length;
    await poll(60_000);
    expect(relayGet.mock.calls.length).toBe(gets);

    fireEvent.click(button("New request"));
    expect(screen.getByPlaceholderText("What should Ultra do?")).toBeInTheDocument();
    expect(window.localStorage.getItem(ULTRA_PLAN_KEY)).toBeNull();
  });

  it("pick card: AI picks pre-ticked, Send these only at exactly pick_n, posts the ids in card order", async () => {
    window.localStorage.setItem(ULTRA_KEY, "1");
    window.localStorage.setItem(ULTRA_PLAN_KEY, "p1");
    current = async () => plan("needs_you", { step_states: [waiting, { id: "mass", state: "pending" }] });
    await openPanel();
    const card = await screen.findByRole("region", { name: "Pick 2" });
    expect(within(card).getByText("Which 2 for the mass?")).toBeInTheDocument();
    expect(within(card).getAllByRole("img").map((i) => i.getAttribute("alt"))).toEqual(["pic 21", "pic 22", "pic 23"]);
    expect(within(card).getByRole("checkbox", { name: "pic 22 (AI pick)" })).toBeChecked();
    expect([...card.querySelectorAll("[data-pick-caption]")].map((c) => c.textContent)).toEqual(["pic 21", "pic 22", "pic 23"]);
    expect(button("Send these")).toBeDisabled();

    fireEvent.click(within(card).getByRole("checkbox", { name: "pic 23" }));
    expect(button("Send these")).toBeEnabled();
    fireEvent.click(within(card).getByRole("checkbox", { name: "pic 21" }));
    expect(button("Send these")).toBeDisabled();
    fireEvent.click(within(card).getByRole("checkbox", { name: "pic 22 (AI pick)" }));

    relayPost.mockResolvedValueOnce(plan("running"));
    current = async () => plan("running");
    fireEvent.click(button("Send these"));
    await waitFor(() => expect(relayPost).toHaveBeenCalledWith("/admin/ultra/plans/p1/pick", { step: "pick", ids: [21, 23] }, undefined,
      expect.any(AbortSignal)));
    await waitFor(() => expect(screen.queryByRole("region", { name: "Pick 2" })).toBeNull());
  });

  it("a refused pick shows the server's words and keeps the ticks", async () => {
    window.localStorage.setItem(ULTRA_KEY, "1");
    window.localStorage.setItem(ULTRA_PLAN_KEY, "p1");
    current = async () => plan("needs_you", { step_states: [waiting, { id: "mass", state: "pending" }] });
    await openPanel();
    const card = await screen.findByRole("region", { name: "Pick 2" });
    fireEvent.click(within(card).getByRole("checkbox", { name: "pic 21" }));
    relayPost.mockRejectedValueOnce(new RelayError(422, {}, "pick ids not offered: 99"));
    fireEvent.click(button("Send these"));
    expect(await screen.findByRole("alert")).toHaveTextContent("pick ids not offered: 99");
    expect(within(card).getByRole("checkbox", { name: "pic 21" })).toBeChecked();
  });

  it("the daily cap (429) reads as the server wrote it; the draft stays", async () => {
    window.localStorage.setItem(ULTRA_KEY, "1");
    await openPanel();
    relayPost.mockRejectedValueOnce(new RelayError(429, {}, "Daily Ultra limit reached (5 plans). Try again tomorrow."));
    fireEvent.change(screen.getByPlaceholderText("What should Ultra do?"), { target: { value: "go" } });
    fireEvent.click(button("Plan it"));
    expect(await screen.findByRole("alert")).toHaveTextContent("Daily Ultra limit reached (5 plans). Try again tomorrow.");
    expect(screen.getByPlaceholderText("What should Ultra do?")).toHaveValue("go");
    expect(button("Plan it")).toBeEnabled();
  });

  it("the panel closed before the start answered: the plan id is kept, reopening resumes it", async () => {
    window.localStorage.setItem(ULTRA_KEY, "1");
    await openPanel();
    let answer!: (p: PlanView) => void;
    relayPost.mockReturnValueOnce(new Promise<PlanView>((res) => { answer = res; }));
    current = async () => planning;
    fireEvent.change(screen.getByPlaceholderText("What should Ultra do?"), { target: { value: "mass the new set" } });
    fireEvent.click(button("Plan it"));
    fireEvent.click(screen.getByLabelText("Ultra mode"));          // Ultra off: the panel unmounts
    expect(document.querySelector("[data-ultra]")).toBeNull();
    await act(async () => { answer(planning); });
    expect(window.localStorage.getItem(ULTRA_PLAN_KEY)).toBe("p1");
    fireEvent.click(screen.getByLabelText("Ultra mode"));
    await waitFor(() => expect(note()).toHaveTextContent("Planning… turn 2 of 25"));
    expect(button("Stop planning")).toBeEnabled();
  });

  it("closed and reopened before the start answered: the reopened panel waits, then shows the plan (one POST)", async () => {
    window.localStorage.setItem(ULTRA_KEY, "1");
    await openPanel();
    let answer!: (p: PlanView) => void;
    relayPost.mockReturnValueOnce(new Promise<PlanView>((res) => { answer = res; }));
    current = async () => planning;
    fireEvent.change(screen.getByPlaceholderText("What should Ultra do?"), { target: { value: "mass the new set" } });
    fireEvent.click(button("Plan it"));
    fireEvent.click(screen.getByLabelText("Ultra mode"));          // closed: the panel unmounts
    fireEvent.click(screen.getByLabelText("Ultra mode"));          // reopened while the POST is still out
    expect(button("Plan it")).toBeDisabled();
    expect(screen.getByPlaceholderText("What should Ultra do?")).toBeDisabled();
    expect(screen.getByText("Sending your request to the planner…")).toBeInTheDocument();
    await act(async () => { answer(planning); });
    await waitFor(() => expect(note()).toHaveTextContent("Planning… turn 2 of 25"));
    expect(relayPost.mock.calls.filter(([p]) => p === "/admin/ultra/plans")).toHaveLength(1);
    expect(window.localStorage.getItem(ULTRA_PLAN_KEY)).toBe("p1");
  });

  it("a 400 that is not the login guard reads as written; the draft stays", async () => {
    window.localStorage.setItem(ULTRA_KEY, "1");
    await openPanel();
    relayPost.mockRejectedValueOnce(new RelayError(400, {}, "request is empty"));
    fireEvent.change(screen.getByPlaceholderText("What should Ultra do?"), { target: { value: "go" } });
    fireEvent.click(button("Plan it"));
    expect(await screen.findByRole("alert")).toHaveTextContent("request is empty");
    expect(screen.queryByRole("link", { name: /Connect card/ })).toBeNull();
    expect(screen.getByPlaceholderText("What should Ultra do?")).toHaveValue("go");
  });

  it("the relay's login 400 links the Connect card and clears the draft", async () => {
    window.localStorage.setItem(ULTRA_KEY, "1");
    await openPanel();
    relayPost.mockRejectedValueOnce(new RelayError(400, {}, "paste logins in the Connect card"));
    fireEvent.change(screen.getByPlaceholderText("What should Ultra do?"), { target: { value: "go" } });
    fireEvent.click(button("Plan it"));
    expect(await screen.findByRole("link", { name: "paste logins in the Connect card" })).toBeInTheDocument();
    expect(screen.getByPlaceholderText("What should Ultra do?")).toHaveValue("");
  });

  it("a stale OK (409) shows the server's words and the re-read plan", async () => {
    window.localStorage.setItem(ULTRA_KEY, "1");
    window.localStorage.setItem(ULTRA_PLAN_KEY, "p1");
    await openPanel();
    await screen.findByRole("button", { name: "OK, run 2 steps" });
    relayPost.mockRejectedValueOnce(new RelayError(409, {}, "plan changed since you saw it"));
    current = async () => plan("expired");
    fireEvent.click(button("OK, run 2 steps"));
    expect(await screen.findByRole("alert")).toHaveTextContent("plan changed since you saw it");
    await screen.findByRole("button", { name: "New request" });
    expect(screen.queryByRole("button", { name: /^OK/ })).toBeNull();
  });

  it("a reload resumes the open plan; a plan gone (404) drops back to the composer", async () => {
    window.localStorage.setItem(ULTRA_KEY, "1");
    window.localStorage.setItem(ULTRA_PLAN_KEY, "p1");
    await openPanel();
    await screen.findByRole("button", { name: "OK, run 2 steps" });
    expect(relayGet).toHaveBeenCalledWith("/admin/ultra/plans/p1", undefined, expect.any(AbortSignal));
    cleanup();

    current = async () => { throw new RelayError(404, {}, "plan not found"); };
    await openPanel();
    expect(await screen.findByPlaceholderText("What should Ultra do?")).toBeInTheDocument();
    await act(async () => {});
    expect(window.localStorage.getItem(ULTRA_PLAN_KEY)).toBeNull();
  });
});
