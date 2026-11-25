"use client";


import Link from "next/link";
import { usePathname } from "next/navigation";
import { createContext, useCallback, useContext, useEffect, useReducer, useRef, useSyncExternalStore, type ReactNode } from "react";

import { Download, FolderOpen, X } from "lucide-react";

import { useAccounts } from "@/hooks/useAccounts";
import { cn } from "@/lib/utils";

import {
  askWrite, canWrite, downloadSink, linksFor, linksShareFiles, pickRoot, runQueue, shareFiles, showSavedFolder,
  startDownload, type Sink, type StartArgs,
} from "@/components/vault/vaultDownload";
import {
  batchLabel, canRetry, countText, holdsFiles, initialDownloadState, isBusy, outcomeParts, panelTitle, progressText,
  queues, readyBatch, retryable, summarize, unsaved, vaultDownloadReducer,
  type Action, type DlJobArgs, type DlSink, type DlState,
} from "@/components/vault/vaultDownloadReducer";

const noSubscribe = () => () => {};
export const VAULT_PRO_PATH = "/growth/vault-pro";

export interface VaultDownload {
  state: DlState;
  sink: DlSink | null;
  start: (a: DlJobArgs) => Promise<boolean>;
  cancel: () => void;
  clearQueue: () => void;
  resume: () => void;
  retryFailed: () => void;
  close: (discard?: boolean) => void;
  saveBatch: (index: number) => void;
  saveLinks: () => void;
  openFolder: () => void;
  keepAccounts: (ids: readonly string[]) => void;
}

export function useVaultDownload(): VaultDownload {
  const [state, dispatch] = useReducer(vaultDownloadReducer, initialDownloadState);
  const ref = useRef(state);
  // claim: between a start and its `start` action the claimant holds the slot so no second start, queue driver or retry runs a queue of its own.
  const claims = useRef(0);
  const abort = useRef<AbortController | null>(null);
  const sinkRef = useRef<Sink | null>(null);
  const rootRef = useRef<FileSystemDirectoryHandle | null>(null);
  const files = useRef(new Map<number, File>());
  // null on the server, the browser's answer after hydration (no mismatch).
  const sink = useSyncExternalStore(noSubscribe, downloadSink, () => null);

  const send = useCallback((a: Action) => {
    // The runner reads state between awaits, so the ref advances synchronously with the same pure reducer.
    ref.current = vaultDownloadReducer(ref.current, a);
    dispatch(a);
  }, []);
  const stopRunAndQueue = () => {
    abort.current?.abort();
    send({ type: "stop" });
  };
  // Downloads stop on provider unmount, so they survive navigation within the signed-in shell. Slop matches this effect line.
  useEffect(() => () => stopRunAndQueue(), []);   // eslint-disable-line react-hooks/exhaustive-deps

  const why = (e: unknown) => (e as Error)?.message || String(e);
  const fail = (ac: AbortController, attempt: number) => (e: unknown) => {
    ac.abort();
    send({ type: "runError", error: why(e), attempt });
  };
  const note = (e: unknown) => send({ type: "note", text: why(e) });
  const clearNote = () => { if (ref.current.note) send({ type: "note", text: "" }); };
  const deps = (ac: AbortController) => ({
    send, get: () => ref.current, signal: ac.signal,
    keep: (id: number, f: File) => { files.current.set(id, f); },
  });
  const next = () => {
    abort.current?.abort();
    // Each run aborts the previous one: a cancelled queue's late workers stop, and what they still send is dropped by the reducer by attempt.
    const ac = new AbortController();
    abort.current = ac;
    return ac;
  };

  const claim = (): number | null => {
    const id = ++claims.current;
    send({ type: "claim", id });
    return ref.current.claim === id ? id : null;
  };
  const launch = (a: StartArgs, root: FileSystemDirectoryHandle | null): Promise<boolean> => new Promise((resolve) => {
    if (!sink) return resolve(false);
    const id = claim();
    if (id === null) return resolve(false);
    const ac = next();
    files.current.clear();
    let attempt: number | null = null;
    const release = () => send({ type: "release", id });
    startDownload(a, deps(ac), sink, (k, n, r) => {
      sinkRef.current = k;
      if (r) rootRef.current = r;
      attempt = n;
      release();
      resolve(true);
    }, root)
      .catch((e) => (attempt === null ? note(e) : fail(ac, attempt)(e)))
      .finally(() => {
        release();
        resolve(false);
      });
  });

  const start = async (a: DlJobArgs): Promise<boolean> => {
    if (queues(sink, ref.current)) {
      const before = ref.current.jobs.length;
      send({ type: "enqueue", job: a });
      return ref.current.jobs.length > before;
    }
    if (!sink || holdsFiles(ref.current)) return false;
    return launch(a, null);
  };

  useEffect(() => {
    if (isBusy(state) || state.picking || !state.jobs.length || state.paused || state.claim) return;
    const root = rootRef.current;
    if (!root) {
      send({ type: "paused" });
      return;
    }
    const id = claim();
    if (id === null) return;
    void canWrite(root).then((ok) => {
      send({ type: "release", id });
      const s = ref.current;
      if (isBusy(s) || s.paused || !s.jobs.length) return;
      if (!ok) send({ type: "paused" });
      else void launch(s.jobs[0], root);
    });
  }, [state]);   // eslint-disable-line react-hooks/exhaustive-deps

  const cancel = () => {
    abort.current?.abort();
    send({ type: "cancel" });
  };
  const clearQueue = () => send({ type: "clearQueue" });
  const resume = () => {
    const root = rootRef.current;
    clearNote();
    const ask = root ? askWrite(root) : pickRoot().then((r) => {
      if (r) rootRef.current = r;
      return !!r;
    });
    ask.then((ok) => {
      if (ok) send({ type: "resumed" });
      else send({ type: "note", text: "No permission to write into the download folder" });
    }).catch(note);
  };
  const retryFailed = () => {
    const sinkNow = sinkRef.current;
    if (!canRetry(ref.current) || !sinkNow) return;
    const run = () => {
      if (!canRetry(ref.current)) return;
      send({ type: "retryFailed" });
      const ac = next();
      const attempt = ref.current.attempt;
      runQueue({ ...deps(ac), sink: sinkNow }).catch(fail(ac, attempt));
    };
    const root = ref.current.sink === "folder" ? rootRef.current : null;
    if (!root) {
      run();
      return;
    }
    const id = claim();
    if (id === null) return;
    clearNote();
    void askWrite(root).then((ok) => {
      send({ type: "release", id });
      if (ok) run();
      else send({ type: "retryLater" });
    });
  };
  const close = (discard = false) => {
    send({ type: "close", discard });
    if (!holdsFiles(ref.current)) files.current.clear();
  };
  const saveBatch = (index: number) => {
    const b = ref.current.batches[index];
    if (!b?.sealed || b.saved) return;
    const batch = b.ids.map((id) => files.current.get(id)).filter((f): f is File => !!f);
    const attempt = ref.current.attempt;
    // The share sheet must be opened straight from the tap.
    shareFiles(batch).then((r) => {
      if (r !== "saved") return;
      send({ type: "batchSaved", index, attempt });
      if (ref.current.attempt === attempt) for (const id of b.ids) files.current.delete(id);
    }).catch(note);
  };
  const saveLinks = () => {
    const s = ref.current;
    if (s.sink !== "share" || !s.items.length || s.links === "saved") return;
    const fs = linksShareFiles(linksFor(s));
    if (!fs.length) {
      send({ type: "note", text: "This browser can't share the links file" });
      return;
    }
    const attempt = s.attempt;
    shareFiles(fs).then((r) => send({ type: "links", ok: r === "saved", attempt })).catch(note);
  };
  const openFolder = () => {
    const at = ref.current.savedAt;
    if (!at) return;
    clearNote();
    showSavedFolder(at).catch(note);
  };
  const keepAccounts = useCallback((ids: readonly string[]) => {
    const s = ref.current;
    if (isBusy(s) && !ids.includes(s.accountId)) abort.current?.abort();
    send({ type: "keepAccounts", ids });
    if (!holdsFiles(ref.current)) files.current.clear();
  }, [send]);
  return { state, sink, start, cancel, clearQueue, resume, retryFailed, close,
           saveBatch, saveLinks, openFolder, keepAccounts };
}

const DownloadCtx = createContext<VaultDownload | null>(null);

export function VaultDownloadProvider({ children }: { children: ReactNode }) {
  const dl = useVaultDownload();
  const q = useAccounts();
  const keep = dl.keepAccounts;
  const data = q.isSuccess ? q.data : undefined;
  useEffect(() => {
    if (!data) return;
    keep([...(data.accounts ?? []).map((a) => a.id), ...(data.watchers ?? []).map((a) => a.id)]);
  }, [keep, data]);
  return (
    <DownloadCtx.Provider value={dl}>
      {children}
      <VaultDownloadPanel dl={dl} />
    </DownloadCtx.Provider>
  );
}

export function useVaultDownloadContext(): VaultDownload {
  const dl = useContext(DownloadCtx);
  if (!dl) throw new Error("useVaultDownloadContext: no VaultDownloadProvider above this component");
  return dl;
}

function mb(n: number): string {
  return n >= 1 << 30 ? `${(n / (1 << 30)).toFixed(2)} GB` : `${(n / (1 << 20)).toFixed(1)} MB`;
}

const BTN = "px-2.5 py-1 rounded-md text-xs border border-border bg-bg-elev-1 hover:text-fg";

export default function VaultDownloadPanel({ dl }: { dl: VaultDownload }) {
  const { state: s } = dl;
  const pathname = usePathname();
  const error = [s.runError, s.note].filter(Boolean).join(" · ");
  if (s.picking) {
    return (
      <div role="status" data-testid="dl-pick-hint"
        className="fixed bottom-24 left-3 right-3 sm:left-auto sm:right-6 z-40 sm:w-[340px] rounded-lg border border-border bg-panel shadow-lg text-xs px-3 py-2">
        {/* Chrome's own dialog refuses Home/Desktop/Documents/Downloads themselves (File System Access blocklist), never a folder inside them. */}
        Pick any folder. Chrome won&apos;t take Desktop, Documents or Downloads themselves: open one and click New Folder.
      </div>
    );
  }
  if (s.phase === "idle" && !error && !s.jobs.length && !s.paused) return null;
  const sum = summarize(s);
  const busy = isBusy(s);
  const noFile = s.items.filter((i) => i.status === "failed" || i.status === "stalled" || i.status === "drm");
  const pct = sum.total ? Math.round(((sum.total - sum.active - s.items.filter((i) => i.status === "queued").length) / sum.total) * 100) : 0;
  const share = s.sink === "share";
  const ready = share ? readyBatch(s) : -1;
  const left = share ? unsaved(s) : 0;
  const title = panelTitle(s);
  const linksBtn = share && sum.total > 0 && s.links !== "saved";
  const offPage = !!pathname && !pathname.startsWith(VAULT_PRO_PATH);
  const openFolder = !share && !!s.savedAt && s.phase !== "idle";
  const retry = canRetry(s) ? retryable(s) : 0;
  return (
    <div
      role="region"
      aria-label="Vault download"
      data-phase={s.phase}
      data-job={s.jobId}
      data-account={s.accountId}
      data-done={sum.done}
      data-failed={sum.failed}
      data-stalled={sum.stalled}
      data-cancelled={sum.cancelled}
      data-drm={sum.drm}
      data-total={sum.total}
      data-direct={sum.direct}
      data-relay={sum.relay}
      data-sink={s.sink}
      data-queued={s.jobs.length}
      data-paused={s.paused ? "1" : "0"}
      data-batches={s.batches.length}
      data-saved={s.batches.filter((b) => b.saved).length}
      data-unsaved={left}
      className="fixed bottom-24 left-3 right-3 sm:left-auto sm:right-6 z-40 sm:w-[340px] flex flex-col rounded-lg border border-border bg-panel shadow-lg text-sm"
    >
      <div className="px-3 py-1.5 flex items-center gap-2 border-b border-border">
        <Download size={16} aria-hidden className="text-fg-dim shrink-0" />
        <div className="flex-1 font-medium truncate" title={title}>{title}</div>
        {busy && <span data-testid="dl-progress" className="text-xs text-fg-dim shrink-0">{progressText(s)}</span>}
        {!holdsFiles(s) && !s.claim && (
          <button type="button" aria-label="Close download" onClick={() => dl.close()} className="text-fg-dim hover:text-fg">
            <X size={16} aria-hidden />
          </button>
        )}
      </div>
      <div className="px-3 py-1.5 space-y-1.5">
        {error && <div role="alert" className="text-xs text-err">{error}</div>}
        {s.phase !== "listing" && sum.total > 0 && (
          <>
            {busy && (
              <div className="h-1.5 rounded bg-bg-elev-1 overflow-hidden">
                <div className="h-full bg-accent transition-[width]" style={{ width: `${pct}%` }} />
              </div>
            )}
            <div className="text-xs text-fg-dim flex flex-wrap gap-x-3">
              <span data-testid="dl-count">{countText(s)}</span>
              {outcomeParts(sum).map((p) => (
                <span key={p.text} className={p.bad ? "text-err" : undefined}>{p.text}</span>
              ))}
              <span>{mb(sum.bytes)}</span>
              <span title="Fetched by this browser from OnlyFans' CDN / streamed through the relay">
                direct {sum.direct} · relay {sum.relay}
              </span>
            </div>
          </>
        )}
        {s.phase === "done" && sum.total === 0 && !s.runError && <div className="text-xs text-fg-dim">Nothing to download.</div>}
        {!share && s.savedAt && !busy && sum.done > 0 && (
          <div data-testid="dl-saved-at" data-links={s.links} className="text-xs text-fg-dim">
            Saved in {[s.savedAt.root.name, ...s.savedAt.dirs].join("/")}/
            {s.savedAt.dirs.length === 1 && <>&lt;folder&gt;/</>}
            {s.links === "saved" ? "; links-valid-*.html there opens each file on a computer." : "."}
            {s.links === "failed" && <span className="text-warn"> Links file not saved.</span>}
          </div>
        )}
        {noFile.length > 0 && !busy && (
          <details className="text-xs">
            <summary className="cursor-pointer text-fg-dim">{noFile.length} without a file</summary>
            <ul aria-label="Items without a file" className="mt-1 max-h-28 overflow-y-auto space-y-0.5">
              {noFile.slice(0, 200).map((i) => (
                <li key={i.id} data-status={i.status} className="flex gap-2">
                  <span className="font-mono">{i.folder}/{i.name}</span>
                  <span className={`truncate ${i.status === "drm" ? "text-fg-dim" : "text-err"}`} title={i.error ?? ""}>{i.error}</span>
                </li>
              ))}
              {noFile.length > 200 && <li className="text-fg-dim">…and {noFile.length - 200} more</li>}
            </ul>
          </details>
        )}
        {s.jobs.length > 0 && (
          <div data-testid="dl-queue" className="text-xs text-fg-dim truncate"
            title={s.jobs.map((j) => `${j.creator}: ${j.label}`).join("\n")}>
            Next: {s.jobs.map((j) => `${j.creator}: ${j.label}`).join(" · ")}
          </div>
        )}
        {s.paused && (
          <div className="text-xs text-err">The download folder needs its permission again: Resume to continue.</div>
        )}
        {s.finished.length > 0 && (
          <ul aria-label="Finished downloads" className="text-xs text-fg-dim space-y-0.5 border-t border-border pt-1">
            {s.finished.map((f) => (
              <li key={f.jobId} data-job={f.jobId} data-account={f.accountId} data-total={f.total} data-done={f.done}
                data-failed={f.failed} data-stalled={f.stalled} data-cancelled={f.cancelled} data-drm={f.drm}
                className="truncate" title={f.title}>
                {f.title}
              </li>
            ))}
          </ul>
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
      <div className="px-3 py-1.5 border-t border-border flex flex-wrap justify-end items-center gap-2">
        {(offPage || openFolder) && (
          <div className="mr-auto flex items-center gap-2">
            {openFolder && (
              <button type="button" data-testid="dl-open-folder" onClick={dl.openFolder}
                title="Opens your computer's file window in the download folder"
                className={cn(BTN, "inline-flex items-center gap-1")}>
                <FolderOpen size={13} aria-hidden /> Open folder
              </button>
            )}
            {offPage && <Link href={VAULT_PRO_PATH} className="text-xs text-accent hover:underline">Open Vault Pro</Link>}
          </div>
        )}
        {!busy && left > 0 && (
          <button type="button" data-testid="dl-discard" onClick={() => dl.close(true)}
            title="Drop the fetched files nobody saved yet and close"
            className="px-2.5 py-1 rounded-md text-xs border border-border text-fg-dim hover:text-fg">
            Discard {left}
          </button>
        )}
        {busy && (
          <button type="button" onClick={dl.cancel}
            className="px-2.5 py-1 rounded-md text-xs border border-err/50 text-err hover:bg-err/10">
            {s.jobs.length ? "Cancel current" : "Cancel"}
          </button>
        )}
        {s.jobs.length > 0 && (
          <button type="button" onClick={dl.clearQueue} className={BTN}>Clear queue ({s.jobs.length})</button>
        )}
        {s.paused && (
          <button type="button" onClick={dl.resume}
            className="px-2.5 py-1 rounded-md text-xs border border-accent/60 bg-accent/15 text-accent hover:bg-accent/25">
            Resume
          </button>
        )}
        {linksBtn && (
          <button type="button" data-testid="dl-save-links" onClick={dl.saveLinks} className={BTN}>Save links</button>
        )}
        {ready >= 0 && (
          <button type="button" data-testid="dl-save" onClick={() => dl.saveBatch(ready)}
            className="px-3 py-1.5 rounded-md text-sm border border-accent/60 bg-accent/15 text-accent hover:bg-accent/25">
            {batchLabel(s, ready)}
          </button>
        )}
        {retry > 0 && (
          <button type="button" onClick={dl.retryFailed} className={BTN}>Retry {retry}</button>
        )}
      </div>
    </div>
  );
}
