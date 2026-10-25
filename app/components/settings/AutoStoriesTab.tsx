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
 * select (`?creator=`), Learn (the blurb) and "Edit raw JSON"; the form is the
 * S4S-settings blocks (Source, When to post, Stories, Vault clean-up, Status).
 */

import { useEffect, useMemo, useState } from "react";
import { Images, Trash2 } from "lucide-react";

import { IfButton, IfInput, IfLearn, IfSelect } from "@/components/ui/infloww";
import { EditRuleJsonButton } from "@/components/automations/EditRuleJsonModal";
import {
  ConfirmDelete, FieldLabel, FormBlock, NoCreator, SwitchRow, useAutomationCreator,
} from "@/components/automations/automationPage";
import { PageFrame } from "@/components/shell/PageFrame";
import { VaultPicker } from "@/components/chat/VaultPicker";
import { useVaultLists } from "@/hooks/useVaultMedia";
import {
  useAutomationRules,
  useCreateRule,
  useUpdateRule,
  useDeleteRule,
  useRunRuleNow,
  type AutomationRule,
} from "@/hooks/useAutomations";
import { boolKnob } from "@/lib/boolKnob";
import { cn } from "@/lib/utils";

type Mode = "clock" | "interval";

const TITLE = "Auto Story";

interface FormState {
  folderId: number | null;
  mediaIds: number[];       // explicit image pool — combines with the folder
  mode: Mode;
  times: string[];          // ["09:00", …] for clock mode
  everyHours: number;       // interval mode
  perRun: number;
  hoursToLive: number;      // 0 = keep
  removeVaultDupe: boolean; // hide the re-uploaded vault copy (default ON)
  maxRuns: number | null;   // null = run forever
  enabled: boolean;
}

const DEFAULT_FORM: FormState = {
  folderId: null,
  mediaIds: [],
  mode: "clock",
  times: ["09:00"],
  everyHours: 6,
  perRun: 1,
  hoursToLive: 6,
  removeVaultDupe: true,
  maxRuns: null,
  enabled: true,
};

/** Minutes to add to UTC to get the user's local time (e.g. +120 for UTC+2). */
function tzOffsetMinutes(): number {
  return -new Date().getTimezoneOffset();
}

function ruleToForm(rule: AutomationRule): FormState {
  const t = rule.trigger ?? {};
  const p = rule.payload ?? {};
  const clock = Array.isArray(t.daily_at) && t.daily_at.length > 0;
  return {
    folderId: typeof p.folder_id === "number" ? p.folder_id : null,
    mediaIds: Array.isArray(p.media_files)
      ? (p.media_files as unknown[]).filter((x): x is number => typeof x === "number")
      : [],
    mode: clock ? "clock" : "interval",
    times: clock ? (t.daily_at as string[]) : ["09:00"],
    everyHours: t.every_seconds ? Math.max(1, Math.round(t.every_seconds / 3600)) : 6,
    perRun: typeof p.per_run === "number" ? p.per_run : 1,
    hoursToLive: typeof p.hours_to_live === "number" ? p.hours_to_live : 0,
    // Default ON: only an explicit `false` opts a rule out. Through `boolKnob`,
    // because `auto_stories` reads the same key through `_common.bool_knob` —
    // and this pair used to be the one that disagreed (see the ⚠️ beside
    // `remove_dupe` in auto_stories.py).
    removeVaultDupe: boolKnob(p.remove_vault_dupe, true),
    maxRuns: typeof t.max_runs === "number" ? t.max_runs : null,
    enabled: rule.is_enabled,
  };
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

  const [form, setForm] = useState<FormState>(DEFAULT_FORM);
  const set = <K extends keyof FormState>(k: K, v: FormState[K]) =>
    setForm((f) => ({ ...f, [k]: v }));

  // Load the existing rule into the form whenever it (re)loads.
  useEffect(() => {
    if (rule) setForm(ruleToForm(rule));
    else setForm(DEFAULT_FORM);
  }, [rule?.id]); // eslint-disable-line react-hooks/exhaustive-deps

  const createM = useCreateRule(accountId);
  const updateM = useUpdateRule(accountId);
  const deleteM = useDeleteRule(accountId);
  const runM = useRunRuleNow(accountId);
  const busy = createM.isPending || updateM.isPending || deleteM.isPending;

  const [err, setErr] = useState<string | null>(null);
  const [runMsg, setRunMsg] = useState<string | null>(null);
  const [pickerOpen, setPickerOpen] = useState(false);
  const [deleting, setDeleting] = useState(false);

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
        `✓ Posting ${n} ${n === 1 ? "story" : "stories"} from “${
          folders.find((f) => f.id === saved.folderId)?.name ?? "folder"
        }” now — it’ll appear on the account within ~30s.`,
      );
    } catch (e) {
      setRunMsg(`Run failed: ${(e as Error)?.message || "unknown error"}`);
    }
  }

  function buildTrigger() {
    const max_runs = form.maxRuns && form.maxRuns > 0 ? form.maxRuns : undefined;
    if (form.mode === "clock") {
      return { daily_at: form.times, tz_offset_minutes: tzOffsetMinutes(), max_runs };
    }
    return { every_seconds: Math.max(1, Math.round(form.everyHours)) * 3600, max_runs };
  }

  function buildPayload() {
    const p: Record<string, unknown> = {
      folder_id: form.folderId,
      per_run: Math.max(1, Math.round(form.perRun)),
      hours_to_live: Math.max(0, Math.round(form.hoursToLive)),
      remove_vault_dupe: form.removeVaultDupe,
    };
    // Explicit image pool combines with the folder (backend unions them).
    if (form.mediaIds.length) p.media_files = form.mediaIds;
    return p;
  }

  async function save() {
    setErr(null);
    if (!accountId) return;
    if (!form.folderId && form.mediaIds.length === 0) {
      setErr("Pick a vault folder or an image pool first."); return;
    }
    if (form.mode === "clock" && form.times.length === 0) {
      setErr("Add at least one time."); return;
    }
    try {
      if (rule) {
        await updateM.mutateAsync({
          id: rule.id, trigger: buildTrigger(),
          payload: buildPayload(), is_enabled: form.enabled,
        });
      } else {
        await createM.mutateAsync({
          account_id: accountId, kind: "auto_stories",
          name: "Auto stories", trigger: buildTrigger(),
          payload: buildPayload(), is_enabled: form.enabled,
        });
      }
    } catch (e) {
      setErr((e as Error)?.message || "Save failed");
    }
  }

  const actions = (
    <>
      {LEARN}
      <EditRuleJsonButton accountId={accountId} kind="auto_stories" label="Edit raw JSON"
        className="text-[14px] text-accent hover:text-accent-hover disabled:cursor-not-allowed disabled:opacity-50 max-sm:hidden" />
    </>
  );

  if (!accountId) {
    return <PageFrame title={TITLE} creators={creators} actions={LEARN}>{!loading && <NoCreator />}</PageFrame>;
  }

  const last = rule?.last_run;

  return (
    <PageFrame title={TITLE} creators={creators} actions={actions}>
      <div className="max-w-[720px] space-y-8">
        <FormBlock title="Source">
          <div>
            <FieldLabel htmlFor="story-folder">Vault folder</FieldLabel>
            {foldersQ.isLoading ? (
              <p className="text-[14px] text-muted">Loading folders…</p>
            ) : folders.length === 0 ? (
              <p className="text-[14px] text-muted">No vault folders with photos found for this account.</p>
            ) : (
              <IfSelect
                id="story-folder"
                value={form.folderId == null ? null : String(form.folderId)}
                placeholder="Pick a folder"
                options={folders.map((f) => ({ value: String(f.id), label: `${f.name} (${f.photosCount} photos)` }))}
                onChange={(v) => set("folderId", Number(v))}
                className="w-full sm:w-[320px]"
              />
            )}
          </div>

          {/* Explicit image pool — combines with the folder above into one pool. */}
          <div>
            <FieldLabel>…or pick specific images</FieldLabel>
            <div className="flex flex-wrap items-center gap-4">
              <IfButton icon={Images} onClick={() => setPickerOpen(true)}>
                {form.mediaIds.length
                  ? `${form.mediaIds.length} image${form.mediaIds.length === 1 ? "" : "s"} in pool`
                  : "Pick images"}
              </IfButton>
              {form.mediaIds.length > 0 && (
                <button type="button" onClick={() => set("mediaIds", [])} className="text-[14px] text-accent hover:text-accent-hover">
                  Clear
                </button>
              )}
            </div>
            <p className="mt-2 text-[12px] text-muted">
              Folder + picked images form one pool; “Stories per run” photos are
              sampled from it each time.
            </p>
          </div>
        </FormBlock>

        {/* Schedule — pick ONE of the two modes */}
        <FormBlock title={<>When to post <span className="text-[14px] font-normal text-muted">(choose one)</span></>}>
          <div role="radiogroup" aria-label="When to post" className="space-y-4">
            <ScheduleOption
              selected={form.mode === "clock"}
              onSelect={() => set("mode", "clock")}
              title="At set times each day"
              desc="Posts once at each time below, every day."
            >
              <TimesEditor times={form.times} onChange={(times) => set("times", times)} />
            </ScheduleOption>
            <ScheduleOption
              selected={form.mode === "interval"}
              onSelect={() => set("mode", "interval")}
              title="Every few hours"
              desc="Posts on a repeating interval, starting when you save (not immediately — use Run now for that)."
            >
              <label className="flex items-center gap-2 text-[14px] text-fg">
                <span>Every</span>
                <IfInput
                  type="number" min={1} className="w-20" aria-label="Every N hours"
                  value={form.everyHours}
                  onChange={(e) => set("everyHours", Number(e.target.value))}
                />
                <span>hours</span>
              </label>
            </ScheduleOption>
          </div>
        </FormBlock>

        <FormBlock title="Stories">
          <div className="grid gap-4 sm:grid-cols-3">
            <div>
              <FieldLabel htmlFor="story-per-run">Stories per run</FieldLabel>
              <IfInput id="story-per-run" type="number" min={1} className="w-full"
                value={form.perRun} onChange={(e) => set("perRun", Number(e.target.value))} />
            </div>
            <div>
              <FieldLabel htmlFor="story-ttl">Delete after (hours, 0 = keep)</FieldLabel>
              <IfInput id="story-ttl" type="number" min={0} className="w-full"
                value={form.hoursToLive} onChange={(e) => set("hoursToLive", Number(e.target.value))} />
            </div>
            <div>
              <FieldLabel htmlFor="story-max-runs">Total runs (blank = forever)</FieldLabel>
              <IfInput id="story-max-runs" type="number" min={1} className="w-full" placeholder="∞"
                value={form.maxRuns ?? ""}
                onChange={(e) => set("maxRuns", e.target.value ? Number(e.target.value) : null)} />
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
            onChange={(on) => set("removeVaultDupe", on)}
          />
        </FormBlock>

        <FormBlock title="Status">
          <SwitchRow label="Enabled" checked={form.enabled} onChange={(on) => set("enabled", on)} />
        </FormBlock>

        {err && <p className="text-[14px] text-err">{err}</p>}

        <div className="flex flex-wrap items-center gap-2">
          <IfButton variant="primary" onClick={save} disabled={busy} className="min-w-[76px]">
            {rule ? "Save" : "Create automation"}
          </IfButton>
          {rule && (
            <>
              <IfButton onClick={runNow} disabled={runM.isPending} title="Post one batch now (bypasses the schedule)">
                {runM.isPending ? "Posting…" : "Run now"}
              </IfButton>
              <IfButton onClick={() => setDeleting(true)} disabled={deleteM.isPending}
                className="text-err hover:border-err hover:text-err sm:ml-auto">
                Delete
              </IfButton>
            </>
          )}
        </div>

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

      <VaultPicker
        open={pickerOpen}
        onClose={() => setPickerOpen(false)}
        accountId={accountId}
        fanId={null}
        initialSelectedIds={form.mediaIds}
        onConfirm={(picked) => {
          set("mediaIds", picked.map((m) => m.id));
          setPickerOpen(false);
        }}
      />
    </PageFrame>
  );
}

// ── small bits ────────────────────────────────────────────────────────

/** One selectable schedule mode, a radio card: 1px L1 radius 8; selected, 1px M1 on a 40% #384360 fill, its own
 *  controls (time pickers / interval input) below. Clicking anywhere on the card selects it. */
function ScheduleOption({
  selected, onSelect, title, desc, children,
}: {
  selected: boolean;
  onSelect: () => void;
  title: string;
  desc: string;
  children: React.ReactNode;
}) {
  return (
    <div
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
        selected ? "border-accent bg-[#384360]/40" : "border-border hover:border-accent",
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
  times, onChange,
}: { times: string[]; onChange: (t: string[]) => void }) {
  return (
    <div className="flex flex-wrap items-center gap-2">
      {times.map((t, i) => (
        <span key={i} className="inline-flex items-center gap-1">
          <IfInput
            type="time"
            aria-label={`Time ${i + 1}`}
            value={t}
            className="w-28"
            onChange={(e) => {
              const next = [...times];
              next[i] = e.target.value;
              onChange(next);
            }}
          />
          <button
            type="button"
            className="inline-grid size-8 shrink-0 place-items-center text-muted hover:text-err"
            onClick={() => onChange(times.filter((_, j) => j !== i))}
            title="Remove time"
            aria-label="Remove time"
          >
            <Trash2 className="size-3.5" />
          </button>
        </span>
      ))}
      <IfButton onClick={() => onChange([...times, "12:00"])}>+ Add time</IfButton>
    </div>
  );
}
