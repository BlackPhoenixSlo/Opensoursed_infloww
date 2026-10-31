"use client";

/**
 * The Human style block Auto-reply and Get to know fans share: `useHumanStyle` holds the boxes touched on the page
 * (the style PUT merges, so only those are sent) and saves them with the page's own Save; `HumanStyleBlock` renders
 * the boxes once the style blob is in hand. A save drops only the boxes it wrote (humanStyle.ts `dropSaved`).
 * `usePageSave` is that one Save: the page's own mutation and the style save, one verdict.
 */

import { useState } from "react";

import { FormBlock, SwitchRow, type SaveVerdict } from "@/components/automations/automationPage";
import { dropSaved, styleBoxes, type StyleEngine } from "@/components/automations/humanStyle";
import type { Saved } from "@/components/automations/sentDraft";
import { useSaveStyleConfig, useStyleConfig, type StyleConfig } from "@/hooks/useStyleConfig";

export function useHumanStyle(engine: StyleEngine, accountId: string) {
  const q = useStyleConfig(accountId);
  const m = useSaveStyleConfig(accountId);
  // Only the boxes touched here; the rest render the stored/default value.
  const [edits, setEdits] = useState<StyleConfig>({});
  const value: StyleConfig = { ...q.data?.defaults, ...q.data?.config, ...edits };
  return {
    engine,
    loaded: !!q.data,
    value,
    /** A toggle; it clears the last failed style save's message. */
    set: (k: keyof StyleConfig, on: boolean) => {
      if (m.isError) m.reset();
      setEdits((prev) => ({ ...prev, [k]: on }));
    },
    /** PUTs the touched boxes, if any. */
    save: () => {
      if (Object.keys(edits).length === 0) return;
      const sent = edits;
      m.mutate(sent, { onSuccess: () => setEdits((prev) => dropSaved(prev, sent)) });
    },
    pending: m.isPending,
    error: m.error,
    /** The style half of "Saved": no box left unsaved (a sent one stays an edit until its save lands, one toggled
     *  during a save stays after) and no failed save. */
    clean: !m.isError && Object.keys(edits).length === 0,
  };
}

export type HumanStyle = ReturnType<typeof useHumanStyle>;

export function HumanStyleBlock({ style }: { style: HumanStyle }) {
  if (!style.loaded) return null;
  const v = style.value;
  return (
    <FormBlock title="Human style">
      {styleBoxes(style.engine).map(({ key, label, hint, parent }) => (
        <SwitchRow
          key={key}
          label={label}
          hint={hint}
          checked={!!v[key]}
          disabled={!!parent && !v[parent]}
          onChange={(on) => style.set(key, on)}
        />
      ))}
    </FormBlock>
  );
}

/** What `usePageSave` reads of the page's own save mutation. */
interface PageMutation { isPending: boolean; isSuccess: boolean; isError: boolean; error: Error | null; reset: () => void }

/** The page's Save: its mutation `m` plus the style save, one verdict (automationPage.tsx `<SaveRow>` renders it).
 *  `pageUnsaved` is the page form's sentDraft.ts `unsaved`, so an edit turns "Saved" off by itself; `edit` (each page
 *  edit) clears a failed save's message, then dispatches. `save(run)` saves the style, records the draft as sent, then
 *  `run`s the page's own mutate. */
export function usePageSave<E extends { type: string }>(
  m: PageMutation,
  style: Pick<HumanStyle, "save" | "pending" | "error" | "clean">,
  pageUnsaved: boolean,
  dispatch: (a: E | Saved) => void,
): SaveVerdict & { edit: (a: E) => void; save: (run: () => void) => void } {
  const failed = m.error ?? style.error;
  return {
    edit: (a: E) => { if (m.isError) m.reset(); dispatch(a); },
    save: (run: () => void) => { style.save(); dispatch({ type: "saved" }); run(); },
    pending: m.isPending || style.pending,
    saved: m.isSuccess && !pageUnsaved && style.clean,
    error: failed ? failed.message || "Save failed" : null,
  };
}
