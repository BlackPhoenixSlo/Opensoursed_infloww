"use client";

/**
 * RawJsonModal — the one raw-JSON editor dialog (presentation only). The callers own loading, parsing and saving:
 * EditRuleJsonModal (PATCH one automation rule) and JsonConfigModal (a per-account config blob).
 */

import type { ReactNode } from "react";

import { IfButton, IfHelp, IfModal } from "@/components/ui/infloww";
import { IF_FIELD } from "@/components/ui/ifSelect";
import { cn } from "@/lib/utils";

export function RawJsonModal({
  name, subtitle, text, onText, error, status, busy, onReformat, onSave, onClose,
}: {
  /** "Edit raw JSON · {name}". */
  name: string;
  subtitle?: ReactNode;
  text: string;
  onText: (text: string) => void;
  error?: string | null;
  /** Shown instead of the textarea (loading / load failed); disables Reformat and Save. */
  status?: ReactNode;
  busy?: boolean;
  onReformat: () => void;
  onSave: () => void;
  onClose: () => void;
}) {
  return (
    <IfModal
      width={820}
      title={`Edit raw JSON · ${name}`}
      onClose={onClose}
      footer={(
        <>
          <IfButton variant="link" onClick={onReformat} disabled={!!status} className="mr-2">Reformat</IfButton>
          <IfButton onClick={onClose}>Cancel</IfButton>
          <IfButton variant="primary" onClick={onSave} disabled={busy || !!status}>
            {busy ? "Saving…" : "Save"}
          </IfButton>
        </>
      )}
    >
      {subtitle && <IfHelp className="-mt-3 mb-3 truncate">{subtitle}</IfHelp>}
      {status ? (
        <div className="py-10 text-center text-muted">{status}</div>
      ) : (
        <textarea
          aria-label="Raw JSON"
          value={text}
          onChange={(e) => onText(e.target.value)}
          spellCheck={false}
          placeholder="{ }"
          className={cn(IF_FIELD, "block h-[52vh] w-full resize-none px-[11px] py-1 font-mono text-[13px] outline-none placeholder:text-muted focus:border-accent")}
        />
      )}
      {error && <div className="mt-2 whitespace-pre-wrap text-[12px] text-err">{error}</div>}
    </IfModal>
  );
}
