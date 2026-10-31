"use client";

/**
 * useScriptSuggestions — the Composer's "Next in" bubbles: the next step of
 * the user Script the chat last sent a step of (`useScriptCursor`). A send
 * that rode a step moves it on (`advance`); ✕ ends one (`dismiss`).
 */

import { useMemo } from "react";

import type { FanId } from "@/lib/fanId";
import { useSavedReplies } from "@/hooks/useSavedReplies";
import { useScriptCursor } from "@/hooks/useScriptCursor";

import type { ComposerDraft } from "./composerDraft";
import { fromLocal as savedReplyToPicked } from "./TemplatePicker";

export function useScriptSuggestions(accountId: string | null, fanId: FanId | null) {
  // Script-cursor state — remembers the last sent script step per chat so
  // the composer can suggest the next step in the same script. The cursor
  // survives reloads (localStorage) and is sticky: typing a one-off reply
  // between script steps does NOT clear it, so the user can resume the
  // sequence after side-conversations. Cleared on manual dismiss only.
  const [scriptCursor, setScriptCursor] = useScriptCursor(accountId, fanId);
  // We only need the saved-reply list when a cursor exists — gate the
  // fetch so cold chats don't pay a /admin/saved-replies roundtrip just
  // to render the empty composer.
  const replyQ = useSavedReplies(scriptCursor ? accountId : null);
  // Every template at step N+1, not just the first: a Script may hold
  // several per step ("2.1/2.2", e.g. bought / not bought), and the
  // chatter picks the branch.
  const nextSteps = useMemo(() => {
    if (!scriptCursor || !replyQ.data) return [];
    const target = scriptCursor.step + 1;
    return replyQ.data
      .filter((r) => (r.script_id ?? "") === scriptCursor.scriptId && r.script_step === target)
      .map((r) => ({
        key: String(r.id), scriptId: r.script_id ?? "", label: String(r.script_step),
        title: r.title, text: r.text, picked: savedReplyToPicked(r),
      }));
  }, [scriptCursor, replyQ.data]);
  /** After a send that rode Script step `picked` (the draft's `script`). */
  function advance(picked: ComposerDraft["script"]) {
    if (picked) setScriptCursor({ scriptId: picked.scriptId, step: picked.scriptStep });
  }
  /** ✕ on a bubble: the Script stops suggesting next steps. */
  function dismiss() {
    setScriptCursor(null);
  }
  return { nextSteps, advance, dismiss };
}
