"use client";


import { useMemo, useRef } from "react";

import type { FanId } from "@/lib/fanId";
import { SCRIPT_SOURCE, type ScriptSourceSlot, type SourceStep } from "@/lib/chatSlots";
import { useSavedReplies } from "@/hooks/useSavedReplies";
import { useScriptCursor } from "@/hooks/useScriptCursor";

import type { ComposerDraft } from "./composerDraft";
import { EMPTY_SCRIPT_PROGRESS, canSkip, epochOf, scriptProgress } from "./scriptProgress";
import { fromLocal as savedReplyToPicked, type PickedTemplate } from "./TemplatePicker";

const NO_SOURCE: ReturnType<ScriptSourceSlot["useSource"]> = {
  scriptId: null, next: null, dismiss: () => {}, skip: () => {}, markSent: () => {},
};
const useNoSource: ScriptSourceSlot["useSource"] = () => NO_SOURCE;
const useSource = SCRIPT_SOURCE?.useSource ?? useNoSource;

export function useScriptSuggestions(accountId: string | null, fanId: FanId | null, fanSpokeLastAt: string | null) {
  // Sticky: a one-off reply between script steps does not clear the cursor; only manual dismiss does.
  const [scriptCursor, setScriptCursor] = useScriptCursor(accountId, fanId);
  // Fetch saved replies only when a cursor exists, so a mass-send composer pays no roundtrip.
  const replyQ = useSavedReplies(scriptCursor ? accountId : null);
  const source = useSource(accountId, fanId, fanSpokeLastAt);
  // Every template at step N+1: a script may hold several per step (2.1/2.2) and the chatter picks the branch.
  const nextSteps = useMemo(() => {
    if (scriptCursor && replyQ.data) {
      const { scriptId } = scriptCursor;
      const step = scriptCursor.step + 1;
      const replies = replyQ.data.filter((r) => r.script_id === scriptId && r.script_step === step);
      if (replies.length > 0) {
        return replies.map((r) => ({
          key: String(r.id), scriptId, step, label: String(step),
          title: r.title, text: r.text, picked: savedReplyToPicked(r),
        }));
      }
    }
    return source.next ? [{
      key: "source", scriptId: source.next.scriptId, step: source.next.step, label: source.next.label,
      title: null, text: source.next.text, picked: sourceStepPicked(source.next),
    }] : [];
  }, [scriptCursor, replyQ.data, source.next]);

  const progress = useRef(EMPTY_SCRIPT_PROGRESS);

  function afterSend(picked: ComposerDraft["script"]) {
    if (!picked) return;
    const { scriptId, scriptStep } = picked;
    const token = epochOf(progress.current, scriptId);
    return (failed: boolean) => {
      if (epochOf(progress.current, scriptId) !== token) return;
      if (SCRIPT_SOURCE?.owns(scriptId)) {
        if (!failed) source.markSent(scriptId, scriptStep);
      } else {
        setScriptCursor({ scriptId, step: scriptStep });
      }
    };
  }

  function dismiss(scriptId: string) {
    progress.current = scriptProgress(progress.current, { type: "end", scriptId });
    if (SCRIPT_SOURCE?.owns(scriptId)) source.dismiss();
    else setScriptCursor(null);
  }

  function skip(scriptId: string, step: number) {
    const now = Date.now();
    if (!canSkip(progress.current, now)) return;
    progress.current = scriptProgress(progress.current, { type: "skip", scriptId, now });
    if (SCRIPT_SOURCE?.owns(scriptId)) source.skip(scriptId, step);
    else setScriptCursor({ scriptId, step });
  }
  return { activeScriptId: scriptCursor?.scriptId ?? null, pinnedScriptId: source.scriptId, nextSteps, afterSend, dismiss, skip };
}

function sourceStepPicked(n: SourceStep): PickedTemplate {
  return {
    source: "local", text: n.text, displayText: n.text, mediaCount: 0, price: 0,
    lockedText: false, isWelcome: false, media: [], previews: [], taggedUsers: [],
    title: n.label, scriptId: n.scriptId, scriptStep: n.step,
  };
}
