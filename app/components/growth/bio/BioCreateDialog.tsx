"use client";

/** "New bio page": the address (username), the display name and an optional Creator. A picked Creator prefills the
 *  name and a username from its OF profile (the shared `/users/me` query); the server adds its OnlyFans link. A
 *  created page opens in the editor. State: `bioCreateForm.ts`. */
import { useEffect, useId, useReducer } from "react";
import { useRouter } from "next/navigation";

import { IfButton, IfCreatorSelect, IfHelp, IfInput, IfLabel, IfModal } from "@/components/ui/infloww";
import { useAccounts } from "@/hooks/useAccounts";
import { bioFailure, bioPageHref, useCreateBioPage } from "@/hooks/useBioPages";
import { useOfMe } from "@/hooks/useGrowth";
import {
  INITIAL_CREATE, MAX_DISPLAY_NAME, bioCreateReducer, buildCreatePayload, canSubmit, createFormError, isDirty,
} from "@/components/growth/bio/bioCreateForm";

export function BioCreateDialog({ publicBase, onClose }: { publicBase: string | null; onClose: () => void }) {
  const router = useRouter();
  const accounts = useAccounts().data?.accounts ?? [];
  const create = useCreateBioPage();
  const [form, dispatch] = useReducer(bioCreateReducer, INITIAL_CREATE);
  const id = useId();
  const bad = (field: string) => form.error?.fields.includes(field) || undefined;
  const me = useOfMe(form.accountId).data;
  useEffect(() => {
    if (form.accountId && me) dispatch({ type: "creator_identity", accountId: form.accountId, name: me.name, username: me.username });
  }, [form.accountId, me]);

  function submit(e: React.FormEvent) {
    e.preventDefault();
    dispatch({ type: "submit" });
    if (!canSubmit(form)) return;
    create.mutateAsync(buildCreatePayload(form))
      .then((P) => router.push(bioPageHref(P.profile.id)))
      .catch((err) => {
        const f = bioFailure(err, "Create failed");
        dispatch({ type: "failed", msg: f.msg, fields: f.fields });
      });
  }

  const touched = isDirty(form);
  return (
    <IfModal title="New bio page" width={520} onClose={onClose} keyboard={!touched}
      footer={<>
        <IfButton onClick={onClose} disabled={form.busy}>Cancel</IfButton>
        <IfButton type="submit" form={id} variant="primary" disabled={form.busy}
          title={createFormError(form)?.msg}>
          {form.busy ? "Creating…" : "Create"}
        </IfButton>
      </>}>
      <form id={id} onSubmit={submit} noValidate className="space-y-4">
        <div>
          <IfLabel>Creator</IfLabel>
          <IfCreatorSelect accounts={accounts} value={form.accountId} allLabel="No Creator" className="w-full"
            onAll={() => dispatch({ type: "pick_creator", accountId: null })}
            onChange={(accountId) => dispatch({ type: "pick_creator", accountId })} />
          <IfHelp>Optional. Fills the name and username from this Creator&rsquo;s OnlyFans profile, adds an OnlyFans
            link and lets the page use its tracking links.</IfHelp>
        </div>
        <div>
          <IfLabel htmlFor={`${id}-u`} required>Username</IfLabel>
          <div className="flex min-w-0 items-center gap-1">
            <span className="max-w-[55%] shrink-0 truncate text-[13px] text-muted" title={`${publicBase ?? ""}/`}>
              {publicBase ? `${publicBase}/` : "/"}
            </span>
            <IfInput id={`${id}-u`} className="min-w-0 flex-1" value={form.username} autoComplete="off"
              autoCapitalize="none" spellCheck={false} maxLength={40} placeholder="alice" aria-invalid={bad("username")}
              onChange={(e) => dispatch({ type: "set", patch: { username: e.target.value } })} />
          </div>
          <IfHelp>Your page&rsquo;s address: 3-30 lowercase letters, digits or _. It can&rsquo;t be changed.</IfHelp>
        </div>
        <div>
          <IfLabel htmlFor={`${id}-n`} required={!form.accountId}>Display name</IfLabel>
          <IfInput id={`${id}-n`} className="w-full" value={form.displayName} maxLength={MAX_DISPLAY_NAME}
            aria-invalid={bad("display_name")}
            onChange={(e) => dispatch({ type: "set", patch: { displayName: e.target.value } })} />
          {form.accountId && !form.displayName.trim() && <IfHelp>Left blank: the Creator&rsquo;s OnlyFans name.</IfHelp>}
        </div>
        {form.error && <p role="alert" className="text-[12px] text-err">{form.error.msg}</p>}
      </form>
    </IfModal>
  );
}
