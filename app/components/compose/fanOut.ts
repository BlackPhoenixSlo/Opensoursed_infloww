export interface FanOutResult {
  accountId: string;
  ok: boolean;
  error?: string;
}

export interface FanOutProgress {
  done: number;
  total: number;
}

export interface FanOutState {
  progress: FanOutProgress | null;
  results: FanOutResult[] | null;
}

export type FanOutAction =
  | ({ type: "progress" } & FanOutProgress)
  | { type: "results"; v: FanOutResult[] }
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

// Content locks once a model took it: clearing instead would re-send to models that already posted; a retry must carry the SAME content.
export function fanOutLocked(s: FanOutState): boolean {
  return s.progress !== null || (s.results?.some((r) => r.ok) ?? false);
}

export function includedTargets<A extends { id: string }>(
  accounts: readonly A[], isIncluded: (id: string) => boolean, results: FanOutResult[] | null,
): { included: A[]; targets: string[] } {
  const included = accounts.filter((a) => isIncluded(a.id));
  return { included, targets: fanOutTargets(results, included.map((a) => a.id)) };
}

export function fanOutTargets(results: FanOutResult[] | null, includedIds: string[]): string[] {
  const done = new Set((results ?? []).filter((r) => r.ok).map((r) => r.accountId));
  return includedIds.filter((id) => !done.has(id));
}

export function noTargetsReason(results: FanOutResult[] | null): string {
  return results ? "Nothing to retry: every failed model is excluded" : "No models picked for broadcast";
}

export function summarizeFanOut(results: FanOutResult[]): string {
  const ok = results.filter((r) => r.ok).length;
  return `${ok}/${results.length} succeeded`;
}

export function fanOutNote(results: FanOutResult[] | null): string | null {
  return results?.some((r) => !r.ok) ? summarizeFanOut(results) : null;
}

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
