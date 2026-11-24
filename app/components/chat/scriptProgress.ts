export interface ScriptProgress {
  epochs: ReadonlyMap<string, number>;
  skippedAt: number;
}

export const EMPTY_SCRIPT_PROGRESS: ScriptProgress = {
  epochs: new Map(),
  skippedAt: -Infinity,
};

export type ScriptProgressAction =
  | { type: "skip"; scriptId: string; now: number }
  | { type: "end"; scriptId: string };

export function epochOf(state: ScriptProgress, scriptId: string): number {
  return state.epochs.get(scriptId) ?? 0;
}

export function canSkip(state: ScriptProgress, now: number): boolean {
  return now - state.skippedAt >= 400;
}

export function scriptProgress(state: ScriptProgress, action: ScriptProgressAction): ScriptProgress {
  if (action.type === "skip" && !canSkip(state, action.now)) return state;
  return {
    epochs: new Map(state.epochs).set(action.scriptId, epochOf(state, action.scriptId) + 1),
    skippedAt: action.type === "skip" ? action.now : state.skippedAt,
  };
}
