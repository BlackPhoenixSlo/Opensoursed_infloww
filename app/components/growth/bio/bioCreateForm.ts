import type { ProfileCreate } from "@/hooks/useBioPages";
import { chars, MAX_DISPLAY_NAME, NAME_MSG, RESERVED, RESERVED_MSG, USERNAME, USERNAME_MSG, type FormError } from "@/components/growth/bio/bioRules";
export { MAX_DISPLAY_NAME, NAME_MSG, RESERVED_MSG, USERNAME_MSG } from "@/components/growth/bio/bioRules";


export interface BioCreateForm {
  username: string;
  displayName: string;
  accountId: string | null;
  busy: boolean;
  error: FormError | null;
  filled: { username: string; displayName: string };
}

export type Action =
  | { type: "set"; patch: Partial<Pick<BioCreateForm, "username" | "displayName">> }
  | { type: "pick_creator"; accountId: string | null }
  | { type: "creator_identity"; accountId: string; name?: string | null; username?: string | null }
  | { type: "submit" }
  | { type: "failed"; msg: string; fields?: string[] };

export const INITIAL_CREATE: BioCreateForm = {
  username: "", displayName: "", accountId: null, busy: false, error: null, filled: { username: "", displayName: "" },
};

export const normalizeUsername = (raw: string) => raw.trim().replace(/^@/, "").toLowerCase();

export function suggestUsername(ofUsername: string | null | undefined): string | null {
  const u = (ofUsername ?? "").toLowerCase().replace(/[^a-z0-9_]/g, "").slice(0, 30);
  return USERNAME.test(u) && !RESERVED.includes(u) ? u : null;
}

export const isDirty = (f: BioCreateForm) => f.username !== "" || f.displayName !== "" || f.accountId !== null;

export function createFormError(f: BioCreateForm): FormError | null {
  const u = normalizeUsername(f.username);
  if (!USERNAME.test(u)) return { msg: USERNAME_MSG, fields: ["username"] };
  if (RESERVED.includes(u)) return { msg: RESERVED_MSG, fields: ["username"] };
  const name = f.displayName.trim();
  if (!name && !f.accountId) return { msg: NAME_MSG, fields: ["display_name"] };
  if (chars(name) > MAX_DISPLAY_NAME) {
    return { msg: `Display name: at most ${MAX_DISPLAY_NAME} characters.`, fields: ["display_name"] };
  }
  return null;
}

export const canSubmit = (f: BioCreateForm) => !f.busy && createFormError(f) === null;

export function buildCreatePayload(f: BioCreateForm): ProfileCreate {
  const body: ProfileCreate = { username: normalizeUsername(f.username), display_name: f.displayName.trim() };
  if (f.accountId) body.account_id = f.accountId;
  return body;
}

const prefillable = (value: string, filled: string) => value.trim() === "" || value === filled;

export function bioCreateReducer(state: BioCreateForm, action: Action): BioCreateForm {
  switch (action.type) {
    case "set":
      return { ...state, ...action.patch, error: null };
    case "pick_creator":
      return { ...state, accountId: action.accountId, error: null };
    case "creator_identity": {
      if (action.accountId !== state.accountId) return state;
      const name = Array.from((action.name ?? "").trim()).slice(0, MAX_DISPLAY_NAME).join("");
      const user = suggestUsername(action.username) ?? "";
      const nameIn = name !== "" && name !== state.displayName && prefillable(state.displayName, state.filled.displayName);
      const userIn = user !== "" && user !== state.username && prefillable(state.username, state.filled.username);
      if (!nameIn && !userIn) return state;
      return {
        ...state,
        displayName: nameIn ? name : state.displayName,
        username: userIn ? user : state.username,
        filled: {
          displayName: nameIn ? name : state.filled.displayName,
          username: userIn ? user : state.filled.username,
        },
      };
    }
    case "submit": {
      if (state.busy) return state;
      const error = createFormError(state);
      return error ? { ...state, error } : { ...state, busy: true, error: null };
    }
    case "failed":
      return { ...state, busy: false, error: { msg: action.msg, fields: action.fields ?? [] } };
  }
}
