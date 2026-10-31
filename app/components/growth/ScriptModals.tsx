"use client";

/** ScriptsPage's two modals (growth-scripts #72, #81, #83): the tag / sequence name prompt and the script editor's
 *  frame. */

import { useState, type ReactNode } from "react";

import { extractError } from "@/components/settings/TemplateDraftEditor";
import { IfButton, IfModal } from "@/components/ui/infloww";

/** A tag or sequence name modal (#81, #83): title, one field, "Enter name", Cancel / OK. `onOk` may throw; its
 *  message shows under the field (e.g. "Sequence name already exists"). */
export function NameModal({
  title, label, initial = "", maxLength, options, onOk, onClose,
}: {
  title: string;
  label: string;
  initial?: string;
  maxLength: number;
  options?: string[];
  onOk: (name: string) => Promise<void> | void;
  onClose: () => void;
}) {
  const [name, setName] = useState(initial);
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const submit = async () => {
    const v = name.trim();
    if (!v) return;
    setBusy(true);
    setErr(null);
    try {
      await onOk(v);
      onClose();
    } catch (e) {
      setErr(extractError(e));
    } finally {
      setBusy(false);
    }
  };
  const footer = (
    <>
      <IfButton onClick={onClose}>Cancel</IfButton>
      <IfButton variant="primary" onClick={() => void submit()} disabled={!name.trim() || busy}>OK</IfButton>
    </>
  );
  return (
    <IfModal title={title} width={520} closable={!busy} onClose={onClose} footer={footer}>
      {/* #82: the bundle's body is `padding:24px 16px 4px`; IfModal's body is 24px all round. */}
      <div className="-mx-2 -mb-5">
        <label htmlFor="script-name-modal-input" className="block text-sm mb-1">
          {label}<span aria-hidden className="text-err ml-0.5">*</span>
        </label>
        <input
          id="script-name-modal-input"
          autoFocus
          type="text"
          list={options ? "script-name-modal-options" : undefined}
          maxLength={maxLength}
          value={name}
          placeholder="Enter name"
          onChange={(e) => setName(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && void submit()}
          className="w-full h-8 rounded-md border border-border bg-bg px-[11px] text-sm text-fg outline-none placeholder:text-muted hover:border-accent focus:border-accent"
        />
        {options && (
          <datalist id="script-name-modal-options">
            {options.map((o) => <option key={o} value={o} />)}
          </datalist>
        )}
        {err && <div className="mt-1 text-xs text-err">{err}</div>}
      </div>
    </IfModal>
  );
}

/** The script editor's frame (#72): antd's 535px modal titled "Add script" or "Edit script" around the saved-reply
 *  editor (story 25), which holds the fields, Cancel and OK. Escape and the × close it, except while saving. */
export function ScriptEditModal({ title, saving, onClose, children }: {
  title: string;
  saving: boolean;
  onClose: () => void;
  children: ReactNode;
}) {
  return (
    <IfModal title={title} width={535} closable={!saving} onClose={onClose}>
      {children}
    </IfModal>
  );
}
