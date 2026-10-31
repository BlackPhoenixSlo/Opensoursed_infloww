/**
 * massFanOut — one round of the Mass composer's all-models broadcast, pure
 * but for the injected `post` (useMassSend's relay POST; slop's node run its
 * fetch): the same text-only body (massMessageReducer `buildMassBody`) from
 * each target in turn (compose/fanOut `fanOutTargets`: the included models
 * without a success), its progress and results dispatched to the form.
 * Resolves to the round's results.
 */

import type { Dispatch } from "react";

import { fanOutTargets, runFanOut, type FanOutResult } from "./fanOut";
import { buildMassBody, type MassAction, type MassForm } from "./massMessageReducer";

export async function massFanOutRound(
  form: MassForm,
  /** The included models, chip order. */
  includedIds: string[],
  online: boolean,
  post: (accountId: string, body: Record<string, unknown>) => Promise<unknown>,
  dispatch: Dispatch<MassAction>,
): Promise<FanOutResult[]> {
  const targets = fanOutTargets(form.results, includedIds);
  const body = buildMassBody(form, online);
  const round = await runFanOut(targets, (aid) => post(aid, body), (p) => dispatch({ type: "progress", ...p }));
  dispatch({ type: "results", v: round });
  return round;
}
