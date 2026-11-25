"use client";


import { useState } from "react";

import { FormBlock, SwitchRow } from "@/components/automations/automationPage";
import { saveVerdict, type SaveVerdict } from "@/components/ui/infloww";
import { dropSaved, styleBoxes, type StyleEngine } from "@/components/automations/humanStyle";
import type { Saved } from "@/components/automations/sentDraft";
import { useSaveStyleConfig, useStyleConfig, type StyleConfig } from "@/hooks/useStyleConfig";

export function useHumanStyle(engine: StyleEngine, accountId: string) {
  const q = useStyleConfig(accountId);
  const m = useSaveStyleConfig(accountId);
  const [edits, setEdits] = useState<StyleConfig>({});
  const value: StyleConfig = { ...q.data?.defaults, ...q.data?.config, ...edits };
  return {
    engine,
    loaded: !!q.data,
    value,
    set: (k: keyof StyleConfig, on: boolean) => {
      if (m.isError) m.reset();
      setEdits((prev) => ({ ...prev, [k]: on }));
    },
    save: () => {
      if (Object.keys(edits).length === 0) return;
      const sent = edits;
      m.mutate(sent, { onSuccess: () => setEdits((prev) => dropSaved(prev, sent)) });
    },
    pending: m.isPending,
    error: m.error,
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

interface PageMutation { isPending: boolean; isSuccess: boolean; isError: boolean; error: Error | null; reset: () => void }

export function usePageSave<E extends { type: string }>(
  m: PageMutation,
  style: Pick<HumanStyle, "save" | "pending" | "error" | "clean">,
  pageUnsaved: boolean,
  dispatch: (a: E | Saved) => void,
): SaveVerdict & { edit: (a: E) => void; save: (run: () => void) => void } {
  return {
    edit: (a: E) => { if (m.isError) m.reset(); dispatch(a); },
    save: (run: () => void) => { style.save(); dispatch({ type: "saved" }); run(); },
    ...saveVerdict({ isPending: m.isPending || style.pending, isSuccess: m.isSuccess, error: m.error ?? style.error },
      !pageUnsaved && style.clean),
  };
}
