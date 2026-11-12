/**
 * The bio editor's Profile card: the saved profile (`base`), the Creator's edits (`draft`), the save in flight and its
 * refusal. A pure reducer (BioEditor holds it, the card only dispatches) with `isDirty`, the API's profile rules
 * mirrored (`decide.check_profile`) and the PATCH body: only what changed, so an untouched legacy value never blocks a
 * save.
 *
 * `hydrate` (a fresh read of the page) is IGNORED while the draft is dirty: a focus refetch or another write's answer
 * landing mid-edit must not wipe what the Creator typed (the `nudgeOnlineReducer.ts` trap). The base is kept with it,
 * so the PATCH still holds only the Creator's own changes; `saved` takes the answer as both.
 */
import { isBioMode, type BioMode, type BioPage, type BioProfile, type ProfilePatch } from "@/hooks/useBioPages";
import { chars, MAX_BIO, MAX_DISPLAY_NAME, NAME_MSG, type FormError } from "@/components/growth/bio/bioRules";
export { MAX_BIO } from "@/components/growth/bio/bioRules";

export interface ProfileDraft {
  displayName: string;
  bio: string;
  mode: BioMode;
  verified: boolean;
  accountId: string | null;
}

export interface BioProfileForm {
  base: ProfileDraft;
  draft: ProfileDraft;
  busy: boolean;
  error: FormError | null;
}

export type Action =
  | { type: "hydrate"; profile: BioProfile }
  | { type: "set"; patch: Partial<ProfileDraft> }
  | { type: "submit" }
  | { type: "saved"; page: BioPage }
  | { type: "failed"; msg: string; fields?: string[] };

export const initProfileForm = (profile: BioProfile): BioProfileForm => {
  const draft = draftOf(profile);
  return { base: draft, draft, busy: false, error: null };
};

/** A legacy mode the API no longer offers reads as the public page reads it: Escape. */
export const asMode = (m: string): BioMode => isBioMode(m) ? m : "escape_ig";

export const draftOf = (p: BioProfile): ProfileDraft => ({
  displayName: p.display_name, bio: p.bio, mode: asMode(p.mode), verified: p.verified, accountId: p.account_id,
});

const same = (a: ProfileDraft, b: ProfileDraft) =>
  a.displayName === b.displayName && a.bio === b.bio && a.mode === b.mode && a.verified === b.verified
  && a.accountId === b.accountId;

export const isDirty = (f: BioProfileForm) => !same(f.base, f.draft);

export function profileFormError(d: ProfileDraft, base: ProfileDraft | null = null): FormError | null {
  const name = d.displayName.trim();
  if (d.displayName !== base?.displayName && !name) return { msg: NAME_MSG, fields: ["display_name"] };
  if (d.displayName !== base?.displayName && chars(name) > MAX_DISPLAY_NAME) return { msg: `Display name: at most ${MAX_DISPLAY_NAME} characters.`, fields: ["display_name"] };
  if (d.bio !== base?.bio && chars(d.bio) > MAX_BIO) return { msg: `Bio: at most ${MAX_BIO} characters.`, fields: ["bio"] };
  return null;
}

/** The PATCH body: each changed field (the name trimmed), or null when nothing changed. */
export function buildProfilePatch(base: ProfileDraft, draft: ProfileDraft): ProfilePatch | null {
  const out: ProfilePatch = {};
  if (draft.displayName !== base.displayName) out.display_name = draft.displayName.trim();
  if (draft.bio !== base.bio) out.bio = draft.bio;
  if (draft.mode !== base.mode) out.mode = draft.mode;
  if (draft.verified !== base.verified) out.verified = draft.verified;
  if (draft.accountId !== base.accountId) out.account_id = draft.accountId;
  return Object.keys(out).length ? out : null;
}

export const canSubmit = (f: BioProfileForm) => !f.busy && isDirty(f) && profileFormError(f.draft, f.base) === null;

export function bioProfileReducer(state: BioProfileForm, action: Action): BioProfileForm {
  switch (action.type) {
    case "hydrate": {
      if (isDirty(state) || state.busy) return state;
      const fresh = draftOf(action.profile);
      if (same(state.base, fresh)) return state;
      return { ...state, base: fresh, draft: fresh };
    }
    case "set":
      return { ...state, draft: { ...state.draft, ...action.patch }, error: null };
    case "submit": {
      if (state.busy || !isDirty(state)) return state;
      const error = profileFormError(state.draft, state.base);
      return error ? { ...state, error } : { ...state, busy: true, error: null };
    }
    case "saved": {
      const fresh = draftOf(action.page.profile);
      return { base: fresh, draft: fresh, busy: false, error: null };
    }
    case "failed":
      return { ...state, busy: false, error: { msg: action.msg, fields: action.fields ?? [] } };
  }
}
