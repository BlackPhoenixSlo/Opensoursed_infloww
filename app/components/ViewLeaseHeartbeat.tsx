"use client";

/**
 * ViewLeaseHeartbeat — this tab's View lease (ADR-0031, phase-01), mounted once in the root layout inside the auth
 * gate, so it runs in every signed-in tab on any page. It posts the lease (`lib/viewLease.ts`) every
 * VIEW_LEASE_RENEW_MS and at once when `shouldPostNow` says so (`lib/viewLeaseState.ts`). The first post of a mount
 * carries `opened: true`, sent once the event stream is open or after OPENED_WAIT_MS: the Relay's App-open warm of
 * every Creator this Employee can access. A soft navigation keeps the mount, so it is not an open. The scope
 * provider's selected Creator is the first lease source: selecting a Creator posts at once (its Select refresh). The
 * on-screen holds (`holdLease` / `useViewLease` / `useOnScreenLease`: the open chat, the rail's, the strip's and OF
 * Manager's column's visible rows) arrive through `onLeaseHolds`. A hidden tab, or one in Idle mode (useIdleMode),
 * renews nothing, so its lease lapses within the Relay's TTL; shown again or back from Idle, it posts at once. A load
 * opened hidden or idle still sends its opening post (the App-open warm), leasing nothing. Hidden and Idle come from
 * react-query's focusManager, which useIdleMode turns off for Idle mode: not focused while the page is visible is Idle.
 * Renders nothing; only dispatches and posts.
 */

import { useCallback, useEffect, useReducer, useRef } from "react";
import { focusManager } from "@tanstack/react-query";

import { useScope } from "@/contexts/ScopeContext";
import { eventBus } from "@/lib/events";
import { onLeaseHolds, OPENED_WAIT_MS, postLease, tabId, VIEW_LEASE_RENEW_MS } from "@/lib/viewLease";
import {
  canPost, INITIAL_LEASE, leaseBody, SELECTED_SOURCE, shouldPostNow, viewLeaseReducer,
} from "@/lib/viewLeaseState";

export function ViewLeaseHeartbeat() {
  const { scope } = useScope();
  const [state, dispatch] = useReducer(viewLeaseReducer, INITIAL_LEASE);
  const stateRef = useRef(state);
  const prevRef = useRef(INITIAL_LEASE);

  const selected = scope.kind === "model" ? scope.accountId : null;
  useEffect(() => {
    dispatch(selected ? { type: "Hold", source: SELECTED_SOURCE, accountIds: [selected] }
      : { type: "Release", source: SELECTED_SOURCE });
  }, [selected]);

  useEffect(() => onLeaseHolds((source, accountIds) => dispatch(accountIds.length
    ? { type: "Hold", source, accountIds } : { type: "Release", source })), []);

  useEffect(() => {
    const read = () => {
      const hidden = document.visibilityState === "hidden";
      dispatch({ type: "Visibility", hidden });
      dispatch({ type: "Idle", idle: !hidden && !focusManager.isFocused() });
    };
    read();
    return focusManager.subscribe(read);
  }, []);

  useEffect(() => {
    const t = setTimeout(() => dispatch({ type: "Opened" }), OPENED_WAIT_MS);
    const off = eventBus.onStateChange((connected) => { if (connected) dispatch({ type: "Opened" }); });
    return () => { clearTimeout(t); off(); };
  }, []);

  const post = useCallback(() => {
    const s = stateRef.current;
    if (!canPost(s)) return;
    const body = leaseBody(s, tabId());
    postLease(body).then(() => dispatch({ type: "Posted", opened: body.opened }), () => { /* the next tick retries */ });
  }, []);

  useEffect(() => {
    stateRef.current = state;
    const prev = prevRef.current;
    prevRef.current = state;
    if (shouldPostNow(prev, state)) post();
  }, [state, post]);

  useEffect(() => {
    const id = setInterval(post, VIEW_LEASE_RENEW_MS);
    return () => clearInterval(id);
  }, [post]);

  return null;
}
