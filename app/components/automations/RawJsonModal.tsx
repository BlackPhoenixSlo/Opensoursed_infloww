"use client";

/**
 * RawJsonModal — the one raw-JSON editor dialog (presentation only). The callers own loading, parsing and saving:
 * EditRuleJsonModal (PATCH one automation rule) and JsonConfigModal (a per-account config blob).
 * Its parts, controlled (the caller owns the text): `RawJsonEditor` (textarea, or a status line instead, and the error
 * under it) and `RawJsonActions` (Reformat and Save with its busy label). FullAiSettings' config JSON renders two of
 * each in its own dialog.
 */

import { useState, type ReactNode } from "react";

import { IfButton, IfHelp, IfModal, IfTextArea } from "@/components/ui/infloww";
import { cn } from "@/lib/utils";

/** The textarea (or `status` instead of it) and the error under it. */
export function RawJsonEditor({ label, text, onText, error, status, placeholder, className }: {
  /** The textarea's accessible name. */
  label: string;
  text: string;
  onText: (text: string) => void;
  error?: string | null;
  /** Shown instead of the textarea (loading / load failed). */
  status?: ReactNode;
  placeholder?: string;
  /** The textarea's height and text size. */
  className?: string;
}) {
  return (
    <div className="flex min-w-0 flex-col gap-2">
      {status ? (
        <div className="py-10 text-center text-muted">{status}</div>
      ) : (
        <IfTextArea
          aria-label={label}
          value={text}
          onChange={(e) => onText(e.target.value)}
          spellCheck={false}
          placeholder={placeholder}
          className={cn("resize-none font-mono", className)}
        />
      )}
      {error && <div className="whitespace-pre-wrap text-[12px] text-err">{error}</div>}
    </div>
  );
}

/** Reformat, then `children` (the dialog's Cancel), then Save ("Saving…"-style `busyLabel` while `busy`). */
export function RawJsonActions({
  onReformat, reformatDisabled, onSave, saveDisabled, busy, saveLabel = "Save", busyLabel = "Saving…", reformatClassName, children,
}: {
  onReformat: () => void;
  reformatDisabled?: boolean;
  onSave: () => void;
  saveDisabled?: boolean;
  busy?: boolean;
  saveLabel?: string;
  busyLabel?: string;
  /** For a row with no gap of its own (the dialog footer). */
  reformatClassName?: string;
  children?: ReactNode;
}) {
  return (
    <>
      <IfButton variant="link" onClick={onReformat} disabled={reformatDisabled} className={reformatClassName}>Reformat</IfButton>
      {children}
      <IfButton variant="primary" onClick={onSave} disabled={saveDisabled}>
        {busy ? busyLabel : saveLabel}
      </IfButton>
    </>
  );
}

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
        <RawJsonActions onReformat={onReformat} reformatDisabled={!!status} onSave={onSave}
          saveDisabled={busy || !!status} busy={busy} reformatClassName="mr-2">
          <IfButton onClick={onClose}>Cancel</IfButton>
        </RawJsonActions>
      )}
    >
      {subtitle && <IfHelp className="-mt-3 mb-3 truncate">{subtitle}</IfHelp>}
      <RawJsonEditor label="Raw JSON" text={text} onText={(t) => { setTyped(true); onText(t); }} error={error}
        status={status} placeholder="{ }" className="h-[52vh] text-[13px]" />
    </IfModal>
  );
}
