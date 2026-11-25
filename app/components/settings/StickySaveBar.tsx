"use client";


import type { ReactNode } from "react";
import { Save } from "lucide-react";

import { Button } from "@/components/ui/primitives";
import { IF_BTN_PRIMARY } from "@/components/settings/ifButton";
import { cn } from "@/lib/utils";

export type SaveControl = {
  onSave: () => void;
  saving: boolean;
  // The load gate, a data-loss guard: these endpoints REPLACE the whole blob, so saving an unseeded form overwrites real settings.
  canSave?: boolean;
  label?: string;
  saved?: boolean;
  error?: string | null;
  gateNote?: GateNote | null;
  size?: "sm" | "md";
  variant?: "primary" | "ghost";
  look?: "house" | "settings";
};

export type GateNote = {
  text: string;
  failed: boolean;
};

export function loadGateNote(q: {
  data: unknown; isError: boolean; isSuccess: boolean;
}): GateNote | null {
  // An empty 200 ("") and JSON null both leave the form unseeded.
  if (q.data) {
    return q.isSuccess ? null : {
      text: "Couldn't refresh these settings — what's on screen is still yours.",
      failed: true,
    };
  }
  if (q.isSuccess || q.isError) {
    return {
      text: "These settings never loaded — saving would replace them with defaults.",
      failed: true,
    };
  }
  return {
    text: "Still waiting for these settings — Save is off until they arrive.",
    failed: false,
  };
}

export function RetryLoad({ q }: {
  q: { isFetching: boolean; refetch: () => unknown };
}) {
  return (
    <Button size="sm" variant="secondary" disabled={q.isFetching}
      onClick={() => void q.refetch()}>
      {q.isFetching ? "Retrying…" : "Retry"}
    </Button>
  );
}

export type GateNotePalette = "legacy" | "settings";

const GATE_NOTE_CLASSES: Record<GateNotePalette, { base: string; failed: string; waiting: string }> = {
  legacy: { base: "text-xs", failed: "text-err", waiting: "text-fg-dim" },
  settings: { base: "text-[length:var(--if-fs-sm)]", failed: "text-[var(--if-danger)]", waiting: "text-[var(--if-fg-2)]" },
};

export function GateNoteText({ note, palette = "legacy" }: { note: GateNote; palette?: GateNotePalette }) {
  const c = GATE_NOTE_CLASSES[palette];
  return <span className={cn(c.base, note.failed ? c.failed : c.waiting)}>{note.text}</span>;
}

export function SaveRow({
  onSave, saving, canSave = true, label = "Save", size = "md",
  variant = "primary", look = "house", saved, error, gateNote, children, className, testId,
}: SaveControl & {
  children?: ReactNode;
  className?: string;
  testId?: string;
}) {
  return (
    <div
      data-testid={testId}
      className={cn("flex items-center gap-2 flex-wrap", className)}
    >
      {look === "settings" ? (
        <button type="button" className={IF_BTN_PRIMARY} onClick={onSave} disabled={saving || !canSave}>
          {saving ? "Saving…" : label}
        </button>
      ) : (
        <Button size={size} variant={variant} onClick={onSave}
          disabled={saving || !canSave}>
          <Save size={14} />
          {saving ? "Saving…" : label}
        </Button>
      )}
      {saved && <span className="text-xs text-ok">Saved ✓</span>}
      {error && <span className="text-xs text-err">{error}</span>}
      {gateNote && <GateNoteText note={gateNote} palette={look === "settings" ? "settings" : "legacy"} />}
      {children}
    </div>
  );
}

export type PinPolicy = "always" | "desktop-only";

const PIN_DISPLAY: Record<PinPolicy, string> = {
  always: "flex",
  "desktop-only": "hidden md:flex",
};

const BLEED: Record<0 | 4 | 5, string> = {
  0: "px-0",
  4: "-mx-4 px-4",
  5: "-mx-5 px-5",
};

export default function StickySaveBar({
  pin = "always",
  hostPadding = 4,
  children,
  ...control
}: SaveControl & {
  pin?: PinPolicy;
  hostPadding?: 0 | 4 | 5;
  children?: ReactNode;
}) {
  return (
    <SaveRow
      {...control}
      testId="sticky-save-bar"
      className={cn(
        // z-20: under modals (z-50+), the toaster and the z-40 docks, so a dialog opened from a tab covers this bar.
        "sticky bottom-0 z-20 py-3 rounded-b-2xl",
        "bg-panel/95 backdrop-blur border-t border-border",
        "pb-[calc(env(safe-area-inset-bottom)+0.75rem)]",
        BLEED[hostPadding],
        PIN_DISPLAY[pin],
      )}
    >
      {children}
    </SaveRow>
  );
}
