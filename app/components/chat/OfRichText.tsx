"use client";

import { useMemo, type ReactNode } from "react";

import { docHasFormatting, isOfHtml, ofPlainText, parseOfHtml, type OfRun } from "@/lib/ofRichText";
import { cn } from "@/lib/utils";

function Run({ r }: { r: OfRun }): ReactNode {
  if ("br" in r) return "\n";
  let n: ReactNode = r.text;
  if (r.italic) n = <em>{n}</em>;
  if (r.bold) n = <strong>{n}</strong>;
  const cls = [r.size, r.color].filter(Boolean).join(" ");
  if (cls) n = <span className={cls}>{n}</span>;
  return n;
}

export function OfRichText({ raw, className, title, as: Tag = "span" }: {
  raw: string; className?: string; title?: string;
  as?: "span" | "p" | "div";
}) {
  const doc = useMemo(() => (isOfHtml(raw) ? parseOfHtml(raw) : null), [raw]);
  if (!doc) return <Tag className={className} title={title}>{raw}</Tag>;
  if (!docHasFormatting(doc)) return <Tag className={className} title={title}>{ofPlainText(raw)}</Tag>;
  // React nodes only, never dangerouslySetInnerHTML.
  const nodes: ReactNode[] = [];
  doc.forEach((p, i) => {
    if (i > 0) nodes.push("\n");
    p.forEach((r, j) => nodes.push(<Run key={`${i}.${j}`} r={r} />));
  });
  return <Tag data-of-rich="" className={cn("of-rt whitespace-pre-wrap", className)} title={title}>{nodes}</Tag>;
}
