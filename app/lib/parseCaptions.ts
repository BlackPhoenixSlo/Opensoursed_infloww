/**
 * parseCaptions — turn a pasted/uploaded caption file into a text-variant pool.
 *
 *   • JSON (text starts with `[` / `{` and parses): an array of strings, an
 *     array of objects (first string `text|caption|message|content` field), or
 *     an object holding such an array under one of those keys.
 *   • CSV: RFC-4180 quotes (`""` escapes, newlines inside quotes), `\t` / `;` /
 *     `,` sniffed from the first records (one that splits them all into the same
 *     >1 cell count; none → single column). A header row with a
 *     `text|caption|message|content|variant(s)` cell picks that column, else
 *     column 0. Chosen for a `.csv`/`.tsv` file; for a paste only when it is
 *     clearly tabular (header / clean quoted cells / tab columns), so a plain
 *     caption with a comma is never split.
 *   • Text: one caption per non-empty line, a fully quoted line unquoted.
 *   • Always: trimmed, empties dropped, exact duplicates dropped, order kept.
 *
 * `mergeCaptions` is the one pool-merge rule every editor uses.
 */

export type CaptionFormat = "csv" | "json" | "text";

export interface ParsedCaptions {
  items: string[];
  format: CaptionFormat;
}

const KEYS = ["text", "caption", "message", "content"] as const;
const HEADER = /^(text|caption|message|content|variant)s?$/i;
const DELIMS = ["\t", ";", ","] as const;

function clean(xs: string[]): string[] {
  return [...new Set(xs.map((x) => x.trim()).filter(Boolean))];
}

function fromJson(text: string): string[] | null {
  let v: unknown;
  try { v = JSON.parse(text); } catch { return null; }
  const pick = (o: unknown): string | null => {
    if (typeof o === "string") return o;
    if (o && typeof o === "object") {
      for (const k of KEYS) {
        const f = (o as Record<string, unknown>)[k];
        if (typeof f === "string") return f;
      }
    }
    return null;
  };
  if (v && typeof v === "object" && !Array.isArray(v)) {
    const k = KEYS.find((key) => Array.isArray((v as Record<string, unknown>)[key])) ?? (
      KEYS.map((key) => `${key}s`).find((key) => Array.isArray((v as Record<string, unknown>)[key]))
    );
    if (!k) return null;
    v = (v as Record<string, unknown>)[k];
  }
  if (!Array.isArray(v)) return null;
  return v.map(pick).filter((s): s is string => s !== null);
}

/** RFC-4180 records. `delim` null = single column (only quotes + newlines).
 *  `ok` is false when a quote opens mid-cell, text follows a closing quote, or
 *  a quote never closes (the parse still returns its lenient best effort). */
function records(text: string, delim: string | null): { rows: string[][]; ok: boolean } {
  const rows: string[][] = [];
  let row: string[] = [];
  let cell = "";
  let quoted = false;   // inside a quoted cell
  let wasQuoted = false; // current cell closed a quote
  let ok = true;
  const endCell = () => { row.push(cell); cell = ""; wasQuoted = false; };
  const endRow = () => { endCell(); rows.push(row); row = []; };
  for (let i = 0; i < text.length; i++) {
    const c = text[i];
    if (quoted) {
      if (c === '"') {
        if (text[i + 1] === '"') { cell += '"'; i++; }
        else { quoted = false; wasQuoted = true; }
      } else cell += c;
    } else if (c === '"' && cell === "" && !wasQuoted) {
      quoted = true;
    } else if (delim !== null && c === delim) {
      endCell();
    } else if (c === "\r" || c === "\n") {
      if (c === "\r" && text[i + 1] === "\n") i++;
      endRow();
    } else {
      if (c === '"' || wasQuoted) ok = false;
      cell += c;
    }
  }
  if (quoted) ok = false;
  if (cell !== "" || row.length || wasQuoted) endRow();
  return { rows: rows.filter((r) => r.some((x) => x.trim())), ok };
}

function sniff(text: string): string | null {
  for (const d of DELIMS) {
    const head = records(text, d).rows.slice(0, 5);
    if (head.length && head.every((r) => r.length > 1 && r.length === head[0].length)) return d;
  }
  return null;
}

function column(rows: string[][]): string[] {
  const h = rows[0]?.findIndex((c) => HEADER.test(c.trim())) ?? -1;
  return h >= 0 ? rows.slice(1).map((r) => r[h] ?? "") : rows.map((r) => r[0] ?? "");
}

function fromCsv(text: string, force: boolean): string[] | null {
  const delim = sniff(text);
  const { rows, ok } = records(text, delim);
  const header = rows[0]?.some((c) => HEADER.test(c.trim())) ?? false;
  const tabular = header || delim === "\t" || (ok && text.trimStart().startsWith('"'));
  return force || tabular ? column(rows) : null;
}

function fromText(text: string): string[] {
  return text.split(/\r\n|\r|\n/).map((l) => {
    const t = l.trim();
    return t.length >= 2 && t.startsWith('"') && t.endsWith('"') ? t.slice(1, -1).replace(/""/g, '"') : t;
  });
}

export function parseCaptions(text: string, hint?: { filename?: string }): ParsedCaptions {
  const body = text.replace(/^﻿/, "");
  const ext = hint?.filename?.toLowerCase().match(/\.([a-z0-9]+)$/)?.[1] ?? "";
  const t = body.trim();
  if (t.startsWith("[") || t.startsWith("{")) {
    const j = fromJson(t);
    if (j) return { items: clean(j), format: "json" };
  }
  if (ext !== "txt") {
    const c = fromCsv(body, ext === "csv" || ext === "tsv");
    if (c) return { items: clean(c), format: "csv" };
  }
  return { items: clean(fromText(body)), format: "text" };
}

export interface MergeResult {
  pool: string[];
  /** The captions that went in, in order. */
  added: string[];
  /** Already in the pool (exact match), skipped. */
  dupes: number;
  /** Over `max`, cut. */
  dropped: number;
}

/** Imported captions into a pool: a lone blank variant is replaced, otherwise
 *  appended; exact duplicates of what is there are skipped; `max` caps the
 *  pool size (the rest is counted as dropped). */
export function mergeCaptions(pool: string[], items: string[], max?: number): MergeResult {
  const base = pool.length === 1 && !pool[0].trim() ? [] : pool;
  const have = new Set(base.map((p) => p.trim()));
  const fresh = items.filter((x) => !have.has(x));
  const room = max === undefined ? fresh.length : Math.max(0, max - base.length);
  const take = fresh.slice(0, room);
  return {
    pool: take.length ? [...base, ...take] : pool,
    added: take,
    dupes: items.length - fresh.length,
    dropped: fresh.length - take.length,
  };
}
