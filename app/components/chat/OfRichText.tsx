"use client";

/**
 * An OF message body as the fan sees it: OF's rich text (bold, italic, OF's colours and sizes, lib/ofRichText's
 * allow-list) built as React nodes, never `dangerouslySetInnerHTML`. Markup without formatting renders as its plain
 * text (`ofPlainText`, lines kept); text that is not markup renders exactly as written. The classes are OF's own; globals.css
 * draws them under `.of-rt` (the default colour inherits, so it reads on every bubble and theme).
 */
import { useMemo, type ReactNode } from "react";

import { docHasFormatting, isOfHtml, ofPlainText, parseOfHtml, type OfRun } from "@/lib/ofRichText";
import { cn } from "@/lib/utils";

function Run({ r }: { r: OfRun }): ReactNode {
  if ("br" in r) return "\n";
  let n: ReactNode = r.text;
  // OF's own nesting (its wire, lib/ofMirrorFormat): span outermost, size class first.
  if (r.italic) n = <em>{n}</em>;
  if (r.bold) n = <strong>{n}</strong>;
  const cls = [r.size, r.color].filter(Boolean).join(" ");
  if (cls) n = <span className={cls}>{n}</span>;
  return n;
}

export function OfRichText({ raw, className, title, as: Tag = "span" }: {
  raw: string; className?: string; title?: string;
  /** The root element (a script row's text is its own `<p>`). */
  as?: "span" | "p" | "div";
}) {
  const doc = useMemo(() => (isOfHtml(raw) ? parseOfHtml(raw) : null), [raw]);
  // Not OF markup (a typed script, a local echo): exactly as written, `<VIP20>` and `&amp;` included.
  if (!doc) return <Tag className={className} title={title}>{raw}</Tag>;
  if (!docHasFormatting(doc)) return <Tag className={className} title={title}>{ofPlainText(raw)}</Tag>;
  // Paragraphs end a line each, as `ofPlainText` reads them: the bubble's pre-wrap draws the breaks.
  const nodes: ReactNode[] = [];
  doc.forEach((p, i) => {
    if (i > 0) nodes.push("\n");
    p.forEach((r, j) => nodes.push(<Run key={`${i}.${j}`} r={r} />));
  });
  return <Tag data-of-rich="" className={cn("of-rt whitespace-pre-wrap", className)} title={title}>{nodes}</Tag>;
}
