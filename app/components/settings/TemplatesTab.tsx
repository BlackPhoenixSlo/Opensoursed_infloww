"use client";


import { useEffect, useState } from "react";

import {
  EMPTY_REPLY,
  revealDraft,
  type TemplateDraft,
} from "@/components/settings/TemplateDraftEditor";
import { extractError } from "@/components/settings/extractError";
import { useActiveAccounts } from "@/hooks/useAccounts";
import {
  useSavedReplies,
  useCreateSavedReply,
  useDeleteSavedReply,
  useUpdateSavedReply,
} from "@/hooks/useSavedReplies";
import { isSourceScript } from "@/lib/chatSlots";
import type { SavedReply, VaultMedia } from "@/lib/relay";
import { ifConfirm } from "@/components/ui/ifConfirm";

function localMediaToVault(r: SavedReply): VaultMedia[] {
  return (r.media ?? []).map((m) => ({
    id: m.id,
    type: (m.type as VaultMedia["type"]) || "photo",
    files: m.files ?? null,
  }));
}

export function useSavedReplyEditor(accountId: string | null) {
  const [draft, setDraft] = useState<TemplateDraft | null>(null);
  const [saveErr, setSaveErr] = useState<string | null>(null);

  const replyQ = useSavedReplies(accountId);
  const createReplyM = useCreateSavedReply(accountId);
  const updateReplyM = useUpdateSavedReply(accountId);
  const deleteReplyM = useDeleteSavedReply(accountId);
  const replies = (replyQ.data ?? []).filter((r) => !isSourceScript(r.script_id));

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
      const attachedIds = new Set(draft.attached.map((m) => m.id));
      const previewIds = new Set(
        draft.previews.filter((id) => attachedIds.has(id)),
      );
      // The composer preview is count-based (leading N tiles are free), so FREE-marked tiles must come first.
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
    if (!(await ifConfirm("Delete this saved reply?", { danger: true }))) return;
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

export function useScopedAccount() {
  const accounts = useActiveAccounts();
  const [accountId, setAccountId] = useState<string | null>(null);
  useEffect(() => {
    if (!accountId && accounts.length > 0) setAccountId(accounts[0].id);
  }, [accountId, accounts]);
  return [accountId, setAccountId] as const;
}
