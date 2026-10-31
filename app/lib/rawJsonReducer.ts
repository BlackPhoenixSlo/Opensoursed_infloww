/**
 * An "Edit raw JSON" escape hatch as a pure reducer. `value` is the one source
 * of truth; a typed view and the raw textarea are two ways to edit it. A codec
 * turns text ⇄ value and carries all validation.
 *
 *   • `open` serializes `value` into the textarea. If `format` throws (the
 *     value can't be written yet), raw mode stays off and `error` says why.
 *   • `edit` re-parses on every keystroke through the codec's `parse` — never
 *     an unchecked cast. Valid → `value` follows the text; invalid → `value`
 *     keeps the last valid one, `invalid` is set and `error` says why.
 *   • `close` with an invalid buffer stays in raw mode (text and error kept),
 *     so neither the hand edit nor the last valid value is lost.
 *   • `set` / `update` replace `value` from the typed view and clear `error`.
 *     In raw mode the text is re-formatted so it never shows a stale value (a
 *     value that can't be formatted drops back to the typed view, with why).
 *   • `fail` shows an error from outside the codec (a failed save) — the one
 *     user-facing error channel; a no-op while the buffer is invalid (the
 *     parse error is what blocks the save).
 *   • Nothing is saved while the buffer is invalid (`canSubmit`): saving the
 *     last valid value while the textarea shows something else would surprise.
 */

import { useMemo, useReducer } from "react";

export interface RawJsonCodec<T> {
  /** Text → value; throws an Error with a user-facing message. */
  parse(text: string): T;
  /** Value → text; may throw (the value can't be written yet). */
  format(value: T): string;
}

export interface RawJsonState<T> {
  /** The textarea is shown (raw mode on). */
  raw: boolean;
  text: string;
  /** The last valid value — what both views show and what is saved. */
  value: T;
  /** Raw mode: `text` doesn't parse (blocks close and save). */
  invalid: boolean;
  /** What to show the user: why `text` doesn't parse, `open` failed, or `fail`. */
  error: string | null;
}

export type RawJsonAction<T> =
  | { type: "open" }
  | { type: "edit"; text: string }
  | { type: "close" }
  | { type: "set"; value: T }
  /** `set` from the current value — `fn` must be pure. */
  | { type: "update"; fn: (value: T) => T }
  | { type: "fail"; error: string };

const message = (e: unknown) => (e instanceof Error ? e.message : String(e));

export function initialRawJson<T>(value: T): RawJsonState<T> {
  return { raw: false, text: "", value, invalid: false, error: null };
}

export function rawJsonReducer<T>(codec: RawJsonCodec<T>) {
  const setValue = (state: RawJsonState<T>, value: T): RawJsonState<T> => {
    if (!state.raw) return { ...state, value, error: null };
    try {
      return { ...state, value, text: codec.format(value), invalid: false, error: null };
    } catch (e) {
      return { ...state, raw: false, value, invalid: false, error: message(e) };
    }
  };
  return (state: RawJsonState<T>, action: RawJsonAction<T>): RawJsonState<T> => {
    switch (action.type) {
      case "open": {
        if (state.raw) return state;
        try {
          return { ...state, raw: true, text: codec.format(state.value), invalid: false, error: null };
        } catch (e) {
          return { ...state, error: message(e) };
        }
      }
      case "edit": {
        try {
          return { ...state, text: action.text, value: codec.parse(action.text), invalid: false, error: null };
        } catch (e) {
          return { ...state, text: action.text, invalid: true, error: message(e) };
        }
      }
      case "close":
        if (!state.raw || state.invalid) return state;
        return { ...state, raw: false, error: null };
      case "set":
        return setValue(state, action.value);
      case "update":
        return setValue(state, action.fn(state.value));
      case "fail":
        return state.invalid ? state : { ...state, error: action.error };
    }
  };
}

/** Saving is blocked while the raw buffer doesn't parse. */
export function canSubmit(state: RawJsonState<unknown>): boolean {
  return !(state.raw && state.invalid);
}

/** `text` as a JSON object (blank → `{}`); throws `"<label> is not valid JSON: …"`
 *  or `"<label> must be a JSON object, e.g. <example>"`. */
export function parseJsonObject(text: string, label: string, example: string): Record<string, unknown> {
  let parsed: unknown;
  try {
    parsed = JSON.parse(text.trim() || "{}");
  } catch (e) {
    throw new Error(`${label} is not valid JSON: ${message(e)}`);
  }
  if (typeof parsed !== "object" || parsed === null || Array.isArray(parsed)) {
    throw new Error(`${label} must be a JSON object, e.g. ${example}`);
  }
  return parsed as Record<string, unknown>;
}

/** `parseJsonObject` for a form: the object, or null after handing its message to `onError`. */
export function parseJsonObjectOr(
  text: string, label: string, example: string, onError: (message: string) => void,
): Record<string, unknown> | null {
  try {
    return parseJsonObject(text, label, example);
  } catch (e) {
    onError(message(e));
    return null;
  }
}

/** `codec` should be stable (module-level or memoized). */
export function useRawJson<T>(codec: RawJsonCodec<T>, init: () => T) {
  const reducer = useMemo(() => rawJsonReducer(codec), [codec]);
  return useReducer(reducer, undefined, () => initialRawJson(init()));
}
