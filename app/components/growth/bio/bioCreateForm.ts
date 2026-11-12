/**
 * "New bio page": username, display name and an optional Creator, the create in flight and its refusal. A pure
 * reducer (BioCreateDialog only dispatches), the API's create rules mirrored (`decide.check_profile(create=True)`) so
 * a refusal shows before the round trip, and the body the create sends.
 */
import type { ProfileCreate } from "@/hooks/useBioPages";
import { chars, MAX_DISPLAY_NAME, NAME_MSG, RESERVED, RESERVED_MSG, USERNAME, USERNAME_MSG, type FormError } from "@/components/growth/bio/bioRules";
export { MAX_DISPLAY_NAME, NAME_MSG, RESERVED_MSG, USERNAME_MSG } from "@/components/growth/bio/bioRules";


export interface BioCreateForm {
  username: string;
  displayName: string;
  accountId: string | null;
  busy: boolean;
  error: FormError | null;
}

export type Action =
  | { type: "set"; patch: Partial<Pick<BioCreateForm, "username" | "displayName" | "accountId">> }
  | { type: "submit" }
  | { type: "failed"; msg: string; fields?: string[] };

export const INITIAL_CREATE: BioCreateForm = { username: "", displayName: "", accountId: null, busy: false, error: null };

/** What the Creator typed as a page address: `@Alice ` names `alice`. */
export const normalizeUsername = (raw: string) => raw.trim().replace(/^@/, "").toLowerCase();

export const isDirty = (f: BioCreateForm) => f.username !== "" || f.displayName !== "" || f.accountId !== null;

export function createFormError(f: BioCreateForm): FormError | null {
  const u = normalizeUsername(f.username);
  if (!USERNAME.test(u)) return { msg: USERNAME_MSG, fields: ["username"] };
  if (RESERVED.includes(u)) return { msg: RESERVED_MSG, fields: ["username"] };
  const name = f.displayName.trim();
  if (!name) return { msg: NAME_MSG, fields: ["display_name"] };
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

export function bioCreateReducer(state: BioCreateForm, action: Action): BioCreateForm {
  switch (action.type) {
    case "set":
      return { ...state, ...action.patch, error: null };
    case "submit": {
      if (state.busy) return state;
      const error = createFormError(state);
      return error ? { ...state, error } : { ...state, busy: true, error: null };
    }
    case "failed":
      return { ...state, busy: false, error: { msg: action.msg, fields: action.fields ?? [] } };
  }
}
