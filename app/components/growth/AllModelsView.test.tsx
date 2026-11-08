/**
 * Growth > Scripts' All models matrix: a row's "Share to all" reads its first holder's list through the list query
 * (the Scripts page's, fetched fresh) and copies that entry's scripts to every other
 * Creator, showing the copy's counts; a failed share shows its error. `@/lib/relay` mocked, a fresh QueryClient.
 */
import { afterEach, beforeEach, describe, expect, it, vi, type Mock } from "vitest";
import { cleanup, fireEvent, screen, waitFor, within } from "@testing-library/react";

vi.mock("@/lib/relay", async (importOriginal) => {
  const mod = await importOriginal<typeof import("@/lib/relay")>();
  return { ...mod, relay: { ...mod.relay, get: vi.fn(), post: vi.fn() } };
});

import { AllModelsView } from "@/components/growth/AllModelsView";
import { savedRepliesQuery } from "@/hooks/useSavedReplies";
import { relay, type AccountMeta } from "@/lib/relay";
import { makeTestQueryClient, renderWithProviders } from "@/test-utils";

const get = relay.get as unknown as Mock;
const post = relay.post as unknown as Mock;
const ACCOUNTS = [{ id: "a", nickname: "Creator A" }, { id: "b", nickname: "Creator B" }] as AccountMeta[];
const OVERVIEW = {
  accounts: [{ id: "a", nickname: "a-nick" }, { id: "b", nickname: null }, { id: "c", nickname: "only here" }],
  sequences: [{ name: "Night", per_account: { b: 2 } }],
  tags: [{ name: "VIP", per_account: { a: 1 } }],
};
const LIST_B = [
  { id: 7, account_id: "b", title: "n1", text: "x", script_id: "Night", script_step: 1, tags: [] },
  { id: 8, account_id: "b", title: "n2", text: "y", script_id: "Night", script_step: 2, tags: ["VIP"] },
  { id: 9, account_id: "b", title: "loose", text: "z", tags: ["VIP"] },
];

beforeEach(() => {
  vi.clearAllMocks();
  get.mockImplementation((path: string) => {
    if (path === "/admin/saved-replies/overview") return Promise.resolve(OVERVIEW);
    if (path === "/admin/saved-replies?account_id=b") return Promise.resolve({ list: LIST_B });
    return Promise.reject(new Error(`unmocked GET ${path}`));
  });
});
afterEach(cleanup);

const shareNight = () => fireEvent.click(within(screen.getByRole("row", { name: /Night/ })).getByRole("button"));

describe("AllModelsView", () => {
  it("names each column off the roster, else the overview, else its id", async () => {
    renderWithProviders(<AllModelsView accounts={ACCOUNTS} />);
    await screen.findByRole("row", { name: /Night/ });
    const head = screen.getAllByRole("columnheader").map((h) => h.textContent);
    expect(head).toEqual(["Sequence", "Creator A", "Creator B", "only here", ""]);
  });

  it("shares a row's scripts from its first holder to all creators and shows what the copy did", async () => {
    post.mockResolvedValue({ copied: 4, skipped: 2, media_dropped: 0 });
    renderWithProviders(<AllModelsView accounts={ACCOUNTS} />);
    await screen.findByRole("row", { name: /Night/ });
    shareNight();
    await screen.findByLabelText("Share result");
    expect(post).toHaveBeenCalledWith("/admin/saved-replies/copy", {
      from_account_ids: ["b"], to_account_ids: [], all_creators: true, ids: [7, 8],
    });
    expect(screen.getByLabelText("Share result")).toHaveTextContent(/Shared “Night” to all creators.*4 scripts copied, 2 skipped/);
    // Once done the row is free again; a re-share copies the same ids.
    shareNight();
    await waitFor(() => expect(post).toHaveBeenCalledTimes(2));
    expect(post.mock.calls[1]).toEqual(post.mock.calls[0]);
  });

  it("shares the holder's list as it is now, never a cached (stale) one", async () => {
    post.mockResolvedValue({ copied: 2, skipped: 0, media_dropped: 0 });
    const queryClient = makeTestQueryClient();
    const { queryKey } = savedRepliesQuery("b");
    queryClient.setQueryDefaults(queryKey, { gcTime: Infinity });
    queryClient.setQueryData(queryKey, [LIST_B[0]]);  // the Scripts page's list, a step since added
    renderWithProviders(<AllModelsView accounts={ACCOUNTS} />, queryClient);
    await screen.findByRole("row", { name: /Night/ });
    shareNight();
    await screen.findByLabelText("Share result");
    expect(post.mock.calls[0][1].ids).toEqual([7, 8]);
  });

  it("a failed share shows its error and frees the row", async () => {
    post.mockRejectedValue(new Error("HTTP 422: no target creators"));
    renderWithProviders(<AllModelsView accounts={ACCOUNTS} />);
    await screen.findByRole("row", { name: /Night/ });
    shareNight();
    expect(await screen.findByRole("alert")).toHaveTextContent("HTTP 422: no target creators");
    expect(within(screen.getByRole("row", { name: /Night/ })).getByRole("button")).toBeEnabled();
  });
});
