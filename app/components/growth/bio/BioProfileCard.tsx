"use client";

/**
 * The bio editor's Profile card: the avatar and the page background (each uploads on pick, or a photo from the saved
 * Creator's vault; Remove), display name, the address (read-only), bio, default Mode, the Verified badge and the
 * Creator, under one Save. State: `bioProfileForm.ts`, held by BioEditor (the preview draws the draft); this card only
 * dispatches (which image the vault picker is open for is its one local state).
 */
import { useId, useRef, useState, type Dispatch } from "react";

import {
  IfButton, IfCard, IfCreatorSelect, IfHelp, IfInput, IfLabel, IfNativeSelect, IfSwitch, IfTextArea, SaveRow,
} from "@/components/ui/infloww";
import { useAccounts } from "@/hooks/useAccounts";
import { VaultPicker } from "@/components/chat/VaultPicker";
import {
  BIO_MODES, bioFailure, useBioAvatar, useBioAvatarFromVault, useBioBackground, useBioBackgroundFromVault,
  usePatchBioPage, type BioMode, type BioPage,
} from "@/hooks/useBioPages";
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
  const fromVault = useBioAvatarFromVault(pid);
  const background = useBioBackground(pid);
  const bgFromVault = useBioBackgroundFromVault(pid);
  const [vaultFor, setVaultFor] = useState<"avatar" | "background" | null>(null);
  const fileRef = useRef<HTMLInputElement>(null);
  const bgFileRef = useRef<HTMLInputElement>(null);
  // The saved Creator: the relay reads the vault of the page's stored account, not the unsaved draft's.
  const vaultAccount = page.profile.account_id || null;
  const avatarBusy = avatar.isPending || fromVault.isPending;
  const avatarError = avatar.error ? bioFailure(avatar.error, "Upload failed").msg
    : fromVault.error ? bioFailure(fromVault.error, "Vault pick failed").msg : null;
  const bgUrl = page.profile.background_url;
  const bgBusy = background.isPending || bgFromVault.isPending;
  const bgError = background.error ? bioFailure(background.error, "Upload failed").msg
    : bgFromVault.error ? bioFailure(bgFromVault.error, "Vault pick failed").msg : null;
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
                if (file) {
                  fromVault.reset();
                  avatar.mutate(file);
                }
              }} />
            <IfButton onClick={() => fileRef.current?.click()} disabled={avatarBusy}>
              {avatarBusy ? "Uploading…" : page.profile.avatar ? "Change avatar" : "Upload avatar"}
            </IfButton>
            {vaultAccount && (
              <IfButton onClick={() => setVaultFor("avatar")} disabled={avatarBusy}>Pick from vault</IfButton>
            )}
            {page.profile.avatar && (
              <IfButton variant="link" onClick={() => { fromVault.reset(); avatar.mutate(null); }} disabled={avatarBusy}>Remove</IfButton>
            )}
          </div>
          {avatarError && <p role="alert" className="w-full text-[12px] text-err">{avatarError}</p>}
        </div>
        <div className="flex flex-wrap items-center gap-4" data-bio-background>
          <span aria-hidden className="h-16 w-16 shrink-0 rounded-md bg-bg-elev-2 bg-cover bg-center"
            style={bgUrl ? { backgroundImage: `url("${bgUrl}")` } : undefined} />
          <div className="flex flex-wrap items-center gap-2">
            <input ref={bgFileRef} type="file" accept={IMAGE_ACCEPT} className="hidden" aria-label="Background image"
              onChange={(e) => {
                const file = e.target.files?.[0];
                e.target.value = "";
                if (file) {
                  bgFromVault.reset();
                  background.mutate(file);
                }
              }} />
            <IfButton onClick={() => bgFileRef.current?.click()} disabled={bgBusy}>
              {bgBusy ? "Uploading…" : bgUrl ? "Change background" : "Upload background"}
            </IfButton>
            {vaultAccount && (
              <IfButton onClick={() => setVaultFor("background")} disabled={bgBusy}>Pick from vault</IfButton>
            )}
            {bgUrl && (
              <IfButton variant="link" onClick={() => { bgFromVault.reset(); background.mutate(null); }} disabled={bgBusy}>
                Remove
              </IfButton>
            )}
          </div>
          <IfHelp className="w-full">The page&rsquo;s backdrop behind the profile and links.</IfHelp>
          {bgError && <p role="alert" className="w-full text-[12px] text-err">{bgError}</p>}
        </div>
        {vaultAccount && vaultFor && (
          <VaultPicker open onClose={() => setVaultFor(null)} accountId={vaultAccount} fanId={null}
            initialSelectedIds={[]}
            onConfirm={(picked) => {
              const target = vaultFor;
              setVaultFor(null);
              // One image: the first photo picked (a lone video goes through, for the relay's "photo" refusal).
              const m = picked.find((p) => p.type === "photo") ?? picked[0];
              if (!m) return;
              if (target === "avatar") {
                avatar.reset();
                fromVault.mutate({ id: m.id, type: m.type });
              } else {
                background.reset();
                bgFromVault.mutate({ id: m.id, type: m.type });
              }
            }} />
        )}

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
