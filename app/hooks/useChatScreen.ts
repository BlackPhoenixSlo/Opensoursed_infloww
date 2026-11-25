import { useQueryClient, type QueryKey, type QueryState } from "@tanstack/react-query";
import { useMemo, useRef } from "react";

import { preloadImg } from "@/lib/imgBlobs";
import { proxyImage } from "@/lib/mediaUrl";
import { prefetchScreenBundle } from "@/lib/relay";
import { useScreen } from "@/lib/screenBundle";
import { screenKey, type ChatLack, type Screen } from "@/lib/screenKey";
import { SENSITIVE_WORDS_KEY } from "@/lib/sensitiveWords";
import { resolveShareToken } from "@/lib/shareToken";

const LISTS: ReadonlyArray<[ChatLack, (accountId: string) => QueryKey, number]> = [
  ["savedReplies", (a) => ["saved-replies", a], 5 * 60_000],
  ["sensitiveWords", (a) => [...SENSITIVE_WORDS_KEY, a], 60_000],
];

export function chatLacks(
  state: (key: QueryKey) => Pick<QueryState, "data" | "dataUpdatedAt" | "isInvalidated"> | undefined,
  accountId: string, now: number,
): ChatLack[] {
  return LISTS.filter(([, key, stale]) => {
    const s = state(key(accountId));
    return !s || s.data === undefined || s.isInvalidated || now - s.dataUpdatedAt > stale;
  }).map(([lack]) => lack);
}

export function useChatScreen(accountId: string | null, fanId: number | string | null): void {
  const qc = useQueryClient();
  const thread = accountId && fanId != null ? `${accountId}|${fanId}` : null;
  const screen = useMemo<Screen | null>(() => (accountId && fanId != null && !resolveShareToken() ? {
    kind: "chat", accountId, fanId: String(fanId),
    lacks: chatLacks((k) => qc.getQueryState(k), accountId, Date.now()),
  } : null),
  // eslint-disable-next-line react-hooks/exhaustive-deps
  [thread]);
  const started = useRef<string | null>(null);
  if (screen && accountId && typeof window !== "undefined" && started.current !== screenKey(screen)) {
    started.current = screenKey(screen);
    void prefetchScreenBundle(screen).then((b) => {
      const thumbs = (b as { thumbs?: unknown } | null)?.thumbs;
      if (Array.isArray(thumbs)) for (const u of thumbs) if (typeof u === "string") preloadImg(proxyImage(u, accountId));
    });
  }
  useScreen(screen);
}
