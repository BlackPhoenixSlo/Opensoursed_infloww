import { revokePreviews } from "@/lib/blobPreviews";
import type { OFMessage, VaultMedia } from "@/lib/relay";

export interface SendInput {
  text: string;
  price?: number;
  lockedText?: boolean;
  attached?: VaultMedia[];
  previews?: number[];
  scheduledAt?: string;
  replyToMessageId?: number | string;
  replyToMessage?: OFMessage["replyToMessage"];
  taggedUsers?: number[];
  giphyId?: string;
}

export interface StashedFile {
  file: File;
  previewUrl: string | null;
  media?: VaultMedia[];
  cancel?: () => void;
}

export interface StashEntry {
  input: SendInput;
  opId: string;
  files: StashedFile[];
}

const entries = new Map<number, StashEntry>();
const deliveredIds = new Set<number>();
export const DELIVERED_CAP = 200;

// Module-level like temp ids: a send waiting on its files finishes after the chat closes, and Retry works from the reopened chat.
export const sendStash = {
  get(tempId: number): StashEntry | undefined {
    return entries.get(tempId);
  },
  set(tempId: number, entry: StashEntry): void {
    entries.set(tempId, entry);
  },
  sent(tempId: number): void {
    entries.delete(tempId);
    deliveredIds.delete(tempId);
    deliveredIds.add(tempId);
    if (deliveredIds.size > DELIVERED_CAP) deliveredIds.delete(deliveredIds.values().next().value as number);
  },
  delivered(tempId: number): boolean {
    return deliveredIds.has(tempId);
  },
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

export function clearSendStash(): void {
  for (const tempId of [...entries.keys()]) sendStash.discard(tempId);
  deliveredIds.clear();
}
