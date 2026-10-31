/**
 * MassMessageComposer on the rendered form:
 *   • the Broadcast button is disabled while the form is invalid and its
 *     `title` says why — but a phone has no hover, so the footer shows the same
 *     reason and clears once the form is valid;
 *   • the button and the send read the ONE validateMass result: an invalid
 *     form never POSTs, a valid one POSTs exactly its body once;
 *   • the all-models switch resets the Smart List picks with the rest of the
 *     audience (the reducer owns them), and disables the segment query;
 *   • a trailing GIF send that fails after the broadcast landed leaves the
 *     form spent: the failure is listed and Broadcast stays off, so the paid
 *     broadcast can't be sent twice;
 *   • an all-models partial failure locks the content and the retry sends
 *     the same body from the failed model only.
 */
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, screen, waitFor } from "@testing-library/react";

import { renderWithProviders } from "@/test-utils";
import { MassMessageComposer } from "@/components/compose/MassMessageComposer";
import { PRICE_NOTE } from "@/lib/sendGuards";

const postSpy = vi.fn(async (..._a: unknown[]) => ({}));
vi.mock("@/lib/relay", async (importOriginal) => {
  const mod = await importOriginal<typeof import("@/lib/relay")>();
  return { ...mod, relay: { ...mod.relay, post: (...a: unknown[]) => postSpy(...a), get: vi.fn(async () => []) } };
});
vi.mock("@/contexts/EmployeeContext", () => ({ useEmployee: () => ({ current: { id: 1 } }) }));
vi.mock("@/contexts/ScopeContext", () => {
  const all = { scope: { kind: "all" } };
  return { useScope: () => all };
});
vi.mock("@/hooks/useAccounts", () => {
  const accounts = [{ id: "acct1", nickname: "A", color: "#fff" }, { id: "acct2", nickname: "B", color: "#fff" }];
  return { useActiveAccounts: () => accounts, usePlatformAccounts: () => accounts };
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
// The GIF strip as one button per GIF (the real one searches a GIF API).
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

afterEach(() => {
  cleanup();
  postSpy.mockClear();
  vi.restoreAllMocks();
});

const REASON = "Add text, media, or a GIF";
const broadcast = () => screen.getByRole("button", { name: /^Broadcast$/ });
const typeText = (v: string) => fireEvent.change(screen.getByPlaceholderText("What's the broadcast?"), { target: { value: v } });
const typePrice = (v: string) => fireEvent.change(screen.getByPlaceholderText("0 (free)"), { target: { value: v } });

describe("MassMessageComposer — why the button is disabled, visible without hover", () => {
  it("an empty draft shows the reason; typing clears it", async () => {
    renderWithProviders(<MassMessageComposer onClose={() => {}} />);
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
    renderWithProviders(<MassMessageComposer onClose={() => {}} />);
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
    renderWithProviders(<MassMessageComposer onClose={onClose} />);
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
    renderWithProviders(<MassMessageComposer onClose={() => {}} />);
    typeText("hello");
    const btn = broadcast();
    await waitFor(() => expect(btn).toHaveProperty("disabled", false));
    fireEvent.click(btn);
    await new Promise((r) => setTimeout(r, 20));
    expect(postSpy).not.toHaveBeenCalled();
  });
});

describe("MassMessageComposer — all-models resets the Smart List picks", () => {
  it("a picked Smart List is cleared by all-models on → off", async () => {
    renderWithProviders(<MassMessageComposer onClose={() => {}} />);
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
    renderWithProviders(<MassMessageComposer onClose={onClose} />);
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
    expect(screen.getByRole("button", { name: "Close" })).toBeTruthy();
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
    renderWithProviders(<MassMessageComposer onClose={onClose} />);
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
