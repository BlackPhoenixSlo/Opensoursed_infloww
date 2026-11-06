import { describe, expect, it } from "vitest";

import { chatLacks } from "./useChatScreen";

const NOW = 1_000_000_000;
type S = { data: unknown; dataUpdatedAt: number; isInvalidated: boolean } | undefined;
const at = (m: Record<string, S>) => (k: readonly unknown[]) => m[String(k[0])];

describe("chatLacks", () => {
  it.each<[string, Record<string, S>, string[]]>([
    ["nothing cached", {}, ["savedReplies", "sensitiveWords"]],
    ["both fresh", {
      "saved-replies": { data: {}, dataUpdatedAt: NOW - 1000, isInvalidated: false },
      "sensitive-words": { data: {}, dataUpdatedAt: NOW - 1000, isInvalidated: false },
    }, []],
    ["words past 60 s", {
      "saved-replies": { data: {}, dataUpdatedAt: NOW - 61_000, isInvalidated: false },
      "sensitive-words": { data: {}, dataUpdatedAt: NOW - 61_000, isInvalidated: false },
    }, ["sensitiveWords"]],
    ["replies invalidated", {
      "saved-replies": { data: {}, dataUpdatedAt: NOW, isInvalidated: true },
      "sensitive-words": { data: {}, dataUpdatedAt: NOW, isInvalidated: false },
    }, ["savedReplies"]],
    ["errored, no data", {
      "saved-replies": { data: undefined, dataUpdatedAt: 0, isInvalidated: false },
      "sensitive-words": { data: {}, dataUpdatedAt: NOW, isInvalidated: false },
    }, ["savedReplies"]],
  ])("%s", (_n, m, want) => {
    expect(chatLacks(at(m), "A1", NOW)).toEqual(want);
  });
});
