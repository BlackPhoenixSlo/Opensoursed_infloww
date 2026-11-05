"use client";

/**
 * EditPostModal — lightweight editor for an existing feed post's TEXT and
 * PRICE via PUT /api/of/v2/posts/{id}.
 *
 * Deliberately scoped to text + price (the common edits). Re-attaching /
 * reordering media is intentionally NOT here: the feed payload only gives
 * us media id stubs, and a partial media_files array would drop the rest
 * of the post's media on OF. The relay does a sparse update, so omitting
 * media_files leaves the existing media untouched.
 */

import { useId, useState } from "react";
import { useMutation } from "@tanstack/react-query";

import { IfButton, IfHelp, IfInput, IfLabel, IfModal, IfTextArea } from "@/components/ui/infloww";
import { sanitizePriceInput } from "@/lib/priceInput";
import { postPlainText, type OFPost } from "@/hooks/usePosts";
import { relay } from "@/lib/relay";

interface Props {
  post: OFPost;
  accountId: string;
  onClose: () => void;
  onSaved: (patch: { text: string; price: number }) => void;
}

export default function EditPostModal({ post, accountId, onClose, onSaved }: Props) {
  const initialText = post.rawText ?? postPlainText(post);
  const initialPrice =
    typeof post.price === "string" ? post.price : post.price != null ? String(post.price) : "";

  const [text, setText] = useState(initialText);
  const [price, setPrice] = useState(initialPrice);
  const [error, setError] = useState<string | null>(null);
  const textId = useId();
  const priceId = useId();

  const save = useMutation({
    mutationFn: async () => {
      const priceNum = price ? Number(price) : 0;
      if (!Number.isFinite(priceNum) || priceNum < 0) throw new Error("Invalid price");
      const trimmed = text.trim();
      if (!trimmed) throw new Error("Text can't be empty");

      const body: Record<string, unknown> = { text: trimmed, price: priceNum };

      if (priceNum > 0) {
        // OF rejects a paid post that doesn't declare its protected media
        // ("Paid post must contain protected content"). A sparse PUT with
        // only price omits that, so we must re-send the media to lock. Pull
        // the AUTHORITATIVE media set from the post detail rather than the
        // (possibly lossy) feed payload — sending a partial list would drop
        // the rest of the post's media on OF. Preserve existing free
        // previews so re-pricing doesn't silently lock the teasers.
        const detail = await relay.get<{
          media?: { id: number }[];
          previews?: number[];
        }>(`/api/of/v2/posts/${post.id}`, { accountId });
        const mediaIds = (detail.media ?? [])
          .map((m) => m.id)
          .filter((id) => typeof id === "number" && Number.isFinite(id));
        if (mediaIds.length === 0) {
          throw new Error(
            "This is a text-only post — OnlyFans can't charge for it. Set the price to 0, or add media to the post on OnlyFans first.",
          );
        }
        body.media_files = mediaIds;
        if (Array.isArray(detail.previews) && detail.previews.length > 0) {
          body.previews = detail.previews;
        }
      }

      await relay.put(`/api/of/v2/posts/${post.id}`, body, { accountId });
      return { text: trimmed, price: priceNum };
    },
    onSuccess: (patch) => {
      onSaved(patch);
      onClose();
    },
    onError: (err: Error) => setError(err.message),
  });

  const close = () => { if (!save.isPending) onClose(); };
  return (
    <IfModal
      title="Edit post"
      width={520}
      onClose={close}
      footer={<>
        <IfButton onClick={onClose} disabled={save.isPending}>Cancel</IfButton>
        <IfButton variant="primary" onClick={() => { setError(null); save.mutate(); }} disabled={save.isPending}>
          {save.isPending ? "Saving…" : "Save"}
        </IfButton>
      </>}
    >
      <div className="space-y-4">
        <div>
          <IfLabel htmlFor={textId}>Text</IfLabel>
          <IfTextArea id={textId} value={text} onChange={(e) => setText(e.target.value)} rows={5}
            placeholder="Post text…" />
        </div>

        <div>
          <IfLabel htmlFor={priceId}>Price (USD)</IfLabel>
          <IfInput id={priceId} value={price} onChange={(e) => setPrice(sanitizePriceInput(e.target.value))}
            inputMode="decimal" placeholder="0" className="w-40" />
          <IfHelp>0 = free. A price locks the post&apos;s existing media behind the paywall.</IfHelp>
        </div>

        {error && <div role="alert" className="text-[14px] text-err">{error}</div>}
      </div>
    </IfModal>
  );
}
