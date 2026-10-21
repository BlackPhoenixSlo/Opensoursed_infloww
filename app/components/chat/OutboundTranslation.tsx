"use client";

/**
 * OutboundTranslation — Infloww's composer translation (04 M15/M16): the
 * chatter writes in their own language and the Fan gets it in the Fan's.
 * Each Fan has a language (`useFanLanguage`); while the strip is open the
 * draft is translated into it through /admin/translate's `target` (cached in
 * `translation_cache`), and the strip offers "Use translation" (the draft
 * becomes the translation, Shift+Alt+R) and "Send translation" (Ctrl+Enter,
 * which while the strip is open never sends the untranslated draft).
 * Alt+T, or the Translate popover's "Translate my messages" (the Composer
 * hands it `toggle`), opens and closes it; it opens by itself for a Fan whose
 * language is set. Absent while the
 * Agency's AI translation is off for a chatter, and on a composer with no Fan.
 */

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
  /** The current draft in the Fan's language; null while none is ready. */
  translated: string | null;
  translating: boolean;
}

export function useOutboundTranslation(accountId: string | null, fanId: FanId | null, text: string): OutboundTranslation {
  // A chatter's is unknown until the Applied read answers: off till then.
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
    ).then((r) => r.results?.[0]?.text ?? null),
    enabled: on && !!settled,
    staleTime: Infinity,
    retry: false,
  });
  // Only a translation of the draft as it stands now: never send an older one.
  const current = on && !!draft && settled === draft;
  return {
    available, open: available && open, toggle, target, setTarget,
    translated: current ? q.data ?? null : null,
    translating: on && !!draft && (settled !== draft || q.isFetching),
  };
}

/** The composer textarea's translation keys; true when one was handled. */
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
  // While the strip is open Ctrl+Enter is always "Send translation": with none
  // ready yet it does nothing, never the untranslated draft.
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

/** The strip in the composer's notice stack. */
export function OutboundTranslationStrip({
  t, onUse, onSend, canSend,
}: {
  t: OutboundTranslation;
  onUse: (s: string) => void;
  onSend: (s: string) => void;
  canSend: boolean;
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
        {t.translated ?? (t.translating ? "Translating…" : "")}
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
    </section>
  );
}
