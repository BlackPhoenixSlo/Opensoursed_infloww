"use client";

import {
  forwardRef, useCallback, useEffect, useImperativeHandle, useLayoutEffect, useRef, useState,
  type ClipboardEvent as ReactClipboardEvent, type KeyboardEvent as ReactKeyboardEvent,
  type PointerEvent as ReactPointerEvent,
} from "react";
import { ChevronDown, RemoveFormatting } from "lucide-react";

import {
  applyFormat, COLORS, commandState, execCommand as exec, setOfHtml, SIZES, type FormatCommand,
} from "@/lib/ofMirrorFormat";
import {
  cutTo, editorHtmlOf, editorValue, formatAtCaret, marksAt, NO_MARKS, pastedOfHtml, plainLength, tidy, type Marks,
} from "@/lib/ofRichTextEditor";
import { cn } from "@/lib/utils";

export interface OfRichTextEditorHandle {
  insert(text: string): void;
  focus(): void;
}

type Props = {
  value: string;
  onChange: (value: string) => void;
  id?: string;
  placeholder?: string;
  maxLength?: number;
  required?: boolean;
  "aria-labelledby"?: string;
  "aria-label"?: string;
  className?: string;
  inputClassName?: string;
  toolbar?: boolean;
  disabled?: boolean;
  onKeyDown?: (e: ReactKeyboardEvent<HTMLDivElement>) => void;
  onPaste?: (e: ReactClipboardEvent<HTMLDivElement>) => void;
};

// Toolbar buttons take no focus on press so the editor keeps its selection (iOS Safari drops it on a tap anyway).
const keep = (e: ReactPointerEvent | React.MouseEvent) => e.preventDefault();
function insertAtRange(sel: Selection, node: Node): void {
  const r = sel.getRangeAt(0);
  r.deleteContents();
  const last = node.nodeType === Node.DOCUMENT_FRAGMENT_NODE ? node.lastChild : node;
  r.insertNode(node);
  if (!last) return;
  r.setStartAfter(last);
  r.collapse(true);
  sel.removeAllRanges();
  sel.addRange(r);
}
const TOOL = "inline-grid place-items-center rounded-md text-fg-dim hover:text-fg hover:bg-bg-elev-1 h-11 min-w-11 md:h-8 md:min-w-8 px-1";
const ON = "text-[#4166f6] bg-[#4166f6]/10 hover:text-[#4166f6]";

export const OfRichTextEditor = forwardRef<OfRichTextEditorHandle, Props>(function OfRichTextEditor(
  {
    value, onChange, id, placeholder, maxLength, required, className, inputClassName, toolbar = true, disabled,
    onKeyDown, onPaste, ...aria
  },
  ref,
) {
  const rootRef = useRef<HTMLDivElement>(null);
  const savedRange = useRef<Range | null>(null);
  const emitted = useRef<string | null>(null);
  const [marks, setMarks] = useState<Marks>(NO_MARKS);
  const [menu, setMenu] = useState<"size" | "color" | null>(null);

  useLayoutEffect(() => {
    const root = rootRef.current;
    if (!root || value === emitted.current) return;
    setOfHtml(root, editorHtmlOf(value));
    emitted.current = value;
  }, [value]);

  const refreshMarks = useCallback(() => {
    const root = rootRef.current;
    const sel = root?.ownerDocument.getSelection();
    if (!root || !sel?.rangeCount || !root.contains(sel.anchorNode)) return;
    savedRange.current = sel.getRangeAt(0).cloneRange();
    const m = marksAt(root, sel.anchorNode);
    const doc = root.ownerDocument;
    setMarks({ ...m, bold: m.bold || commandState(doc, "bold"), italic: m.italic || commandState(doc, "italic") });
  }, []);

  useEffect(() => {
    const doc = rootRef.current?.ownerDocument;
    if (!doc) return;
    doc.addEventListener("selectionchange", refreshMarks);
    return () => doc.removeEventListener("selectionchange", refreshMarks);
  }, [refreshMarks]);

  useEffect(() => {
    if (!menu) return;
    const close = (e: Event) => {
      if (e instanceof KeyboardEvent ? e.key === "Escape" : !(e.target as Element)?.closest?.("[data-of-rt-toolbar]")) setMenu(null);
    };
    document.addEventListener("pointerdown", close);
    document.addEventListener("keydown", close);
    return () => {
      document.removeEventListener("pointerdown", close);
      document.removeEventListener("keydown", close);
    };
  }, [menu]);

  const emit = useCallback(() => {
    const root = rootRef.current;
    if (!root) return;
    tidy(root);
    const v = editorValue(root);
    if (v === emitted.current) return;
    emitted.current = v;
    onChange(v);
  }, [onChange]);

  const restore = useCallback(() => {
    const root = rootRef.current;
    if (!root) return null;
    const sel = root.ownerDocument.getSelection();
    if (!sel) return null;
    let r = sel.rangeCount && root.contains(sel.anchorNode) ? sel.getRangeAt(0).cloneRange() : savedRange.current;
    if (!r || !root.contains(r.startContainer)) {
      r = root.ownerDocument.createRange();
      r.selectNodeContents(root.lastElementChild ?? root);
      r.collapse(false);
    }
    if (root.ownerDocument.activeElement !== root) root.focus({ preventScroll: true });
    sel.removeAllRanges();
    sel.addRange(r);
    return sel;
  }, []);

  const run = (cmd: FormatCommand) => {
    const root = rootRef.current;
    const sel = restore();
    if (!root || !sel) return;
    if (!sel.isCollapsed) applyFormat(root, cmd);
    else formatAtCaret(root, sel, cmd);
    setMenu(null);
    emit();
    refreshMarks();
  };

  const left = useCallback(() => {
    if (maxLength == null) return Infinity;
    const sel = rootRef.current?.ownerDocument.getSelection();
    const picked = sel && sel.rangeCount && rootRef.current?.contains(sel.anchorNode) ? sel.toString().length : 0;
    return maxLength - plainLength(emitted.current ?? "") + picked;
  }, [maxLength]);
  const room = (add: number) => add <= left();

  useImperativeHandle(ref, () => ({
    insert(text: string) {
      const root = rootRef.current;
      const sel = restore();
      if (!root || !sel) return;
      if (text.length > left()) return;
      if (!exec(root.ownerDocument, "insertText", text)) insertAtRange(sel, root.ownerDocument.createTextNode(text));
      emit();
    },
    focus() {
      restore();
    },
  }), [emit, left, restore]);

  const insertPlain = (text: string) => {
    text = cutTo(text, left());
    if (text) exec(rootRef.current?.ownerDocument, "insertText", text);
  };
  const paste = (html: string, text: string) => {
    const root = rootRef.current;
    const marked = html && root ? pastedOfHtml(html, root.ownerDocument) : null;
    if (!root || !marked || plainLength(marked) > left()) return insertPlain(text);
    const one = /^<p>((?:(?!<\/?p>).)*)<\/p>$/s.exec(marked);
    if (exec(root.ownerDocument, "insertHTML", one ? one[1] : marked)) return;
    const sel = root.ownerDocument.getSelection();
    if (!sel?.rangeCount) return;
    const tpl = root.ownerDocument.createElement("template");
    tpl.innerHTML = one ? one[1] : marked;
    insertAtRange(sel, tpl.content);
  };
  const len = plainLength(value);
  const size = SIZES.find((s) => s.cls === marks.size) ?? SIZES.find((s) => s.cls === "m-editor-fs__default")!;
  const color = COLORS.find((c) => c.cls === marks.color && c.css)?.css;

  return (
    <div className={cn("rounded-lg border border-border bg-bg focus-within:border-accent", className)}>
      {toolbar && <div data-of-rt-toolbar="" role="toolbar" aria-label="Text formatting"
        className="relative flex flex-wrap items-center gap-0.5 border-b border-border px-1 py-0.5">
        <button type="button" title="Text size" aria-label={`Text size: ${size.label}`} aria-haspopup="menu" aria-expanded={menu === "size"}
          onPointerDown={keep} onMouseDown={keep} onClick={() => setMenu((m) => (m === "size" ? null : "size"))}
          className={cn(TOOL, "grid-flow-col gap-1 px-2 text-sm text-fg")}>
          <span className="min-w-[4.5rem] text-left">{size.label}</span>
          <ChevronDown size={14} aria-hidden />
        </button>
        <button type="button" title="Bold" aria-label="Bold" aria-pressed={marks.bold}
          onPointerDown={keep} onMouseDown={keep} onClick={() => run({ kind: "bold" })}
          className={cn(TOOL, "font-bold text-[15px]", marks.bold && ON)}>B</button>
        <button type="button" title="Italic" aria-label="Italic" aria-pressed={marks.italic}
          onPointerDown={keep} onMouseDown={keep} onClick={() => run({ kind: "italic" })}
          className={cn(TOOL, "italic font-serif text-[16px]", marks.italic && ON)}>I</button>
        <button type="button" title="Text color" aria-label="Text color" aria-haspopup="menu" aria-expanded={menu === "color"}
          onPointerDown={keep} onMouseDown={keep} onClick={() => setMenu((m) => (m === "color" ? null : "color"))}
          className={cn(TOOL, "flex-col gap-0 text-[15px] font-semibold", !!color && "text-fg")}>
          <span className="leading-none">A</span>
          <span aria-hidden className="mt-0.5 block h-[3px] w-4 rounded-full" style={{ background: color ?? "currentColor" }} />
        </button>
        <span aria-hidden className="mx-1 h-5 w-px bg-border" />
        <button type="button" title="Clear formatting" aria-label="Clear formatting"
          onPointerDown={keep} onMouseDown={keep} onClick={() => run({ kind: "clear" })}
          className={TOOL}>
          <RemoveFormatting size={16} aria-hidden />
        </button>
        {maxLength != null && (
          <span className={cn("ml-auto px-2 text-[11px] tabular-nums", len > maxLength ? "text-err" : "text-fg-dim")}>
            {len}/{maxLength}
          </span>
        )}
        {menu === "size" && (
          <div role="menu" aria-label="Text size"
            className="absolute left-1 top-full z-20 mt-1 w-48 max-w-[calc(100%-8px)] rounded-lg border border-border bg-bg-elev-1 p-1 shadow-xl">
            {SIZES.map((s) => (
              <button key={s.cls} type="button" role="menuitemradio" aria-checked={size.cls === s.cls}
                onPointerDown={keep} onMouseDown={keep} onClick={() => run({ kind: "size", cls: s.cls })}
                className={cn("of-rt flex w-full items-center rounded-md px-3 text-left min-h-11 md:min-h-8 hover:bg-bg",
                  size.cls === s.cls && "text-[#4166f6]")}>
                <span className={s.cls}>{s.label}</span>
              </button>
            ))}
          </div>
        )}
        {menu === "color" && (
          <div role="menu" aria-label="Text color"
            className="absolute left-1 top-full z-20 mt-1 flex items-center gap-2 rounded-lg border border-border bg-bg-elev-1 p-2 shadow-xl">
            {COLORS.map((c) => (
              <span key={c.cls} className="contents">
                {!c.css && <span aria-hidden className="h-6 w-px bg-border" />}
                <button type="button" role="menuitemradio" aria-label={c.label} title={c.label}
                  aria-checked={(marks.color ?? "m-editor-fc__default") === c.cls}
                  onPointerDown={keep} onMouseDown={keep} onClick={() => run({ kind: "color", cls: c.cls })}
                  className="grid h-11 w-11 place-items-center rounded-full md:h-8 md:w-8">
                  <span className={cn("block h-6 w-6 rounded-full ring-offset-2 ring-offset-bg-elev-1",
                    (marks.color ?? "m-editor-fc__default") === c.cls && "ring-2 ring-[#4166f6]",
                    !c.css && "bg-fg")} style={c.css ? { background: c.css } : undefined} />
                </button>
              </span>
            ))}
          </div>
        )}
      </div>}
      <div
        ref={rootRef}
        id={id}
        role="textbox"
        aria-multiline="true"
        aria-required={required || undefined}
        aria-placeholder={placeholder}
        {...{ placeholder }}
        data-maxlength={maxLength}
        data-empty={len === 0 ? "true" : undefined}
        {...aria}
        aria-disabled={disabled || undefined}
        contentEditable={!disabled}
        suppressContentEditableWarning
        spellCheck
        onFocus={() => exec(rootRef.current?.ownerDocument, "defaultParagraphSeparator", "p")}
        onInput={(e) => {
          // An IME's composition is left alone (normalizing would move its text under it): read once it ends.
          if (!(e.nativeEvent as InputEvent).isComposing) emit();
        }}
        onCompositionEnd={emit}
        onBeforeInput={(e) => {
          const ev = e.nativeEvent as InputEvent;
          const t = ev.inputType ?? "insertText";
          if (!ev.isComposing && t !== "insertCompositionText" && t.startsWith("insert") && !room((ev.data ?? " ").length)) {
            e.preventDefault();
          }
        }}
        onKeyDown={(e) => {
          onKeyDown?.(e);
          if (e.defaultPrevented || e.key !== "Enter" || !e.shiftKey || e.nativeEvent.isComposing) return;
          e.preventDefault();
          if (room(1)) exec(rootRef.current?.ownerDocument, "insertParagraph");
        }}
        onPaste={(e) => {
          onPaste?.(e);
          if (e.defaultPrevented) return;
          e.preventDefault();
          paste(e.clipboardData.getData("text/html"), e.clipboardData.getData("text/plain"));
        }}
        onDrop={(e) => {
          e.preventDefault();
          const doc = rootRef.current?.ownerDocument;
          const at = (doc as Document & { caretRangeFromPoint?: (x: number, y: number) => Range | null })
            ?.caretRangeFromPoint?.(e.clientX, e.clientY);
          if (at && rootRef.current?.contains(at.startContainer)) {
            const sel = doc!.getSelection();
            sel?.removeAllRanges();
            sel?.addRange(at);
          }
          insertPlain(e.dataTransfer.getData("text/plain"));
        }}
        onKeyUp={refreshMarks}
        onMouseUp={refreshMarks}
        className={cn(
          "of-rt relative min-h-24 max-h-[40vh] overflow-y-auto px-3 py-2 text-base md:text-sm leading-relaxed",
          "whitespace-pre-wrap break-words outline-none [&_p]:min-h-[1lh]",
          "data-[empty=true]:before:pointer-events-none data-[empty=true]:before:absolute",
          "data-[empty=true]:before:text-muted data-[empty=true]:before:content-[attr(placeholder)]",
          disabled && "cursor-not-allowed",
          inputClassName,
        )}
      />
    </div>
  );
});
