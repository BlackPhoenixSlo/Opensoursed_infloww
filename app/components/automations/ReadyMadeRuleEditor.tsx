"use client";

/** ReadyMadePanel's create / edit dialog for one saved ready-made rule. */

import { useState } from "react";
import { PenLine } from "lucide-react";

import { IfButton, IfHelp, IfInput, IfLabel, IfModal, IfSegmented, IfSelect, IfSwitch } from "@/components/ui/infloww";
import { IF_FIELD } from "@/components/ui/ifSelect";
import { EDITOR_MODAL } from "@/components/automations/automationPage";
import { useCreateRule, useUpdateRule, type AutomationRule } from "@/hooks/useAutomations";
import { canSubmit, useRawJson } from "@/lib/rawJsonReducer";
import { PAYLOAD_RAW, withoutDryRun } from "@/lib/rulePayload";
import { UNIT_S, splitInterval, type Unit } from "@/components/automations/ruleInterval";
import type { Kind } from "@/components/compose/premadeRows";
import { ComposeModal } from "@/components/automations/ComposeModal";
import { cn } from "@/lib/utils";

/** The words each rule kind is shown with. Auto Mass sends OF mass messages
 *  (`mass_premade` delegates to `send_mass_message`, OF's messages/queue), so
 *  its copy uses Infloww's names: "mass message", "Auto-unsend". */
export const KIND_COPY: Record<Kind, {
  /** The page title when the panel is pinned to this kind (`only`). */
  title: string;
  /** Learn's popover text when pinned. */
  blurb: string;
  /** The pinned header's primary. */
  button: string;
  /** "New …" (the editor's title). */
  noun: string;
  /** "No … yet" (the empty table). */
  plural: string;
  /** One item of the payload list, and the list's label. */
  item: string;
  items: string;
}> = {
  auto_posts: {
    title: "Auto Post",
    button: "New auto post",
    blurb:
      "Posts that publish on their own schedule, one at a time, and can delete " +
      "themselves after the hours you set. See what's queued next and the recent " +
      "runs below. “Run now” posts the next one immediately.",
    noun: "auto post",
    plural: "auto posts",
    item: "post",
    items: "Posts",
  },
  mass_premade: {
    title: "Auto Mass",
    button: "New auto mass",
    blurb:
      "Mass messages that send on their own schedule to the fans you pick, " +
      "through the same OF mass message path as Smart Messages (sent to the " +
      "general inbox). Each message can be resent on a timer and unsent " +
      "automatically after the hours you set. See what's queued next and the " +
      "recent runs below. “Run now” sends it immediately.",
    noun: "auto mass message",
    plural: "auto mass messages",
    item: "message",
    items: "Messages",
  },
};

// ── Inline editor (create / edit a saved ready-made definition) ─────────

/** One-line summary of a premade payload for the compose read-out: "3 posts · reposts ×2 · first caption…". */
function summarize(payload: Record<string, unknown>): string | null {
  const posts = Array.isArray(payload.posts) ? payload.posts : null;
  const messages = Array.isArray(payload.messages) ? payload.messages : null;
  const arr = posts ?? messages;
  if (!arr || arr.length === 0) return null;
  const noun = posts ? "post" : "message";
  const bits = [`${arr.length} ${noun}${arr.length === 1 ? "" : "s"}`];
  const rc = payload.resend_count;
  if (typeof rc === "number" && rc > 0) bits.push(`reposts ×${rc}`);
  const first = arr[0] as { text?: unknown; texts?: unknown } | undefined;
  const text = typeof first?.text === "string" ? first.text
    : Array.isArray(first?.texts) && typeof first.texts[0] === "string" ? first.texts[0] : "";
  if (text.trim()) bits.push(text.trim());
  return bits.join(" · ");
}

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
  const summary = summarize(composed);

  const fail = (error: string) => dispatch({ type: "fail", error });

  async function save() {
    if (!canSubmit(raw)) return; // the raw buffer's parse error is already shown
    if (everySeconds < 30) return fail("Interval must be at least 30 seconds.");
    const arr = kind === "auto_posts" ? composed.posts : composed.messages;
    if (!Array.isArray(arr) || arr.length === 0) {
      return fail(`Compose at least one ${KIND_COPY[kind].item} first.`);
    }
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

  const ids = { name: `rm-${kind}-name`, every: `rm-${kind}-every` };
  const items = KIND_COPY[kind].items;
  return (
    <IfModal
      width={722}
      title={editing ? `Edit · ${editing.name}` : `New ${KIND_COPY[kind].noun}`}
      onClose={onClose}
      className={EDITOR_MODAL}
      footer={(
        <>
          <IfButton onClick={onClose} disabled={busy}>Cancel</IfButton>
          <IfButton variant="primary" onClick={save} disabled={busy}>
            {busy ? "Saving…" : isEdit ? "Save changes" : "Create"}
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
              placeholder={kind === "auto_posts" ? "Auto posts" : "Auto mass"}
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
            <IfHelp>Plans each run; nothing is {kind === "auto_posts" ? "posted" : "sent"}.</IfHelp>
          </div>
        </div>

        {/* The payload: built with the rich PremadeForm (Composer), or hand-edited as JSON (paste a big
         *  media_files pool, tweak a field the form doesn't expose). The Dry run switch owns `dry_run`. */}
        <div>
          <div className="mb-2 flex flex-wrap items-center justify-between gap-2">
            <IfLabel className="mb-0">{items}</IfLabel>
            <IfSegmented
              aria-label={`${items} editor`}
              value={raw.raw ? "raw" : "composer"}
              onChange={(v) => dispatch({ type: v === "raw" ? "open" : "close" })}
              options={[{ value: "composer", label: "Composer" }, { value: "raw", label: "Raw JSON" }]}
            />
          </div>

          {raw.raw ? (
            <textarea
              aria-label={`${items} JSON`}
              value={raw.text}
              onChange={(e) => dispatch({ type: "edit", text: e.target.value })}
              rows={12}
              spellCheck={false}
              className={cn(IF_FIELD, "block w-full resize-y px-[11px] py-1 font-mono text-[13px] outline-none placeholder:text-muted focus:border-accent")}
              placeholder={`{ "${kind === "auto_posts" ? "posts" : "messages"}": [ … ] }`}
            />
          ) : (
            <div className="flex items-center gap-4">
              {summary
                ? <span className="min-w-0 flex-1 truncate text-fg-dim">{summary}</span>
                : <IfHelp className="mt-0 flex-1">No content yet</IfHelp>}
              <IfButton icon={PenLine} onClick={() => setComposerOpen(true)}>
                {summary ? "Edit content" : "Compose"}
              </IfButton>
            </div>
          )}
        </div>

        {raw.error && <div className="text-[12px] text-err whitespace-pre-wrap">{raw.error}</div>}
      </div>

      {composerOpen && (
        <ComposeModal
          kind={kind}
          accountId={accountId}
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
