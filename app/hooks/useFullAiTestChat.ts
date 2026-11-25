"use client";


import { useQueryClient } from "@tanstack/react-query";
import { useCallback, useEffect, useReducer, useRef, type Dispatch } from "react";

import {
  buildSettlePayload, buildTurnPayload, canSettle, initTestChat, SIDE_OF, sessionTurns, testChatReducer, UI_SIDES,
  type Describing, type FanPhoto, type Outcome, type PendingTurn, type SessionBody, type SettlePayload, type TestChatAction, type TestChatState,
  type TurnPayload, type TurnResponse, type UiSide,
} from "@/components/automations/fullAiTestChat";
import { useFullAiConfig } from "@/hooks/useFullAiConfig";
import { fullAiTodayKey } from "@/hooks/useFullAiToday";
import { relay, RelayError } from "@/lib/relay";

export const newPairId = () => `${Date.now().toString(36)}${Math.random().toString(36).slice(2, 10)}`;

const message = (e: unknown) => (e instanceof Error && e.message) || "Request failed";
const SETTLE_ERRORS: Record<string, string> = {
  not_this_session: "This chat was restarted. Tap New chat.",
  not_a_priced_offer: "Nothing to pay for on this message.",
  already_owned: "Already bought in this chat.",
};

async function postTurn(
  accountId: string, ui: UiSide, body: TurnPayload,
  dispatch: Dispatch<TestChatAction>, refreshToday: () => void,
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
  } finally {
    refreshToday();
  }
}

async function postPhoto(accountId: string, pair: string, d: Describing, dispatch: Dispatch<TestChatAction>) {
  try {
    const photo = await relay.post<FanPhoto>("/admin/full-ai/test/photo",
      { account_id: accountId, image: d.image, text: d.text, pair }, { accountId });
    dispatch({ type: "photoDescribed", pair, photo });
  } catch (e) {
    dispatch({ type: "photoFailed", pair, error: message(e) });
  }
}

function storedOutcome(e: unknown): Outcome | null {
  if (!(e instanceof RelayError && e.status === 409)) return null;
  const o = (e.body as { outcome?: unknown } | null)?.outcome;
  return o === "bought" || o === "declined" ? o : null;
}

async function postSettle(ui: UiSide, body: SettlePayload, dispatch: Dispatch<TestChatAction>) {
  const { pair, row_id: rowId } = body;
  try {
    const r = await relay.post<{ outcome: Outcome }>("/admin/full-ai/test/settle", body, { accountId: body.account_id });
    dispatch({ type: "settled", pair, side: ui, rowId, outcome: r.outcome });
  } catch (e) {
    const stored = storedOutcome(e);
    dispatch(stored ? { type: "settled", pair, side: ui, rowId, outcome: stored }
      : { type: "settleFailed", pair, side: ui, rowId, error: SETTLE_ERRORS[message(e)] ?? message(e) });
  }
}

function startSettle(
  state: TestChatState, accountId: string, ui: UiSide, rowId: number, outcome: Outcome, dispatch: Dispatch<TestChatAction>,
) {
  const turn = state.sides[ui].turns.find((t) => t.result.row_id === rowId);
  if (!turn || !canSettle(turn)) return;
  dispatch({ type: "settle", side: ui, rowId, outcome });
  void postSettle(ui, buildSettlePayload(state, ui, rowId, outcome, accountId), dispatch);
}

export function useFullAiTestChat(accountId: string) {
  const [state, dispatch] = useReducer(testChatReducer, undefined, () => initTestChat(newPairId()));
  const posted = useRef(new WeakSet<PendingTurn | Describing>());
  const { L, R } = state.sides;
  const qc = useQueryClient();

  useEffect(() => {
    const d = state.describing;
    if (!d || posted.current.has(d)) return;
    posted.current.add(d);
    void postPhoto(accountId, state.pair, d, dispatch);
  }, [accountId, state.describing, state.pair]);

  useEffect(() => {
    for (const ui of UI_SIDES) {
      const p = state.sides[ui].pending;
      if (!p?.inFlight || posted.current.has(p)) continue;
      const body = buildTurnPayload(state, ui)!;
      posted.current.add(p);
      void postTurn(accountId, ui, body, dispatch, () => void qc.invalidateQueries({ queryKey: fullAiTodayKey(accountId) }));
    }
  }, [accountId, state, qc]);

  useEffect(() => {
    const timers = UI_SIDES.flatMap((ui) => {
      const at = ui === "L" ? L.revealAt : R.revealAt;
      if (at === null) return [];
      return [setTimeout(() => dispatch({ type: "reveal", side: ui, now: Date.now() }), Math.max(0, at - Date.now()))];
    });
    return () => timers.forEach(clearTimeout);
  }, [L.revealAt, R.revealAt]);

  const edit = useCallback((text: string) => dispatch({ type: "edit", text }), []);
  const attach = useCallback((image: string) => dispatch({ type: "attach", image }), []);
  const detach = useCallback(() => dispatch({ type: "detach" }), []);
  const replyTo = useCallback((n: number) => dispatch({ type: "replyTo", n }), []);
  const clearReply = useCallback(() => dispatch({ type: "clearReply" }), []);
  const send = useCallback(() => dispatch({ type: "send" }), []);
  const retry = useCallback((side: UiSide) => dispatch({ type: "retry", side }), []);
  const toggleSkip = useCallback(() => dispatch({ type: "toggleSkip" }), []);
  const newChat = useCallback(() => dispatch({ type: "newChat", pair: newPairId() }), []);
  const settle = (ui: UiSide, rowId: number, outcome: Outcome) => startSettle(state, accountId, ui, rowId, outcome, dispatch);
  const config = useFullAiConfig(accountId, state, dispatch);
  return { state, config, edit, attach, detach, replyTo, clearReply, send, retry, toggleSkip, newChat, settle };
}

export type FullAiTestChatApi = ReturnType<typeof useFullAiTestChat>;
