"use client";

/** ReadyMadePanel's create / edit popup for one saved ready-made rule: the trigger and its ONE post / message in one
 *  dialog (ruleEditorForm owns the state; Escape never drops an edit, useTouched). */

import { useReducer } from "react";
import { Code } from "lucide-react";

import { IfButton, IfHelp, IfInput, IfLabel, IfModal, IfSegmented, IfSelect, IfSwitch } from "@/components/ui/infloww";
import { IF_FIELD } from "@/components/ui/ifSelect";
import { useCreateRule, useUpdateRule, type AutomationRule } from "@/hooks/useAutomations";
import { type Unit } from "@/components/automations/ruleInterval";
import { LIST_KEY, type Kind } from "@/components/compose/payloadRules";
import {
  formHoldNotice, KIND_COPY, MASS_PPV_ADVICE, summarize, waitHelp,
} from "@/components/automations/readyMadeContent";
import {
  buildBody, canSave, derive, initRuleEditor, ruleEditorReducer, type Fields,
} from "@/components/automations/ruleEditorForm";
import { PremadeFields } from "@/components/compose/PremadeFields";
import { useTouched } from "@/components/compose/useTouched";
import { cn } from "@/lib/utils";

export function ReadyMadeRuleEditor({
  kind,
  accountId,
  editing,
  onClose,
}: {
  kind: Kind;
  accountId: string;
  editing: AutomationRule | null;
  onClose: () => void;
}) {
  const isEdit = editing !== null;
  const createM = useCreateRule(accountId);
  const updateM = useUpdateRule(accountId);

  const [s, rawDispatch] = useReducer(ruleEditorReducer, undefined, () => initRuleEditor(kind, editing));
  const { touched, dispatch } = useTouched(s, rawDispatch, noSeed);
  const field = (patch: Partial<Fields>) => dispatch({ type: "field", patch });
  const raw = s.raw;
  const d = derive(s);
  const { view } = d;

  const busy = createM.isPending || updateM.isPending;
  const copy = KIND_COPY[kind];
  const ready = canSave(s, d);
  const submitLabel = isEdit ? "Save changes" : "Create";
  /** Why Create / Save changes waits, in the words of the view the user is in. */
  const emptyHelp = waitHelp(d.wait, view, kind, submitLabel);

  const fail = (error: string) => dispatch({ type: "raw", a: { type: "fail", error } });

  async function save() {
    const body = buildBody(s, d);
    if (!body) return; // Create is disabled; the parse error or the help line says why
    try {
      if (isEdit && editing) {
        // Untouched name / interval: the stored ones stay (buildBody leaves them out).
        await updateM.mutateAsync({ id: editing.id, ...body, name: body.name ?? editing.name });
      } else {
        // A blank name reads as the placeholder it showed, never the server's bare kind ("auto_posts").
        await createM.mutateAsync({ account_id: accountId, kind, ...body, name: body.name ?? copy.namePlaceholder });
      }
      onClose();
    } catch (e) {
      fail((e as Error)?.message || "Save failed");
    }
  }

  const ids = {
    name: `rm-${kind}-name`, every: `rm-${kind}-every`, items: `rm-${kind}-items`, emptyHelp: `rm-${kind}-empty-help`,
    error: `rm-${kind}-error`,
  };
  const help = (
    <>
      {emptyHelp && <IfHelp id={ids.emptyHelp}>{emptyHelp}</IfHelp>}
      {/* D6: a warning only, Save stays on. */}
      {d.advice === "ppv" && <IfHelp className="text-warn">{MASS_PPV_ADVICE}</IfHelp>}
    </>
  );
  const items = copy.items;
  return (
    <IfModal
      width={722}
      title={editing ? `Edit · ${editing.name}` : `New ${copy.noun}`}
      onClose={onClose}
      // While saving, neither × nor Escape: a failed save must land on an open editor, not vanish with it.
      closable={!busy}
      keyboard={!touched && !busy}
      size="editor"
      footer={(
        <>
          <IfButton onClick={onClose} disabled={busy}>Cancel</IfButton>
          <IfButton variant="primary" onClick={save} disabled={busy || !ready}
            aria-describedby={emptyHelp ? ids.emptyHelp : undefined}>
            {busy ? "Saving…" : submitLabel}
          </IfButton>
        </>
      )}
    >
      <div className="space-y-6">
        <div className="grid gap-6 sm:grid-cols-2">
          <div>
            <IfLabel htmlFor={ids.name}>Name</IfLabel>
            <IfInput
              id={ids.name}
              value={s.name}
              onChange={(e) => field({ name: e.target.value })}
              placeholder={copy.namePlaceholder}
              className="w-full"
            />
          </div>

          <div>
            <IfLabel htmlFor={ids.every}>Run every</IfLabel>
            <div className="flex items-center gap-2">
              <IfInput
                id={ids.every}
                type="number"
                min={1}
                value={s.intervalValue}
                onChange={(e) => field({ intervalValue: Math.max(1, Number(e.target.value) || 0) })}
                className="w-24"
              />
              <IfSelect<Unit>
                aria-label="Interval unit"
                value={s.intervalUnit}
                onChange={(intervalUnit) => field({ intervalUnit })}
                options={[{ value: "minutes", label: "minutes" }, { value: "hours", label: "hours" }]}
                className="w-[120px]"
              />
            </div>
          </div>
        </div>

        {/* The one post / message: its fields inline (Composer), or hand-edited as JSON (paste a big media_files
         *  pool, set a field the form doesn't expose — such a payload then stays in Raw JSON, `formHoldReason`). The Dry
         *  run switch owns `dry_run`. */}
        <div role="group" aria-labelledby={ids.items}>
          <div className="mb-4 flex flex-wrap items-center justify-between gap-2 border-b border-border pb-2">
            <IfLabel id={ids.items} className="mb-0 text-[16px] font-medium">{items}</IfLabel>
            <IfSegmented
              aria-label={`${items} editor`}
              value={raw.raw ? "raw" : "composer"}
              onChange={(v) => dispatch({ type: v === "raw" ? "toRaw" : "toForm" })}
              options={[{ value: "composer", label: "Composer" }, { value: "raw", label: "Raw JSON" }]}
            />
          </div>

          {view === "raw" ? (
            <>
              <textarea
                aria-label={`${items} JSON`}
                aria-describedby={[emptyHelp && ids.emptyHelp, raw.error && ids.error].filter(Boolean).join(" ") || undefined}
                aria-invalid={raw.invalid}
                value={raw.text}
                onChange={(e) => dispatch({ type: "raw", a: { type: "edit", text: e.target.value } })}
                rows={12}
                spellCheck={false}
                className={cn(IF_FIELD, "block w-full resize-y px-[11px] py-1 font-mono text-[13px] outline-none placeholder:text-muted focus:border-accent")}
                placeholder={`{ "${LIST_KEY[kind]}": [ … ] }`}
              />
              {help}
            </>
          ) : view === "legacy" ? (
            // A payload the one-item fields can't hold losslessly keeps running; the fields would drop its other keys.
            // Phone: stacked, 2-line summary, 44px full-width button.
            <div className="flex flex-col gap-3 rounded-md border border-border-light bg-bg-elev-1 px-4 py-4 sm:flex-row sm:items-center sm:gap-4">
              <div className="min-w-0 flex-1">
                <span className="line-clamp-2 break-words text-fg sm:block sm:truncate">{summarize(raw.value, kind)}</span>
                {d.hold && <IfHelp className="text-warn">{formHoldNotice(d.hold, kind)}</IfHelp>}
                {help}
              </div>
              <IfButton size="lg" icon={Code} className="border-border-light max-sm:h-11 max-sm:w-full"
                onClick={() => dispatch({ type: "toRaw" })}>
                Edit in Raw JSON
              </IfButton>
            </div>
          ) : (
            <>
              <PremadeFields kind={kind} accountId={accountId} row={s.row}
                dispatch={(a) => dispatch({ type: "row", a })} />
              {help}
            </>
          )}
        </div>

        {/* wrapped so the grid cell doesn't stretch the switch off its row */}
        <div className="grid gap-6 border-t border-border pt-4 sm:grid-cols-2">
          <div>
            <IfSwitch label="Enabled" checked={s.enabled} onChange={(enabled) => field({ enabled })} />
          </div>
          <div>
            <IfSwitch label="Dry run" checked={s.dryRun} onChange={(dryRun) => field({ dryRun })} />
            <IfHelp>Plans each run; nothing is {copy.pastVerb}.</IfHelp>
          </div>
        </div>

        {/* no alert while the buffer is unparseable: parse errors would re-announce per keystroke;
         *  aria-invalid/aria-describedby on the textarea carry them. Other errors (open/format/fail) alert. */}
        {raw.error && <div id={ids.error} role={raw.invalid ? undefined : "alert"} className="text-[12px] text-err whitespace-pre-wrap">{raw.error}</div>}
      </div>
    </IfModal>
  );
}

/** No automatic action seeds the popup: every dispatch is the user's. */
const noSeed = () => false;
