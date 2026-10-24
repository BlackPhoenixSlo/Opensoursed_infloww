/**
 * The local seed's structural sharing: a live DM moves one row to the top,
 * and every other row must keep its object (FanRow's memo bails on it). The
 * default index-wise sharing gave every shifted row a new object.
 */
import { describe, expect, it } from "vitest";

import type { OFChatItem } from "@/lib/relay";
import { shareSeedList } from "./useRecentChatsLocal";

const row = (fan: number, text = "hi") => ({
  withUser: { id: fan, name: `Fan ${fan}` },
  lastMessage: { id: fan, text, fromUser: { id: fan } },
  __accountId: "7",
}) as unknown as OFChatItem;
const resp = (list: OFChatItem[]) => ({ list, source: "local" });
const fresh = (l: OFChatItem[]) => JSON.parse(JSON.stringify(l)) as OFChatItem[];

describe("shareSeedList", () => {
  it("a row moved to the top keeps every other row's object", () => {
    const prev = resp([row(1), row(2), row(3), row(4)]);
    // As the refetch hands it: all new objects, fan 3 now on top with a new message.
    const next = resp(fresh([row(3, "new"), row(1), row(2), row(4)]));
    const out = shareSeedList(prev, next) as ReturnType<typeof resp>;
    expect(out.list.map((c) => c.withUser.id)).toEqual([3, 1, 2, 4]);
    expect(out.list[1]).toBe(prev.list[0]);
    expect(out.list[2]).toBe(prev.list[1]);
    expect(out.list[3]).toBe(prev.list[3]);
    expect(out.list[0]).not.toBe(prev.list[2]);
    expect(out.list[0].lastMessage?.text).toBe("new");
  });

  it("an equal answer returns the previous data itself", () => {
    const prev = resp([row(1), row(2)]);
    expect(shareSeedList(prev, resp(fresh(prev.list)))).toBe(prev);
  });
});
