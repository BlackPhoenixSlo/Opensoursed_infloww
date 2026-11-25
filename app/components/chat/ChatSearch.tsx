"use client";


import { useEffect, useMemo, useRef, useState } from "react";

import { relay, type OFMessage } from "@/lib/relay";
import { type FanId } from "@/lib/fanId";
import { useCan } from "@/hooks/useCan";
import { stripHtmlPreview } from "@/lib/htmlPreview";
import { MP } from "@/lib/messagesPro";
import { cn } from "@/lib/utils";

const O = MP.ours.ChatSearch;

export interface ChatSearchProps {
  accountId: string;
  fanId: FanId;
  messages: OFMessage[];
  ownerUserId: number | null;
  hasOlder: boolean;
  loadingOlder: boolean;
  olderFailed?: boolean;
  onLoadOlder: () => Promise<{ added: number; hasMore: boolean }> | void;
  onPick: (messageId: number) => void;
  onClose: () => void;
}

// Cap older-page pulls per search: OF's cursor rate limit.
const MAX_PAGES_TO_LOAD = 12;
const AUTO_FILL_COUNT = 3;

export function ChatSearch(props: ChatSearchProps) {
  const {
    accountId, fanId, messages, ownerUserId,
    hasOlder, loadingOlder, olderFailed = false, onLoadOlder, onPick, onClose,
  } = props;
  const allowed = useCan(accountId, "chat_search");
  const [q, setQ] = useState("");
  const [debounced, setDebounced] = useState("");
  const [ids, setIds] = useState<number[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [searching, setSearching] = useState(false);
  const [jumpingId, setJumpingId] = useState<number | null>(null);
  const [autoFilling, setAutoFilling] = useState(false);
  const autoFillKeyRef = useRef<string>("");
  const inputRef = useRef<HTMLInputElement | null>(null);
  useEffect(() => {
    const t = setTimeout(() => setDebounced(q.trim()), 250);
    return () => clearTimeout(t);
  }, [q]);

  useEffect(() => {
    inputRef.current?.focus();
    function onKey(e: KeyboardEvent) {
      if (e.key !== "Escape") return;
      e.preventDefault();
      onClose();
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  useEffect(() => {
    let cancelled = false;
    if (!debounced || !allowed) {
      setIds([]);
      setError(null);
      setSearching(false);
      return;
    }
    setSearching(true);
    setError(null);
    relay
      .get<unknown>(
        `/api/of/v2/chats/${fanId}/messages/search?query=${encodeURIComponent(debounced)}`,
        { accountId },
      )
      .then((resp) => {
        if (cancelled) return;
        // OF answers a flat id array or {list: [...]}; accept both.
        const list = Array.isArray(resp)
          ? resp
          : Array.isArray((resp as { list?: unknown[] })?.list)
          ? (resp as { list: unknown[] }).list
          : [];
        const numeric = list
          .map((x) => (typeof x === "number" ? x : Number(x)))
          .filter((n) => Number.isFinite(n));
        setIds(numeric as number[]);
      })
      .catch((err) => {
        if (cancelled) return;
        console.warn("[chat-search] failed", err);
        setError((err as Error)?.message || "Search failed");
        setIds([]);
      })
      .finally(() => {
        if (!cancelled) setSearching(false);
      });
    return () => { cancelled = true; };
  }, [debounced, accountId, fanId, allowed]);

  const byId = useMemo(() => {
    const m = new Map<number, OFMessage>();
    for (const msg of messages) {
      const id = Number(msg.id);
      if (Number.isFinite(id) && id > 0) m.set(id, msg);
    }
    return m;
  }, [messages]);

  useEffect(() => {
    if (!debounced || ids.length === 0 || !hasOlder || olderFailed) return;
    const top = ids.slice(0, AUTO_FILL_COUNT);
    const key = `${debounced}|${top.join(",")}`;
    if (autoFillKeyRef.current === key) return;
    if (top.every((id) => byId.has(id))) {
      autoFillKeyRef.current = key;
      return;
    }
    autoFillKeyRef.current = key;
    let cancelled = false;
    setAutoFilling(true);
    (async () => {
      try {
        for (let i = 0; i < MAX_PAGES_TO_LOAD && !cancelled; i++) {
          // DOM, not byId: the closure holds a stale snapshot.
          const allLoaded = top.every((id) =>
            document.querySelector(`[data-msg-id="${CSS.escape(String(id))}"]`),
          );
          if (allLoaded) break;
          const res = await onLoadOlder();
          const ok = res && typeof res === "object" && "added" in res ? res : null;
          if (!ok || ok.added === 0 || !ok.hasMore) break;
        }
      } catch {
      } finally {
        if (!cancelled) setAutoFilling(false);
      }
    })();
    return () => { cancelled = true; setAutoFilling(false); };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [debounced, ids, hasOlder, olderFailed]);

  function retryOlder() {
    autoFillKeyRef.current = "";
    setError(null);
    void Promise.resolve(onLoadOlder()).catch(() => {});
  }

  async function handlePick(id: number) {
    if (byId.has(id)) {
      onPick(id);
      return;
    }
    if (!hasOlder) {
      setError("Match is older than what's been loaded, and OF says there is no more history.");
      return;
    }
    setJumpingId(id);
    try {
      for (let i = 0; i < MAX_PAGES_TO_LOAD; i++) {
        const res = await onLoadOlder();
        const ok = res && typeof res === "object" && "added" in res ? res : null;
        if (!ok) break;
        if (ok.added === 0) break;
        if (!ok.hasMore) break;
        const el = document.querySelector(`[data-msg-id="${CSS.escape(String(id))}"]`);
        if (el) break;
      }
      onPick(id);
    } catch {
      setError("Couldn’t load older messages to reach that match.");
    } finally {
      setJumpingId(null);
    }
  }

  return (
    <div className="border-b border-border bg-bg-elev-1/40 px-3 py-2 space-y-2">
      <div className="flex items-center gap-2">
        <input
          ref={inputRef}
          value={q}
          onChange={(e) => setQ(e.target.value)}
          placeholder="Search this conversation…"
          className="flex-1 bg-bg border border-border rounded-md px-2.5 py-2.5 md:py-1.5 text-base md:text-sm focus:outline-none focus:border-accent placeholder:text-muted"
        />
        {(searching || jumpingId != null || autoFilling || loadingOlder) && (
          <span className={cn(O.note, "text-fg-dim")}>
            {searching
              ? "Searching…"
              : jumpingId != null
              ? "Loading context…"
              : autoFilling
              ? "Loading top previews…"
              : "Loading…"}
          </span>
        )}
        <button
          type="button"
          onClick={onClose}
          className={cn(O.close, "grid md:block place-items-center text-fg-dim hover:text-fg")}
          title="Close"
          aria-label="Close search"
        >
          ✕
        </button>
      </div>
      {error && (
        <div className={cn(O.note, "text-err")}>{error}</div>
      )}
      {olderFailed && hasOlder && (
        <div className={cn(O.note, "text-err")}>
          Couldn’t load older messages ·{" "}
          <button type="button" onClick={retryOlder} disabled={loadingOlder} className="underline disabled:opacity-60">
            Retry
          </button>
        </div>
      )}
      {debounced && !searching && (
        <div className={cn(O.small, "text-fg-dim")}>
          {ids.length} match{ids.length === 1 ? "" : "es"} across the full chat history
          {byId.size > 0 && ids.length > 0 &&
            ` · ${ids.filter((id) => byId.has(id)).length} previewable here`}
        </div>
      )}
      {debounced && ids.length > 0 && (
        <div className="max-h-64 overflow-y-auto rounded-md border border-border bg-bg divide-y divide-border">
          {ids.map((id) => {
            const msg = byId.get(id);
            const outgoing = msg && ownerUserId != null && msg.fromUser?.id === ownerUserId;
            const preview = msg
              ? stripHtmlPreview(msg.text || (msg.mediaCount ? `(${msg.mediaCount} media)` : "(message)"), 160)
              : null;
            return (
              <button
                key={id}
                type="button"
                onClick={() => handlePick(id)}
                disabled={jumpingId != null}
                className={cn(O.hit, "w-full text-left hover:bg-bg-elev-1 disabled:opacity-60")}
              >
                <div className="flex items-center gap-2">
                  {msg ? (
                    <span
                      className={cn(O.who, outgoing ? "text-[var(--inf-accent-text,var(--color-accent))]" : "text-info")}
                    >
                      {outgoing ? "you" : "fan"}
                    </span>
                  ) : (
                    <span className={cn(O.who, "text-fg-dim")}>
                      not loaded
                    </span>
                  )}
                  <span className={cn(O.small, "text-fg-dim")}>
                    {msg?.createdAt ? fmt(msg.createdAt) : `id ${id}`}
                  </span>
                </div>
                <div className="truncate">
                  {preview
                    ? highlightMatch(preview, debounced)
                    : <span className="italic text-fg-dim">Click to load context…</span>}
                </div>
              </button>
            );
          })}
        </div>
      )}
    </div>
  );
}

function highlightMatch(text: string, needle: string) {
  if (!needle) return text;
  const idx = text.toLowerCase().indexOf(needle.toLowerCase());
  if (idx < 0) return text;
  return (
    <>
      {text.slice(0, idx)}
      <mark className="bg-info/30 text-fg rounded-sm px-0.5">
        {text.slice(idx, idx + needle.length)}
      </mark>
      {text.slice(idx + needle.length)}
    </>
  );
}

function fmt(iso?: string): string {
  if (!iso) return "";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "";
  return d.toLocaleString([], {
    month: "short", day: "numeric", hour: "2-digit", minute: "2-digit",
  });
}
