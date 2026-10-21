/**
 * What an unsent message replays, by temp id (useSendMessage): the send's
 * input and its uploaded files, each with the media it landed as once it did.
 * Module-level, as temp ids are, so a send waiting on its files finishes after
 * the chat closes and Retry works from the reopened chat.
 *
 * An entry leaves on success (its previews stay: the sent bubble shows them),
 * on discard, and on an identity switch (`clearSendStash`, from the identity
 * wipes in UserContext and ChatterContext). The last two cancel its files'
 * uploads (a running one is aborted, a queued one never starts), revoke its
 * blob: previews, and stop the send: it checks that its entry is still the
 * stashed one before it sends.
 */

import { revokePreviews } from "@/lib/blobPreviews";
import type { OFMessage, VaultMedia } from "@/lib/relay";

/** An immediate send's input, as useSendMessage takes it (less the uploads
 *  still running, which become the entry's `files`). */
export interface SendInput {
  text: string;
  price?: number;
  lockedText?: boolean;
  /** Attached vault items. Their ids form the wire payload; their thumb
   *  URLs seed the optimistic bubble so the sender sees their picks
   *  instantly + survives reconcile via mergeMedia. */
  attached?: VaultMedia[];
  /** Vault ids (subset of `attached`) sent unlocked when `price > 0`.
   *  Empty / omitted = everything locked. */
  previews?: number[];
  /** ISO 8601 timestamp. If set + future, the message is queued via
   *  /messages/scheduled instead of /messages — no optimistic bubble. */
  scheduledAt?: string;
  /** OF native quote-reply target id. Threaded into both the wire body
   *  and the optimistic bubble so the sender sees their reply context
   *  immediately. */
  replyToMessageId?: number | string;
  /** Optimistic-only snapshot of the quoted message — used so the
   *  outgoing bubble can render a quote card before the server response
   *  comes back populated. */
  replyToMessage?: OFMessage["replyToMessage"];
  /** Numeric OF user ids of creators to @-tag (sent as `userTags`).
   *  Source: TagCreatorsPicker — never user-typed. */
  taggedUsers?: number[];
  /** Giphy id (e.g. "0ndspgUFbm9iQtyX2Q"). When set, OF treats the send
   *  as a GIF message — `text` typically empty, `media_files` empty,
   *  `giphyId` rides at the top level. One GIF per send. */
  giphyId?: string;
}

export interface StashedFile {
  file: File;
  previewUrl: string | null;
  /** The attachments it landed as; unset while it uploads or after it failed. */
  media?: VaultMedia[];
  /** Cancels its current upload attempt, if one runs or waits. */
  cancel?: () => void;
}

export interface StashEntry {
  input: SendInput;
  files: StashedFile[];
}

const entries = new Map<number, StashEntry>();

export const sendStash = {
  get(tempId: number): StashEntry | undefined {
    return entries.get(tempId);
  },
  set(tempId: number, entry: StashEntry): void {
    entries.set(tempId, entry);
  },
  /** The message went out: forget it, keeping its previews. */
  sent(tempId: number): void {
    entries.delete(tempId);
  },
  /** The message is discarded: forget it, cancel its uploads, revoke its
   *  previews. */
  discard(tempId: number): void {
    const entry = entries.get(tempId);
    if (!entry) return;
    entries.delete(tempId);
    for (const f of entry.files) f.cancel?.();
    revokePreviews([
      ...(entry.input.attached ?? []).map((m) => m._localPreview),
      ...entry.files.map((f) => f.previewUrl),
    ]);
  },
};

/** Drop every unsent message (an identity switch). */
export function clearSendStash(): void {
  for (const tempId of [...entries.keys()]) sendStash.discard(tempId);
}
