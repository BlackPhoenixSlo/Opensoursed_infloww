"use client";

/** Vault Pro's download: `useVaultDownload` (the reducer, its ref for the runner, the abort) and the progress card.
 *  The card only dispatches; the queue is `vaultDownload.ts`, the rules `vaultDownloadReducer.ts`. */

import { useCallback, useEffect, useReducer, useRef, useState, useSyncExternalStore } from "react";

import { Download, X } from "lucide-react";

import {
  downloadSupported, runQueue, startDownload, type StartArgs,
} from "@/components/vault/vaultDownload";
import {
  canRetry, initialDownloadState, isBusy, summarize, vaultDownloadReducer, type Action, type DlState,
} from "@/components/vault/vaultDownloadReducer";

const noSubscribe = () => () => {};

export const DOWNLOAD_OFF = "Download needs Chrome or Edge (it saves into a folder you pick)";

export interface VaultDownload {
  state: DlState;
  supported: boolean;
  /** Why the picker or the run could not start (not a per-item failure). */
  error: string;
  start: (a: Omit<StartArgs, "accountId" | "creator">) => void;
  cancel: () => void;
  retryFailed: () => void;
  close: () => void;
}

export function useVaultDownload(accountId: string, creator: string): VaultDownload {
  const [state, dispatch] = useReducer(vaultDownloadReducer, initialDownloadState);
  const ref = useRef(state);
  const abort = useRef<AbortController | null>(null);
  const root = useRef<FileSystemDirectoryHandle | null>(null);
  const [error, setError] = useState("");
  // false on the server, the browser's answer after hydration (no mismatch).
  const supported = useSyncExternalStore(noSubscribe, downloadSupported, () => false);
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
    startDownload({ ...a, accountId, creator }, deps(ac), (r) => { root.current = r; })
      .catch((e) => setError((e as Error)?.message || String(e)));
  };
  const cancel = () => {
    abort.current?.abort();
    send({ type: "cancel" });
  };
  const retryFailed = () => {
    if (!canRetry(ref.current) || !root.current) return;
    send({ type: "retryFailed" });
    const ac = new AbortController();
    abort.current = ac;
    void runQueue({ ...deps(ac), root: root.current });
  };
  const close = () => {
    send({ type: "close" });
    setError("");
  };
  return { state, supported, error, start, cancel, retryFailed, close };
}

function mb(n: number): string {
  return n >= 1 << 30 ? `${(n / (1 << 30)).toFixed(2)} GB` : `${(n / (1 << 20)).toFixed(1)} MB`;
}

export default function VaultDownloadPanel({ dl }: { dl: VaultDownload }) {
  const { state: s, error } = dl;
  if (s.phase === "idle" && !error) return null;
  const sum = summarize(s);
  const busy = isBusy(s);
  const failed = s.items.filter((i) => i.status === "failed");
  const pct = sum.total ? Math.round(((sum.done + sum.failed) / sum.total) * 100) : 0;
  const title = s.phase === "listing" ? `Listing ${s.label}…`
    : s.phase === "running" ? `Downloading ${s.label}`
    : s.phase === "cancelled" ? `Cancelled: ${s.label}`
    : s.label ? `Downloaded ${s.label}` : "Download";
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
      className="fixed bottom-24 right-6 z-40 w-[340px] max-h-[60vh] flex flex-col rounded-lg border border-border bg-panel shadow-lg text-sm"
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
              <span data-testid="dl-count">{sum.done} of {sum.total} saved</span>
              {sum.failed > 0 && <span className="text-err">{sum.failed} failed</span>}
              <span>{mb(sum.bytes)}</span>
              <span title="Fetched by this browser from OnlyFans' CDN / streamed through the relay">
                direct {sum.direct} · relay {sum.relay}
              </span>
            </div>
          </>
        )}
        {s.phase === "done" && sum.total === 0 && !s.error && <div className="text-xs text-fg-dim">Nothing to download.</div>}
        {s.creator && !busy && sum.done > 0 && (
          <div className="text-xs text-fg-dim">Saved under {s.creator}/&lt;folder&gt;/</div>
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
