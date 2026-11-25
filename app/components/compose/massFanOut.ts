import type { Dispatch } from "react";

import { fanOutTargets, runFanOut, type FanOutResult } from "./fanOut";
import { buildMassBody, type MassAction, type MassForm } from "./massMessageReducer";

export async function massFanOutRound(
  form: MassForm,
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
