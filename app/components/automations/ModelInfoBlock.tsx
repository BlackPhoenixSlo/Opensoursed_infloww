"use client";

/**
 * Model info, the account's short note every chat prompt pins (`account_ai_config.model_notes`, through
 * `_persona.compose_persona`: Get to know fans and Auto-reply). One block, shown on both pages, with its own Save
 * ("Save model info"): it PUTs the STORED brain back with only `model_notes` changed (the PUT replaces the brain).
 * The box mounts only once the stored brain is in hand, so a failed read is never saved back; its Save waits while any
 * brain PUT or re-read is out (`useAccountConfigBusy`), so it never lands on a stale copy. Form state: `personaDraft.ts`.
 * `draftFromImages` (Full AI Chat only) adds "Make persona from the Creator's images": POST /admin/full-ai/persona/draft fills the
 * box, unsaved; only Save writes. With a persona in the box it asks first (the house `ifConfirm`), before the paid call.
 * `saveNote` is a line beside Save (Full AI Chat: it saves for every live chat, not into the config checkpoint).
 */

import { useReducer, type ReactNode } from "react";

import { FormBlock } from "@/components/automations/automationPage";
import { Skeleton } from "@/components/ui/Skeleton";
import { ifConfirm } from "@/components/ui/ifConfirm";
import { IfButton, IfTextArea, SaveRow, saveVerdict } from "@/components/ui/infloww";
import { useAccountConfig, useAccountConfigBusy, useSaveAccountConfig, type AccountConfigResp } from "@/hooks/useAccountConfig";
import { relay } from "@/lib/relay";

import {
  buildPayload, busyLine, canDraft, dirty, initPersonaDraft, MODEL_NOTES_MAX as NOTES_MAX, personaDraftReducer, requestBody, type PersonaDraftResp,
} from "./personaDraft";

// Spec phase-03c › Solution 1 / story 14, word for word.
const NEED_DESCRIBE = "No described images yet. Run Prepare content or the vault describe first.";
const REPLACE_ASK = "Replace the Model info in the box with a new draft from the Creator's images? Nothing is saved until you tap Save.";

/** A form block's fields while its read runs: a label bar over an input-sized bar, twice. */
export function FormSkeleton() {
  return (
    <div role="status" aria-label="Loading" className="space-y-3">
      <Skeleton className="h-3 w-28" />
      <Skeleton className="h-10 w-full" />
      <Skeleton className="h-3 w-40" />
      <Skeleton className="h-10 w-full" />
    </div>
  );
}

export function ModelInfoBlock({ accountId, draftFromImages = false, saveNote }: {
  accountId: string; draftFromImages?: boolean; saveNote?: ReactNode;
}) {
  const cfgQ = useAccountConfig(accountId);
  return (
    <FormBlock title="Model info">
      {cfgQ.data ? <ModelInfoForm accountId={accountId} resp={cfgQ.data} draftFromImages={draftFromImages} saveNote={saveNote} /> : cfgQ.isLoading ? <FormSkeleton /> : (
        <p className="text-[14px] text-err">{(cfgQ.error as Error)?.message || "Could not load Model info."}</p>
      )}
    </FormBlock>
  );
}

function ModelInfoForm({ accountId, resp, draftFromImages, saveNote }: {
  accountId: string; resp: AccountConfigResp; draftFromImages: boolean; saveNote?: ReactNode;
}) {
  const saveM = useSaveAccountConfig(accountId);
  // Any brain PUT or re-read out (this Save's or the page's model Save): `resp` may be stale, a PUT now could undo it.
  const busy = useAccountConfigBusy(accountId);
  // Empty → the prewritten template; its lines left blank never reach a prompt.
  const [draft, dispatch] = useReducer(personaDraftReducer,
    resp.config.model_notes || resp.model_notes_template || "", initPersonaDraft);
  const text = draft.text;
  const template = resp.model_notes_template || "";
  const drafting = draft.phase === "drafting";
  const busyText = busyLine(draft);
  const asking = draft.phase === "confirm";

  const makeDraft = async () => {
    const click = { type: "click", template } as const;
    const next = personaDraftReducer(draft, click);
    if (next === draft) return;  // a request out or a question open: a double tap is one request
    const body = requestBody(draft, accountId);
    dispatch(click);
    if (next.phase === "confirm") {
      const ok = await ifConfirm(REPLACE_ASK, { confirmLabel: "Make new draft" });
      dispatch({ type: ok ? "confirm" : "cancel" });
      if (!ok) return;  // Cancel: no request, the text stays
    }
    relay.post<PersonaDraftResp>("/admin/full-ai/persona/draft", body, { accountId }).then(
      (r) => dispatch(r.need_describe ? { type: "draftEmpty", note: NEED_DESCRIBE } : { type: "draftOk", text: r.text, notes: r.notes }),
      (e: unknown) => dispatch({ type: "draftFail", error: (e as Error)?.message || "Could not make a persona." }),
    );
  };

  return (
    <>
      <p className="text-[12px] text-muted">
        A few short lines about this model. The AI reads them in Get to know fans and Auto-reply chats; a line left
        blank is ignored.
      </p>
      {draftFromImages && (
        <div className="flex flex-wrap items-center gap-3">
          <IfButton onClick={makeDraft} disabled={!canDraft(draft)}>
            {drafting ? "Making persona…" : "Make persona from the Creator's images"}
          </IfButton>
          {busyText && <span role="status" className="text-[12px] text-muted">{busyText}</span>}
          {draft.error && <span className="text-[12px] text-err">{draft.error}</span>}
        </div>
      )}
      <IfTextArea
        aria-label="Model info"
        value={text}
        readOnly={drafting || asking}
        onChange={(e) => {
          if (saveM.isSuccess || saveM.isError) saveM.reset();
          dispatch({ type: "edit", text: e.target.value });
        }}
        rows={7}
        maxLength={NOTES_MAX}
      />
      <SaveRow
        save={saveVerdict(saveM, !dirty(draft))}
        label="Save model info"
        disabled={busy}
        onSave={() => saveM.mutate(buildPayload(resp.config, draft), { onSuccess: () => dispatch({ type: "saved", text }) })}
      >
        <span className="text-[12px] text-muted tabular-nums">{text.length}/{NOTES_MAX}</span>
        {saveNote && <span className="text-[12px] text-muted">{saveNote}</span>}
      </SaveRow>
      {draft.notes.length > 0 && (
        <ul className="space-y-1 text-[12px] text-muted">
          {draft.notes.map((n) => <li key={n}>{n}</li>)}
        </ul>
      )}
    </>
  );
}
