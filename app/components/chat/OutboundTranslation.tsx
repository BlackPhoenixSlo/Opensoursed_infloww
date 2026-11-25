"use client";


import { useEffect, useId, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Languages, X } from "lucide-react";

import { useTranslationAllowed } from "@/lib/appliedSettings";
import type { FanId } from "@/lib/fanId";
import { LANGUAGES, useFanLanguage } from "@/lib/fanLanguage";
import { MP } from "@/lib/messagesPro";
import { relay } from "@/lib/relay";
import { cn } from "@/lib/utils";

const DEBOUNCE_MS = 400;

export interface OutboundTranslation {
  available: boolean;
  open: boolean;
  toggle: () => void;
  target: string | null;
  setTarget: (code: string | null) => void;
  translated: string | null;
  translating: boolean;
  failed: boolean;
  retry: () => void;
}

export function useOutboundTranslation(accountId: string | null, fanId: FanId | null, text: string): OutboundTranslation {
  const allowed = useTranslationAllowed(accountId) === true;
  const available = fanId != null && allowed;
  const [target, setTarget] = useFanLanguage(accountId, fanId);
  const [open, setOpen] = useState(() => target != null);
  const toggle = () => setOpen((v) => !v);

  const draft = text.trim();
  const [settled, setSettled] = useState(draft);
  useEffect(() => {
    const t = setTimeout(() => setSettled(draft), DEBOUNCE_MS);
    return () => clearTimeout(t);
  }, [draft]);

  const on = available && open && !!target;
  const q = useQuery({
    queryKey: ["translate-out", accountId, target, settled],
    queryFn: () => relay.post<{ results: Array<{ text: string } | null> }>(
      "/admin/translate", { texts: [settled], target }, { accountId },
    ).then((r) => {
      const out = r.results?.[0]?.text;
      if (!out) throw new Error("no translation");
      return out;
    }),
    enabled: on && !!settled,
    staleTime: Infinity,
    retry: false,
  });
  const current = on && !!draft && settled === draft;
  return {
    available, open: available && open, toggle, target, setTarget,
    translated: current ? q.data ?? null : null,
    translating: on && !!draft && (settled !== draft || q.isFetching),
    failed: current && q.isError && !q.isFetching,
    retry: () => void q.refetch(),
  };
}

export function outboundTranslationKey(
  e: React.KeyboardEvent, t: OutboundTranslation, replace: (s: string) => void, send: (s: string) => void,
): boolean {
  if (!t.available) return false;
  if (e.altKey && !e.shiftKey && !e.ctrlKey && !e.metaKey && e.code === "KeyT") {
    e.preventDefault();
    t.toggle();
    return true;
  }
  if (!t.open) return false;
  // While the strip is open Ctrl+Enter never sends the untranslated draft.
  if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) {
    e.preventDefault();
    if (t.translated) send(t.translated);
    return true;
  }
  if (t.translated && e.altKey && e.shiftKey && e.code === "KeyR") {
    e.preventDefault();
    replace(t.translated);
    return true;
  }
  return false;
}

export function OutboundTranslationStrip({
  t, onUse, onSend, canSend, formatted = false,
}: {
  t: OutboundTranslation;
  onUse: (s: string) => void;
  onSend: (s: string) => void;
  canSend: boolean;
  formatted?: boolean;
}) {
  const selectId = useId();
  if (!t.open) return null;
  return (
    <section
      aria-label="Translate my message"
      className={cn(MP.ours.Composer.notice, "flex flex-wrap items-center border-border bg-bg-elev-1 text-fg")}
    >
      <Languages aria-hidden className="size-3.5 shrink-0 text-fg-dim" />
      <label htmlFor={selectId} className="shrink-0 text-fg-dim">Translate into</label>
      <select
        id={selectId}
        value={t.target ?? ""}
        onChange={(e) => t.setTarget(e.target.value || null)}
        className="shrink-0 bg-transparent border border-border rounded px-1"
      >
        <option value="">Choose the Fan&apos;s language</option>
        {LANGUAGES.map((l) => <option key={l.code} value={l.code}>{l.name}</option>)}
      </select>
      <span className="flex-1 min-w-0 truncate" title={t.translated ?? undefined}>
        {t.translated ?? (t.translating ? "Translating…" : t.failed ? (
          <>
            <span role="status" className="text-fg-dim">Translation failed. </span>
            <button type="button" onClick={t.retry} className="text-[var(--inf-accent-text,var(--color-accent))]">
              Retry
            </button>
          </>
        ) : "")}
      </span>
      <button
        type="button"
        disabled={!t.translated}
        onClick={() => t.translated && onUse(t.translated)}
        title="Replace the message with the translation (Shift+Alt+R)"
        className="shrink-0 text-[var(--inf-accent-text,var(--color-accent))] disabled:text-fg-dim disabled:cursor-not-allowed"
      >
        Use translation
      </button>
      <button
        type="button"
        disabled={!t.translated || !canSend}
        onClick={() => t.translated && onSend(t.translated)}
        title="Send the translation (Ctrl+Enter)"
        className="shrink-0 text-[var(--inf-accent-text,var(--color-accent))] disabled:text-fg-dim disabled:cursor-not-allowed"
      >
        Send translation
      </button>
      <button type="button" onClick={t.toggle} aria-label="Close translation" title="Close (Alt+T)" className="shrink-0 text-fg-dim hover:text-fg">
        <X aria-hidden className="size-3.5" />
      </button>
      {formatted && (
        <span data-translation-plain="" className="basis-full text-fg-dim">
          The translation is plain text: Use or Send translation drops the formatting.
        </span>
      )}
    </section>
  );
}
