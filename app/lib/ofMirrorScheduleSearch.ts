"use client";


import { useEffect, type RefObject } from "react";
import { useQuery } from "@tanstack/react-query";
import { useScope } from "@/contexts/ScopeContext";
import { mirrorPageOfPath } from "@/lib/of-mirror-route";
import { ofMeQuery } from "@/lib/ofMirrorIdentity";
import { bindFeedSearch, feedSearchHandlers } from "@/lib/ofMirrorPost";

export const PAGE = "streaming/dashboard/create";

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
