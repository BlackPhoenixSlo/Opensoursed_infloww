"use client";


import { useCallback, useEffect, useReducer, useRef } from "react";
import { focusManager } from "@tanstack/react-query";

import { useScope } from "@/contexts/ScopeContext";
import { eventBus } from "@/lib/events";
import { holdLease, onLeaseHolds, OPENED_WAIT_MS, postLease, tabId, VIEW_LEASE_RENEW_MS } from "@/lib/viewLease";
import {
  canPost, INITIAL_LEASE, leaseBody, SELECTED_SOURCE, shouldPostNow, viewLeaseReducer,
} from "@/lib/viewLeaseState";

export function ViewLeaseHeartbeat() {
  const { scope } = useScope();
  const [state, dispatch] = useReducer(viewLeaseReducer, INITIAL_LEASE);
  const stateRef = useRef(state);
  const prevRef = useRef(INITIAL_LEASE);

  const selected = scope.kind === "model" ? scope.accountId : null;
  useEffect(() => (selected ? holdLease(SELECTED_SOURCE, [selected]) : undefined), [selected]);

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
    postLease(body).then(() => dispatch({ type: "Posted", opened: body.opened }), () => { });
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
