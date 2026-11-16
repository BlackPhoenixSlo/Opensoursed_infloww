import type { ReactNode } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, renderHook, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { useAllChatFolders, useChatFolders, type ChatFolder } from "./useChatFolders";
import { mirrorQuery, USER_LISTS } from "@/lib/ofMirrorDataQueries";
import { afterListWrite } from "@/lib/ofMirrorKeys";
import { applyData } from "@/lib/ofMirrorData";
import { load, shown } from "@/lib/ofMirrorData.fixtures";
import { relay } from "@/lib/relay";

vi.mock("@/lib/relay", () => ({ relay: { get: vi.fn() } }));
afterEach(() => { cleanup(); vi.resetAllMocks(); });

const makeRows = (count: number): ChatFolder[] => Array.from({ length: count }, (_, id) => ({
  id, name: id === 131 ? "Late list" : `List ${id}`, canAddUsers: true,
  isPinnedToChat: id === 131, usersCount: 0,
}));
const client = () => new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: 0 } } });
function serve(read: () => ChatFolder[]) {
  vi.mocked(relay.get).mockImplementation(async (path) => {
    const offset = Number(new URL(path, "https://relay.test").searchParams.get("offset"));
    const all = read();
    return { list: all.slice(offset, offset + 50), hasMore: offset + 50 < all.length };
  });
}

describe("every list in Collections and Messages", () => {
  it("renders Late list from page 3 in Collections and keeps its write permissions", async () => {
    const all = makeRows(132);
    serve(() => all);
    const qc = client();
    // A persisted result from the old app must not mask the subsequent pages.
    qc.setQueryData(["of-mirror-data", "account-a", USER_LISTS], { list: all.slice(0, 50) });
    const result = await qc.fetchQuery(mirrorQuery<{ list: ChatFolder[] }>("account-a", USER_LISTS, true));
    expect(result.list).toEqual(all);
    const doc = load("collections/index");
    applyData(doc, "collections/index", { userLists: result.list });
    expect(shown(doc, '.b-user-lists__list a.b-rows-lists__item__text')).toHaveLength(132);
    expect(doc.querySelector('a[href="/of-manager/collections/user-lists/list?list=131"]')?.textContent).toContain("Late list");
    expect(result.list.at(-1)?.canAddUsers).toBe(true);
    expect(vi.mocked(relay.get).mock.calls.map(([path, scope]) => [path, scope])).toEqual([
      [USER_LISTS, { accountId: "account-a" }],
      [`${USER_LISTS}&offset=50`, { accountId: "account-a" }],
      [`${USER_LISTS}&offset=100`, { accountId: "account-a" }],
    ]);
    qc.clear();
  });

  it("shares all 132 folders between the picker and pinned chips, then refreshes after creation", async () => {
    let all = makeRows(132);
    serve(() => all);
    const qc = client();
    qc.setQueryData(["chat-folders", "account-a", "all"], all.slice(0, 50));
    const wrapper = ({ children }: { children: ReactNode }) => <QueryClientProvider client={qc}>{children}</QueryClientProvider>;
    const { result } = renderHook(() => ({ all: useAllChatFolders("account-a"), pinned: useChatFolders("account-a") }), { wrapper });
    await waitFor(() => expect(result.current.all.data).toHaveLength(132));
    expect(result.current.pinned.data).toEqual([all[131]]);
    expect(result.current.all.data?.[0].name).toBe("Late list");
    expect(relay.get).toHaveBeenCalledTimes(3);
    all = [...all, { id: 132, name: "New list", canAddUsers: true }];
    await afterListWrite(qc, "account-a");
    await waitFor(() => expect(result.current.all.data).toHaveLength(133));
    expect(relay.get).toHaveBeenCalledTimes(6);
    qc.clear();
  });

  it("does not fetch in unified mode without a selected account", () => {
    const qc = client();
    const wrapper = ({ children }: { children: ReactNode }) => <QueryClientProvider client={qc}>{children}</QueryClientProvider>;
    renderHook(() => useAllChatFolders(null), { wrapper });
    expect(relay.get).not.toHaveBeenCalled();
    qc.clear();
  });
});
