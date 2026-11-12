"use client";

/**
 * AutoStoriesTab — My Automations > Auto Story (/growth/auto-story).
 *
 * One `auto_stories` automation_rule per account. The owner picks a vault
 * folder, a schedule ("cron time"), how many stories to post per trigger, how
 * long each lives before auto-delete, and an optional total run-limit. On its
 * cadence the executor posts `per_run` random photos from the folder as stories
 * (vault/CDN → convert → POST /stories) and enqueues each delete at now+hours.
 *
 * Schedule modes (all three the spec asked for):
 *   • "At set times"  → daily_at: ["09:00","20:00", …]  (one fire per slot/day)
 *   • "Every N hours" → every_seconds interval
 * Run-limit ("how many times to run") → trigger.max_runs; blank = run forever.
 * Per-trigger count ("how many to post") → payload.per_run; default 1.
 *
 * On Infloww's look (page-parity ticket 16): the page header holds the creator
 * select (`?creator=`), Learn (the blurb), the On / Off pill + switch, a "More
 * actions" menu (Run now, Edit raw JSON for fast imports, Delete) and the primary
 * Save; the form is the S4S-settings blocks (Source, When to post, Stories, Vault
 * clean-up). The switch saves the moment it flips once the rule exists (a PATCH of
 * `is_enabled` alone); before that it picks whether Save creates the rule on.
 *
 * The form is a pure reducer (autoStoriesForm.ts); the page only dispatches. It registers on the help bot's agent
 * bridge as the `auto_stories` editor (docs/spec/assistant-do-mode.md D13): "Do it for me" fills this form and saves a
 * NEW rule through `agentSave`, always switched off; with a rule already here it refuses (one per account).
 */

import { useEffect, useMemo, useReducer, useState } from "react";
import { Images, MoreHorizontal, Plus, Trash2 } from "lucide-react";

import { IfButton, IfHelp, IfInput, IfLabel, IfLearn, IfSelect } from "@/components/ui/infloww";
import { useAgentEditor, type SaveResult } from "@/components/assistant/agentBridge";
import { EditRuleJsonModal } from "@/components/automations/EditRuleJsonModal";
import { HeaderSwitch } from "@/components/automations/HeaderSwitch";
import {
  ConfirmDelete, FormBlock, NoCreator, SwitchRow, useAutomationCreator,
} from "@/components/automations/automationPage";
import { Menu } from "@/components/ui/Menu";
import { PageFrame } from "@/components/shell/PageFrame";
import { VaultPicker } from "@/components/chat/VaultPicker";
import { useVaultLists } from "@/hooks/useVaultMedia";
import {
  useAutomationRules,
  useCreateRule,
  useUpdateRule,
  useDeleteRule,
  useRunRuleNow,
} from "@/hooks/useAutomations";
import { cn } from "@/lib/utils";
import { Skeleton } from "@/components/ui/Skeleton";
import {
  autoStoriesReducer, buildPayload, buildTrigger, DEFAULT_FORM, ruleToForm, sameForm, saveGap, type AutoStoriesAction, type FormState,
} from "./autoStoriesForm";

const TITLE = "Auto Story";

/** Minutes to add to UTC to get the user's local time (e.g. +120 for UTC+2). */
function tzOffsetMinutes(): number {
  return -new Date().getTimezoneOffset();
}

const LEARN = (
  <IfLearn tip="Post random photos from a vault folder as stories on a schedule, each auto-deleting after a set number of hours.">
    <span className="max-sm:sr-only">Learn</span>
  </IfLearn>
);

export default function AutoStoriesTab() {
  const { accountId, creators, loading } = useAutomationCreator();

  const rulesQ = useAutomationRules(accountId);
  const rule = useMemo(
    () => (rulesQ.data ?? []).find((r) => r.kind === "auto_stories") ?? null,
    [rulesQ.data],
  );

  const foldersQ = useVaultLists(accountId);
  // Only folders that actually hold photos are postable as stories.
  const folders = useMemo(
    () => (foldersQ.data?.list ?? []).filter((f) => (f.photosCount ?? 0) > 0),
    [foldersQ.data],
  );

  const [form, dispatch] = useReducer(autoStoriesReducer, DEFAULT_FORM);
  const set = (patch: Partial<FormState>) => dispatch({ type: "set", patch });
  // What the form was loaded with: unsaved edits = not the same.
  const baseline = useMemo(() => (rule ? ruleToForm(rule) : DEFAULT_FORM), [rule]);

  // Load the existing rule into the form whenever it (re)loads.
  useEffect(() => {
    dispatch({ type: "load", form: rule ? ruleToForm(rule) : DEFAULT_FORM });
  }, [rule?.id]); // eslint-disable-line react-hooks/exhaustive-deps

  const createM = useCreateRule(accountId);
  const updateM = useUpdateRule(accountId);
  const deleteM = useDeleteRule(accountId);
  // The header switch's own PATCH, so its pending never reads as the Save's.
  const switchM = useUpdateRule(accountId);
  const runM = useRunRuleNow(accountId);
  const busy = createM.isPending || updateM.isPending || deleteM.isPending;

  const [err, setErr] = useState<string | null>(null);
  const [runMsg, setRunMsg] = useState<string | null>(null);
  const [pickerOpen, setPickerOpen] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const [editingJson, setEditingJson] = useState(false);

  // With a rule: saves at once (is_enabled alone), flipping back if the PATCH fails. Without one: Save creates it so.
  function flip(on: boolean) {
    set({ enabled: on });
    if (rule) switchM.mutate({ id: rule.id, is_enabled: on }, { onError: () => set({ enabled: !on }) });
  }

  async function runNow() {
    if (!rule) return;
    setRunMsg(null);
    // Run now fires the SAVED rule, so report its count/folder — not the
    // (possibly dirty, unsaved) form.
    const saved = ruleToForm(rule);
    const n = Math.max(1, Math.round(saved.perRun));
    try {
      await runM.mutateAsync(rule.id);
      setRunMsg(
        `Posting ${n} ${n === 1 ? "story" : "stories"} from “${
          folders.find((f) => f.id === saved.folderId)?.name ?? "folder"
        }” now — it’ll appear on the account within ~30s.`,
      );
    } catch (e) {
      setRunMsg(`Run failed: ${(e as Error)?.message || "unknown error"}`);
    }
  }

  async function save() {
    setErr(null);
    if (!accountId) return;
    const gap = saveGap(form);
    if (gap) { setErr(gap); return; }
    try {
      if (rule) {
        await updateM.mutateAsync({
          id: rule.id, trigger: buildTrigger(form, tzOffsetMinutes()),
          payload: buildPayload(form), is_enabled: form.enabled,
        });
      } else {
        await createM.mutateAsync({
          account_id: accountId, kind: "auto_stories",
          name: "Auto stories", trigger: buildTrigger(form, tzOffsetMinutes()),
          payload: buildPayload(form), is_enabled: form.enabled,
        });
      }
    } catch (e) {
      setErr((e as Error)?.message || "Save failed");
    }
  }

  // The help bot's save (D13): a NEW rule only, Save's own gate, switched OFF whatever the form says.
  async function agentSave(): Promise<SaveResult> {
    if (!accountId) return { ok: false, reason: "No creator picked — nothing was saved." };
    if (rule) return { ok: false, reason: "Auto Story is already set up for this creator — nothing was saved." };
    if (busy) return { ok: false, reason: "Already saving" };
    setErr(null);
    const gap = saveGap(form);
    if (gap) { setErr(gap); return { ok: false, reason: gap }; }
    try {
      await createM.mutateAsync({
        account_id: accountId, kind: "auto_stories",
        name: "Auto stories", trigger: buildTrigger(form, tzOffsetMinutes()),
        payload: buildPayload(form), is_enabled: false,
      });
      return { ok: true };
    } catch (e) {
      const reason = (e as Error)?.message || "Save failed";
      setErr(reason);
      return { ok: false, reason };
    }
  }
  useAgentEditor<AutoStoriesAction>("auto_stories", {
    accountId: accountId ?? "", isNew: !rule, dispatch, agentSave,
    ready: !!accountId && rulesQ.isSuccess && !rulesQ.isPlaceholderData, dirty: !sameForm(form, baseline),
  });

  // 12px apart on phones (the header's 16px left "Auto Story" too little room).
  const actions = (
    <span className="flex items-center gap-3 sm:gap-4">
      {LEARN}
      <HeaderSwitch id="story-enabled" label={TITLE} checked={form.enabled} loading={switchM.isPending}
        disabled={busy || rulesQ.isLoading} status={rule ? undefined : "Not saved"} onChange={flip} />
      {/* The rule's less-used actions, right-aligned under the ⋯ so the menu never runs off a phone's edge. */}
      <Menu align="right" menuLabel="More actions" panelClassName="z-50 w-44" itemClassName="text-[14px] text-fg disabled:opacity-60"
        trigger={(p) => <IfButton icon={MoreHorizontal} aria-label="More actions" title="More actions" {...p}
          className="w-8 px-0 [&>svg]:h-4 [&>svg]:w-4" />}
        items={[
          { label: runM.isPending ? "Posting…" : "Run now", onClick: runNow, disabled: !rule || runM.isPending,
            title: rule ? "Post one batch now (bypasses the schedule)" : "Save this automation first" },
          { label: "Edit raw JSON", onClick: () => setEditingJson(true), disabled: !rule,
            title: rule ? "Edit the raw JSON payload for this rule" : "Save this automation once, then edit its raw JSON" },
          { label: "Delete", onClick: () => setDeleting(true), disabled: !rule || deleteM.isPending, danger: true },
        ]} />
      <IfButton id="story-save" variant="primary" onClick={save} disabled={busy || switchM.isPending} className="min-w-[64px]">
        {createM.isPending || updateM.isPending ? "Saving…" : "Save"}
      </IfButton>
    </span>
  );

  if (!accountId) {
    return <PageFrame title={TITLE} creators={creators} actions={LEARN}><NoCreator loading={loading} /></PageFrame>;
  }

  const last = rule?.last_run;

  return (
    <PageFrame title={TITLE} creators={creators} actions={actions}>
      <div className="max-w-[720px] space-y-8">
        {(err || runMsg || switchM.isError || (rule && last)) && (
          <div className="space-y-1">
            {err && <p className="text-[14px] text-err">{err}</p>}
            {switchM.isError && <p className="text-[14px] text-err">Couldn&apos;t switch Auto Story: {switchM.error.message}</p>}
            {runMsg && <p className="text-[14px] text-accent">{runMsg}</p>}
            {rule && last && (
              <p className="text-[12px] text-muted">
                Last run: <span className="text-fg">{last.status}</span>
                {typeof last.stats?.posted === "number" && (
                  <span className="text-fg"> · posted {last.stats.posted as number}</span>
                )}
                {typeof last.stats?.failed === "number" && (last.stats.failed as number) > 0 && (
                  <span className="text-err"> · {last.stats.failed as number} failed</span>
                )}
                {last.started_at && ` · ${new Date(last.started_at).toLocaleString()}`}
                {rule.has_pending_job && " · job queued"}
                {last.error_text && <span className="text-err"> · {last.error_text}</span>}
              </p>
            )}
          </div>
        )}

        <FormBlock title="Source">
          <div>
            <IfLabel htmlFor="story-folder">Vault folder</IfLabel>
            {foldersQ.isLoading ? (
              <Skeleton className="h-9 w-full" />
            ) : folders.length === 0 ? (
              <p className="text-[14px] text-muted">No vault folders with photos found for this account.</p>
            ) : (
              <IfSelect
                id="story-folder"
                value={form.folderId == null ? null : String(form.folderId)}
                placeholder="Pick a folder"
                options={folders.map((f) => ({ value: String(f.id), label: `${f.name} (${f.photosCount} photos)` }))}
                onChange={(v) => set({ folderId: Number(v) })}
                className="w-full sm:w-[320px]"
              />
            )}
          </div>

          {/* Explicit image pool — combines with the folder above into one pool. */}
          <div>
            <IfLabel>Or pick specific images</IfLabel>
            <div className="flex flex-wrap items-center gap-4">
              <IfButton icon={Images} onClick={() => setPickerOpen(true)}>
                {form.mediaIds.length
                  ? `${form.mediaIds.length} image${form.mediaIds.length === 1 ? "" : "s"} in pool`
                  : "Pick images"}
              </IfButton>
              {form.mediaIds.length > 0 && (
                <button type="button" onClick={() => set({ mediaIds: [] })} className="text-[14px] text-accent hover:text-accent-hover">
                  Clear
                </button>
              )}
            </div>
            <IfHelp className="mt-2">Folder + picked images form one pool; “Stories per run” photos are sampled from it.</IfHelp>
          </div>
        </FormBlock>

        {/* Schedule — pick ONE of the two modes */}
        <FormBlock title={<>When to post <span className="text-[14px] font-normal text-muted">(choose one)</span></>}>
          <div role="radiogroup" aria-label="When to post" className="space-y-4">
            <ScheduleOption
              id="story-mode-clock"
              selected={form.mode === "clock"}
              onSelect={() => set({ mode: "clock" })}
              title="At set times each day"
              desc="Posts once at each time below, every day."
            >
              <TimesEditor times={form.times} dispatch={dispatch} />
            </ScheduleOption>
            <ScheduleOption
              id="story-mode-interval"
              selected={form.mode === "interval"}
              onSelect={() => set({ mode: "interval" })}
              title="Every few hours"
              desc="Posts on a repeating interval, starting when you save (not immediately — use Run now for that)."
            >
              <label className="flex items-center gap-2 text-[14px] text-fg">
                <span>Every</span>
                <IfInput
                  id="story-every" type="number" min={1} className="w-20" aria-label="Every N hours"
                  value={form.everyHours}
                  onChange={(e) => set({ everyHours: Number(e.target.value) })}
                />
                <span>hours</span>
              </label>
            </ScheduleOption>
          </div>
        </FormBlock>

        <FormBlock title="Stories">
          <div className="grid gap-4 sm:grid-cols-3">
            <div>
              <IfLabel htmlFor="story-per-run">Stories per run</IfLabel>
              <IfInput id="story-per-run" type="number" min={1} className="w-full"
                value={form.perRun} onChange={(e) => set({ perRun: Number(e.target.value) })} />
            </div>
            <div>
              <IfLabel htmlFor="story-ttl">Delete after</IfLabel>
              <IfInput id="story-ttl" type="number" min={0} className="w-full"
                value={form.hoursToLive} onChange={(e) => set({ hoursToLive: Number(e.target.value) })} />
              <IfHelp>hours · 0 = keep</IfHelp>
            </div>
            <div>
              <IfLabel htmlFor="story-max-runs">Total runs</IfLabel>
              <IfInput id="story-max-runs" type="number" min={1} className="w-full" placeholder="∞"
                value={form.maxRuns ?? ""}
                onChange={(e) => set({ maxRuns: e.target.value ? Number(e.target.value) : null })} />
              <IfHelp>blank = forever</IfHelp>
            </div>
          </div>
        </FormBlock>

        {/* Vault-dupe cleanup — posting a story re-uploads the photo, which
            leaves an extra copy in the vault. This hides that copy for you. */}
        <FormBlock title="Vault clean-up">
          <SwitchRow
            label="Remove the re-uploaded copy from the vault"
            hint="Every story re-uploads its photo (OnlyFans requires it), leaving a duplicate in your vault. This hides that duplicate automatically once it finishes processing — your live story is unaffected."
            checked={form.removeVaultDupe}
            onChange={(on) => set({ removeVaultDupe: on })}
          />
        </FormBlock>

      </div>

      {deleting && rule && (
        <ConfirmDelete
          title="Delete this automation?"
          pending={deleteM.isPending}
          onConfirm={() => { setDeleting(false); deleteM.mutate(rule.id); }}
          onClose={() => setDeleting(false)}
        >
          Auto Story stops posting for this Creator.
        </ConfirmDelete>
      )}

      {editingJson && rule && (
        <EditRuleJsonModal rule={rule} accountId={accountId} onClose={() => setEditingJson(false)}
          extraCount={(rulesQ.data ?? []).filter((r) => r.kind === "auto_stories").length - 1} />
      )}

      <VaultPicker
        open={pickerOpen}
        onClose={() => setPickerOpen(false)}
        accountId={accountId}
        fanId={null}
        initialSelectedIds={form.mediaIds}
        onConfirm={(picked) => {
          set({ mediaIds: picked.map((m) => m.id) });
          setPickerOpen(false);
        }}
      />
    </PageFrame>
  );
}

// ── small bits ────────────────────────────────────────────────────────

/** One selectable schedule mode, a radio card: 1px L1 radius 8; selected, 1px M1 on the selected-row tint (40%), its own
 *  controls (time pickers / interval input) below. Clicking anywhere on the card selects it. */
function ScheduleOption({
  id, selected, onSelect, title, desc, children,
}: {
  id: string;
  selected: boolean;
  onSelect: () => void;
  title: string;
  desc: string;
  children: React.ReactNode;
}) {
  return (
    <div
      id={id}
      role="radio"
      aria-checked={selected}
      aria-label={title}
      tabIndex={0}
      onClick={onSelect}
      onKeyDown={(e) => {
        if (e.target === e.currentTarget && (e.key === " " || e.key === "Enter")) { e.preventDefault(); onSelect(); }
      }}
      className={cn(
        "cursor-pointer rounded-lg border p-4 outline-none transition-colors focus-visible:ring-2 focus-visible:ring-accent/40",
        selected ? "border-accent bg-selected/40" : "border-border hover:border-accent",
      )}
    >
      <div className="flex items-start gap-2.5">
        <span
          aria-hidden
          className={cn(
            "mt-0.5 grid size-4 shrink-0 place-items-center rounded-full border",
            selected ? "border-accent" : "border-border",
          )}
        >
          {selected && <span className="size-2 rounded-full bg-accent" />}
        </span>
        <div className="min-w-0 flex-1">
          <div className="text-[14px] text-fg">{title}</div>
          <p className="mt-0.5 text-[12px] text-muted">{desc}</p>
          {selected && (
            // Stop clicks on the controls from bubbling up (they'd re-select,
            // harmless, but keep focus/typing clean).
            <div className="mt-3" onClick={(e) => e.stopPropagation()}>
              {children}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

function TimesEditor({
  times, dispatch,
}: { times: string[]; dispatch: (a: AutoStoriesAction) => void }) {
  return (
    <div className="flex flex-wrap items-center gap-2">
      {times.map((t, i) => (
        <span key={i} className="inline-flex items-center gap-1">
          <IfInput
            id={`story-time-${i}`}
            type="time"
            aria-label={`Time ${i + 1}`}
            value={t}
            className="w-28"
            onChange={(e) => dispatch({ type: "setTime", index: i, value: e.target.value })}
          />
          <button
            type="button"
            className="inline-grid size-8 shrink-0 place-items-center text-muted hover:text-err"
            onClick={() => dispatch({ type: "removeTime", index: i })}
            title="Remove time"
            aria-label="Remove time"
          >
            <Trash2 className="size-3.5" />
          </button>
        </span>
      ))}
      <IfButton icon={Plus} onClick={() => dispatch({ type: "addTime" })}>Add time</IfButton>
    </div>
  );
}
