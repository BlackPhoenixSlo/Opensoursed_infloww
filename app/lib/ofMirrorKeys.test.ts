import { describe, expect, it } from "vitest";
import { QueryClient } from "@tanstack/react-query";
import { afterChatWrite, afterProfileWrite, MIRROR, mirrorKey, mirrorUnder } from "./ofMirrorKeys";
import { mirrorQuery } from "./ofMirrorData";

/** Every key a model's page could have cached, for models A and B, and one nobody's write touches. */
const KEYS: Record<string, unknown[]> = {
  "mirror A path": [MIRROR, "A", "/api/of/v2/chats/1"],
  "mirror A pages": [MIRROR, "A", "/api/of/v2/posts", "pages"],
  "mirror A vault": [MIRROR, "A", "/api/of/v2/vault/lists"],
  "mirror B path": [MIRROR, "B", "/api/of/v2/chats/1"],
  chats: ["chats"],
  "chats A list": ["chats", "A", "all"],
  "messages A": ["messages", "A", 1],
  "messages B": ["messages", "B", 1],
  "of-me A": ["of-me", "A"],
  "of-me B": ["of-me", "B"],
  "of-settings sub": ["of-settings", "subscription", "promotions", "A", "x"],
  "of-settings settings": ["of-settings", "settings", "A"],
  unrelated: ["chat-folders", "A"],
};

const seeded = () => {
  const qc = new QueryClient();
  for (const k of Object.values(KEYS)) qc.setQueryData(k, 1);
  return qc;
};
const flipped = (qc: QueryClient) => Object.keys(KEYS).filter((n) => qc.getQueryState(KEYS[n])?.isInvalidated);

describe("ofMirrorKeys: which cached reads each refresh marks stale", () => {
  it.each<[string, (qc: QueryClient) => Promise<unknown>, string[]]>([
    ["afterChatWrite", (qc) => afterChatWrite(qc, "A"), ["mirror A path", "mirror A pages", "mirror A vault", "chats", "chats A list"]],
    ["afterProfileWrite", (qc) => afterProfileWrite(qc, "A"), ["of-me A", "of-settings sub", "of-settings settings"]],
    ["mirrorKey(acc)", (qc) => qc.invalidateQueries({ queryKey: mirrorKey("A") }), ["mirror A path", "mirror A pages", "mirror A vault"]],
    ["mirrorKey(acc, path)", (qc) => qc.invalidateQueries({ queryKey: mirrorKey("A", "/api/of/v2/posts") }), ["mirror A pages"]],
    ["mirrorUnder", (qc) => qc.invalidateQueries({ predicate: mirrorUnder("A", (p) => String(p).includes("/vault/")) }), ["mirror A vault"]],
  ])("%s", async (_, run, want) => {
    const qc = seeded();
    await run(qc);
    expect(flipped(qc)).toEqual(want);
  });
});

describe("mirrorKey", () => {
  it("is today's literal keys, and mirrorQuery's", () => {
    expect(mirrorKey("A")).toEqual(["of-mirror-data", "A"]);
    expect(mirrorKey("A", "/p")).toEqual(mirrorQuery("A", "/p", true).queryKey);
  });
});
