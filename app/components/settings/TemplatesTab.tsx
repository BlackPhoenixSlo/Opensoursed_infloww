"use client";

/**
 * Saved-reply editing state, shared by Growth > Scripts (`ScriptsPage`).
 *
 * Saved replies live in local SQLite (/admin/saved-replies/*). OF's
 * /messages/templates rejects creates for everything but the welcome slot, so
 * regular replies never round-trip through OF; the composer reads them locally.
 * The draft form itself is `TemplateDraftEditor`.
 */

import { useEffect, useState } from "react";

import {
  EMPTY_REPLY,
  extractError,
  revealDraft,
  type TemplateDraft,
} from "@/components/settings/TemplateDraftEditor";
import { useActiveAccounts } from "@/hooks/useAccounts";
import {
  useSavedReplies,
  useCreateSavedReply,
  useDeleteSavedReply,
  useUpdateSavedReply,
} from "@/hooks/useSavedReplies";
import type { SavedReply, VaultMedia } from "@/lib/relay";

function localMediaToVault(r: SavedReply): VaultMedia[] {
  return (r.media ?? []).map((m) => ({
    id: m.id,
    type: (m.type as VaultMedia["type"]) || "photo",
    files: m.files ?? null,
  }));
}

/**
 * The saved-reply list and its editor, for one Creator: the list read, the
 * one open draft, and create / edit / delete through `/admin/saved-replies`.
 * `save` only ever saves a reply draft.
 */
export function useSavedReplyEditor(accountId: string | null) {
  const [draft, setDraft] = useState<TemplateDraft | null>(null);
  const [saveErr, setSaveErr] = useState<string | null>(null);

  // Local saved replies.
  const replyQ = useSavedReplies(accountId);
  const createReplyM = useCreateSavedReply(accountId);
  const updateReplyM = useUpdateSavedReply(accountId);
  const deleteReplyM = useDeleteSavedReply(accountId);
  const replies = replyQ.data ?? [];

  function startNewReply(seed?: Partial<TemplateDraft>) {
    setDraft({ ...EMPTY_REPLY, ...seed });
    setSaveErr(null);
    revealDraft();
  }

  function startEditReply(r: SavedReply) {
    const attached = localMediaToVault(r);
    const attachedIds = new Set(attached.map((m) => m.id));
    setDraft({
      kind: "reply",
      id: r.id,
      title: r.title ?? "",
      text: r.text,
      price: r.price ? String(r.price) : "",
      lockedText: !!r.locked_text,
      attached,
      previews: (r.previews ?? []).filter((id) => attachedIds.has(id)),
      // The picker resolves the live name/avatar by querying OF when its
      // popover opens; we only persist ids, so seed the chip row with
      // placeholder labels that the user can replace by re-tagging if
      // they care about the display name.
      taggedCreators: (r.tagged_users ?? []).map((id) => ({
        id, name: `user${id}`, username: "", avatar: null,
      })),
      gif: r.gif_id
        ? { id: r.gif_id, thumbUrl: r.gif_url ?? "", fullUrl: r.gif_url ?? "" }
        : null,
      scriptId: r.script_id ?? "",
      scriptStep: r.script_step != null ? String(r.script_step) : "",
      tags: r.tags ?? [],
      notes: r.notes ?? "",
    });
    setSaveErr(null);
    revealDraft();
  }

  async function save() {
    if (draft?.kind !== "reply") return;
    const text = draft.text.trim();
    if (!text) return;
    const price = Number(draft.price) || 0;
    setSaveErr(null);
    try {
      // Filter previews down to ids actually attached so deletions
      // don't leave orphan preview ids that confuse the composer.
      const attachedIds = new Set(draft.attached.map((m) => m.id));
      const previewIds = new Set(
        draft.previews.filter((id) => attachedIds.has(id)),
      );
      // Reorder on save: FREE-marked tiles first, then PPV. The chat
      // composer's preview model is count-based ("leading N tiles are
      // free"), so without this rewrite a user who clicked FREE on the
      // 2nd tile would, on apply, see tile #1 marked FREE and tile #2
      // marked PPV. Stable within each group so the user's manual
      // ordering between free-vs-free / paid-vs-paid is preserved.
      const orderedAttached =
        price > 0 && previewIds.size > 0
          ? [
              ...draft.attached.filter((m) => previewIds.has(m.id)),
              ...draft.attached.filter((m) => !previewIds.has(m.id)),
            ]
          : draft.attached;
      const body = {
        title: draft.title.trim() || null,
        text,
        price,
        lockedText: price > 0 ? draft.lockedText : false,
        media: orderedAttached.map((m) => ({
          id: m.id,
          type: m.type,
          files: m.files ?? null,
        })),
        taggedUsers: draft.taggedCreators.map((c) => c.id),
        previews: price > 0 ? Array.from(previewIds) : [],
        gifId: draft.gif?.id ?? null,
        gifUrl: draft.gif?.thumbUrl ?? draft.gif?.fullUrl ?? null,
        // Only persist the script pair when both halves are present —
        // a script id without a step (or vice versa) can't anchor the
        // next-step lookup, so coerce to null and don't surface it.
        scriptId: draft.scriptId.trim() || null,
        scriptStep:
          draft.scriptId.trim() && /^\d+$/.test(draft.scriptStep.trim())
            ? Number(draft.scriptStep)
            : null,
        tags: draft.tags,
        notes: draft.notes.trim() || null,
      };
      if (typeof draft.id === "number") {
        await updateReplyM.mutateAsync({ id: draft.id, ...body });
      } else {
        await createReplyM.mutateAsync(body);
      }
      setDraft(null);
    } catch (err) {
      const msg = extractError(err);
      console.warn("[templates] save failed", err);
      setSaveErr(msg);
    }
  }

  async function removeReply(id: number) {
    if (!confirm("Delete this saved reply?")) return;
    try { await deleteReplyM.mutateAsync(id); }
    catch (err) { console.warn("[templates] delete reply failed", err); }
  }

  const saving = createReplyM.isPending || updateReplyM.isPending;
  const deletingId = deleteReplyM.isPending ? deleteReplyM.variables : undefined;

  return {
    draft, setDraft, saveErr, saving, deletingId,
    replyQ, replies, startNewReply, startEditReply, save, removeReply,
  };
}

/** The Creator a saved-reply page is scoped to: the first session-backed one until another is picked. */
export function useScopedAccount() {
  const accounts = useActiveAccounts();
  const [accountId, setAccountId] = useState<string | null>(null);
  useEffect(() => {
    if (!accountId && accounts.length > 0) setAccountId(accounts[0].id);
  }, [accountId, accounts]);
  return [accountId, setAccountId] as const;
}
