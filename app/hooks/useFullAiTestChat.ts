"use client";

/**
 * useFullAiTestChat — the Test chat's requests and reveal timers around the pure `fullAiTestChat` reducer. Each side's
 * owed request (`pending`, in flight) is POSTed once to `/admin/full-ai/test/turn` with `account_id` and the reducer's
 * `{pair, side, n, text}`; the two sides go as two parallel requests. A 409 (that Turn number is taken or out of step)
 * reloads the session (`GET /admin/full-ai/test/session`) and replaces that side's thread. The server never waits:
 * a reply's `wait_s` is a timer here, skipped with skip-wait. The same reducer holds the draft config; its requests are
 * `useFullAiConfig`, returned as `config` (the settings column's handlers).
 */

import { useCallback, useEffect, useReducer, useRef, type Dispatch } from "react";

import {
  buildTurnPayload, initTestChat, SIDE_OF, sessionTurns, testChatReducer, UI_SIDES,
  type PendingTurn, type SessionBody, type TestChatAction, type TurnPayload, type TurnResponse, type UiSide,
} from "@/components/automations/fullAiTestChat";
import { useFullAiConfig } from "@/hooks/useFullAiConfig";
import { relay, RelayError } from "@/lib/relay";

/** A fresh pair id: the two sessions of one New chat. Not crypto.randomUUID, which a phone on plain-http LAN lacks. */
export const newPairId = () => `${Date.now().toString(36)}${Math.random().toString(36).slice(2, 10)}`;

const message = (e: unknown) => (e instanceof Error && e.message) || "Request failed";

async function postTurn(
  accountId: string, ui: UiSide, body: TurnPayload,
  dispatch: Dispatch<TestChatAction>,
) {
  const { pair, n } = body;
  try {
    const result = await relay.post<TurnResponse>("/admin/full-ai/test/turn", { account_id: accountId, ...body }, { accountId });
    dispatch({ type: "turnResult", pair, side: ui, n, result, now: Date.now() });
  } catch (e) {
    if (!(e instanceof RelayError && e.status === 409)) {
      dispatch({ type: "turnFailed", pair, side: ui, n, error: message(e) });
      return;
    }
    try {
      const q = `account_id=${encodeURIComponent(accountId)}&pair=${encodeURIComponent(pair)}`;
      const session = await relay.get<SessionBody>(`/admin/full-ai/test/session?${q}`, { accountId });
      dispatch({ type: "sessionLoaded", pair, side: ui, turns: sessionTurns(session, SIDE_OF[ui]) });
    } catch (e2) {
      dispatch({ type: "turnFailed", pair, side: ui, n, error: message(e2) });
    }
  }
}

export function useFullAiTestChat(accountId: string) {
  const [state, dispatch] = useReducer(testChatReducer, undefined, () => initTestChat(newPairId()));
  // Each send / retry makes a new `pending` object; one POST per object, whatever re-runs the effect.
  const posted = useRef(new WeakSet<PendingTurn>());
  const { L, R } = state.sides;

  useEffect(() => {
    for (const ui of UI_SIDES) {
      const p = state.sides[ui].pending;
      if (!p?.inFlight || posted.current.has(p)) continue;
      const body = buildTurnPayload(state, ui)!; // non-null: p is set
      posted.current.add(p);
      void postTurn(accountId, ui, body, dispatch);
    }
  }, [accountId, state]);

  useEffect(() => {
    const timers = UI_SIDES.flatMap((ui) => {
      const at = ui === "L" ? L.revealAt : R.revealAt;
      if (at === null) return [];
      return [setTimeout(() => dispatch({ type: "reveal", side: ui, now: Date.now() }), Math.max(0, at - Date.now()))];
    });
    return () => timers.forEach(clearTimeout);
  }, [L.revealAt, R.revealAt]);

  const edit = useCallback((text: string) => dispatch({ type: "edit", text }), []);
  const send = useCallback(() => dispatch({ type: "send" }), []);
  const retry = useCallback((side: UiSide) => dispatch({ type: "retry", side }), []);
  const toggleSkip = useCallback(() => dispatch({ type: "toggleSkip" }), []);
  const newChat = useCallback(() => dispatch({ type: "newChat", pair: newPairId() }), []);
  const config = useFullAiConfig(accountId, state, dispatch);
  return { state, config, edit, send, retry, toggleSkip, newChat };
}

export type FullAiTestChatApi = ReturnType<typeof useFullAiTestChat>;
