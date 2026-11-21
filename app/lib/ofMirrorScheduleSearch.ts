"use client";

/**
 * ticket 84: the stream schedule form's right column "Search users or posts" box and its Search button
 * (streaming/dashboard/create), as on Home and New post (bindFeedSearch): rows listed as the operator types, each a link
 * to its profile; Enter and the Search button run it at once and send nothing else (bindWrites sends only the schedule
 * form's own submit). All Creators: the Select-model note and no search GET. Both keep their Not-yet title (D1: it drops
 * on a Live-proof pass); the Search button is off while the box is empty, as OF's.
 */

import { useEffect, type RefObject } from "react";
import { useQuery } from "@tanstack/react-query";
import { useScope } from "@/contexts/ScopeContext";
import { mirrorPageOfPath } from "@/lib/of-mirror-route";
import { ofMeQuery } from "@/lib/ofMirrorIdentity";
import { bindFeedSearch, feedSearchHandlers } from "@/lib/ofMirrorPost";

export const PAGE = "streaming/dashboard/create";

/** The schedule form in the frame: its search, on every load. */
export function useOfScheduleSearch(frameRef: RefObject<HTMLIFrameElement | null>, src: string): void {
  const { accountId } = useScope();
  const on = mirrorPageOfPath(src) === PAGE;
  const meId = useQuery(ofMeQuery(on ? accountId : null)).data?.id ?? undefined;
  useEffect(() => {
    const frame = frameRef.current;
    if (!frame || !on) return;
    let unbind: (() => void) | undefined;
    const handlers = accountId ? feedSearchHandlers(accountId) : null;
    const bind = () => {
      unbind?.();
      const doc = frame.contentDocument;
      unbind = doc?.body ? bindFeedSearch(doc, { handlers, meId }) : undefined;
    };
    if (frame.contentDocument?.readyState === "complete") bind();
    frame.addEventListener("load", bind);
    return () => {
      frame.removeEventListener("load", bind);
      unbind?.();
    };
  }, [frameRef, on, accountId, meId]);
}
