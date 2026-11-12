"use client";

/**
 * The bio editor's Profile card: the avatar (uploads on pick; Remove), display name, the address (read-only), bio,
 * default Mode, the Verified badge and the Creator, under one Save. State: `bioProfileForm.ts`, held by BioEditor (the
 * preview draws the draft); this card only dispatches.
 */
import { useId, useRef, type Dispatch } from "react";

import {
  IfButton, IfCard, IfCreatorSelect, IfHelp, IfInput, IfLabel, IfNativeSelect, IfSwitch, IfTextArea, SaveRow,
} from "@/components/ui/infloww";
import { useAccounts } from "@/hooks/useAccounts";
import { BIO_MODES, bioFailure, useBioAvatar, usePatchBioPage, type BioMode, type BioPage } from "@/hooks/useBioPages";
import { IMAGE_ACCEPT, MAX_DISPLAY_NAME, MAX_BIO, chars } from "@/components/growth/bio/bioRules";
import {
  buildProfilePatch, canSubmit, isDirty, type Action, type BioProfileForm,
} from "@/components/growth/bio/bioProfileForm";
import { MODE_HELP, MODE_NAMES, PageAvatar } from "@/components/growth/bio/bioBits";

export function BioProfileCard({ page, form, dispatch }: {
  page: BioPage;
  form: BioProfileForm;
  dispatch: Dispatch<Action>;
}) {
  const pid = page.profile.id;
  const id = useId();
  const accounts = useAccounts().data?.accounts ?? [];
  const patch = usePatchBioPage(pid);
  const avatar = useBioAvatar(pid);
  const fileRef = useRef<HTMLInputElement>(null);
  const d = form.draft;
  const dirty = isDirty(form);

  function save() {
    if (!canSubmit(form)) {
      dispatch({ type: "submit" });
      return;
    }
    const body = buildProfilePatch(form.base, d);
    if (!body) return;
    dispatch({ type: "submit" });
    patch.mutateAsync(body)
      .then((P) => dispatch({ type: "saved", page: P }))
      .catch((e) => dispatch({ type: "failed", ...bioFailure(e, "Save failed") }));
  }

  return (
    <IfCard title="Profile">
      <fieldset disabled={form.busy} className="mt-4 space-y-4">
        <div className="flex flex-wrap items-center gap-4">
          <PageAvatar url={page.profile.avatar_url} name={d.displayName} size={64} />
          <div className="flex flex-wrap items-center gap-2">
            <input ref={fileRef} type="file" accept={IMAGE_ACCEPT} className="hidden" aria-label="Avatar image"
              onChange={(e) => {
                const file = e.target.files?.[0];
                e.target.value = "";
                if (file) avatar.mutate(file);
              }} />
            <IfButton onClick={() => fileRef.current?.click()} disabled={avatar.isPending}>
              {avatar.isPending ? "Uploading…" : page.profile.avatar ? "Change avatar" : "Upload avatar"}
            </IfButton>
            {page.profile.avatar && (
              <IfButton variant="link" onClick={() => avatar.mutate(null)} disabled={avatar.isPending}>Remove</IfButton>
            )}
          </div>
          {avatar.error && <p role="alert" className="w-full text-[12px] text-err">{bioFailure(avatar.error, "Upload failed").msg}</p>}
        </div>

        <div className="grid gap-4 sm:grid-cols-2">
          <div className="min-w-0">
            <IfLabel htmlFor={`${id}-name`} required>Display name</IfLabel>
            <IfInput id={`${id}-name`} className="w-full" value={d.displayName} maxLength={MAX_DISPLAY_NAME}
              aria-invalid={form.error?.fields.includes("display_name") || undefined}
              onChange={(e) => dispatch({ type: "set", patch: { displayName: e.target.value } })} />
          </div>
          <div className="min-w-0">
            <IfLabel htmlFor={`${id}-user`}>Username</IfLabel>
            <IfInput id={`${id}-user`} className="w-full opacity-70" value={`@${page.profile.username}`} readOnly />
            <IfHelp>Your page&rsquo;s address. It can&rsquo;t be changed.</IfHelp>
          </div>
        </div>

        <div>
          <IfLabel htmlFor={`${id}-bio`}>Bio</IfLabel>
          <IfTextArea id={`${id}-bio`} rows={3} value={d.bio}
            aria-invalid={form.error?.fields.includes("bio") || undefined}
            onChange={(e) => dispatch({ type: "set", patch: { bio: e.target.value } })} />
          <IfHelp className={chars(d.bio) > MAX_BIO ? "text-err" : undefined}>{chars(d.bio)}/{MAX_BIO}</IfHelp>
        </div>

        <div className="grid gap-4 sm:grid-cols-2">
          <div className="min-w-0">
            <IfLabel htmlFor={`${id}-mode`}>Default Mode</IfLabel>
            <IfNativeSelect id={`${id}-mode`} className="w-full" value={d.mode}
              onChange={(e) => dispatch({ type: "set", patch: { mode: e.target.value as BioMode } })}>
              {BIO_MODES.map((m) => <option key={m} value={m}>{MODE_NAMES[m]}</option>)}
            </IfNativeSelect>
            <IfHelp>{MODE_HELP[d.mode]} Every Link left on &ldquo;Profile default&rdquo; follows this Mode.</IfHelp>
          </div>
          <div className="min-w-0">
            <IfLabel>Creator</IfLabel>
            <IfCreatorSelect accounts={accounts} value={d.accountId} allLabel="No Creator" className="w-full"
              disabled={form.busy}
              onAll={() => dispatch({ type: "set", patch: { accountId: null } })}
              onChange={(accountId) => dispatch({ type: "set", patch: { accountId } })} />
            <IfHelp>Lets links use this Creator&rsquo;s OnlyFans tracking links.</IfHelp>
          </div>
        </div>

        <IfSwitch checked={d.verified} label="Verified badge"
          onChange={(verified) => dispatch({ type: "set", patch: { verified } })} />
      </fieldset>
      <div className="mt-4">
        <SaveRow onSave={save} disabled={!dirty}
          save={{ pending: form.busy, saved: patch.isSuccess && !dirty, error: form.error?.msg ?? null }} />
      </div>
    </IfCard>
  );
}
