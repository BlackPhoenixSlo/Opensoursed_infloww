"use client";

/**
 * RawJsonModal — the one raw-JSON editor dialog (presentation only). The callers own loading, parsing and saving:
 * EditRuleJsonModal (PATCH one automation rule) and JsonConfigModal (a per-account config blob).
 */

import { useState, type ReactNode } from "react";

import { IfButton, IfHelp, IfModal, IfTextArea } from "@/components/ui/infloww";

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
  // Escape closes only an untyped buffer (the caller's async seed is not a user edit), and never mid-save.
  const [typed, setTyped] = useState(false);
  return (
    <IfModal
      width={820}
      title={`Edit raw JSON · ${name}`}
      onClose={onClose}
      keyboard={!typed && !busy}
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
        <IfTextArea
          aria-label="Raw JSON"
          value={text}
          onChange={(e) => { setTyped(true); onText(e.target.value); }}
          spellCheck={false}
          placeholder="{ }"
          className="h-[52vh] resize-none font-mono text-[13px]"
        />
      )}
      {error && <div className="mt-2 whitespace-pre-wrap text-[12px] text-err">{error}</div>}
    </IfModal>
  );
}
