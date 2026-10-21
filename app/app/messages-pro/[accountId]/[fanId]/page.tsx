"use client";

/**
 * /messages-pro/[accountId]/[fanId] — a Deep link into the one Messages Pro
 * tree (ADR-0002; was /chat/…, which redirects). It renders no Thread of its
 * own: it parses the fan id and hands it to `MessagesPro`, which arrives with
 * that Fan selected, its Thread open and Fan insights closed. The bell, the
 * Buys & tips rail, the money toasts and the Message dashboard rows link here.
 */

import { use, useMemo } from "react";

import { MessagesPro } from "@/components/chat/MessagesPro";
import { fanIdFromParam } from "@/lib/fanId";

export default function DeepLinkPage({
  params,
}: { params: Promise<{ accountId: string; fanId: string }> }) {
  const { accountId, fanId: fanIdStr } = use(params);
  // Keep the id EXACTLY as the URL spelled it. This was `Number(fanIdStr)`,
  // which silently corrupted every Fansly fan: a snowflake exceeds JS's 2^53,
  // so `Number("900604711209099264")` is 900604711209099300 — a fan id that
  // does not exist. The popout then asked the relay for that ghost, which is
  // why "↗ pop out" landed on an empty thread reading "Couldn't refresh:
  // observe-only" while the inbox row it was opened from worked fine.
  //
  // The inbox never had the bug because it passes `chat.withUser.id` straight
  // through from JSON, and the Fansly shim emits ids as STRINGS for exactly
  // this reason. Parsing here was the one place that re-introduced the loss,
  // so the popout's query keys ("messages"/"of-user"/"fan") also disagreed
  // with the inbox's and split the cache. `fanIdFromParam` keeps OF's small
  // numeric ids as numbers (their keys stay identical) and leaves anything
  // too large for float64 as the exact string.
  const fanId = useMemo(() => fanIdFromParam(fanIdStr), [fanIdStr]);
  const deepLink = useMemo(
    () => (fanId == null ? null : { accountId, fanId }),
    [accountId, fanId],
  );

  // Guard AFTER every hook: an early return above any hook makes the hook
  // count differ between renders (React #310) if fanId turns valid in place.
  if (deepLink == null) {
    return (
      <div className="grid place-items-center h-chat text-sm text-err">
        Invalid fan id: {fanIdStr}
      </div>
    );
  }

  // Keyed by the link so following another Deep link re-arrives instead of
  // keeping the previous link's selection.
  return <MessagesPro key={`${accountId}:${fanIdStr}`} deepLink={deepLink} />;
}
