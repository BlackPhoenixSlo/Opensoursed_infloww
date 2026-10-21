"use client";

/**
 * useComposerUploads — the chat Composer's uploads from the computer, restored
 * 2026-10-16 at the human's request (docs/spec/phase-04-composer-ppv-vault.md,
 * Out of Scope). Row 3's Upload, a drop on the Composer and a pasted image all
 * come through `add`.
 *
 * Each file goes to `POST /api/of/v2/upload` (the Creator's OF vault), one at a
 * time, as the removed `onPickLocalFile` did (commit 1ccd82f): OF's signed
 * upload and S3 PUT do not like parallel uploads. While a file waits or uploads
 * its chip spins (`relay.uploadFile` reports no progress). A failure keeps the
 * chip with the error and a Retry. A success drops the chip and hands
 * `onUploaded` the media, shaped as a Vault pick (`toAttachments`), so price,
 * free previews and send treat it the same. An image keeps a blob: preview
 * (`_localPreview`) for its tile and the sent bubble; a video gets none, as an
 * `<img>` cannot show it.
 *
 * Send does not wait for a running upload (2026-10-16): `handOff` takes the
 * uploading chips off the Composer and gives the send each file's `done`
 * promise, so the message goes out when its files land (useSendMessage).
 * The uploads run on a module-level queue per Creator, outside any mount, so
 * a handed-off upload keeps going when the chat closes.
 *
 * The Composer remounts per Fan chat (MessagesPro keys ChatSurface by account
 * and Fan), so chips are per Fan by mount. Unmounting cancels the chips'
 * uploads and revokes their previews; handed-off uploads are not the
 * Composer's any more (the send's `cancel` stops them). ✕ discards a chip.
 * A cancelled upload never starts if it is still queued; a running one is
 * aborted (the file may still land in the vault if OF already has it).
 *
 * An upload gets a deadline from its turn in the queue (`uploadDeadlineMs`):
 * past it the request is aborted and the upload fails as "timed out", so one
 * hung request cannot hold the Creator's queue for the session.
 */

import { useCallback, useEffect, useRef, useState } from "react";

import { revokePreviews } from "@/lib/blobPreviews";
import { relay, type VaultMedia, type VaultUploadResp } from "@/lib/relay";

export const UPLOAD_PATH = "/api/of/v2/upload";
/** The file chooser's `accept`; `isUploadable` applies it to drops and pastes. */
export const UPLOAD_ACCEPT = "image/*,video/*";

export function isUploadable(f: File): boolean {
  return f.type.startsWith("image/") || f.type.startsWith("video/");
}

export interface UploadChip {
  key: string;
  accountId: string;
  file: File;
  /** An image's blob: URL for the chip's thumbnail and the sent bubble; null
   *  for a video, and without `URL.createObjectURL` (jsdom). */
  previewUrl: string | null;
  status: "uploading" | "failed";
  error?: string;
}

// Claim attachments carry no vault id; negative ids keep React keys and
// removal distinct (the wire body sends `_claim`, not `id`).
let claimSeq = 0;

/** An upload response as Composer attachments: a vault id as a Vault pick
 *  (with the vault's files when the upload was a duplicate), a fresh claim
 *  dict as `_claim`. Throws the relay's note when the upload is not ready. */
export function toAttachments(resp: VaultUploadResp, file: File, previewUrl: string | null): VaultMedia[] {
  if (resp?.ready !== true) throw new Error(resp?.note || "Upload not ready");
  const type = file.type.startsWith("video") ? "video" : "photo";
  const local = previewUrl ?? undefined;
  const media = (resp.send_with ?? []).map((entry): VaultMedia =>
    typeof entry === "number"
      ? { id: entry, type: resp.existing?.type || type, files: resp.existing?.files ?? null, _localPreview: local }
      : { id: -(++claimSeq), type, files: null, _claim: entry, _localPreview: local },
  );
  if (media.length === 0) throw new Error("Upload returned no media");
  return media;
}

/** A failure as the chip and the failed bubble word it: OF's status for an
 *  upstream error, OF's own message (else its status) when its converter
 *  refused the file, a short relay note as it is, else a plain line. The raw
 *  text stays for the tooltip. */
export function uploadErrorText(raw: string): string {
  const upstream = /^upstream (\d{3})\b/.exec(raw);
  if (upstream) return `Upload failed — OnlyFans error ${upstream[1]}`;
  // The relay's note when OF's convert claim (the step after the S3 PUT)
  // answers non-2xx: "… convert register failed: 400 {"error":{…,"message":"Invalid input."}}".
  const convert = /convert register failed: (\d{3})/.exec(raw);
  if (convert) {
    const why = /"message"\s*:\s*"([^"]{1,60})"/.exec(raw)?.[1] ?? `error ${convert[1]}`;
    return `Upload failed — OnlyFans refused the file (${why})`;
  }
  if (raw && raw.length <= 60 && !/^[{[]/.test(raw)) return `Upload failed — ${raw}`;
  return "Upload failed";
}

export class UploadCancelled extends Error {}

/** How long one upload may take from its turn: two minutes, plus a second
 *  per 50 KB (a slow uplink), before it is aborted as timed out. */
export function uploadDeadlineMs(size: number): number {
  return 120_000 + size / 50;
}

// One queue per Creator: OF's signed upload and S3 PUT do not like parallel
// uploads. Module-level so an upload outlives the Composer that started it.
const queues = new Map<string, Promise<unknown>>();

/** Upload one file to the Creator's vault after the uploads queued before it,
 *  as Composer attachments. `cancel` aborting stops it: before its turn it
 *  never starts, during it the request is aborted; either way it rejects
 *  with `UploadCancelled`. */
export function uploadToVault(
  accountId: string, file: File, previewUrl: string | null, cancel?: AbortSignal,
): Promise<VaultMedia[]> {
  const run = (queues.get(accountId) ?? Promise.resolve()).then(async () => {
    if (cancel?.aborted) throw new UploadCancelled();
    const ctl = new AbortController();
    let stop!: (why: Error) => void;
    // Race the request too: the queue moves on at once even if the request
    // ignores its abort.
    const stopped = new Promise<never>((_, reject) => {
      stop = (why) => {
        ctl.abort();
        reject(why);
      };
    });
    const onCancel = () => stop(new UploadCancelled());
    cancel?.addEventListener("abort", onCancel);
    const timer = setTimeout(() => stop(new Error("timed out")), uploadDeadlineMs(file.size));
    try {
      const resp = await Promise.race([
        relay.uploadFile<VaultUploadResp>(UPLOAD_PATH, file, "file", { accountId }, ctl.signal),
        stopped,
      ]);
      return toAttachments(resp, file, previewUrl);
    } finally {
      clearTimeout(timer);
      cancel?.removeEventListener("abort", onCancel);
    }
  });
  queues.set(accountId, run.catch(() => undefined));
  return run;
}

/** An upload a send waits on: the file (for a re-upload on Retry), its
 *  preview (for the pending bubble), the attachments it lands as, and how to
 *  cancel it (the bubble discarded). */
export interface PendingUpload {
  file: File;
  previewUrl: string | null;
  done: Promise<VaultMedia[]>;
  cancel: () => void;
}

/** Who a chip's attempt answers to: the Composer, nobody (removed, retried,
 *  left), or the send it was handed to. */
type Owner = { to: "composer" | "dropped" | "send" };

type Attempt = { owner: Owner; ctl: AbortController; done: Promise<VaultMedia[]> };

/** The chip's attempt is nobody's now: it stops, and its result is ignored. */
function dropAttempt(a: Attempt) {
  a.owner.to = "dropped";
  a.ctl.abort();
}

let chipSeq = 0;

export function useComposerUploads(
  accountId: string | null,
  onUploaded: (media: VaultMedia[]) => void,
) {
  const [chips, setChips] = useState<UploadChip[]>([]);
  // The current attempt of each live chip, and the promise it lands with.
  const attempts = useRef(new Map<string, Attempt>());
  const latest = useRef(onUploaded);
  latest.current = onUploaded;
  const chipsRef = useRef(chips);
  chipsRef.current = chips;

  // Leaving the chat cancels the chips' uploads. Handed-off uploads are no
  // longer in `attempts`.
  useEffect(() => () => {
    for (const a of attempts.current.values()) dropAttempt(a);
    attempts.current.clear();
    revokePreviews(chipsRef.current.map((c) => c.previewUrl));
  }, []);

  const start = useCallback((chip: UploadChip) => {
    const prior = attempts.current.get(chip.key);
    if (prior) dropAttempt(prior);
    const owner: Owner = { to: "composer" };
    const ctl = new AbortController();
    const done = uploadToVault(chip.accountId, chip.file, chip.previewUrl, ctl.signal);
    attempts.current.set(chip.key, { owner, ctl, done });
    done.then(
      (media) => {
        if (owner.to !== "composer") return;
        attempts.current.delete(chip.key);
        setChips((prev) => prev.filter((c) => c.key !== chip.key));
        latest.current(media);
      },
      (err) => {
        if (owner.to !== "composer") return;
        const error = err instanceof Error && err.message ? err.message : "Upload failed";
        setChips((prev) => prev.map((c) => (c.key === chip.key ? { ...c, status: "failed", error } : c)));
      },
    );
  }, []);

  const add = useCallback((files: File[]) => {
    if (!accountId) return;
    const added = files.filter(isUploadable).map((file): UploadChip => ({
      key: `upload-${++chipSeq}`,
      accountId,
      file,
      previewUrl: file.type.startsWith("image/") && typeof URL.createObjectURL === "function"
        ? URL.createObjectURL(file)
        : null,
      status: "uploading",
    }));
    if (added.length === 0) return;
    setChips((prev) => [...prev, ...added]);
    added.forEach(start);
  }, [accountId, start]);

  const retry = useCallback((key: string) => {
    const chip = chips.find((c) => c.key === key);
    if (!chip) return;
    setChips((prev) => prev.map((c) => (c.key === key ? { ...c, status: "uploading", error: undefined } : c)));
    start(chip);
  }, [chips, start]);

  const discard = useCallback((drop: (c: UploadChip) => boolean) => {
    const gone = chips.filter(drop);
    for (const c of gone) {
      const a = attempts.current.get(c.key);
      if (a) dropAttempt(a);
      attempts.current.delete(c.key);
    }
    revokePreviews(gone.map((c) => c.previewUrl));
    setChips((prev) => prev.filter((c) => !drop(c)));
  }, [chips]);

  const remove = useCallback((key: string) => discard((c) => c.key === key), [discard]);
  /** Drop every chip (the PPV row's Clear). */
  const clear = useCallback(() => discard(() => true), [discard]);

  /** Give the uploading chips to a send: they leave the Composer (their
   *  previews now the pending bubble's) and keep uploading after it unmounts,
   *  until the send cancels them. */
  const handOff = useCallback((): PendingUpload[] => {
    const handed: PendingUpload[] = [];
    for (const c of chips) {
      const a = c.status === "uploading" ? attempts.current.get(c.key) : undefined;
      if (!a) continue;
      a.owner.to = "send";
      attempts.current.delete(c.key);
      const { ctl } = a;
      handed.push({ file: c.file, previewUrl: c.previewUrl, done: a.done, cancel: () => ctl.abort() });
    }
    if (handed.length > 0) setChips((prev) => prev.filter((c) => c.status !== "uploading"));
    return handed;
  }, [chips]);

  return {
    chips,
    uploading: chips.some((c) => c.status === "uploading"),
    failed: chips.some((c) => c.status === "failed"),
    add,
    retry,
    remove,
    clear,
    handOff,
  };
}
