"use client";

/**
 * Growth > Sensitive words (`/growth/sensitive-words`), Infloww's page of the same
 * name (remote web bundle, menu 87; help center H262068), on
 * service/sensitive_words_api.py. The layout is Infloww's `SensitiveWords` chunk
 * CSS (`index.f52ea2fc.css`, `_1hxt5`; page-parity ticket 14): a full-height box,
 * the 16 / 500 title, a 50px toolbar, the 30px letter tabs, the list's own scroll
 * box of 182x70 word cards, and a "Total" row.
 *
 * One list per Agency. The toolbar has a search box (it filters the open letter
 * tab), "Import from Excel", "Export Excel" and "+ Add Sensitive Word" (Infloww's
 * `top:55px; right:28px`: the title's 48px plus the toolbar's 7px puts it at the
 * toolbar's right end, and the letter row, spread across the full width, has no
 * room for it). Each word card shows "Edit"
 * and "Delete" over itself on hover or focus. The add dialog takes up to 20 words
 * of at most 32 characters ("+ Add the next column"); edit reuses it with one
 * row. Delete is immediate, as in Infloww. Excel import reads column A under a
 * header row, like Infloww's template, and reports how many words were added and
 * failed. "Total" counts every listed word, not just the open tab's.
 *
 * Every composer (Messages Pro, the mass message composer, Scripts) warns while
 * its text holds a listed word; see lib/sensitiveWords.ts.
 *
 * ASSUMPTION: the import result lists the failed words in the dialog, where
 * Infloww offers them as a download. Rung 4; the owner chose to keep it.
 */

import { useMutation, useQueryClient } from "@tanstack/react-query";
import { CheckCircle2, Download, Plus, Trash2, Upload, X } from "lucide-react";
import { useMemo, useRef, useState, type KeyboardEvent } from "react";

import { EmptyState, IfButton, IfInput, IfModal, InflowwPageHeader } from "@/components/ui/infloww";
import { relay } from "@/lib/relay";
import {
  LETTER_TABS, SENSITIVE_WORDS_KEY, SENSITIVE_WORD_MAX, SENSITIVE_WORD_ROWS_MAX,
  tabOf, useSensitiveWords,
} from "@/lib/sensitiveWords";
import { cn } from "@/lib/utils";
import { Skeleton } from "@/components/ui/Skeleton";

interface ImportResult {
  total: number;
  success_count: number;
  fail_count: number;
  failed: Array<{ word: string; reason: string }>;
}

const ROUTE = "/admin/sensitive-words";
/** `--tc-Home-B-th`, the list's scroll box: B-th #1a1a1a dark (Home-B-th has no dark entry), #fff light. */
const HOME_B_TH = "bg-[#1a1a1a] [html[data-theme=light]_&]:bg-white";
/** `--tc-M-B1`: #2f2f2f dark, #fff light (the import dialog's template button and drop box). */
const M_B1 = "bg-[#2f2f2f] [html[data-theme=light]_&]:bg-white";
/** Infloww centres "No data" in `100vh - 260px`; ours fills the scroll box instead (the viewport less the shell's
 *  top bar and the 323px of header, toolbar, letters, list title, padding and Total above and below it), so an
 *  empty letter never scrolls. */
const EMPTY_BOX = "min-h-[240px] sm:min-h-[calc(100dvh-var(--chrome-top)-323px)]";
/** IfButton `default`'s look, for Export: an `<a download>` standing in for a button. */
const LINK_BUTTON = cn(
  "inline-flex h-8 shrink-0 items-center justify-center whitespace-nowrap rounded-md border border-border bg-transparent",
  "px-[15px] text-[14px] text-fg transition-colors hover:border-accent hover:text-accent",
  "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent/40",
);

export default function SensitiveWordsPage() {
  const qc = useQueryClient();
  const listQ = useSensitiveWords();
  const [tab, setTab] = useState<string>(LETTER_TABS[0]);
  const [search, setSearch] = useState("");
  const [editor, setEditor] = useState<{ mode: "add" } | { mode: "edit"; word: string } | null>(null);
  const [importOpen, setImportOpen] = useState(false);
  const [notice, setNotice] = useState<{ ok: boolean; text: string } | null>(null);
  const tabRefs = useRef<Array<HTMLButtonElement | null>>([]);

  const refresh = () => qc.invalidateQueries({ queryKey: SENSITIVE_WORDS_KEY });
  const del = useMutation({
    mutationFn: (word: string) => relay.post<{ deleted: number }>(`${ROUTE}/delete`, { words: [word] }),
    onSuccess: (_r, word) => {
      setNotice({ ok: true, text: `Deleted "${word}"` });
      void refresh();
    },
    onError: (e) => setNotice({ ok: false, text: (e as Error).message }),
  });

  const words = listQ.data?.words;
  const shown = useMemo(() => {
    const q = search.trim().toLowerCase();
    return (words ?? []).filter((w) => tabOf(w) === tab && w.toLowerCase().includes(q));
  }, [words, tab, search]);

  // The letter tabs are one Tab stop; the arrows (and Home / End) open the next tab and move focus to it.
  const onTabKey = (e: KeyboardEvent<HTMLButtonElement>, i: number) => {
    const n = LETTER_TABS.length;
    const to = e.key === "ArrowRight" ? (i + 1) % n
      : e.key === "ArrowLeft" ? (i - 1 + n) % n
        : e.key === "Home" ? 0
          : e.key === "End" ? n - 1 : -1;
    if (to < 0) return;
    e.preventDefault();
    setTab(LETTER_TABS[to]);
    tabRefs.current[to]?.focus();
  };

  return (
    <div className="flex min-w-0 flex-col bg-bg [html[data-theme=light]_&]:bg-bg-elev-1 sm:h-[calc(100dvh-var(--chrome-top))] sm:overflow-hidden">
      <InflowwPageHeader title="Sensitive words" weight="medium" />

      <div className="mt-[7px] flex min-h-[50px] shrink-0 flex-wrap items-center justify-between gap-x-[15px] gap-y-2 bg-bg px-6 py-2 lg:flex-nowrap lg:py-0">
        <div className="flex min-w-0 items-center">
          <span className="mr-[15px] hidden whitespace-nowrap text-[14px] text-fg lg:inline">
            Composers warn when a message holds a listed word.
          </span>
          <div className="relative w-[300px] max-w-full">
            <IfInput
              aria-label="Search sensitive words"
              placeholder="Search"
              value={search}
              maxLength={SENSITIVE_WORD_MAX}
              search={!search}
              onChange={(e) => setSearch(e.target.value)}
              className="w-full"
            />
            {search && (
              <button type="button" aria-label="Clear search" onClick={() => setSearch("")}
                className="absolute right-[11px] top-1/2 -translate-y-1/2 text-muted hover:text-fg">
                <X size={14} />
              </button>
            )}
          </div>
        </div>
        <div className="flex flex-wrap items-center gap-[15px] lg:shrink-0 lg:flex-nowrap">
          <IfButton onClick={() => setImportOpen(true)}>Import from Excel</IfButton>
          <a href={`${ROUTE}/export`} download className={LINK_BUTTON}>Export Excel</a>
          <IfButton variant="primary" icon={Plus} onClick={() => setEditor({ mode: "add" })}>Add Sensitive Word</IfButton>
        </div>
      </div>

      {notice && (
        <div role="status" className={cn("mx-6 mt-2 flex items-center rounded-md border px-3 py-2 text-xs",
          notice.ok ? "bg-ok/10 border-ok/30 text-ok" : "bg-err/10 border-err/30 text-err")}>
          <span className="flex-1">{notice.text}</span>
          <button type="button" aria-label="Dismiss" onClick={() => setNotice(null)}><X size={12} /></button>
        </div>
      )}

      <div className="my-[15px] shrink-0 bg-bg px-6 py-[13px]">
        <div role="tablist" aria-label="First letter"
          className="flex flex-wrap gap-[3px] sm:flex-nowrap sm:justify-between">
          {LETTER_TABS.map((t, i) => (
            <button
              key={t}
              ref={(el) => { tabRefs.current[i] = el; }}
              type="button"
              role="tab"
              aria-selected={t === tab}
              tabIndex={t === tab ? 0 : -1}
              onClick={() => setTab(t)}
              onKeyDown={(e) => onTabKey(e, i)}
              className={cn(
                "flex h-[30px] min-w-[30px] shrink-0 items-center justify-center whitespace-nowrap rounded border px-[0.8vw]",
                "border-bg-elev-2 bg-bg-elev-2 text-[14px] text-fg transition-colors hover:border-accent hover:text-accent",
                "[html[data-theme=light]_&]:border-[#eff4ff] [html[data-theme=light]_&]:bg-[#eff4ff]",
                "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent/40",
                t === tab && "border-accent text-accent [html[data-theme=light]_&]:border-accent",
              )}
            >
              {t}
            </button>
          ))}
        </div>
      </div>

      <div className="flex min-h-0 flex-1 flex-col px-6">
        <div role="tabpanel" aria-label={tab}
          className={cn("min-h-0 flex-1 overscroll-contain sm:overflow-y-auto sm:overflow-x-hidden", HOME_B_TH)}>
          <h2 className="my-4 text-[14px] font-medium text-fg">Sensitive words list</h2>
          <div className={cn("rounded-lg px-2.5 py-[15px]", HOME_B_TH)}>
            {listQ.isLoading ? (
              <div className="flex flex-wrap gap-2" aria-busy="true">
                {["w-16", "w-24", "w-20", "w-14", "w-28", "w-16", "w-20"].map((w, i) => (
                  <Skeleton key={i} className={cn("h-8 rounded-md", w)} />
                ))}
              </div>
            ) : listQ.isError ? (
              <EmptyState kind="error" size="md" text="Couldn't load the list." onRetry={() => void listQ.refetch()}
                className={EMPTY_BOX} />
            ) : shown.length === 0 ? (
              <EmptyState kind="data" size="md" className={EMPTY_BOX} />
            ) : (
              <ul className="flex flex-wrap" aria-label="Sensitive words">
                {shown.map((w) => (
                  <WordCard key={w} word={w} busy={del.isPending}
                    onEdit={() => setEditor({ mode: "edit", word: w })} onDelete={() => del.mutate(w)} />
                ))}
              </ul>
            )}
          </div>
        </div>
        <div className="flex h-[50px] shrink-0 items-center border-t border-border text-[14px] text-fg">
          Total: {words?.length ?? 0}
        </div>
      </div>

      {editor && (
        <WordDialog
          key={editor.mode === "edit" ? editor.word : "add"}
          editing={editor.mode === "edit" ? editor.word : null}
          onClose={() => setEditor(null)}
          onDone={(text) => { setEditor(null); setNotice({ ok: true, text }); void refresh(); }}
        />
      )}
      {importOpen && (
        <ImportDialog onClose={() => setImportOpen(false)} onImported={() => void refresh()} />
      )}
    </div>
  );
}

/** Infloww's 182x70 word card. Edit and Delete cover it while the pointer is over it or focus is inside it; a tap
 *  focuses it first, so a phone never deletes on the first touch. */
function WordCard({ word, busy, onEdit, onDelete }: {
  word: string;
  busy: boolean;
  onEdit: () => void;
  onDelete: () => void;
}) {
  const [hover, setHover] = useState(false);
  const [focus, setFocus] = useState(false);
  const action = "text-white hover:text-accent focus-visible:text-accent focus-visible:outline-none";
  return (
    <li
      tabIndex={0}
      aria-label={word}
      onMouseEnter={() => setHover(true)}
      onMouseLeave={() => setHover(false)}
      onFocus={() => setFocus(true)}
      onBlur={(e) => { if (!e.currentTarget.contains(e.relatedTarget as Node | null)) setFocus(false); }}
      className="relative m-2.5 inline-flex h-[70px] w-[calc(50%-20px)] cursor-pointer items-center justify-center rounded-[10px] border border-border text-[14px] text-fg outline-none focus-visible:border-accent sm:w-[182px]"
    >
      <span className={cn("line-clamp-2 max-w-[90px] break-all text-center", (hover || focus) && "invisible")}>{word}</span>
      {(hover || focus) && (
        <span className="absolute inset-0 flex items-center justify-center gap-2.5 rounded-[10px] bg-black/60">
          <button type="button" className={action} onClick={onEdit}>Edit</button>
          <button type="button" className={cn(action, "disabled:opacity-50")} disabled={busy} onClick={onDelete}>
            Delete
          </button>
        </span>
      )}
    </li>
  );
}

function WordDialog({ editing, onClose, onDone }: {
  editing: string | null;
  onClose: () => void;
  onDone: (notice: string) => void;
}) {
  const [rows, setRows] = useState<string[]>([editing ?? ""]);
  const [checked, setChecked] = useState(false);
  const save = useMutation({
    mutationFn: async (words: string[]) => {
      if (editing !== null) {
        await relay.post(`${ROUTE}/update`, { old: editing, latest: words[0] });
        return `Saved "${words[0]}"`;
      }
      const r = await relay.post<ImportResult>(`${ROUTE}/add`, { words });
      if (r.fail_count > 0) {
        const why = r.failed.map((f) => `"${f.word}" (${f.reason})`).join(", ");
        if (r.success_count === 0) throw new Error(`Nothing added: ${why}`);
        return `Added ${r.success_count} sensitive word${r.success_count === 1 ? "" : "s"}; not added: ${why}`;
      }
      return words.length === 1
        ? `Added "${words[0]}"`
        : `Added ${words.length} sensitive words: ${words.map((w) => `"${w}"`).join(", ")}`;
    },
    onSuccess: onDone,
  });

  const submit = () => {
    setChecked(true);
    const words = rows.map((r) => r.trim());
    if (words.some((w) => w.length === 0 || w.length > SENSITIVE_WORD_MAX)) return;
    save.mutate(words);
  };

  return (
    <IfModal
      title={editing !== null ? "Edit Sensitive Word" : "Add Sensitive Word"}
      width={520}
      onClose={onClose}
      footer={<>
        <IfButton onClick={onClose}>Cancel</IfButton>
        <IfButton variant="primary" type="submit" form="sensitive-word-form" disabled={save.isPending}>
          {save.isPending ? "Saving…" : "Save"}
        </IfButton>
      </>}
    >
      <form id="sensitive-word-form" className="max-h-[500px] overflow-y-auto"
        onSubmit={(e) => { e.preventDefault(); if (!save.isPending) submit(); }}>
        {rows.map((value, i) => {
          const bad = checked && value.trim().length === 0;
          return (
            <div key={i} className="relative flex h-[55px] items-center gap-2">
              <div className="relative flex-1">
                <IfInput
                  aria-label={`Sensitive word ${i + 1}`}
                  value={value}
                  maxLength={SENSITIVE_WORD_MAX}
                  placeholder="Enter a sensitive word"
                  autoFocus={i === rows.length - 1}
                  onChange={(e) => setRows((rs) => rs.map((r, j) => (j === i ? e.target.value : r)))}
                  className={cn("h-10 w-full pr-12", bad && "border-err hover:border-err focus-within:border-err")}
                />
                <span className="pointer-events-none absolute right-[11px] top-1/2 -translate-y-1/2 text-[12px] text-muted">
                  {value.length}/{SENSITIVE_WORD_MAX}
                </span>
              </div>
              {rows.length > 1 && (
                <button type="button" aria-label={`Remove word ${i + 1}`} className="text-muted hover:text-err"
                  onClick={() => setRows((rs) => rs.filter((_, j) => j !== i))}>
                  <Trash2 size={16} />
                </button>
              )}
              {bad && <p className="absolute -bottom-2.5 left-0 text-[12px] text-err">Please enter a sensitive word</p>}
            </div>
          );
        })}
        {editing === null && rows.length < SENSITIVE_WORD_ROWS_MAX && (
          <IfButton variant="link" icon={Plus} className="mt-1 h-6" onClick={() => setRows((rs) => [...rs, ""])}>
            Add the next column
          </IfButton>
        )}
        {save.isError && <p role="alert" className="mt-2 text-xs text-err">{(save.error as Error).message}</p>}
      </form>
    </IfModal>
  );
}

function ImportDialog({ onClose, onImported }: { onClose: () => void; onImported: () => void }) {
  const [file, setFile] = useState<File | null>(null);
  const [result, setResult] = useState<ImportResult | null>(null);
  const input = useRef<HTMLInputElement>(null);
  const upload = useMutation({
    mutationFn: (f: File) => relay.uploadFile<ImportResult>(`${ROUTE}/import`, f),
    onSuccess: (r) => { setResult(r); onImported(); },
  });

  if (result) {
    return (
      <IfModal title="Import from Excel" onClose={onClose}
        footer={<IfButton variant="primary" onClick={onClose}>OK</IfButton>}>
        <div className="flex flex-col items-center justify-center p-4 text-center">
          <CheckCircle2 className="mb-2 h-[50px] w-[50px] text-ok" aria-hidden />
          <p className="text-[18px] text-fg">Import successful</p>
          <p className="mt-1 text-fg-dim">
            You&apos;ve imported a total of {result.total} sensitive words. Of these,{" "}
            <span className="text-ok">{result.success_count}</span> were successful and{" "}
            <span className="text-err">{result.fail_count}</span> failed.
          </p>
        </div>
        {result.failed.length > 0 && (
          <ul className="max-h-40 space-y-0.5 overflow-y-auto rounded-md border border-border p-2 text-xs">
            {result.failed.map((f, i) => (
              <li key={i}><span className="font-medium">{f.word || "(blank)"}</span> <span className="text-fg-dim">— {f.reason}</span></li>
            ))}
          </ul>
        )}
      </IfModal>
    );
  }

  return (
    <IfModal
      title="Import from Excel"
      onClose={onClose}
      footer={<>
        <IfButton onClick={onClose}>Cancel</IfButton>
        <IfButton variant="primary" disabled={!file || upload.isPending} onClick={() => file && upload.mutate(file)}>
          {upload.isPending ? "Importing…" : "Import"}
        </IfButton>
      </>}
    >
      <div className="-m-6 px-[25px] py-[15px]">
        <div className="mb-4 flex flex-col">
          <p className="mb-2 text-fg">1. Download the template and fill in the sensitive words.</p>
          <a href={`${ROUTE}/template`} download
            className={cn("flex w-fit items-center gap-1.5 rounded-lg border border-transparent px-4 py-2 text-accent hover:opacity-90", M_B1)}>
            <Download size={14} />Download template
          </a>
        </div>
        <div className="mb-4 flex flex-col">
          <p className="mb-2 text-fg">2. Upload the completed file.</p>
          <button
            type="button"
            onClick={() => input.current?.click()}
            className={cn("flex w-full flex-col items-center justify-center gap-1 rounded-lg border border-dashed border-[#bfbfbf] py-8 text-accent hover:border-accent", M_B1)}
          >
            <Upload size={24} aria-hidden />
            <span className="w-[95%] truncate text-center">{file ? file.name : "Upload"}</span>
          </button>
          <input
            ref={input}
            type="file"
            hidden
            aria-label="Excel file"
            accept=".xlsx,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            onChange={(e) => { setFile(e.target.files?.[0] ?? null); upload.reset(); }}
          />
        </div>
        {upload.isError && (
          <p role="alert" className="text-xs text-err">Import failed: {(upload.error as Error).message}</p>
        )}
      </div>
    </IfModal>
  );
}
