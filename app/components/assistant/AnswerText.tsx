"use client";


import type { ReactNode } from "react";
import Link from "next/link";

import { cn } from "@/lib/utils";
import { findPaths, type PathHit } from "./answerLinks";
import { parseMarkers } from "./markers";
import { MarkerCards } from "./MarkerCards";

export { findPaths };

const INLINE_RE = /`([^`\n]+)`|\*\*([^\n]+?)\*\*|\*([^*\n]+?)\*/g;

function linked(text: string, offset: number, hits: PathHit[], key: number, onNavigate?: () => void): ReactNode[] {
  const out: ReactNode[] = [];
  let last = 0;
  hits.forEach((h, i) => {
    const start = Math.max(h.start - offset, 0);
    const end = Math.min(h.end - offset, text.length);
    if (end <= start) return;
    if (start > last) out.push(text.slice(last, start));
    out.push(
      <Link
        key={`l${key}-${i}`}
        href={h.href}
        onClick={onNavigate}
        className="text-accent underline decoration-accent/40 underline-offset-2 hover:decoration-accent"
      >
        {text.slice(start, end)}
      </Link>,
    );
    last = end;
  });
  if (last < text.length) out.push(text.slice(last));
  return out;
}

// Model output: build React nodes only, never dangerouslySetInnerHTML.
function inline(text: string, onNavigate: (() => void) | undefined, pages: ReadonlySet<string>): ReactNode[] {
  const spans: Array<{ kind: "text" | "code" | "bold" | "italic"; text: string }> = [];
  let last = 0;
  let m: RegExpExecArray | null;
  INLINE_RE.lastIndex = 0;
  while ((m = INLINE_RE.exec(text))) {
    const [, code, bold, italic] = m;
    if (m.index > last) spans.push({ kind: "text", text: text.slice(last, m.index) });
    if (code !== undefined) spans.push({ kind: "code", text: code });
    else if (bold !== undefined) spans.push({ kind: "bold", text: bold });
    else spans.push({ kind: "italic", text: italic });
    last = INLINE_RE.lastIndex;
  }
  if (last < text.length) spans.push({ kind: "text", text: text.slice(last) });

  // Paths are found on the plain text: the bot bolds a path's labels, so span-by-span would link the last word alone.
  const hits = findPaths(spans.map((s) => (s.kind === "code" ? "\n".repeat(s.text.length) : s.text)).join(""), pages);
  let offset = 0;
  return spans.flatMap((s, i): ReactNode[] => {
    const at = offset;
    offset += s.text.length;
    if (s.kind === "code") {
      return [
        <code
          key={`c${i}`}
          className="px-1 py-0.5 rounded bg-bg-elev-1 border border-border text-[11px] font-mono break-words"
        >
          {s.text}
        </code>,
      ];
    }
    const body = linked(s.text, at, hits, i, onNavigate);
    if (s.kind === "bold") {
      return [
        <strong key={`b${i}`} className="font-semibold text-fg">
          {body}
        </strong>,
      ];
    }
    return s.kind === "italic" ? [<em key={`i${i}`}>{body}</em>] : body;
  });
}

type BlockKind = "p" | "ul" | "ol" | "h";
interface Block {
  kind: BlockKind;
  items: string[];
}

const LINE_KINDS: Array<[Exclude<BlockKind, "p">, RegExp]> = [
  ["h", /^\s*#{1,6}\s+(.*)$/],
  ["ul", /^\s*[-*•]\s+(.*)$/],
  ["ol", /^\s*\d+[.)]\s+(.*)$/],
];

const INDENT_RE = /^\s{2,}\S/;

function classify(line: string): { kind: BlockKind; text: string } {
  for (const [kind, re] of LINE_KINDS) {
    const m = re.exec(line);
    if (m) return { kind, text: m[1] };
  }
  return { kind: "p", text: line.trim() };
}

function parse(text: string): Block[] {
  const blocks: Block[] = [];
  let open: Block | null = null;

  for (const line of text.split("\n")) {
    if (!line.trim()) {
      open = null;
      continue;
    }

    if (open && (open.kind === "ul" || open.kind === "ol") && INDENT_RE.test(line)) {
      open.items[open.items.length - 1] += ` ${line.trim()}`;
      continue;
    }

    const { kind, text: content } = classify(line);
    if (!open || open.kind !== kind || kind === "h") {
      open = { kind, items: [] };
      blocks.push(open);
    }
    open.items.push(content);
  }
  return blocks;
}

export function AnswerText({
  text, muted, onNavigate, focus = null, accountIds = null, canChat = false, pages,
}: {
  text: string; muted?: boolean; onNavigate?: () => void; focus?: string | null; accountIds?: string[] | null; canChat?: boolean;
  pages: ReadonlySet<string>;
}) {
  const { text: prose, markers } = parseMarkers(text);
  const blocks = parse(prose);

  return (
    <div className={cn("flex flex-col gap-1.5", muted && "text-fg-dim")}>
      {blocks.map((b, i) => {
        if (b.kind === "h") {
          return (
            <p key={i} className="font-semibold text-fg">
              {inline(b.items[0], onNavigate, pages)}
            </p>
          );
        }
        if (b.kind === "p") {
          return (
            <p key={i} className="break-words">
              {inline(b.items.join(" "), onNavigate, pages)}
            </p>
          );
        }
        const List = b.kind;
        return (
          <List
            key={i}
            className={cn(
              "flex flex-col gap-1 pl-4 break-words",
              b.kind === "ul" ? "list-disc" : "list-decimal",
            )}
          >
            {b.items.map((it, j) => (
              <li key={j} className="marker:text-fg-dim">
                {inline(it, onNavigate, pages)}
              </li>
            ))}
          </List>
        );
      })}
      {markers.length > 0 && <MarkerCards markers={markers} focus={focus} accountIds={accountIds} canChat={canChat} onNavigate={onNavigate} />}
    </div>
  );
}
