"use client";

/** ReadyMadePanel's create / edit dialog for one saved ready-made rule. */

import { useState } from "react";
import { PenLine } from "lucide-react";

import { EmptyState, IfButton, IfHelp, IfInput, IfLabel, IfModal, IfSegmented, IfSelect, IfSwitch } from "@/components/ui/infloww";
import { IF_FIELD } from "@/components/ui/ifSelect";
import { useCreateRule, useUpdateRule, type AutomationRule } from "@/hooks/useAutomations";
import { useRawJson } from "@/lib/rawJsonReducer";
import { PAYLOAD_RAW, withoutDryRun } from "@/lib/rulePayload";
import { UNIT_S, splitInterval, type Unit } from "@/components/automations/ruleInterval";
import { LIST_KEY, type Kind } from "@/components/compose/premadeRows";
import { KIND_COPY, canSave, hasContent, summarize } from "@/components/automations/readyMadeContent";
import { PremadeForm } from "@/components/compose/PremadeForm";
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

  const [name, setName] = useState(editing?.name ?? "");
  const init = splitInterval(editing?.every_seconds ?? 24 * 3600);
  const [intervalValue, setIntervalValue] = useState<number>(init.value);
  const [intervalUnit, setIntervalUnit] = useState<Unit>(init.unit);
  const [enabled, setEnabled] = useState<boolean>(editing?.is_enabled ?? true);
  const [dryRun, setDryRun] = useState<boolean>(
    Boolean((editing?.payload as Record<string, unknown> | undefined)?.dry_run),
  );

  const [composerOpen, setComposerOpen] = useState(false);
  // The composed payload + the raw-JSON escape hatch (lib/rawJsonReducer):
  // hand-edit / paste the whole `{posts|messages:[…]}` payload directly — the
  // composer forces you to PICK every media id, so this is the only way to
  // paste a big media_files pool or tweak a field the form doesn't expose.
  // Seeded from the rule being edited so saving WITHOUT re-composing preserves
  // it; the composer only overwrites it on "Use in rule". `dry_run` stays owned
  // by the toggle (stripped here, re-merged on save).
  const [raw, dispatch] = useRawJson(PAYLOAD_RAW, () => withoutDryRun(editing?.payload));
  const composed = raw.value;

  const everySeconds = Math.round(intervalValue * UNIT_S[intervalUnit]);
  const busy = createM.isPending || updateM.isPending;
  const copy = KIND_COPY[kind];
  const summary = summarize(composed, kind);
  const empty = !hasContent(composed, kind);
  // Create waits for content and a parseable raw buffer: Compose is the empty editor's one primary action.
  const ready = canSave(raw, kind);
  const submitLabel = isEdit ? "Save changes" : "Create";
  /** The empty payload's help line (Composer and Raw JSON). */
  const emptyHelp = `Add at least one ${copy.item} to enable ${submitLabel}.`;

  const fail = (error: string) => dispatch({ type: "fail", error });

  async function save() {
    if (!ready) return; // Create is disabled; the parse error or the help line says why
    if (everySeconds < 30) return fail("Interval must be at least 30 seconds.");
    const payload: Record<string, unknown> = { ...composed };
    if (dryRun) payload.dry_run = true;
    try {
      if (isEdit && editing) {
        await updateM.mutateAsync({
          id: editing.id,
          name: name.trim() || editing.name,
          every_seconds: everySeconds,
          payload,
          is_enabled: enabled,
        });
      } else {
        await createM.mutateAsync({
          account_id: accountId,
          kind,
          name: name.trim() || undefined,
          every_seconds: everySeconds,
          payload,
          is_enabled: enabled,
        });
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
  /** The one empty-payload help line: under the textarea (Raw JSON) or in the empty panel (Composer). */
  const help = empty ? <IfHelp id={ids.emptyHelp}>{emptyHelp}</IfHelp> : null;
  const items = copy.items;
  return (
    <IfModal
      width={722}
      title={editing ? `Edit · ${editing.name}` : `New ${copy.noun}`}
      onClose={onClose}
      size="editor"
      footer={(
        <>
          <IfButton onClick={onClose} disabled={busy}>Cancel</IfButton>
          <IfButton variant="primary" onClick={save} disabled={busy || !ready}>
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
              value={name}
              onChange={(e) => setName(e.target.value)}
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
                value={intervalValue}
                onChange={(e) => setIntervalValue(Math.max(1, Number(e.target.value) || 0))}
                className="w-24"
              />
              <IfSelect<Unit>
                aria-label="Interval unit"
                value={intervalUnit}
                onChange={setIntervalUnit}
                options={[{ value: "minutes", label: "minutes" }, { value: "hours", label: "hours" }]}
                className="w-[120px]"
              />
            </div>
          </div>

          {/* wrapped like Dry run so the grid cell doesn't stretch it off its row */}
          <div>
            <IfSwitch label="Enabled" checked={enabled} onChange={setEnabled} />
          </div>
          <div>
            <IfSwitch label="Dry run" checked={dryRun} onChange={setDryRun} />
            <IfHelp>Plans each run; nothing is {copy.pastVerb}.</IfHelp>
          </div>
        </div>

        {/* The payload: built with the rich PremadeForm (Composer), or hand-edited as JSON (paste a big
         *  media_files pool, tweak a field the form doesn't expose). The Dry run switch owns `dry_run`. */}
        <div>
          <div className="mb-2 flex flex-wrap items-center justify-between gap-2">
            <IfLabel id={ids.items} className="mb-0">{items}</IfLabel>
            <IfSegmented
              aria-label={`${items} editor`}
              value={raw.raw ? "raw" : "composer"}
              onChange={(v) => dispatch({ type: v === "raw" ? "open" : "close" })}
              options={[{ value: "composer", label: "Composer" }, { value: "raw", label: "Raw JSON" }]}
            />
          </div>

          {raw.raw ? (
            <>
              <textarea
                aria-label={`${items} JSON`}
                aria-describedby={[empty && ids.emptyHelp, raw.error && ids.error].filter(Boolean).join(" ") || undefined}
                aria-invalid={raw.invalid}
                value={raw.text}
                onChange={(e) => dispatch({ type: "edit", text: e.target.value })}
                rows={12}
                spellCheck={false}
                className={cn(IF_FIELD, "block w-full resize-y px-[11px] py-1 font-mono text-[13px] outline-none placeholder:text-muted focus:border-accent")}
                placeholder={`{ "${LIST_KEY[kind]}": [ … ] }`}
              />
              {help}
            </>
          ) : !empty ? (
            // Same panel as the empty state; default variant keeps Create the dialog's one primary.
            // Phone: stacked, 2-line summary, 44px full-width button.
            <div role="group" aria-labelledby={ids.items} className="flex flex-col gap-3 rounded-md border border-border-light bg-bg-elev-1 px-4 py-4 sm:flex-row sm:items-center sm:gap-4">
              <span className="min-w-0 flex-1 line-clamp-2 break-words text-fg sm:truncate">{summary}</span>
              <IfButton size="lg" icon={PenLine} className="border-border-light max-sm:h-11 max-sm:w-full" onClick={() => setComposerOpen(true)}>
                Edit content
              </IfButton>
            </div>
          ) : (
            // Empty: Compose is the next step, so it gets the panel and the dialog's one live primary.
            <EmptyState
              art={false}
              role="group"
              aria-labelledby={ids.items}
              className="rounded-md border border-border-light bg-bg-elev-1 px-4 py-5"
              textClassName="text-fg"
              text="No content yet"
              help={help}
              action={(
                <IfButton variant="primary" icon={PenLine} aria-describedby={ids.emptyHelp} onClick={() => setComposerOpen(true)}>
                  Compose
                </IfButton>
              )}
            />
          )}
        </div>

        {/* no alert while the buffer is unparseable: parse errors would re-announce per keystroke;
         *  aria-invalid/aria-describedby on the textarea carry them. Other errors (open/format/fail) alert. */}
        {raw.error && <div id={ids.error} role={raw.invalid ? undefined : "alert"} className="text-[12px] text-err whitespace-pre-wrap">{raw.error}</div>}
      </div>

      {composerOpen && (
        <PremadeForm
          kind={kind}
          accountId={accountId}
          title={KIND_COPY[kind].composeTitle}
          initialPayload={composed}
          onClose={() => setComposerOpen(false)}
          onComposePayload={(p) => {
            dispatch({ type: "set", value: p });
            setComposerOpen(false);
          }}
        />
      )}
    </IfModal>
  );
}
