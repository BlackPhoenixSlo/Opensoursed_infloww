import type { ReactElement } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { act, cleanup, fireEvent, screen, waitFor, within } from "@testing-library/react";

import { makeTestQueryClient, renderWithProviders as render } from "@/test-utils";
import { relay } from "@/lib/relay";
import { MassMessageComposer } from "@/components/compose/MassMessageComposer";
import { MASS_ONE_GIF_ALL_MODELS } from "@/components/compose/massMessageReducer";
import CreateMessage from "@/components/growth/CreateMessagePopUp";
import { ownerAccountsQuery } from "@/lib/ownerAccounts";
import { IfConfirmHost } from "@/components/ui/ifConfirm";
import { PRICE_NOTE } from "@/lib/sendGuards";
import { AllPlatformsContext, resetPlatformForTests, setPlatform } from "@/lib/platform";

type Fixture = { id: string; nickname: string; color: string; platform?: string };
const BASE: Fixture[] = [{ id: "acct1", nickname: "A", color: "#fff" }, { id: "acct2", nickname: "B", color: "#fff" }];
const fixtures = vi.hoisted(() => ({
  accounts: [] as Fixture[],
  scope: { scope: { kind: "all" } } as { scope: { kind: "all" } | { kind: "model"; accountId: string } },
}));
vi.mock("@/contexts/UserContext", async (importOriginal) => ({
  ...await importOriginal<typeof import("@/contexts/UserContext")>(),
  useOptionalUser: () => ({ user: { user_id: "mass-owner" } }),
}));

function renderWithRoster(ui: ReactElement, client = makeTestQueryClient()) {
  client.setQueryData(ownerAccountsQuery("mass-owner").queryKey, {
    accounts: fixtures.accounts,
    active_account_id: null,
  });
  return render(ui, client);
}

const postSpy = vi.fn(async (..._a: unknown[]) => ({}));
vi.mock("@/lib/relay", async (importOriginal) => {
  const mod = await importOriginal<typeof import("@/lib/relay")>();
  return { ...mod, relay: { ...mod.relay, post: (...a: unknown[]) => postSpy(...a), get: vi.fn(async () => []) } };
});
vi.mock("@/contexts/EmployeeContext", () => ({ useEmployee: () => ({ current: { id: 1 } }) }));
vi.mock("@/contexts/ScopeContext", () => ({ useScope: () => fixtures.scope }));
vi.mock("@/hooks/useAccounts", async () => {
  const { useContext, useMemo } = await import("react");
  const { accountPlatform, AllPlatformsContext, usePlatform } = await import("@/lib/platform");
  return {
    useActiveAccounts: () => fixtures.accounts,
    usePlatformAccounts: () => {
      const platform = usePlatform();
      const every = useContext(AllPlatformsContext);
      const all = fixtures.accounts;
      return useMemo(() => (every ? all : all.filter((a) => accountPlatform(a) === platform)), [all, platform, every]);
    },
    ownerAccountsQuery: (u?: string) => ({ queryKey: ["accounts", u ?? "anon"], queryFn: async () => ({ accounts: fixtures.accounts }) }),
  };
});
vi.mock("@/hooks/useAllModelsInclude", () => ({
  useAllModelsInclude: () => ({ isIncluded: () => true, toggle: vi.fn() }),
}));
const { useSmartListsSpy } = vi.hoisted(() => ({ useSmartListsSpy: vi.fn() }));
vi.mock("@/hooks/useSmartLists", () => {
  const lists = { data: [{ id: 7, name: "Whales" }] };
  return {
    useSmartLists: (accountId: string | null) => {
      useSmartListsSpy(accountId);
      return accountId ? lists : { data: undefined };
    },
    resolveSmartLists: vi.fn(async (ids: ReadonlySet<number>) => (ids.size ? [101, 102] : [])),
  };
});
vi.mock("@/components/chat/VaultPicker", () => ({ VaultPicker: () => null }));
vi.mock("@/components/chat/GifPicker", () => ({
  GifPickerButton: ({ onToggle }: { onToggle: () => void }) => <button type="button" onClick={onToggle}>GIF</button>,
  GifPickerStrip: ({ onPick }: { onPick: (g: { id: string; thumbUrl: string; fullUrl: string; title: string }) => void }) => (
    <>
      {["one", "two"].map((t) => (
        <button key={t} type="button" onClick={() => onPick({ id: `g-${t}`, thumbUrl: "", fullUrl: "", title: t })}>
          pick {t}
        </button>
      ))}
    </>
  ),
}));

beforeEach(() => {
  fixtures.accounts = BASE;
  fixtures.scope = { scope: { kind: "all" } };
});
afterEach(() => {
  cleanup();
  postSpy.mockClear();
  vi.restoreAllMocks();
  window.localStorage.clear();
  resetPlatformForTests();
});

const REASON = "Add text, media, or a GIF";
const broadcast = () => screen.getByRole("button", { name: /^Broadcast$/ });
const typeText = (v: string) => fireEvent.change(screen.getByPlaceholderText("What's the broadcast?"), { target: { value: v } });
const typePrice = (v: string) => fireEvent.change(screen.getByPlaceholderText("0 (free)"), { target: { value: v } });

describe("MassMessageComposer — why the button is disabled, visible without hover", () => {
  it("an empty draft shows the reason; typing clears it", async () => {
    renderWithRoster(<MassMessageComposer onClose={() => {}} />);
    const btn = broadcast();
    await waitFor(() => expect(btn).toHaveProperty("disabled", true));
    expect(btn.getAttribute("title")).toBe(REASON);
    expect(screen.getByRole("status").textContent).toBe(REASON);

    typeText("hello");
    await waitFor(() => expect(screen.queryByText(REASON)).toBeNull());
    expect(btn).toHaveProperty("disabled", false);
    expect(btn.getAttribute("title")).toBeNull();
    expect(screen.queryByRole("status")).toBeNull();
    expect(postSpy).not.toHaveBeenCalled();
  });
});

describe("MassMessageComposer — the button and the send read one check", () => {
  it.each([
    ["empty text", "", "", REASON],
    ["a price under $3", "hello", "2", PRICE_NOTE],
  ])("%s: Broadcast is off, says why, and a click POSTs nothing", async (_n, text, price, reason) => {
    vi.spyOn(window, "confirm").mockReturnValue(true);
    renderWithRoster(<MassMessageComposer onClose={() => {}} />);
    typeText(text);
    typePrice(price);
    const btn = broadcast();
    await waitFor(() => expect(btn.getAttribute("title")).toBe(reason));
    expect(btn).toHaveProperty("disabled", true);
    fireEvent.click(btn);
    await new Promise((r) => setTimeout(r, 20));
    expect(postSpy).not.toHaveBeenCalled();
  });

  it("a valid draft POSTs its body once, then closes", async () => {
    vi.spyOn(window, "confirm").mockReturnValue(true);
    const onClose = vi.fn();
    renderWithRoster(<MassMessageComposer onClose={onClose} />);
    typeText("hello");
    typePrice("5");
    const btn = broadcast();
    await waitFor(() => expect(btn).toHaveProperty("disabled", false));
    fireEvent.click(btn);
    await waitFor(() => expect(onClose).toHaveBeenCalledTimes(1));
    expect(postSpy).toHaveBeenCalledTimes(1);
    const [path, body, opts] = postSpy.mock.calls[0] as [string, Record<string, unknown>, { accountId: string }];
    expect(path).toBe("/api/of/v2/messages/queue");
    expect(opts.accountId).toBe("acct1");
    expect(body).toMatchObject({ text: "hello", price: 5, user_lists: ["fans", "following"], scheduled_date: null });
  });

  it("a cancelled confirm sends nothing", async () => {
    vi.spyOn(window, "confirm").mockReturnValue(false);
    renderWithRoster(<MassMessageComposer onClose={() => {}} />);
    typeText("hello");
    const btn = broadcast();
    await waitFor(() => expect(btn).toHaveProperty("disabled", false));
    fireEvent.click(btn);
    await new Promise((r) => setTimeout(r, 20));
    expect(postSpy).not.toHaveBeenCalled();
  });
});

describe("CreateMessage", () => {
  it("a cold Fansly page with the OnlyFans sidebar never POSTs a broadcast", async () => {
    const client = makeTestQueryClient();
    const rosterKey = ownerAccountsQuery("mass-owner").queryKey;
    const fansly = { id: "900539700124344320", nickname: "Nova", color: "#fff", platform: "fansly" };
    vi.spyOn(window, "confirm").mockReturnValue(true);
    const onClose = vi.fn();
    const popup = render(<CreateMessage open accountId={fansly.id} onClose={onClose} />, client);
    fireEvent.click(screen.getByRole("button", { name: /OF mass message/ }));
    fireEvent.click(screen.getByRole("button", { name: "Next" }));
    popup.rerender(<CreateMessage open={false} accountId={fansly.id} onClose={onClose} />);
    await screen.findByPlaceholderText("What's the broadcast?");
    typeText("keep this draft");
    await act(async () => { fireEvent.click(broadcast()); });
    expect(postSpy.mock.calls).toEqual([]);
    expect(broadcast()).toBeDisabled();

    await act(async () => { client.setQueryData(rosterKey, { accounts: [BASE[0], fansly] }); });
    await waitFor(() => expect(screen.getByPlaceholderText("What's the broadcast?")).toHaveValue("keep this draft"));
    fireEvent.click(screen.getByRole("checkbox", { name: /Broadcast from ALL models/ }));
    fireEvent.click(broadcast());
    expect(broadcast()).toBeDisabled();
    expect(postSpy).not.toHaveBeenCalled();
  });

  it("hides all three broadcast cards for a known Fansly page Creator", () => {
    fixtures.accounts = [BASE[0], { id: "fs1", nickname: "Nova", color: "#fff", platform: "fansly" }];
    renderWithRoster(<CreateMessage open accountId="fs1" onClose={vi.fn()} />);
    expect(screen.queryByRole("button", { name: /mass message|Message online fans/i })).toBeNull();
  });

  it("shows all three cards on a cold OnlyFans page and opens the page Creator as sender", async () => {
    fixtures.accounts = [BASE[1], BASE[0]];
    const onClose = vi.fn();
    const popup = render(<CreateMessage open accountId="acct1" onClose={onClose} />);
    expect(screen.getByRole("button", { name: /Priority mass message/i })).toBeVisible();
    expect(screen.getByRole("button", { name: /Message online fans/ })).toBeVisible();
    fireEvent.click(screen.getByRole("button", { name: /OF mass message/ }));
    fireEvent.click(screen.getByRole("button", { name: "Next" }));
    popup.rerender(<CreateMessage open={false} accountId="acct1" onClose={onClose} />);
    expect(await screen.findByLabelText("Post as")).toHaveValue("acct1");
  });
});

describe("MassMessageComposer — only massSenders send", () => {
  const NOVA: Fixture = { id: "fs1", nickname: "Nova", color: "#fff", platform: "fansly" };
  const options = () => within(screen.getByLabelText("Post as")).queryAllByRole("option").map((o) => o.textContent);
  const allModels = () => fireEvent.click(screen.getByRole("checkbox", { name: /Broadcast from ALL models/ }));

  it("a Fansly Creator is no option and no All-models chip; the OnlyFans ones stay, in order", async () => {
    fixtures.accounts = [BASE[0], NOVA, BASE[1]];
    renderWithRoster(<MassMessageComposer onClose={() => {}} />);
    expect(options()).toEqual(["A", "B"]);
    allModels();
    expect(screen.getByText("(2/2 included)")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Nova/ })).toBeNull();
  });

  it("a forced Fansly id is no sender: Broadcast refuses and POSTs nothing", async () => {
    vi.spyOn(window, "confirm").mockReturnValue(true);
    fixtures.accounts = [BASE[0], NOVA];
    renderWithRoster(<MassMessageComposer forcedAccountId="fs1" onClose={() => {}} />);
    typeText("hello");
    const btn = broadcast();
    await waitFor(() => expect(btn.getAttribute("title")).toBe("Pick an account"));
    fireEvent.click(btn);
    await new Promise((r) => setTimeout(r, 20));
    expect(postSpy).not.toHaveBeenCalled();
  });

  it("a forced OnlyFans Creator with no session still POSTs from her id", async () => {
    vi.spyOn(window, "confirm").mockReturnValue(true);
    const onClose = vi.fn();
    const client = makeTestQueryClient();
    renderWithRoster(<MassMessageComposer forcedAccountId="ofX" onClose={onClose} />, client);
    client.setQueryData(ownerAccountsQuery("mass-owner").queryKey, {
      accounts: [...fixtures.accounts, { id: "ofX", platform: "onlyfans", has_session: false }],
    });
    typeText("hello");
    const btn = broadcast();
    await waitFor(() => expect(btn).toHaveProperty("disabled", false));
    fireEvent.click(btn);
    await waitFor(() => expect(onClose).toHaveBeenCalledTimes(1));
    expect(postSpy).toHaveBeenCalledTimes(1);
    expect((postSpy.mock.calls[0] as [string, unknown, { accountId: string }])[2].accountId).toBe("ofX");
  });

  it("in Fansly mode there is no sender at all", async () => {
    setPlatform("fansly");
    fixtures.accounts = [NOVA];
    renderWithRoster(<MassMessageComposer onClose={() => {}} />);
    expect(options()).toEqual(["(no active sessions)"]);
    typeText("hello");
    await waitFor(() => expect(broadcast().getAttribute("title")).toBe("Pick an account"));
    allModels();
    expect(screen.getByText("No active sessions.")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Aa" })).toBeNull();
  });

  it("in Combined Messages Pro with the switch on Fansly the OnlyFans Creators still send, with Aa", async () => {
    setPlatform("fansly");
    fixtures.accounts = [NOVA, BASE[0], BASE[1]];
    renderWithRoster(<AllPlatformsContext value><MassMessageComposer onClose={() => {}} /></AllPlatformsContext>);
    expect(options()).toEqual(["A", "B"]);
    allModels();
    expect(screen.getByText("(2/2 included)")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Aa" })).toBeInTheDocument();
  });

  const inWindow = (ui: ReactElement) => renderWithRoster(<AllPlatformsContext value>{ui}</AllPlatformsContext>);
  const posted = () => postSpy.mock.calls.map((c) => (c[2] as { accountId: string }).accountId);

  it("in the window an All-models send on a mixed list confirms and POSTs only the OnlyFans Creators", async () => {
    const confirmSpy = vi.spyOn(window, "confirm").mockReturnValue(true);
    const onClose = vi.fn();
    fixtures.accounts = [BASE[0], NOVA, BASE[1]];
    inWindow(<MassMessageComposer onClose={onClose} />);
    typeText("hello all");
    allModels();
    expect(screen.getByText("(2/2 included)")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Nova/ })).toBeNull();
    expect(screen.getByRole("button", { name: "Aa" })).toBeInTheDocument();
    const btn = broadcast();
    await waitFor(() => expect(btn).toHaveProperty("disabled", false));
    fireEvent.click(btn);
    await waitFor(() => expect(onClose).toHaveBeenCalledTimes(1));
    expect(confirmSpy).toHaveBeenLastCalledWith("Broadcast from 2 models?");
    expect(posted()).toEqual(["acct1", "acct2"]);
  });

  it("aborts confirmation when an eligible Creator changes Platform", async () => {
    const onClose = vi.fn();
    const view = () => (
      <AllPlatformsContext value>
        <MassMessageComposer onClose={onClose} />
        <IfConfirmHost />
      </AllPlatformsContext>
    );
    const { rerender } = renderWithRoster(view());
    typeText("hello all");
    allModels();
    fireEvent.click(broadcast());
    expect(screen.getByText("Broadcast from 2 models?")).toBeInTheDocument();

    fixtures.accounts = [BASE[0], { ...BASE[1], platform: "fansly" }];
    rerender(view());
    expect(screen.getByText("(1/1 included)")).toBeInTheDocument();
    await act(async () => fireEvent.click(screen.getByRole("button", { name: "OK" })));

    expect(posted()).toEqual([]);
    expect(broadcast()).toBeEnabled();
  });

  it("rechecks eligible Creators before each POST in a broadcast", async () => {
    vi.spyOn(window, "confirm").mockReturnValue(true);
    let finish!: (value: object) => void;
    postSpy.mockImplementationOnce(() => new Promise((resolve) => { finish = resolve; }));
    const view = <MassMessageComposer onClose={vi.fn()} />;
    const { rerender } = renderWithRoster(view);
    typeText("hello all");
    allModels();
    fireEvent.click(broadcast());
    await waitFor(() => expect(posted()).toEqual(["acct1"]));

    fixtures.accounts = [BASE[0], { ...BASE[1], platform: "fansly" }];
    rerender(<MassMessageComposer onClose={vi.fn()} />);
    await act(async () => finish({}));

    expect(posted()).toEqual(["acct1"]);
  });

  it("a confirmed broadcast still reaches every Creator when the composer unmounts mid-send", async () => {
    vi.spyOn(window, "confirm").mockReturnValue(true);
    let finish!: (value: object) => void;
    postSpy.mockImplementationOnce(() => new Promise((resolve) => { finish = resolve; }));
    const { unmount } = renderWithRoster(<MassMessageComposer onClose={vi.fn()} />);
    typeText("hello all");
    allModels();
    fireEvent.click(broadcast());
    await waitFor(() => expect(posted()).toEqual(["acct1"]));

    unmount();
    await act(async () => finish({}));

    await waitFor(() => expect(posted()).toEqual(["acct1", "acct2"]));
  });

  it("in the window a scoped OnlyFans Creator opens an OnlyFans composer: picker and chips skip Nova", () => {
    fixtures.accounts = [NOVA, BASE[0], BASE[1]];
    inWindow(<MassMessageComposer forcedAccountId="acct2" onClose={() => {}} />);
    expect(options()).toEqual(["A", "B"]);
    expect((screen.getByLabelText("Post as") as HTMLSelectElement).value).toBe("acct2");
    allModels();
    expect(screen.getByText("(2/2 included)")).toBeInTheDocument();
  });

  it("in the window a scoped Fansly Creator opens a Fansly composer, which has no sender at all", async () => {
    vi.spyOn(window, "confirm").mockReturnValue(true);
    fixtures.accounts = [BASE[0], NOVA];
    inWindow(<MassMessageComposer forcedAccountId="fs1" onClose={() => {}} />);
    expect(options()).toEqual(["(no active sessions)"]);
    typeText("hello");
    await waitFor(() => expect(broadcast().getAttribute("title")).toBe("Pick an account"));
    allModels();
    expect(screen.getByText("No active sessions.")).toBeInTheDocument();
    fireEvent.click(broadcast());
    await new Promise((r) => setTimeout(r, 20));
    expect(postSpy).not.toHaveBeenCalled();
  });

  it("in the window the picker seeding a scoped Fansly Creator moves the composer to Fansly: no OnlyFans sender is left", () => {
    fixtures.accounts = [BASE[0], NOVA];
    fixtures.scope = { scope: { kind: "model", accountId: "fs1" } };
    inWindow(<MassMessageComposer onClose={() => {}} />);
    expect(options()).toEqual(["(no active sessions)"]);
  });

  it.each<[string, Fixture[], boolean]>([
    ["OnlyFans All-models keeps Aa", [BASE[0], BASE[1]], true],
    ["a leading Fansly row is skipped for the first OnlyFans sender", [NOVA, BASE[0]], true],
  ])("All-models rich text follows the first sender: %s", async (_label, accounts, aa) => {
    fixtures.accounts = accounts;
    renderWithRoster(<MassMessageComposer onClose={() => {}} />);
    allModels();
    expect(!!screen.queryByRole("button", { name: "Aa" })).toBe(aa);
  });
});

describe("MassMessageComposer — all-models resets the Smart List picks", () => {
  it("a picked Smart List is cleared by all-models on → off", async () => {
    renderWithRoster(<MassMessageComposer onClose={() => {}} />);
    const chip = () => screen.getAllByRole("button", { name: "Whales" })[0];
    await waitFor(() => expect(chip()).toBeTruthy());
    fireEvent.click(chip());
    expect(chip().getAttribute("aria-pressed")).toBe("true");

    const all = screen.getByRole("checkbox", { name: /Broadcast from ALL models/ });
    expect(useSmartListsSpy).toHaveBeenLastCalledWith("acct1");
    fireEvent.click(all);
    expect(screen.queryByRole("button", { name: "Whales" })).toBeNull();
    expect(useSmartListsSpy).toHaveBeenLastCalledWith(null);
    fireEvent.click(all);
    await waitFor(() => expect(chip()).toBeTruthy());
    expect(screen.getAllByRole("button", { name: "Whales" }).map((b) => b.getAttribute("aria-pressed")))
      .toEqual(["false", "false"]);
  });
});

describe("MassMessageComposer — a failed trailing GIF send never re-arms the broadcast", () => {
  it("the second GIF's POST fails: the failure is shown, Broadcast stays off, one primary POST", async () => {
    vi.spyOn(window, "confirm").mockReturnValue(true);
    postSpy
      .mockImplementationOnce(async () => ({}))
      .mockImplementationOnce(async () => { throw new Error("OF said no"); });
    const onClose = vi.fn();
    renderWithRoster(<MassMessageComposer onClose={onClose} />);
    typeText("hello");
    typePrice("5");
    for (const t of ["one", "two"]) {
      fireEvent.click(screen.getByRole("button", { name: "GIF" }));
      fireEvent.click(screen.getByRole("button", { name: `pick ${t}` }));
    }
    const btn = broadcast();
    await waitFor(() => expect(btn).toHaveProperty("disabled", false));
    fireEvent.click(btn);

    const alert = await screen.findByRole("alert");
    expect(alert.textContent).toContain("1 of 1 extra GIF send failed");
    expect(alert.textContent).toContain("GIF two — OF said no");
    expect(broadcast()).toHaveProperty("disabled", true);
    expect(screen.queryByRole("button", { name: "Cancel" })).toBeNull();
    expect(screen.getAllByRole("button", { name: "Close" })).toHaveLength(2);
    expect(onClose).not.toHaveBeenCalled();

    fireEvent.click(broadcast());
    await new Promise((r) => setTimeout(r, 20));
    expect(postSpy).toHaveBeenCalledTimes(2);
    const bodies = postSpy.mock.calls.map((c) => c[1] as Record<string, unknown>);
    expect(bodies.filter((b) => b.text === "hello")).toHaveLength(1);
    expect(bodies.map((b) => [b.text, b.price, b.giphy_id])).toEqual([["hello", 5, "g-one"], ["", 0, "g-two"]]);
  });
});

describe("MassMessageComposer — all-models partial failure", () => {
  it("BUG: the content locks and the retry sends the same body from the failed model only (was: from every model)", async () => {
    const confirmSpy = vi.spyOn(window, "confirm").mockReturnValue(true);
    postSpy.mockImplementation(async (...a: unknown[]) => {
      if ((a[2] as { accountId: string }).accountId === "acct2") throw new Error("HTTP 500");
      return {};
    });
    const onClose = vi.fn();
    renderWithRoster(<MassMessageComposer onClose={onClose} />);
    typeText("hello all");
    fireEvent.click(screen.getByRole("checkbox", { name: /Broadcast from ALL models/ }));
    const btn = broadcast();
    await waitFor(() => expect(btn).toHaveProperty("disabled", false));
    fireEvent.click(btn);
    await waitFor(() => expect(screen.getByRole("status").textContent).toBe("1/2 succeeded"));
    expect(screen.getByText("Fan-out results — 1/2 succeeded")).toBeTruthy();
    expect(screen.getByPlaceholderText("What's the broadcast?").matches(":disabled")).toBe(true);
    expect(onClose).not.toHaveBeenCalled();

    postSpy.mockClear();
    postSpy.mockImplementation(async () => ({}));
    await waitFor(() => expect(btn).toHaveProperty("disabled", false));
    fireEvent.click(btn);
    await waitFor(() => expect(onClose).toHaveBeenCalledTimes(1));
    expect(confirmSpy).toHaveBeenLastCalledWith("Broadcast from 1 model?");
    expect(postSpy.mock.calls.map((c) => [(c[2] as { accountId: string }).accountId, (c[1] as { text: string }).text]))
      .toEqual([["acct2", "hello all"]]);
  });
});

describe("MassMessageComposer — all-models takes one GIF", () => {
  it("BUG: a 2nd GIF disables Broadcast with its reason (was: only the first sent, the rest dropped)", async () => {
    renderWithRoster(<MassMessageComposer onClose={vi.fn()} />);
    typeText("hello all");
    fireEvent.click(screen.getByRole("checkbox", { name: /Broadcast from ALL models/ }));
    for (const t of ["one", "two"]) {
      fireEvent.click(screen.getByRole("button", { name: "GIF" }));
      fireEvent.click(screen.getByRole("button", { name: `pick ${t}` }));
    }
    const btn = broadcast();
    await waitFor(() => expect(btn.getAttribute("title")).toBe(MASS_ONE_GIF_ALL_MODELS));
    expect(btn).toHaveProperty("disabled", true);
    expect(screen.getByRole("status").textContent).toBe(MASS_ONE_GIF_ALL_MODELS);

    fireEvent.click(screen.getAllByRole("button", { name: "Remove GIF" })[1]);
    await waitFor(() => expect(btn).toHaveProperty("disabled", false));
  });
});

describe("MassMessageComposer — once touched, Escape stays off until it closes (a reverted edit too); × always closes", () => {
  const escape = () => fireEvent.keyDown(document.activeElement ?? document.body, { key: "Escape" });
  const VIP = { id: 501, name: "VIP", type: "custom", usersCount: 3 };
  const MASSDM = { id: 502, name: "MASSDMEXCLUDE", type: "custom", usersCount: 2 };
  const box = (name: string, side: 0 | 1) => screen.getAllByRole("checkbox", { name: new RegExp(`^${name}`) })[side];
  it("a custom exclusion ticked before the seeding lands stays an edit after it", async () => {
    let land!: (v: unknown) => void;
    const pending = new Promise((r) => { land = r; });
    const get = vi.mocked(relay.get);
    get.mockImplementation(((path: string) => (path.startsWith("/api/of/v2/lists") ? pending : Promise.resolve([]))) as never);
    try {
      const qc = makeTestQueryClient();
      qc.setQueryData(["fan-lists", "acct1"], [VIP, MASSDM], { updatedAt: 0 });
      const onClose = vi.fn();
      renderWithRoster(<MassMessageComposer forcedAccountId="acct1" onClose={onClose} />, qc);
      fireEvent.click(box("VIP", 1));
      expect(box("MASSDMEXCLUDE", 1)).not.toBeChecked();
      land({ list: [VIP, MASSDM], hasMore: false });
      await waitFor(() => expect(box("MASSDMEXCLUDE", 1)).toBeChecked());
      expect(box("VIP", 1)).toBeChecked();
      escape();
      expect(onClose).not.toHaveBeenCalled();
    } finally {
      get.mockImplementation((async () => []) as never);
    }
  });
  it("typed then cleared: Escape still does nothing (declared), × closes", () => {
    const onClose = vi.fn();
    renderWithRoster(<MassMessageComposer onClose={onClose} />);
    typeText("hello");
    typeText("");
    escape();
    expect(onClose).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "Close" }));
    expect(onClose).toHaveBeenCalledTimes(1);
  });
});

describe("MassMessageComposer — Escape never drops a typed draft", () => {
  const escape = () => fireEvent.keyDown(document.activeElement ?? document.body, { key: "Escape" });
  it("clean: Escape closes", () => {
    const onClose = vi.fn();
    renderWithRoster(<MassMessageComposer onClose={onClose} />);
    escape();
    expect(onClose).toHaveBeenCalledTimes(1);
  });
  it("dirty: Escape does nothing", () => {
    const onClose = vi.fn();
    renderWithRoster(<MassMessageComposer onClose={onClose} />);
    typeText("hello");
    escape();
    expect(onClose).not.toHaveBeenCalled();
  });
  async function seeded(onClose: () => void) {
    renderWithRoster(<MassMessageComposer onClose={onClose} />);
    await waitFor(() => expect(screen.getAllByRole("button", { name: "Whales" })[0]).toBeTruthy());
  }
  it("seeded and untouched: Escape still closes", async () => {
    const onClose = vi.fn();
    await seeded(onClose);
    escape();
    expect(onClose).toHaveBeenCalledTimes(1);
  });
  it.each([
    ["a Smart List", () => fireEvent.click(screen.getAllByRole("button", { name: "Whales" })[0])],
    ["the audience (All fans off)", () => fireEvent.click(screen.getByRole("button", { name: /All fans/ }))],
  ])("only %s set: Escape does nothing", async (_n, act) => {
    const onClose = vi.fn();
    await seeded(onClose);
    act();
    escape();
    expect(onClose).not.toHaveBeenCalled();
  });
  it("Mass Online: only a targeting limit set: Escape does nothing", async () => {
    const onClose = vi.fn();
    renderWithRoster(<MassMessageComposer mode="online" onClose={onClose} />);
    await waitFor(() => expect(screen.getAllByRole("button", { name: "Whales" })[0]).toBeTruthy());
    fireEvent.change(screen.getByLabelText(/Include fans with unread msgs/), { target: { value: "50" } });
    escape();
    expect(onClose).not.toHaveBeenCalled();
  });
});

describe("MassMessageComposer — Escape in a picker's search box leaves even a clean composer open", () => {
  it.each([["Emoji picker"], ["Insert saved template"], ["Tag other creators in this message"]])("%s", async (name) => {
    const onClose = vi.fn();
    renderWithRoster(<MassMessageComposer onClose={onClose} />);
    fireEvent.click(screen.getByTitle(name));
    const input = await waitFor(() => {
      const el = [...document.querySelectorAll<HTMLInputElement>("input[type=text], input[type=search]")]
        .find((i) => !i.closest('[role="dialog"]'));
      if (!el) throw new Error(`no search box for ${name}`);
      return el;
    });
    input.focus();
    fireEvent.keyDown(input, { key: "Escape" });
    expect(onClose).not.toHaveBeenCalled();
  });
});
