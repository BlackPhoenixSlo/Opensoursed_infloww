import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactNode } from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

const { relayGet } = vi.hoisted(() => ({ relayGet: vi.fn() }));
vi.mock("@/lib/relay", async (orig) => ({
  SALARY_FREQUENCIES: (await orig<typeof import("@/lib/relay")>()).SALARY_FREQUENCIES,
  relay: { get: relayGet, post: vi.fn(), put: vi.fn(), patch: vi.fn(), del: vi.fn() },
  proxyImage: (u: string) => u,
  proxyScrubFrame: (u: string) => u,
}));

const { update } = vi.hoisted(() => ({
  update: { mutate: vi.fn(), isPending: false },
}));
const FAN = { id: 1, tags: [] as string[], custom_nickname: null, notes: null };
vi.mock("@/hooks/useFan", () => ({
  useFan: () => ({ data: FAN, isLoading: false, update }),
}));
vi.mock("@/hooks/useAccounts", () => ({ useAccountLabel: () => "acct-a" }));
vi.mock("@/hooks/useMassExclude", () => ({
  useMassExclude: () => ({ isOn: false, isLoading: false, toggle: vi.fn() }),
}));
vi.mock("@/hooks/useLastPurchases", () => ({
  useFanActivity: () => ({ lastPurchase: new Map(), recentSpend: new Map() }),
}));
vi.mock("@/hooks/useFanPpvHistory", () => ({
  useFanPpvHistory: () => ({
    data: { items: [], summary: { max_cents: 0, avg_cents: 0 } },
    isLoading: false,
  }),
}));
vi.mock("@/hooks/useFanChatMedia", () => ({
  useFanChatMedia: () => ({ data: { pages: [] }, isLoading: false, fetchNextPage: vi.fn(), hasNextPage: false }),
}));
vi.mock("./PersonaClaims", () => ({ PersonaClaims: () => null }));

import { FanDrawer } from "./FanDrawer";

const CHAT = {
  withUser: { id: 7, name: "Fan Seven", username: "fan7", avatar: null, displayName: "", notice: "" },
} as never;

function queueOFUser(...bodies: Record<string, unknown>[]) {
  relayGet.mockReset();
  let i = 0;
  relayGet.mockImplementation((path: string) => {
    if (!path.includes("/users/")) return Promise.resolve({});
    const body = bodies[Math.min(i, bodies.length - 1)];
    i += 1;
    return Promise.resolve(body);
  });
}

function ofReads() {
  return relayGet.mock.calls.filter(([p]) => String(p).includes("/users/")).length;
}

let qc: QueryClient;
function Wrap({ children }: { children: ReactNode }) {
  return <QueryClientProvider client={qc}>{children}</QueryClientProvider>;
}

function renderDrawer(focusNotesRequest?: number) {
  return render(
    <FanDrawer open onClose={vi.fn()} accountId="acct-a" fanId={7} chat={CHAT}
      focusNotesRequest={focusNotesRequest} />,
    { wrapper: Wrap },
  );
}

beforeEach(() => {
  qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  update.mutate.mockReset();
  queueOFUser({ id: 7, displayName: "from OF", notice: "note from OF" });
});
afterEach(() => { cleanup(); qc.clear(); window.localStorage.clear(); });

const nick = () => screen.getByPlaceholderText("Fan Seven") as HTMLInputElement;
const note = () =>
  screen.getByPlaceholderText(/loves bondage/) as HTMLTextAreaElement;

describe("FanDrawer edit-freshness", () => {
  it("opening the drawer on a cached fan costs no OF read", async () => {
    qc.setQueryData(["of-user", "acct-a", 7, "full"], { id: 7, displayName: "cached", notice: "" });
    renderDrawer();
    await waitFor(() => expect(nick().value).toBe("cached"));
    await new Promise((r) => setTimeout(r, 20));
    expect(ofReads()).toBe(0);
  });

  it("engaging the nickname field re-reads, and picks up a value changed elsewhere", async () => {
    const user = userEvent.setup();
    qc.setQueryData(["of-user", "acct-a", 7, "full"], { id: 7, displayName: "stale", notice: "" });
    queueOFUser({ id: 7, displayName: "changed elsewhere", notice: "" });
    renderDrawer();
    await waitFor(() => expect(nick().value).toBe("stale"));

    await user.click(nick());
    await waitFor(() => expect(nick().value).toBe("changed elsewhere"));
    expect(ofReads()).toBe(1);
  });

  it("re-reads once per open, not on every focus/blur cycle", async () => {
    const user = userEvent.setup();
    qc.setQueryData(["of-user", "acct-a", 7, "full"], { id: 7, displayName: "stale", notice: "" });
    renderDrawer();
    await waitFor(() => expect(nick().value).toBe("stale"));

    await user.click(nick());
    await waitFor(() => expect(ofReads()).toBe(1));
    await user.click(note());
    await user.click(nick());
    await new Promise((r) => setTimeout(r, 20));
    expect(ofReads()).toBe(1);
  });

  it("re-reads again once the stale window passes (pinned drawer, open all day)", async () => {
    const user = userEvent.setup();
    qc.setQueryData(["of-user", "acct-a", 7, "full"], { id: 7, displayName: "stale", notice: "" });
    queueOFUser(
      { id: 7, displayName: "read one", notice: "" },
      { id: 7, displayName: "renamed while pinned", notice: "" },
    );
    renderDrawer();
    await waitFor(() => expect(nick().value).toBe("stale"));

    await user.click(nick());
    await waitFor(() => expect(nick().value).toBe("read one"));
    await user.click(note());
    expect(ofReads()).toBe(1);

    const realNow = Date.now();
    const nowSpy = vi.spyOn(Date, "now").mockImplementation(() => realNow + 6 * 60_000);
    try {
      await user.click(nick());
      await waitFor(() => expect(nick().value).toBe("renamed while pinned"));
      expect(ofReads()).toBe(2);
    } finally {
      nowSpy.mockRestore();
    }
  });

  it("does not clobber what the operator has already typed", async () => {
    const user = userEvent.setup();
    qc.setQueryData(["of-user", "acct-a", 7, "full"], { id: 7, displayName: "stale", notice: "" });
    let release!: (v: unknown) => void;
    relayGet.mockReset();
    relayGet.mockImplementation((path: string) =>
      String(path).includes("/users/")
        ? new Promise((res) => { release = res; })
        : Promise.resolve({}),
    );
    renderDrawer();
    await waitFor(() => expect(nick().value).toBe("stale"));

    await user.click(nick());
    await user.clear(nick());
    await user.type(nick(), "operator typed");
    release({ id: 7, displayName: "arrived late", notice: "" });

    await new Promise((r) => setTimeout(r, 20));
    expect(nick().value).toBe("operator typed");
  });

  it("a higher focus request shows the Insights tab, then expands a collapsed Notes block and focuses Fan notes", async () => {
    const user = userEvent.setup();
    qc.setQueryData(["of-user", "acct-a", 7, "full"], { id: 7, displayName: "cached", notice: "" });
    const { rerender } = renderDrawer(0);
    await waitFor(() => expect(nick().value).toBe("cached"));
    const ask = (focusNotesRequest: number) => rerender(
      <FanDrawer open onClose={vi.fn()} accountId="acct-a" fanId={7} chat={CHAT}
        focusNotesRequest={focusNotesRequest} />,
    );
    const fanNotes = () => screen.getByRole("textbox", { name: "Fan notes" });

    await user.click(screen.getByRole("tab", { name: "Sales" }));
    expect(screen.queryByRole("textbox", { name: "Fan notes" })).not.toBeInTheDocument();
    ask(1);
    expect(screen.getByRole("tab", { name: "Insights" })).toHaveAttribute("aria-selected", "true");
    await waitFor(() => expect(fanNotes()).toHaveFocus());

    await user.click(screen.getByRole("button", { name: "Collapse Notes" }));
    expect(screen.queryByRole("textbox", { name: "Fan notes" })).not.toBeInTheDocument();
    ask(2);
    expect(screen.getByRole("button", { name: "Collapse Notes" })).toHaveAttribute("aria-expanded", "true");
    await waitFor(() => expect(fanNotes()).toHaveFocus());

    await user.click(screen.getByRole("button", { name: "Remove Notes" }));
    expect(screen.queryByRole("textbox", { name: "Fan notes" })).not.toBeInTheDocument();
    ask(3);
    await waitFor(() => expect(fanNotes()).toHaveFocus());
  });

  it("a higher Nickname focus request shows the Insights tab, then expands a collapsed Profile block and focuses Nickname, which re-reads OF", async () => {
    const user = userEvent.setup();
    qc.setQueryData(["of-user", "acct-a", 7, "full"], { id: 7, displayName: "cached", notice: "" });
    const { rerender } = renderDrawer(0);
    await waitFor(() => expect(nick().value).toBe("cached"));
    const ask = (focusNicknameRequest: number) => rerender(
      <FanDrawer open onClose={vi.fn()} accountId="acct-a" fanId={7} chat={CHAT}
        focusNotesRequest={0} focusNicknameRequest={focusNicknameRequest} />,
    );

    await user.click(screen.getByRole("tab", { name: "Sales" }));
    expect(screen.queryByPlaceholderText("Fan Seven")).not.toBeInTheDocument();
    ask(1);
    expect(screen.getByRole("tab", { name: "Insights" })).toHaveAttribute("aria-selected", "true");
    await waitFor(() => expect(nick()).toHaveFocus());
    await waitFor(() => expect(ofReads()).toBe(1));

    await user.click(screen.getByRole("button", { name: "Collapse Profile" }));
    expect(screen.queryByPlaceholderText("Fan Seven")).not.toBeInTheDocument();
    ask(2);
    expect(screen.getByRole("button", { name: "Collapse Profile" })).toHaveAttribute("aria-expanded", "true");
    await waitFor(() => expect(nick()).toHaveFocus());
  });
});
