"use client";


import { useState, type ReactNode } from "react";

import { IfButton, IfHelp, IfModal, IfTextArea } from "@/components/ui/infloww";
import { cn } from "@/lib/utils";

export function RawJsonEditor({ label, text, onText, error, status, placeholder, className }: {
  label: string;
  text: string;
  onText: (text: string) => void;
  error?: string | null;
  status?: ReactNode;
  placeholder?: string;
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
  name: string;
  subtitle?: ReactNode;
  text: string;
  onText: (text: string) => void;
  error?: string | null;
  status?: ReactNode;
  busy?: boolean;
  onReformat: () => void;
  onSave: () => void;
  onClose: () => void;
}) {
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
