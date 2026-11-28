"use client";

import { useCallback, useEffect, useReducer, useRef } from "react";
import { ArrowUp, ChevronLeft, ImagePlus, LifeBuoy, X } from "lucide-react";

import { relay } from "@/lib/relay";
import { cn } from "@/lib/utils";
import { imageFiles, toJpeg } from "./supportPhoto";
import {
  buildPayload, canSend, droppedPhotos, errorText, initialSupportState, MAX_SUPPORT_PHOTOS, messagesOf, photoRoom,
  SUPPORT_THREAD_POLL_MS, supportReducer, type PendingPhoto, type SupportEntryAction, type SupportState,
} from "./supportReducer";

export const SUPPORT_EMPTY = "Tell us what's missing or annoying — the team reads every message.";

export function SupportButton({ unread, onClick }: { unread: boolean; onClick: () => void }) {
  return (
    <button
      type="button"
      onClick={onClick}
      className="relative grid h-8 w-8 place-items-center rounded-md text-current hover:bg-white/10"
      title="Support — message the team"
      aria-label={unread ? "Support (new reply)" : "Support"}
    >
      <LifeBuoy className="h-[18px] w-[18px]" aria-hidden />
      {unread && <span className="absolute right-0.5 top-0.5 h-2.5 w-2.5 rounded-full bg-[#e5372f]" aria-hidden />}
    </button>
  );
}

const lastSupportId = (ms: SupportState["messages"]) => ms.reduce((n, m) => (m.from === "support" && m.id > n ? m.id : n), 0);
const lastMessageId = (ms: SupportState["messages"]) => ms.reduce((n, m) => Math.max(n, m.id), 0);
let photoSeq = 0;

export function SupportPanel({ frame, column, composerPad, inputText, unread, draft, onEntry, onBack, onClose, onRead }: {
  frame: string;
  column: string;
  composerPad: string;
  inputText: string;
  unread: number;
  draft: string;
  onEntry: (a: SupportEntryAction) => void;
  onBack: () => void;
  onClose?: () => void;
  onRead: () => void;
}) {
  const [s, dispatch] = useReducer(supportReducer, initialSupportState);
  const listRef = useRef<HTMLDivElement | null>(null);
  const fileRef = useRef<HTMLInputElement | null>(null);
  const live = useRef(true);
  const loadedOnce = useRef(false);
  const stick = useRef(true);
  const seenSupport = useRef(0);
  const shownPhotos = useRef<PendingPhoto[]>([]);
  const wake = unread > 0;

  useEffect(() => {
    live.current = true;
    return () => {
      live.current = false;
      shownPhotos.current.forEach((p) => URL.revokeObjectURL(p.url));
    };
  }, []);

  useEffect(() => {
    droppedPhotos(shownPhotos.current, s.photos).forEach((p) => URL.revokeObjectURL(p.url));
    shownPhotos.current = s.photos;
  }, [s.photos]);

  const load = useCallback(() => {
    dispatch({ type: "load_started" });
    void Promise.resolve()
      .then(() => relay.get<unknown>("/admin/support/thread"))
      .then((body) => {
        if (!live.current) return;
        const messages = messagesOf(body);
        dispatch({ type: "loaded", messages });
        return relay.post<unknown>("/admin/support/read", { up_to: lastMessageId(messages) }).then(() => {
          seenSupport.current = Math.max(seenSupport.current, lastSupportId(messages));
          if (live.current) onRead();
        });
      })
      .catch((e) => { if (live.current) dispatch({ type: "load_failed", error: errorText(e) }); });
  }, [onRead]);

  useEffect(() => {
    if (loadedOnce.current && !wake) return;
    loadedOnce.current = true;
    load();
  }, [wake, load]);

  useEffect(() => {
    const id = window.setInterval(() => {
      if (document.visibilityState !== "visible") return;
      void Promise.resolve()
        .then(() => relay.get<unknown>("/admin/support/thread"))
        .then((body) => {
          if (!live.current) return;
          const messages = messagesOf(body);
          dispatch({ type: "polled", messages });
          const newest = lastSupportId(messages);
          if (newest > seenSupport.current) {
            return relay.post<unknown>("/admin/support/read", { up_to: lastMessageId(messages) }).then(() => {
              seenSupport.current = Math.max(seenSupport.current, newest);
              if (live.current) onRead();
            });
          }
        })
        .catch(() => {});
    }, SUPPORT_THREAD_POLL_MS);
    return () => window.clearInterval(id);
  }, [onRead]);

  useEffect(() => {
    const el = listRef.current;
    if (el && stick.current) el.scrollTop = el.scrollHeight;
  }, [s.messages]);

  const addPhotos = (files: File[]) => {
    if (files.length === 0) return;
    const take = files.slice(0, photoRoom(s));
    void Promise.all(take.map((f) => toJpeg(f).then(
      (blob): PendingPhoto => ({ key: `p${++photoSeq}`, blob, url: URL.createObjectURL(blob) }),
    )))
      .then((photos) => { if (live.current) dispatch({ type: "photos_added", photos, requested: files.length }); })
      .catch((e: unknown) => {
        if (live.current) dispatch({ type: "photo_failed", error: e instanceof Error ? e.message : "Couldn't read that photo." });
      });
  };

  const send = () => {
    if (!canSend(s, draft)) return;
    const payload = buildPayload(s, draft);
    const keys = payload.photos.map((p) => p.key);
    dispatch({ type: "send_started" });
    void Promise.resolve()
      .then(() => {
        if (payload.photos.length === 0) return relay.post<unknown>("/admin/support/messages", { text: payload.text });
        const form = new FormData();
        form.append("text", payload.text);
        payload.photos.forEach((p, i) => form.append("photos", p.blob, `photo${i}.jpg`));
        return relay.uploadForm<unknown>("/admin/support/messages/upload", form);
      })
      .then((body) => {
        onEntry({ type: "sent", text: payload.text });
        if (!live.current) return;
        stick.current = true;
        dispatch({ type: "sent", messages: messagesOf(body), keys });
      })
      .catch((e) => { if (live.current) dispatch({ type: "send_failed", error: errorText(e) }); });
  };

  return (
    <div data-look="messenger" data-assistant-ui data-support
      className={cn("flex flex-col bg-panel text-fg overflow-hidden", frame)}>
      <div className="shrink-0 bg-[linear-gradient(180deg,#242424_0%,#2d2d2d_55%,var(--color-panel)_100%)] pt-[37px] pb-8 text-white">
        <div className={cn("px-10", column)}>
          <div className="flex h-8 items-center gap-3">
            <button
              type="button"
              onClick={onBack}
              className="-ml-6 grid h-8 w-8 place-items-center rounded-md text-white hover:bg-white/10"
              title="Back to help"
              aria-label="Back to help"
            >
              <ChevronLeft className="h-5 w-5" aria-hidden />
            </button>
            <span className="text-[18px] font-bold">Support</span>
            {onClose && (
              <button
                type="button"
                onClick={onClose}
                className="-mr-4 ml-auto grid h-8 w-8 place-items-center rounded-md text-white hover:bg-white/10"
                title="Close"
                aria-label="Close help"
              >
                <X className="h-5 w-5" aria-hidden />
              </button>
            )}
          </div>
          <p className="mt-2 text-[12px] text-white/60">Message the team behind the product</p>
        </div>
      </div>

      <div ref={listRef} className="-mt-4 flex-1 min-h-0 overflow-y-auto overscroll-contain pb-3"
        onScroll={(e) => {
          const el = e.currentTarget;
          stick.current = el.scrollHeight - el.scrollTop - el.clientHeight < 40;
        }}>
        <div className={cn("px-5 flex flex-col gap-2", column)}>
          {s.phase === "loading" && s.messages.length === 0 && (
            <div className="px-1 text-[13px] text-fg-dim animate-pulse">Loading…</div>
          )}
          {s.phase !== "loading" && s.messages.length === 0 && !s.error && (
            <div className="rounded-2xl border border-border bg-bg-elev-1 px-4 py-3 text-[14px] text-fg-dim">{SUPPORT_EMPTY}</div>
          )}
          {s.messages.map((m) => (
            <div key={m.id} className={cn("flex flex-col gap-0.5", m.from === "me" ? "items-end" : "items-start")}>
              {m.from === "support" && <span className="px-1 text-[11px] text-muted">Support</span>}
              {m.text && (
                <div className={cn(
                  "max-w-[85%] rounded-2xl px-3.5 py-2 text-[13px] whitespace-pre-wrap break-words",
                  m.from === "me" ? "rounded-br-md bg-fg text-panel" : "rounded-bl-md bg-bg-elev-1 text-fg",
                )}>
                  {m.text}
                </div>
              )}
              {m.photos.length > 0 && (
                <div className={cn("flex max-w-[85%] flex-wrap gap-1.5", m.from === "me" && "justify-end")}>
                  {m.photos.map((p) => (
                    <a key={p.id} href={`/admin/support/photos/${p.id}`} target="_blank" rel="noopener noreferrer"
                      title="Open photo" className="block overflow-hidden rounded-xl border border-border bg-bg-elev-1">
                      {/* eslint-disable-next-line @next/next/no-img-element */}
                      <img src={`/admin/support/photos/${p.id}`} alt="Photo" loading="lazy" className="h-24 w-24 object-cover" />
                    </a>
                  ))}
                </div>
              )}
            </div>
          ))}
          {s.error && (
            <div role="alert" className="flex items-center gap-2 px-1 text-[12px] text-fg-dim">
              <span>{s.error}</span>
              {s.phase === "failed" && (
                <button type="button" onClick={load} className="underline hover:text-fg">Retry</button>
              )}
            </div>
          )}
        </div>
      </div>

      <div className="shrink-0 border-t border-border bg-panel">
        <div className={cn("px-4 pt-2.5 pb-4", composerPad, column)}>
          {s.photos.length > 0 && (
            <div className="mb-2 flex flex-wrap gap-2" aria-label="Photos to send">
              {s.photos.map((p) => (
                <div key={p.key} className="relative">
                  {/* eslint-disable-next-line @next/next/no-img-element */}
                  <img src={p.url} alt="Photo to send" className="h-14 w-14 rounded-lg border border-border object-cover" />
                  <button
                    type="button"
                    onClick={() => dispatch({ type: "photo_removed", key: p.key })}
                    className="absolute -right-1.5 -top-1.5 grid h-5 w-5 place-items-center rounded-full border border-border bg-bg-elev-2 text-fg"
                    aria-label="Remove photo"
                    title="Remove photo"
                  >
                    <X className="h-3 w-3" aria-hidden />
                  </button>
                </div>
              ))}
            </div>
          )}
          <div className="flex items-end gap-2 rounded-3xl border border-border bg-panel py-1.5 pl-2 pr-1.5 focus-within:border-fg-dim">
            <input
              ref={fileRef}
              type="file"
              accept="image/*"
              multiple
              hidden
              aria-label="Choose photos"
              onChange={(e) => { addPhotos(imageFiles(e.currentTarget.files)); e.currentTarget.value = ""; }}
            />
            <button
              type="button"
              onClick={() => fileRef.current?.click()}
              disabled={s.photos.length >= MAX_SUPPORT_PHOTOS}
              className="grid h-8 w-8 shrink-0 place-items-center rounded-full text-fg-dim hover:text-fg disabled:opacity-25"
              aria-label="Add photos"
              title={`Add up to ${MAX_SUPPORT_PHOTOS} photos`}
            >
              <ImagePlus className="h-[18px] w-[18px]" aria-hidden />
            </button>
            <textarea
              value={draft}
              onChange={(e) => onEntry({ type: "draft", text: e.target.value })}
              onKeyDown={(e) => {
                if (e.key === "Enter" && !e.shiftKey) {
                  e.preventDefault();
                  send();
                }
              }}
              onPaste={(e) => {
                const files = imageFiles(e.clipboardData?.files);
                if (files.length > 0) {
                  e.preventDefault();
                  addPhotos(files);
                }
              }}
              placeholder="Message Support…"
              title="Goes to the product team. Enter to send · Shift+Enter for a new line"
              aria-label="Message Support"
              rows={1}
              className={cn(
                "flex-1 min-w-0 max-h-28 resize-none bg-transparent py-1.5 leading-5 text-fg placeholder:text-muted focus:outline-none [field-sizing:content]",
                inputText,
              )}
            />
            <button
              type="button"
              onClick={send}
              disabled={!canSend(s, draft)}
              className="grid h-8 w-8 shrink-0 place-items-center rounded-full bg-fg text-panel transition-opacity disabled:opacity-25"
              aria-label="Send to Support"
              title="Send"
            >
              <ArrowUp className="h-4 w-4" aria-hidden />
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
