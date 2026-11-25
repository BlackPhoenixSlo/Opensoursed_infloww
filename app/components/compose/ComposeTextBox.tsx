"use client";

import { forwardRef, useImperativeHandle, useRef } from "react";
import { insertAtCursor } from "@/components/chat/EmojiBar";
import { IfTextArea } from "@/components/ui/infloww";
import { OfRichTextEditor, type OfRichTextEditorHandle } from "@/components/ui/OfRichTextEditor";
import { OF_TEXT_MAX } from "@/lib/ofRichText";
import { cn } from "@/lib/utils";

export interface ComposeTextBoxHandle {
  focus(): void;
  insert(s: string): void;
}

interface Props {
  value: string;
  onChange: (v: string) => void;
  placeholder: string;
  rows: number;
  rich: boolean;
  toolbar: boolean;
  disabled?: boolean;
}

export const ComposeTextBox = forwardRef<ComposeTextBoxHandle, Props>(function ComposeTextBox(
  { value, onChange, placeholder, rows, rich, toolbar, disabled }, ref,
) {
  const ta = useRef<HTMLTextAreaElement | null>(null);
  const ed = useRef<OfRichTextEditorHandle | null>(null);
  useImperativeHandle(ref, () => ({
    focus: () => (ed.current ? ed.current.focus() : ta.current?.focus()),
    insert: (s) => {
      if (ed.current) ed.current.insert(s);
      else if (ta.current) insertAtCursor(ta.current, value, s, onChange);
      else onChange(value + s);
    },
  }), [value, onChange]);

  if (rich) {
    return (
      <OfRichTextEditor ref={ed} value={value} onChange={onChange} placeholder={placeholder} aria-label={placeholder}
        toolbar={toolbar} maxLength={OF_TEXT_MAX} disabled={disabled}
        inputClassName={cn("max-md:text-base", rows >= 5 ? "min-h-[7.5rem]" : "min-h-24")} />
    );
  }
  return (
    <IfTextArea ref={ta} value={value} onChange={(e) => onChange(e.target.value)} placeholder={placeholder}
      rows={rows} maxLength={OF_TEXT_MAX} className="max-md:text-base" />
  );
});

export function AaButton({ on, onToggle }: { on: boolean; onToggle: () => void }) {
  return (
    <button type="button" onClick={onToggle} onMouseDown={(e) => e.preventDefault()} aria-pressed={on}
      title={on ? "Hide text formatting" : "Text formatting (bold, italic, colour, size)"}
      className={cn("grid place-items-center rounded-md px-2 text-[15px] font-semibold min-h-11 min-w-11 md:min-h-8 md:min-w-8",
        on ? "text-[var(--inf-accent-text,var(--color-accent))] bg-accent/10" : "text-fg-dim hover:text-fg")}>
      Aa
    </button>
  );
}
