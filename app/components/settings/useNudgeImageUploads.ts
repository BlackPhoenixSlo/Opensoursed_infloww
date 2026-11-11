"use client";

/**
 * useNudgeImageUploads — images dropped (or chosen) on a Nudge online slot go into the Creator's vault through the
 * Vault page's import (`importAndWait`), because a slot stores vault ids and a plain upload is only a one-send claim.
 * While a file imports its chip spins in the slot; a landed file leaves its chip and `onLanded` adds its vault id to
 * the slot; a failed one keeps its chip with the reason until dismissed. A chip dismissed while it spins is let go:
 * its file may still land in the vault, but not in the slot. One list of chips: the one state here.
 */

import { useCallback, useEffect, useRef, useState } from "react";

import { importAndWait } from "@/lib/vaultImport";
import { type DayBucket } from "@/components/settings/nudgeDayBuckets";

export interface NudgeUploadChip {
  key: string;
  accountId: string;
  bucket: DayBucket;
  slotKey: string;
  name: string;
  /** The image's blob: URL (null without `URL.createObjectURL`, jsdom). */
  previewUrl: string | null;
  error: string | null;
}

export interface Landed { accountId: string; bucket: DayBucket; slotKey: string; ids: number[]; previews: (string | null)[] }

let seq = 0;

export function isImageFile(f: File): boolean {
  return f.type.startsWith("image/");
}

export function useNudgeImageUploads(onLanded: (l: Landed) => void) {
  const [chips, setChips] = useState<NudgeUploadChip[]>([]);
  const latest = useRef(onLanded);
  useEffect(() => { latest.current = onLanded; });
  // Chips let go while spinning: their landing is ignored.
  const dropped = useRef(new Set<string>());

  const upload = useCallback((accountId: string, bucket: DayBucket, slotKey: string, all: File[]) => {
    const files = all.filter(isImageFile);
    if (files.length === 0) return;
    const mine: NudgeUploadChip[] = files.map((f) => ({
      key: `nu${++seq}`, accountId, bucket, slotKey, name: f.name, error: null,
      previewUrl: typeof URL.createObjectURL === "function" ? URL.createObjectURL(f) : null,
    }));
    setChips((cs) => [...cs, ...mine]);
    const fail = (key: string, error: string) =>
      setChips((cs) => cs.map((c) => (c.key === key ? { ...c, error } : c)));
    importAndWait(files, accountId).then(
      (res) => {
        const ok = res.flatMap((r, i) =>
          (r.vaultId != null && !dropped.current.has(mine[i].key) ? [{ id: r.vaultId, chip: mine[i] }] : []));
        if (ok.length) {
          latest.current({ accountId, bucket, slotKey, ids: ok.map((o) => o.id), previews: ok.map((o) => o.chip.previewUrl) });
        }
        const done = new Set(ok.map((o) => o.chip.key));
        setChips((cs) => cs.filter((c) => !done.has(c.key)));
        res.forEach((r, i) => { if (r.vaultId == null) fail(mine[i].key, r.error || "Upload failed"); });
      },
      (e: unknown) => {
        const msg = (e as Error)?.message || "Upload failed";
        mine.forEach((c) => fail(c.key, /409|already running|in progress/i.test(msg)
          ? "Another vault import is running; try again when it ends" : msg));
      },
    );
  }, []);

  const dismiss = useCallback((key: string) => {
    dropped.current.add(key);
    setChips((cs) => cs.filter((c) => c.key !== key));
  }, []);

  return { chips, upload, dismiss };
}
