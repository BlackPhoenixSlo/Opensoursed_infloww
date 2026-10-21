"use client";

/**
 * Growth > Scripts' Import from Excel, Import from other creators and Share (`docs/infloww-layouts/growth-scripts.md`
 * #94 to #98), over `service/scripts_import_api.py`.
 *
 * - Excel: the bundle's two steps (download "Script templates.xlsx", upload an .xlsx), then its result, "You've
 *   imported a total of N data items…", with each failed row listed (the bundle offers them as a downloadable report;
 *   ours lists them in place).
 * - Other creators and Share are one copy: pick up to 5 Creators to import from, or the Creators to share to. Media
 *   stays on its own account (ADR-0008), so a copied script arrives without it, and the result says how many lost it.
 */

import { useRef, useState } from "react";
import { CheckCircle2, Download, Upload } from "lucide-react";

import { IfButton, IfModal } from "@/components/ui/infloww";
import { useCopySavedReplies, useImportSavedReplies, type SavedReplyCopyResult } from "@/hooks/useSavedReplies";
import type { AccountMeta } from "@/lib/relay";

const MAX_SOURCES = 5;
const creatorName = (a: AccountMeta) => a.nickname || a.name || a.id;

export function ExcelImportDialog({ accountId, onClose }: { accountId: string | null; onClose: () => void }) {
  const [file, setFile] = useState<File | null>(null);
  const input = useRef<HTMLInputElement>(null);
  const upload = useImportSavedReplies(accountId);
  const result = upload.data;

  if (result) {
    return (
      <IfModal title="Import successful" onClose={onClose} footer={<IfButton onClick={onClose}>Close</IfButton>}>
        <div className="flex flex-col items-center text-center">
          <CheckCircle2 className="mb-2 h-[42px] w-[42px] text-ok" aria-hidden />
          <p className="text-fg-dim">
            You&apos;ve imported a total of {result.total} data items. Of these,{" "}
            <span className="text-ok">{result.success_count}</span> were successful and{" "}
            <span className="text-err">{result.fail_count}</span> failed.
          </p>
        </div>
        {result.failed.length > 0 && (
          <ul aria-label="Failed data" className="mt-3 max-h-48 space-y-0.5 overflow-y-auto rounded-md border border-border p-2 text-xs">
            {result.failed.map((f) => (
              <li key={`${f.sheet}:${f.row}`}>
                <span className="text-fg-dim">{f.sheet}, row {f.row}:</span>{" "}
                <span className="font-medium">{f.name || "(no name)"}</span>{" "}
                <span className="text-fg-dim">— {f.reason}</span>
              </li>
            ))}
          </ul>
        )}
      </IfModal>
    );
  }

  return (
    <IfModal
      title="Import scripts from Excel"
      closable={!upload.isPending}
      onClose={onClose}
      footer={<>
        <IfButton onClick={onClose} disabled={upload.isPending}>Cancel</IfButton>
        <IfButton variant="primary" disabled={!file || !accountId || upload.isPending}
          onClick={() => file && accountId && upload.mutate(file)}>
          {upload.isPending ? "Importing…" : "Import"}
        </IfButton>
      </>}
    >
      <p className="mb-2">Step1: Download the script template and fill in the data:</p>
      <a href="/admin/saved-replies/import-template" download="Script Templates.xlsx"
        className="mb-1 inline-flex items-center gap-2 text-accent hover:opacity-90">
        <Download size={18} aria-hidden />Script templates.xlsx
      </a>
      <p className="mb-4 text-xs text-fg-dim">
        Each sheet is a tag. Row 1 names the columns: name (up to 64 characters), text (up to 1000) and note (up to
        246). At most 1000 scripts a sheet; a name the Creator already has is skipped.
      </p>
      <p className="mb-2">Step2: Upload the Excel file below (.xlsx only):</p>
      <button
        type="button"
        onClick={() => input.current?.click()}
        className="flex w-full flex-col items-center justify-center gap-1 rounded-lg border border-dashed border-border py-6 text-accent hover:border-accent"
      >
        <Upload size={24} aria-hidden />
        <span className="w-[95%] truncate text-center">{file ? file.name : "Select"}</span>
      </button>
      <input
        ref={input}
        type="file"
        hidden
        aria-label="Excel file"
        accept=".xlsx,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        onChange={(e) => {
          setFile(e.target.files?.[0] ?? null);
          upload.reset();
        }}
      />
      {upload.isError && <p role="alert" className="mt-2 text-xs text-err">Import failed: {upload.error.message}</p>}
    </IfModal>
  );
}

/** Import from other creators (`mode` "import": the picked Creators' scripts come here) or Share (`mode` "share":
 *  `ids`, or every script when omitted, go to the picked Creators). `onCopied` runs once the copy succeeded. */
export function CopyScriptsDialog({
  mode, accountId, accounts, ids, onClose, onCopied,
}: {
  mode: "import" | "share";
  accountId: string | null;
  accounts: AccountMeta[];
  ids?: number[];
  onClose: () => void;
  onCopied?: () => void;
}) {
  const [picked, setPicked] = useState<string[]>([]);
  const copy = useCopySavedReplies();
  const others = accounts.filter((a) => a.id !== accountId);
  const importing = mode === "import";
  const full = importing && picked.length >= MAX_SOURCES;

  const submit = () => {
    if (!accountId || picked.length === 0) return;
    copy.mutate(importing
      ? { fromAccountIds: picked, toAccountIds: [accountId] }
      : { fromAccountIds: [accountId], toAccountIds: picked, ids }, { onSuccess: () => onCopied?.() });
  };

  if (copy.data) {
    return (
      <IfModal title={importing ? "Import successful" : "Shared"} onClose={onClose}
        footer={<IfButton onClick={onClose}>Close</IfButton>}>
        <CopySummary result={copy.data} />
      </IfModal>
    );
  }

  return (
    <IfModal
      title={importing ? "Import scripts from other creators" : "Share script with other Creators"}
      width={480}
      closable={!copy.isPending}
      onClose={onClose}
      footer={<>
        <IfButton onClick={onClose} disabled={copy.isPending}>Cancel</IfButton>
        <IfButton variant="primary" disabled={picked.length === 0 || copy.isPending} onClick={submit}>
          {copy.isPending ? "Copying…" : "Confirm"}
        </IfButton>
      </>}
    >
      <p className="mb-2 text-fg-dim">
        {importing
          ? `Up to ${MAX_SOURCES} creators can be selected.`
          : ids
            ? `${ids.length} script${ids.length === 1 ? "" : "s"} to share.`
            : "Every script of this Creator is shared."}
        {" "}Media is not copied between Creators; a script name the Creator already has is skipped.
      </p>
      {others.length === 0 ? (
        <p className="text-fg-dim">No other Creator.</p>
      ) : (
        <ul aria-label="Creators" className="max-h-64 space-y-1 overflow-y-auto">
          {others.map((a) => {
            const on = picked.includes(a.id);
            return (
              <li key={a.id}>
                <label className="flex items-center gap-2">
                  <input
                    type="checkbox"
                    className="accent-accent"
                    checked={on}
                    disabled={!on && full}
                    onChange={(e) =>
                      setPicked((p) => (e.target.checked ? [...p, a.id] : p.filter((x) => x !== a.id)))
                    }
                  />
                  <span className="truncate">{creatorName(a)}</span>
                </label>
              </li>
            );
          })}
        </ul>
      )}
      {copy.isError && <p role="alert" className="mt-2 text-xs text-err">{copy.error.message}</p>}
    </IfModal>
  );
}

function CopySummary({ result }: { result: SavedReplyCopyResult }) {
  return (
    <div className="flex flex-col items-center text-center">
      <CheckCircle2 className="mb-2 h-[42px] w-[42px] text-ok" aria-hidden />
      <p className="text-fg-dim">
        <span className="text-ok">{result.copied}</span> script{result.copied === 1 ? "" : "s"} copied
        {result.skipped > 0 && <>, {result.skipped} skipped (the name was already there)</>}.
      </p>
      {result.media_dropped > 0 && (
        <p className="mt-1 text-xs text-fg-dim">
          {result.media_dropped} arrived without their media: add it from the Creator&apos;s own vault.
        </p>
      )}
      {result.sequence_dropped > 0 && (
        <p className="mt-1 text-xs text-fg-dim">
          {result.sequence_dropped} arrived outside their sequence: that step was already taken.
        </p>
      )}
    </div>
  );
}
