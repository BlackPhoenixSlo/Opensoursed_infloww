"use client";

/**
 * The vault import's Google Drive section: an Inflowwww extra (Infloww's upload
 * area has no link import, growth-vault-pro#106), closed, after the card's three
 * steps, and only on a server with the Google Drive API key: without one it
 * renders nothing (Settings → AI keys holds the key and says what it is for).
 * The links themselves belong to the card, which sends them with Start import;
 * this owns the read-only preview of what they would import.
 */

import { useState } from "react";
import { useMutation } from "@tanstack/react-query";

import { useVaultAccountId } from "@/components/vault/VaultAccount";
import { ExtraTag } from "@/components/ui/primitives";
import { EXTRA_LABEL } from "@/lib/openinflowwwwExtras";
import { relay } from "@/lib/relay";
import { cn } from "@/lib/utils";

/** One file a Drive link would import, from the relay's read-only listing. */
interface DriveListed {
  name: string;
  size: number | null;
  hashtags: string[];
  importable: boolean;
  reason: string | null;
}

/** What the pasted links listed, and the links they were listed for. */
interface Listing {
  links: string;
  files: DriveListed[];
  maxFiles: number | null;
}

/** "N to import", capped at the run's file limit, which the import enforces. */
function importCount(importable: number, maxFiles: number | null): string {
  if (maxFiles != null && importable > maxFiles) return `${importable} to import (first ${maxFiles} this run)`;
  return `${importable} to import`;
}

export default function VaultImportDrive({
  configured,
  links,
  onLinks,
  disabled,
}: {
  /** The server has the Google Drive API key; false (also while the status read is pending) draws nothing. */
  configured: boolean;
  links: string;
  onLinks: (v: string) => void;
  disabled: boolean;
}) {
  const accountId = useVaultAccountId();
  const ctx = { accountId };
  const trimmed = links.trim();
  const [listing, setListing] = useState<Listing | null>(null);
  // A preview of OTHER links (edited since, or sent and cleared) is no preview.
  const listed = listing && listing.links === trimmed ? listing : null;

  // What the pasted links would import, and the hashtags each file gets from
  // its folder. Read-only on the relay — nothing moves.
  const listDrive = useMutation({
    mutationFn: async (raw: string): Promise<Listing> => {
      const files: DriveListed[] = [];
      let maxFiles: number | null = null;
      for (const link of raw.split(/[\n,]+/).map((l) => l.trim()).filter(Boolean)) {
        const r = await relay.get<{ files: DriveListed[]; max_files?: number }>(
          `/api/of/v2/vault/upload/drive/list?link=${encodeURIComponent(link)}`,
          ctx,
        );
        files.push(...(r.files ?? []));
        maxFiles = r.max_files ?? maxFiles;
      }
      return { links: raw, files, maxFiles };
    },
    onSuccess: setListing,
    onError: () => setListing(null),
  });
  const listError =
    listDrive.isError && listDrive.variables === trimmed
      ? listDrive.error instanceof Error
        ? listDrive.error.message
        : "Could not read that Drive link"
      : null;

  if (!configured) return null;
  const importable = listed?.files.filter((f) => f.importable).length ?? 0;
  const skipped = (listed?.files.length ?? 0) - importable;
  // `<details>` keeps the box mounted, so typed links survive a collapse. Drive
  // files skip step 3: the relay tags each with the folder it sits in.
  return (
    <details>

      <summary title={EXTRA_LABEL} className="cursor-pointer select-none text-xs text-fg-dim">
        Import from Google Drive <ExtraTag />
      </summary>
      <p className="mt-2 text-xs text-fg-dim">
        Paste a folder (or file) link. The folder must be shared as{" "}
        <strong className="text-fg">&quot;Anyone with the link&quot; can view</strong>{" "}
        — a
        private folder reads as not found. Files skip the edit step: each is tagged with
        the sub-folder it sits in, or the folder&apos;s own name for files at its top.
      </p>
      <textarea
        value={links}
        disabled={disabled}
        onChange={(e) => onLinks(e.target.value)}
        rows={2}
        placeholder="https://drive.google.com/drive/folders/…  (one per line)"
        className="mt-2 w-full rounded border border-border bg-bg px-2 py-1.5 text-xs disabled:opacity-50"
      />
      <div className="mt-1 flex items-center gap-3">
        <button
          type="button"
          disabled={!trimmed || listDrive.isPending || disabled}
          onClick={() => listDrive.mutate(trimmed)}
          className="rounded border border-border px-2 py-1 text-xs disabled:opacity-40"
        >
          {listDrive.isPending ? "Reading folder…" : "List files"}
        </button>
        {listed && (
          <span className="text-xs text-fg-dim">
            {importCount(importable, listed.maxFiles)}
            {skipped > 0 && ` · ${skipped} skipped`}
          </span>
        )}
      </div>
      {listError && <p className="mt-1 text-xs text-err">{listError}</p>}
      {listed && listed.files.length > 0 && (
        <ul aria-label="Drive files" className="mt-2 max-h-40 divide-y divide-border overflow-y-auto text-xs">
          {listed.files.map((f, i) => (
            <li key={`${f.name}-${i}`} className="flex items-baseline justify-between gap-3 py-1">
              <span className={cn("truncate", !f.importable && "text-fg-dim line-through")} title={f.reason ?? f.name}>
                {f.name}
              </span>
              <span className="shrink-0 text-fg-dim">
                {f.importable ? f.hashtags.map((t) => `#${t}`).join(" ") : f.reason}
              </span>
            </li>
          ))}
        </ul>
      )}
    </details>
  );
}
