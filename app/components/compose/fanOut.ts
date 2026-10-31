/**
 * fanOut — the all-models fan-out the composers share (PostComposer,
 * MassMessageComposer; PremadeComposer uses the runner): one result type,
 * one runner, one send-lifecycle slice of form state, one set of rules.
 *
 *   • `runFanOut` sends to each target in turn and never throws: every target
 *     gets a `FanOutResult`, and `onProgress` a `{ done, total }` after each.
 *   • A round's results merge into the form's by account, so `results` is every
 *     model's latest outcome and `summarizeFanOut` counts all outstanding
 *     failures, not only the last round's.
 *   • A retry goes only to the included models without a success
 *     (`fanOutTargets`): the first send to all, a retry to the failed (and any
 *     newly included) ones.
 *   • While a round is in flight, and once any model took it, the content is
 *     locked (`fanOutLocked`): the composer's reducer refuses every content
 *     action, so a retry sends the SAME content to the failed models (an edit
 *     would reach only them, the posted ones keeping the old content; the body
 *     of a round in flight is already built). `discardResults` (Start over) is
 *     the explicit way out, refused while a round is in flight (its results
 *     would land on nothing, the successes before it forgotten, so the next
 *     send would repeat them); closing the modal drops the form too. Clearing
 *     instead of locking would re-send to the models that already took it.
 *   • Leaving all-models clears the results (the composers' `setAllModels`).
 */

/** One model's outcome in an all-models fan-out. */
export interface FanOutResult {
  accountId: string;
  ok: boolean;
  error?: string;
}

export interface FanOutProgress {
  done: number;
  total: number;
}

/** The send-lifecycle slice of a composer form. */
export interface FanOutState {
  /** A fan-out in flight: models sent so far of `total`. */
  progress: FanOutProgress | null;
  /** Every model's latest outcome in this composer (a retry's merged in). */
  results: FanOutResult[] | null;
}

export type FanOutAction =
  | ({ type: "progress" } & FanOutProgress)
  /** A fan-out round finished: merged by account, progress clears. */
  | { type: "results"; v: FanOutResult[] }
  /** Start over: drop the results, which unlocks the content (refused while
   *  a round is in flight). */
  | { type: "discardResults" };

export function initFanOut(): FanOutState {
  return { progress: null, results: null };
}

export function fanOutReducer<S extends FanOutState>(s: S, a: FanOutAction): S {
  switch (a.type) {
    case "progress":
      return { ...s, progress: { done: a.done, total: a.total } };
    case "results": {
      const fresh = new Set(a.v.map((r) => r.accountId));
      return { ...s, results: [...(s.results ?? []).filter((r) => !fresh.has(r.accountId)), ...a.v], progress: null };
    }
    case "discardResults":
      return s.progress !== null || s.results === null ? s : { ...s, results: null };
  }
}

/** A round is in flight, or some model already took the content: it can't
 *  change (until Start over, for the latter). */
export function fanOutLocked(s: FanOutState): boolean {
  return s.progress !== null || (s.results?.some((r) => r.ok) ?? false);
}

/** The included accounts (chip order) and, of those, the ones a fan-out goes
 *  to (`fanOutTargets`). */
export function includedTargets<A extends { id: string }>(
  accounts: readonly A[], isIncluded: (id: string) => boolean, results: FanOutResult[] | null,
): { included: A[]; targets: string[] } {
  const included = accounts.filter((a) => isIncluded(a.id));
  return { included, targets: fanOutTargets(results, included.map((a) => a.id)) };
}

/** The included models a fan-out goes to: those without a success in
 *  `results` (the first send: all; a retry: the failed + newly included). */
export function fanOutTargets(results: FanOutResult[] | null, includedIds: string[]): string[] {
  const done = new Set((results ?? []).filter((r) => r.ok).map((r) => r.accountId));
  return includedIds.filter((id) => !done.has(id));
}

/** Why an all-models send has no target: nothing included, or (after a
 *  round) every model still failing is excluded. */
export function noTargetsReason(results: FanOutResult[] | null): string {
  return results ? "Nothing to retry: every failed model is excluded" : "No models picked for broadcast";
}

export function summarizeFanOut(results: FanOutResult[]): string {
  const ok = results.filter((r) => r.ok).length;
  return `${ok}/${results.length} succeeded`;
}

/** The footer's line for results with a failure still outstanding, else null. */
export function fanOutNote(results: FanOutResult[] | null): string | null {
  return results?.some((r) => !r.ok) ? summarizeFanOut(results) : null;
}

/** Send to each target in turn (see the file header). */
export async function runFanOut(
  targets: readonly string[],
  send: (accountId: string) => Promise<unknown>,
  onProgress?: (p: FanOutProgress) => void,
): Promise<FanOutResult[]> {
  const out: FanOutResult[] = [];
  onProgress?.({ done: 0, total: targets.length });
  for (const accountId of targets) {
    try {
      await send(accountId);
      out.push({ accountId, ok: true });
    } catch (e) {
      out.push({ accountId, ok: false, error: (e as Error).message });
    }
    onProgress?.({ done: out.length, total: targets.length });
  }
  return out;
}
