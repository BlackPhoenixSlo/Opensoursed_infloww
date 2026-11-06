/**
 * useAccountAvatar — a Creator's picture is only ever its own.
 *
 * On AE the Manage creators table showed one Creator's (Wren's) OF avatar on
 * every row. A `/users/me` body names whose profile it is (`id` = the OF user
 * id = our account id), so a row keeps a body only when that id is its own:
 * any other body (a shared cache entry, a fallback to the active account)
 * paints the initial instead of someone else's face. The table and the
 * dashboard cards read one entry per Creator (`["of-profile", id]`), so one
 * request serves both.
 */
import { afterEach, beforeEach, describe, expect, it, vi, type Mock } from "vitest";
import { cleanup, renderHook, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

vi.mock("@/lib/relay", () => ({ relay: { get: vi.fn() } }));

import { pickAvatarUrl, useAccountAvatar } from "@/hooks/useAccountAvatar";
import { useAccountProfile } from "@/hooks/useStats";
import { relay } from "@/lib/relay";
const relayGet = relay.get as unknown as Mock;

const WREN = "80000780";
const OTHER = "800000781";
const me = (id: string) => ({
  id: Number(id), username: `u${id}`,
  avatar: `https://public.onlyfans.com/files/x/${id}/avatar.jpg`,
  avatarThumbs: { c50: `https://thumbs.onlyfans.com/50/${id}/avatar.jpg` },
});

let client: QueryClient;
function wrapper({ children }: { children: ReactNode }) {
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}
beforeEach(() => {
  client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  relayGet.mockReset();
});
afterEach(() => { cleanup(); });

describe("useAccountAvatar", () => {
  it.each([
    ["own body", OTHER, me(OTHER), `https://thumbs.onlyfans.com/50/${OTHER}/avatar.jpg`],
    ["another Creator's body (Wren's)", OTHER, me(WREN), null],
    ["body without an id", OTHER, { avatarThumbs: { c50: "https://x/a.jpg" } }, null],
  ])("%s → %s", async (_name, accountId, body, want) => {
    relayGet.mockResolvedValue(body);
    const { result } = renderHook(() => useAccountAvatar(accountId), { wrapper });
    await waitFor(() => expect(result.current.isFetched).toBe(true));
    expect(pickAvatarUrl(result.current.data)).toBe(want);
    expect(relayGet).toHaveBeenCalledWith("/api/of/v2/users/me", expect.objectContaining({ accountId }), expect.any(AbortSignal));
  });

  it("every row gets its own picture, even when the relay answers one Creator for all", async () => {
    relayGet.mockResolvedValue(me(WREN));
    const ids = [WREN, OTHER, "800000782"];
    const { result } = renderHook(() => ids.map((id) => useAccountAvatar(id)), { wrapper });
    await waitFor(() => expect(result.current.every((q) => q.isFetched)).toBe(true));
    expect(result.current.map((q) => pickAvatarUrl(q.data))).toEqual([
      `https://thumbs.onlyfans.com/50/${WREN}/avatar.jpg`, null, null,
    ]);
  });

  it("shares the dashboard card's one users/me read per Creator", async () => {
    relayGet.mockResolvedValue(me(OTHER));
    const { result } = renderHook(
      () => ({ avatar: useAccountAvatar(OTHER), profile: useAccountProfile(OTHER) }), { wrapper });
    await waitFor(() => expect(result.current.avatar.isFetched && result.current.profile.isFetched).toBe(true));
    expect(relayGet).toHaveBeenCalledTimes(1);
    expect(result.current.profile.data?.username).toBe(`u${OTHER}`);
  });
});
