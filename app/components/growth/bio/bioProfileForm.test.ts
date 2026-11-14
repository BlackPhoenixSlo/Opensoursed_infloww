import { describe, expect, it } from "vitest";

import type { BioPage, BioProfile } from "@/hooks/useBioPages";
import {
  initProfileForm, bioProfileReducer, buildProfilePatch, canSubmit, draftOf, isDirty, profileFormError, type Action,
  type BioProfileForm, type ProfileDraft,
} from "@/components/growth/bio/bioProfileForm";

const PROFILE: BioProfile = {
  id: "p".repeat(15), username: "alice", display_name: "Alice", bio: "hi", avatar: "", avatar_url: "", background_url: "",
  account_id: "1000001", mode: "direct", verified: false, custom_domain: null, public_url: null,
  created_at: "", updated_at: "",
};
const page = (over: Partial<BioProfile> = {}): BioPage => ({ profile: { ...PROFILE, ...over }, links: [] });
const run = (actions: Action[], from: BioProfileForm = initProfileForm(PROFILE)) => actions.reduce(bioProfileReducer, from);
const hydrated = run([{ type: "hydrate", profile: PROFILE }]);
const base = draftOf(PROFILE);

describe("bioProfileReducer hydrate", () => {
  it("clean → seeds base and draft", () => {
    expect(hydrated.base).toEqual(base);
    expect(hydrated.draft).toEqual(base);
    expect(isDirty(hydrated)).toBe(false);
  });

  it("dirty → the draft (and its base) are kept", () => {
    const dirty = run([{ type: "set", patch: { bio: "typing" } }], hydrated);
    const after = run([{ type: "hydrate", profile: { ...PROFILE, display_name: "Elsewhere" } }], dirty);
    expect(after).toBe(dirty);
    expect(buildProfilePatch(after.base, after.draft)).toEqual({ bio: "typing" });
  });

  it("a legacy mode reads as Escape and is not a change", () => {
    const s = run([{ type: "hydrate", profile: { ...PROFILE, mode: "weird" } }]);
    expect(s.draft.mode).toBe("escape_ig");
    expect(buildProfilePatch(s.base, s.draft)).toBeNull();
  });
});

describe("buildProfilePatch", () => {
  it.each<[string, Partial<ProfileDraft>, ReturnType<typeof buildProfilePatch>]>([
    ["only bio changed", { bio: "new bio" }, { bio: "new bio" }],
    ["nothing changed", {}, null],
    ["name trimmed", { displayName: "  Al  " }, { display_name: "Al" }],
    ["unlink the Creator", { accountId: null }, { account_id: null }],
    ["mode + verified", { mode: "escape_ig", verified: true }, { mode: "escape_ig", verified: true }],
  ])("%s", (_name, patch, want) => {
    expect(buildProfilePatch(base, { ...base, ...patch })).toEqual(want);
  });
});

describe("profileFormError", () => {
  it.each([
    ["legacy bio untouched", { displayName: "Updated" }, null],
    ["changed invalid bio", { bio: "c".repeat(501) }, "Bio: at most 500 characters."],
  ])("%s", (_name, patch, msg) => {
    const legacy = initProfileForm({ ...PROFILE, bio: "b".repeat(600) });
    const form = { ...legacy, draft: { ...legacy.draft, ...patch } };
    expect(profileFormError(form.draft, form.base)?.msg ?? null).toBe(msg);
    expect(canSubmit(form)).toBe(msg === null);
  });
  it.each([
    ["  ", "x", "Enter a display name."],
    ["a".repeat(101), "", "Display name: at most 100 characters."],
    ["Alice", "b".repeat(501), "Bio: at most 500 characters."],
    ["Alice", "b".repeat(500), null],
  ])("name %j bio %j → %j", (displayName, bio, msg) => {
    expect(profileFormError({ ...base, displayName, bio })?.msg ?? null).toBe(msg);
  });
});

describe("bioProfileReducer save", () => {
  it("submit refused keeps idle; valid goes busy, ignores hydrate, saved takes the answer", () => {
    const refused = run([{ type: "set", patch: { displayName: "  " } }, { type: "submit" }], hydrated);
    expect(refused).toMatchObject({ busy: false, error: { msg: "Enter a display name.", fields: ["display_name"] } });

    const busy = run([{ type: "set", patch: { bio: "x" } }, { type: "submit" }], hydrated);
    expect(busy.busy).toBe(true);
    expect(run([{ type: "submit" }], busy)).toBe(busy);
    const saved = run([{ type: "saved", page: page({ bio: "x" }) }], busy);
    expect(saved).toMatchObject({ busy: false, error: null });
    expect(isDirty(saved)).toBe(false);
    expect(saved.draft.bio).toBe("x");
  });

  it("failed keeps the draft and shows the message", () => {
    const busy = run([{ type: "set", patch: { bio: "x" } }, { type: "submit" }], hydrated);
    const failed = run([{ type: "failed", msg: "nope" }], busy);
    expect(failed).toMatchObject({ busy: false, error: { msg: "nope", fields: [] } });
    expect(failed.draft.bio).toBe("x");
  });

  it("a clean form does not submit", () => {
    expect(run([{ type: "submit" }]).busy).toBe(false);
  });
});
