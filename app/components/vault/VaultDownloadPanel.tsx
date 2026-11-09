"use client";

/** Vault Pro's download: `useVaultDownload` (the reducer, its ref for the runner, the abort, the share sink's files)
 *  and the progress card. The card only dispatches; the queue is `vaultDownload.ts`, the rules `vaultDownloadReducer.ts`. */

import { useCallback, useEffect, useReducer, useRef, useState, useSyncExternalStore } from "react";

import { Download, X } from "lucide-react";

import {
  downloadSink, linksFor, linksShareFiles, runQueue, shareFiles, startDownload, type Sink, type StartArgs,
} from "@/components/vault/vaultDownload";
import {
  batchLabel, canRetry, countText, initialDownloadState, isBusy, panelTitle, readyBatch, summarize, unsaved,
  vaultDownloadReducer,
  type Action, type DlSink, type DlState,
} from "@/components/vault/vaultDownloadReducer";

const noSubscribe = () => () => {};

export interface VaultDownload {
  state: DlState;
  /** Where files go in this browser; null = no download here. */
  sink: DlSink | null;
  /** Why the picker or the run could not start (not a per-item failure). */
  error: string;
  /** Folder sink: the picker is open (the hint shows). */
  picking: boolean;
  start: (a: Omit<StartArgs, "accountId" | "creator">) => void;
  cancel: () => void;
  retryFailed: () => void;
  close: () => void;
  /** Share sink: hand batch `index` to the share sheet (call straight from the tap). */
  saveBatch: (index: number) => void;
  /** Share sink: hand the links file (txt + html) to the share sheet (call straight from the tap). */
  saveLinks: () => void;
}

export function useVaultDownload(accountId: string, creator: string): VaultDownload {
  const [state, dispatch] = useReducer(vaultDownloadReducer, initialDownloadState);
  const ref = useRef(state);
  const abort = useRef<AbortController | null>(null);
  const sinkRef = useRef<Sink | null>(null);
  // Share sink: the fetched files by media id until their batch is saved.
  const files = useRef(new Map<number, File>());
  const [error, setError] = useState("");
  const [picking, setPicking] = useState(false);
  // null on the server, the browser's answer after hydration (no mismatch).
  const sink = useSyncExternalStore(noSubscribe, downloadSink, () => null);
  useEffect(() => () => abort.current?.abort(), []);

  // The runner reads the state between awaits, so the ref is advanced with the same pure reducer, synchronously.
  const send = useCallback((a: Action) => {
    ref.current = vaultDownloadReducer(ref.current, a);
    dispatch(a);
  }, []);
  const deps = (ac: AbortController) => ({ accountId, send, get: () => ref.current, signal: ac.signal });

  const start = (a: Omit<StartArgs, "accountId" | "creator">) => {
    if (isBusy(ref.current)) return;
    setError("");
    const ac = new AbortController();
    abort.current = ac;
    files.current.clear();
    const keep = sink === "share" ? (id: number, f: File) => { files.current.set(id, f); } : null;
    setPicking(sink === "folder");
    startDownload({ ...a, accountId, creator }, deps(ac), (k) => { sinkRef.current = k; }, keep)
      .catch((e) => setError((e as Error)?.message || String(e)))
      .finally(() => setPicking(false));
  };
  const cancel = () => {
    abort.current?.abort();
    send({ type: "cancel" });
  };
  const retryFailed = () => {
    if (!canRetry(ref.current) || !sinkRef.current) return;
    send({ type: "retryFailed" });
    const ac = new AbortController();
    abort.current = ac;
    void runQueue({ ...deps(ac), sink: sinkRef.current });
  };
  const close = () => {
    send({ type: "close" });
    if (!isBusy(ref.current)) files.current.clear();
    setError("");
  };
  const saveBatch = (index: number) => {
    const b = ref.current.batches[index];
    if (!b?.sealed || b.saved) return;
    setError("");
    const batch = b.ids.map((id) => files.current.get(id)).filter((f): f is File => !!f);
    shareFiles(batch).then((r) => {
      if (r !== "saved") return;   // the sheet was dismissed: the button stays
      send({ type: "batchSaved", index });
      for (const id of b.ids) files.current.delete(id);
    }).catch((e) => setError((e as Error)?.message || String(e)));
  };
  const saveLinks = () => {
    const s = ref.current;
    if (s.sink !== "share" || !s.items.length || s.linksSaved) return;
    const fs = linksShareFiles(linksFor(accountId, s));
    if (!fs.length) {
      setError("This browser can't share the links file");
      return;
    }
    setError("");
    shareFiles(fs).then((r) => { if (r === "saved") send({ type: "linksSaved" }); })
      .catch((e) => setError((e as Error)?.message || String(e)));
  };
  return { state, sink, error, picking, start, cancel, retryFailed, close, saveBatch, saveLinks };
}

function mb(n: number): string {
  return n >= 1 << 30 ? `${(n / (1 << 30)).toFixed(2)} GB` : `${(n / (1 << 20)).toFixed(1)} MB`;
}

export default function VaultDownloadPanel({ dl }: { dl: VaultDownload }) {
  const { state: s, error } = dl;
  // Chrome refuses Home / Desktop / Documents / Downloads themselves ("contains system files"; its File System Access
  // blocklist, kDontBlockChildren), never a folder inside them. Its dialog, not ours: say so while the picker is open.
  if (s.phase === "idle" && dl.picking) {
    return (
      <div role="status" data-testid="dl-pick-hint"
        className="fixed bottom-24 left-3 right-3 sm:left-auto sm:right-6 z-40 sm:w-[340px] rounded-lg border border-border bg-panel shadow-lg text-xs px-3 py-2">
        Pick any folder. Chrome won&apos;t take Desktop, Documents or Downloads themselves: open one and click New Folder.
      </div>
    );
  }
  if (s.phase === "idle" && !error) return null;
  const sum = summarize(s);
  const busy = isBusy(s);
  const failed = s.items.filter((i) => i.status === "failed");
  const pct = sum.total ? Math.round(((sum.done + sum.failed) / sum.total) * 100) : 0;
  const share = s.sink === "share";
  const ready = share ? readyBatch(s) : -1;
  const left = share ? unsaved(s) : 0;
  const title = panelTitle(s);
  const linksBtn = share && sum.total > 0 && !s.linksSaved;
  return (
    <div
      role="region"
      aria-label="Vault download"
      data-phase={s.phase}
      data-done={sum.done}
      data-failed={sum.failed}
      data-total={sum.total}
      data-direct={sum.direct}
      data-relay={sum.relay}
      data-sink={s.sink}
      data-batches={s.batches.length}
      data-saved={s.batches.filter((b) => b.saved).length}
      data-unsaved={left}
      className="fixed bottom-24 left-3 right-3 sm:left-auto sm:right-6 z-40 sm:w-[340px] max-h-[60vh] flex flex-col rounded-lg border border-border bg-panel shadow-lg text-sm"
    >
      <div className="px-3 py-2 flex items-center gap-2 border-b border-border">
        <Download size={16} aria-hidden className="text-fg-dim" />
        <div className="flex-1 font-medium truncate" title={title}>{title}</div>
        {!busy && (
          <button type="button" aria-label="Close download" onClick={dl.close} className="text-fg-dim hover:text-fg">
            <X size={16} aria-hidden />
          </button>
        )}
      </div>
      <div className="px-3 py-2 space-y-2">
        {error && <div role="alert" className="text-xs text-err">{error}</div>}
        {s.error && <div role="alert" className="text-xs text-err">Listing failed: {s.error}</div>}
        {s.phase !== "listing" && sum.total > 0 && (
          <>
            <div className="h-1.5 rounded bg-bg-elev-1 overflow-hidden">
              <div className="h-full bg-accent transition-[width]" style={{ width: `${pct}%` }} />
            </div>
            <div className="text-xs text-fg-dim flex flex-wrap gap-x-3">
              <span data-testid="dl-count">{countText(s)}</span>
              {sum.failed > 0 && <span className="text-err">{sum.failed} failed</span>}
              <span>{mb(sum.bytes)}</span>
              <span title="Fetched by this browser from OnlyFans' CDN / streamed through the relay">
                direct {sum.direct} · relay {sum.relay}
              </span>
            </div>
          </>
        )}
        {s.phase === "done" && sum.total === 0 && !s.error && <div className="text-xs text-fg-dim">Nothing to download.</div>}
        {!share && s.creator && !busy && sum.done > 0 && (
          <div className="text-xs text-fg-dim">
            Saved under {s.creator}/&lt;folder&gt;/; links-valid-*.html there opens each file on a computer.
          </div>
        )}
        {linksBtn && (
          <div className="text-xs text-fg-dim">Save links: a file with every item&apos;s link, to open them on a computer.</div>
        )}
        {share && ready >= 0 && (
          <div className="text-xs text-fg-dim">Tap Save, then Save to Photos or Save to Files.</div>
        )}
        {share && ready < 0 && left > 0 && <div className="text-xs text-fg-dim">Fetching the next files…</div>}
        {share && !busy && left === 0 && sum.done > 0 && (
          <div data-testid="dl-all-saved" className="text-xs text-fg-dim">All {sum.done} handed to the share sheet.</div>
        )}
      </div>
      {failed.length > 0 && !busy && (
        <ul aria-label="Failed items" className="px-3 pb-2 overflow-y-auto text-xs space-y-0.5 min-h-0">
          {failed.slice(0, 200).map((i) => (
            <li key={i.id} className="flex gap-2">
              <span className="font-mono">{i.folder}/{i.name}</span>
              <span className="text-err truncate" title={i.error ?? ""}>{i.error}</span>
            </li>
          ))}
          {failed.length > 200 && <li className="text-fg-dim">…and {failed.length - 200} more</li>}
        </ul>
      )}
      <div className="px-3 py-2 border-t border-border flex justify-end gap-2">
        {busy && (
          <button type="button" onClick={dl.cancel}
            className="px-2.5 py-1 rounded-md text-xs border border-err/50 text-err hover:bg-err/10">
            Cancel
          </button>
        )}
        {linksBtn && (
          <button type="button" data-testid="dl-save-links" onClick={dl.saveLinks}
            className="px-2.5 py-1 rounded-md text-xs border border-border bg-bg-elev-1 hover:text-fg">
            Save links
          </button>
        )}
        {ready >= 0 && (
          <button type="button" data-testid="dl-save" onClick={() => dl.saveBatch(ready)}
            className="px-3 py-1.5 rounded-md text-sm border border-accent/60 bg-accent/15 text-accent hover:bg-accent/25">
            {batchLabel(s, ready)}
          </button>
        )}
        {canRetry(s) && (
          <button type="button" onClick={dl.retryFailed}
            className="px-2.5 py-1 rounded-md text-xs border border-border bg-bg-elev-1 hover:text-fg">
            Retry failed
          </button>
        )}
      </div>
    </div>
  );
}
