"use client";


import Link from "next/link";
import { useEffect, useState } from "react";
import { KeyRound, X } from "lucide-react";

import { useOptionalChatter } from "@/contexts/ChatterContext";
import {
  API_KEY_ERROR_EVENT,
  isApiKeyErrorPayload,
  type ApiKeyErrorPayload,
} from "@/lib/relay";

export const DEDUPE_MS = 10_000;
const SHOW_MS = 15_000;

export function ApiKeyMessage({ payload }: { payload: ApiKeyErrorPayload }) {
  const chatter = useOptionalChatter()?.chatter ?? null;
  return (
    <span>
      {payload.message}{" "}
      {chatter ? (
        "Ask your agency owner to add it."
      ) : (
        <>
          {payload.fix}{" "}
          <Link href={payload.fix_url || "/settings/ai-keys"} className="underline text-accent">
            Open Settings › AI keys
          </Link>
        </>
      )}
    </span>
  );
}

interface Toast {
  id: number;
  payload: ApiKeyErrorPayload;
}

const dedupeKey = (p: ApiKeyErrorPayload) => `${p.feature}|${p.provider}|${p.error}`;

export function ApiKeyToaster() {
  const [toasts, setToasts] = useState<Toast[]>([]);

  useEffect(() => {
    const lastShown = new Map<string, number>();
    let seq = 0;
    const timers = new Set<ReturnType<typeof setTimeout>>();
    const onKeyError = (ev: Event) => {
      const payload = (ev as CustomEvent<unknown>).detail;
      if (!isApiKeyErrorPayload(payload)) return;
      const key = dedupeKey(payload);
      const now = Date.now();
      const last = lastShown.get(key);
      if (last !== undefined && now - last < DEDUPE_MS) return;
      lastShown.set(key, now);
      const id = ++seq;
      setToasts((t) => [...t.filter((x) => dedupeKey(x.payload) !== key), { id, payload }]);
      const timer = setTimeout(() => {
        timers.delete(timer);
        setToasts((t) => t.filter((x) => x.id !== id));
      }, SHOW_MS);
      timers.add(timer);
    };
    window.addEventListener(API_KEY_ERROR_EVENT, onKeyError);
    return () => {
      window.removeEventListener(API_KEY_ERROR_EVENT, onKeyError);
      timers.forEach(clearTimeout);
    };
  }, []);

  if (toasts.length === 0) return null;
  return (
    <div className="fixed top-3 left-1/2 -translate-x-1/2 z-[70] flex flex-col gap-2 w-[min(32rem,calc(100vw-1.5rem))]">
      {toasts.map((t) => (
        <div
          key={t.id}
          role="alert"
          className="flex items-start gap-2 rounded-lg border border-warn/50 bg-panel px-3 py-2.5 text-sm text-fg shadow-lg"
        >
          <KeyRound size={16} className="text-warn mt-0.5 shrink-0" aria-hidden />
          <div className="min-w-0 flex-1 leading-snug">
            <ApiKeyMessage payload={t.payload} />
          </div>
          <button
            type="button"
            aria-label="Dismiss"
            className="text-fg-dim hover:text-fg shrink-0"
            onClick={() => setToasts((all) => all.filter((x) => x.id !== t.id))}
          >
            <X size={14} />
          </button>
        </div>
      ))}
    </div>
  );
}
