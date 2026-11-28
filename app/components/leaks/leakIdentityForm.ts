import type { LeakTrimmed } from "./leakCoverage";

export type IdentityField = "username" | "display_name" | "instagram" | "x";

export interface LeakIdentityForm {
  username: string;
  verified: boolean;
  display_name: string;
  aliases: string[];
  instagram: string;
  x: string;
  consent: boolean;
  originalIdentity: string | null;
  error: string | null;
}

export type Action =
  | {
    type: "adopt"; tracked: boolean; username: string; verified: boolean; display_name: string;
    aliases?: string[]; instagram?: string | null; x?: string | null;
  }
  | { type: "edit"; field: IdentityField; value: string }
  | { type: "addAlias"; value: string }
  | { type: "removeAlias"; index: number }
  | { type: "setConsent"; value: boolean }
  | { type: "saveFailed"; message: string };

export type LeakIdentityPayload = {
  username: string;
  verified: boolean;
  display_name: string;
  aliases: string[];
  instagram: string | null;
  x: string | null;
  consent: boolean;
};

export const ALIASES_MAX = 5;
const NAME_MAX = 64;
const HANDLE = /^[A-Za-z0-9_.-]{2,64}$/;
const INSTAGRAM = /^[A-Za-z0-9_.]{1,30}$/;
const X_HANDLE = /^[A-Za-z0-9_]{1,15}$/;

// Mirrors BANNED_ALIASES in service/leak_tracker_api.py.
export const BANNED_ALIASES: readonly string[] = [
  "onlyfans", "fansly", "leak", "leaks", "leaked", "nude", "nudes", "naked", "free", "porn", "sexy", "model",
  "official", "babe", "baby", "video", "videos", "photo", "photos", "pics", "content", "premium", "vip",
];

const ALIAS_MIN = 4;
const STRONG_MIN = 5;

export function normAlias(alias: string): string {
  const decoded = alias.replace(/(%[0-9A-Fa-f]{2})+/g, (run) =>
    new TextDecoder("utf-8", { ignoreBOM: true }).decode(Uint8Array.from(run.slice(1).split("%"), (hex) => parseInt(hex, 16))));
  return decoded.toLowerCase().replace(/[_.-]/g, "");
}

const normLength = (alias: string) => [...normAlias(alias)].length;

export type AliasLane = "alone" | "with_handle";

export function aliasLane(alias: string): AliasLane {
  return normLength(alias) >= STRONG_MIN ? "alone" : "with_handle";
}

export const ALIAS_LANE_LABEL: Record<AliasLane, string> = {
  alone: "Searched on its own", with_handle: "Only with the handle",
};

export const INITIAL_FORM: LeakIdentityForm = {
  username: "", verified: false, display_name: "", aliases: [], instagram: "", x: "",
  consent: false, originalIdentity: null, error: null,
};

export function leakIdentityFormReducer(state: LeakIdentityForm, action: Action): LeakIdentityForm {
  switch (action.type) {
    case "adopt": {
      const adopted = {
        ...INITIAL_FORM,
        username: action.username,
        verified: action.verified && action.username !== "",
        display_name: action.display_name,
        aliases: action.aliases ?? [],
        instagram: action.instagram ?? "",
        x: action.x ?? "",
      };
      return { ...adopted, originalIdentity: action.tracked ? identityOf(adopted) : null };
    }
    case "edit":
      if (action.field === "username") {
        const verified = state.verified && action.value === state.username;
        return edited(state, { username: action.value, verified });
      }
      return edited(state, { [action.field]: action.value });
    case "addAlias": {
      const value = action.value.trim();
      return value ? edited(state, { aliases: [...state.aliases, value] }) : state;
    }
    case "removeAlias":
      return edited(state, { aliases: state.aliases.filter((_, i) => i !== action.index) });
    case "setConsent":
      return { ...state, consent: action.value };
    case "saveFailed":
      return { ...state, error: action.message };
  }
}

export function validate(state: LeakIdentityForm): Partial<Record<"username" | "display_name" | "aliases" | "instagram" | "x", string>> {
  const errors: ReturnType<typeof validate> = {};
  const handle = state.username.trim();
  if (!HANDLE.test(handle)) errors.username = "The handle takes 2–64 letters, numbers, _ . or -";
  if (state.display_name.trim().length > NAME_MAX) errors.display_name = "The display name takes at most 64 characters";
  const taken = new Set([normAlias(handle)]);
  for (const alias of state.aliases) {
    const low = alias.toLowerCase();
    const norm = normAlias(alias);
    if (alias.length < ALIAS_MIN || alias.length > 64) errors.aliases = `"${alias}" must be 4–64 characters`;
    else if ([...norm].length < ALIAS_MIN) errors.aliases = `"${alias}" needs 4 characters besides _ . and -`;
    else if (BANNED_ALIASES.includes(low)) errors.aliases = `"${alias}" is too common to search for`;
    else if (taken.has(norm)) errors.aliases = `"${alias}" is the handle or listed twice`;
    taken.add(norm);
  }
  if (state.aliases.length > ALIASES_MAX) errors.aliases = `At most ${ALIASES_MAX} aliases`;
  const instagram = state.instagram.trim();
  if (instagram && !INSTAGRAM.test(instagram)) errors.instagram = "An Instagram handle takes 1–30 letters, numbers, _ or .";
  const x = state.x.trim();
  if (x && !X_HANDLE.test(x)) errors.x = "An X handle takes 1–15 letters, numbers or _";
  return errors;
}

function identityOf(state: LeakIdentityForm): string {
  const { username, display_name, aliases, instagram, x } = buildPayload(state);
  return JSON.stringify([username.toLowerCase(), display_name, aliases, instagram, x]);
}

function edited(state: LeakIdentityForm, fields: Partial<LeakIdentityForm>): LeakIdentityForm {
  const next = { ...state, ...fields, error: null };
  return { ...next, consent: state.consent && identityOf(state) === identityOf(next) };
}

export function needsConsent(state: LeakIdentityForm): boolean {
  return state.originalIdentity !== identityOf(state);
}

export function canSubmit(state: LeakIdentityForm): boolean {
  return Object.keys(validate(state)).length === 0 && (!needsConsent(state) || state.consent);
}

export function buildPayload(state: LeakIdentityForm): LeakIdentityPayload {
  return {
    username: state.username.trim(),
    verified: state.verified,
    display_name: state.display_name.trim(),
    aliases: state.aliases,
    instagram: state.instagram.trim() || null,
    x: state.x.trim() || null,
    consent: state.consent,
  };
}

export const TRIMMED_NOTE = "Skipped in the last full Google search to stay within budget";

export function isTrimmed(trimmed: LeakTrimmed[], field: "alias" | "instagram" | "x", value: string): boolean {
  const v = value.trim().toLowerCase();
  return v !== "" && trimmed.some((t) =>
    (field === "alias" ? t.field.startsWith("alias:") : t.field === field) && t.value.toLowerCase() === v);
}
