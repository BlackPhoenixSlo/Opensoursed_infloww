"use client";


import { useCallback, useEffect, useRef, useState } from "react";

import { revokePreviews } from "@/lib/blobPreviews";
import { relay, type VaultMedia, type VaultUploadResp } from "@/lib/relay";

export const UPLOAD_PATH = "/api/of/v2/upload";
export const UPLOAD_ACCEPT = "image/*,video/*";

export function isUploadable(f: File): boolean {
  return f.type.startsWith("image/") || f.type.startsWith("video/");
}

export interface UploadChip {
  key: string;
  accountId: string;
  file: File;
  previewUrl: string | null;
  status: "uploading" | "failed";
  error?: string;
}

let claimSeq = 0;

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

export function uploadErrorText(raw: string): string {
  const upstream = /^upstream (\d{3})\b/.exec(raw);
  if (upstream) return `Upload failed — OnlyFans error ${upstream[1]}`;
  // Relay note when OF's convert claim (after the S3 PUT) answers non-2xx.
  const convert = /convert register failed: (\d{3})/.exec(raw);
  if (convert) {
    const why = /"message"\s*:\s*"([^"]{1,60})"/.exec(raw)?.[1] ?? `error ${convert[1]}`;
    return `Upload failed — OnlyFans refused the file (${why})`;
  }
  if (raw && raw.length <= 60 && !/^[{[]/.test(raw)) return `Upload failed — ${raw}`;
  return "Upload failed";
}

export class UploadCancelled extends Error {}

export function uploadDeadlineMs(size: number): number {
  return 120_000 + size / 50;
}

// One queue per Creator: OF's signed upload and S3 PUT do not like parallel uploads.
const queues = new Map<string, Promise<unknown>>();

export function uploadToVault(
  accountId: string, file: File, previewUrl: string | null, cancel?: AbortSignal,
): Promise<VaultMedia[]> {
  const run = (queues.get(accountId) ?? Promise.resolve()).then(async () => {
    if (cancel?.aborted) throw new UploadCancelled();
    const ctl = new AbortController();
    let stop!: (why: Error) => void;
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

export interface PendingUpload {
  file: File;
  previewUrl: string | null;
  done: Promise<VaultMedia[]>;
  cancel: () => void;
}

type Owner = { to: "composer" | "dropped" | "send" };

type Attempt = { owner: Owner; ctl: AbortController; done: Promise<VaultMedia[]> };

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
  const attempts = useRef(new Map<string, Attempt>());
  const latest = useRef(onUploaded);
  latest.current = onUploaded;
  const chipsRef = useRef(chips);
  chipsRef.current = chips;

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
  const clear = useCallback(() => discard(() => true), [discard]);

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
