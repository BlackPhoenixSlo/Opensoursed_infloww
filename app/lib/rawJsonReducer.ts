import { useMemo, useReducer } from "react";
import { errText } from "@/lib/errText";

export interface RawJsonCodec<T> {
  parse(text: string): T;
  format(value: T): string;
}

export interface RawJsonState<T> {
  raw: boolean;
  text: string;
  value: T;
  invalid: boolean;
  error: string | null;
}

export type RawJsonAction<T> =
  | { type: "open" }
  | { type: "edit"; text: string }
  | { type: "close" }
  | { type: "set"; value: T }
  | { type: "update"; fn: (value: T) => T }
  | { type: "fail"; error: string };

export function initialRawJson<T>(value: T): RawJsonState<T> {
  return { raw: false, text: "", value, invalid: false, error: null };
}

export function rawJsonReducer<T>(codec: RawJsonCodec<T>) {
  const setValue = (state: RawJsonState<T>, value: T): RawJsonState<T> => {
    if (!state.raw) return { ...state, value, error: null };
    try {
      return { ...state, value, text: codec.format(value), invalid: false, error: null };
    } catch (e) {
      return { ...state, raw: false, value, invalid: false, error: errText(e) };
    }
  };
  return (state: RawJsonState<T>, action: RawJsonAction<T>): RawJsonState<T> => {
    switch (action.type) {
      case "open": {
        if (state.raw) return state;
        try {
          return { ...state, raw: true, text: codec.format(state.value), invalid: false, error: null };
        } catch (e) {
          return { ...state, error: errText(e) };
        }
      }
      case "edit": {
        try {
          return { ...state, text: action.text, value: codec.parse(action.text), invalid: false, error: null };
        } catch (e) {
          return { ...state, text: action.text, invalid: true, error: errText(e) };
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

// saving the last valid value while the textarea shows something else would surprise
export function canSubmit(state: RawJsonState<unknown>): boolean {
  return !(state.raw && state.invalid);
}

export function parseJsonObject(text: string, label: string, example: string): Record<string, unknown> {
  let parsed: unknown;
  try {
    parsed = JSON.parse(text.trim() || "{}");
  } catch (e) {
    throw new Error(`${label} is not valid JSON: ${errText(e)}`);
  }
  if (typeof parsed !== "object" || parsed === null || Array.isArray(parsed)) {
    throw new Error(`${label} must be a JSON object, e.g. ${example}`);
  }
  return parsed as Record<string, unknown>;
}

export function parseJsonObjectOr(
  text: string, label: string, example: string, onError: (message: string) => void,
): Record<string, unknown> | null {
  try {
    return parseJsonObject(text, label, example);
  } catch (e) {
    onError(errText(e));
    return null;
  }
}

export function useRawJson<T>(codec: RawJsonCodec<T>, init: () => T) {
  const reducer = useMemo(() => rawJsonReducer(codec), [codec]);
  return useReducer(reducer, undefined, () => initialRawJson(init()));
}
