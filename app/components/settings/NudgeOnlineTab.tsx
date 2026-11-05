"use client";

/**
 * NudgeOnlineTab — Settings → "Nudge online" (also opened from +New).
 *
 * Configures the nudge_online automation ("message a fan when they come
 * online"). Two stores, one screen:
 *   • the 60s detector cadence is an `automation_rules` row (kind nudge_online).
 *   • the rich behaviour (timing, caps, quiet hours, tease pools)
 *     is account_ai_config.nudge_config_json — both the detector and the delayed
 *     fire-job read it, so it's persisted server-side via useNudgeConfig.
 *
 * UX: every field has inline help; the tease pools have a friendly per-line
 * editor AND a raw-JSON advanced view (copy in/out); a live Preview composes a
 * sample message for a chosen fan + time; and a "Roll out to models" checklist
 * applies one shared text-only config across many models at once.
 */

import { useEffect, useId, useMemo, useReducer, useState, type ReactNode } from "react";
import { Play, ChevronDown, X, Image as ImageIcon } from "lucide-react";

import {
  IfButton, IfHelp, IfInput, IfLabel, IfLearn, IfNativeSelect, IfSegmented, IfSwitch, IfTextArea,
} from "@/components/ui/infloww";
import { EditorFooter } from "@/components/ui/ifModal";
import { EditRawJsonButton } from "@/components/settings/JsonConfigModal";
import { VaultPicker } from "@/components/chat/VaultPicker";
import { ImportCaptionsButton } from "@/components/compose/ImportCaptionsButton";
import { mergeCaptions } from "@/lib/parseCaptions";
import { type VaultMedia } from "@/lib/relay";
import { proxyImage } from "@/lib/mediaUrl";
import { clearDraft, readDraft, usePendingDraft } from "@/lib/pendingDraft";
import { useActiveAccounts } from "@/hooks/useAccounts";
import {
  useAutomationRules,
  useRunRuleNow,
} from "@/hooks/useAutomations";
import {
  useNudgeConfig,
  useSaveNudgeConfig,
  useBulkApplyNudgeConfig,
  useNudgePreview,
  useNudgeSavePending,
  effectiveConfig,
  nudgeDraftKey,
  type NudgeConfig,
  type NudgeSlotEntry,
} from "@/hooks/useNudgeConfig";
import {
  buildConfig,
  canSave,
  gateNote,
  initialNudgeOnlineState,
  keptDraft,
  nudgeOnlineReducer,
  pickedIds,
  previewPayload,
  restoredNote,
  rolloutBlock,
  RESTORED_MOVED_NOTE,
  RESTORED_NOTE,
  type FormKey,
} from "@/components/settings/nudgeOnlineReducer";

// The 6 time-of-day slots (same buckets send_welcome uses), with friendly labels.
const SLOT_DEFS: [string, string][] = [
  ["morning_1", "Morning · early (5–9)"],
  ["morning_2", "Morning · late (9–12)"],
  ["afternoon_1", "Afternoon · early (12–15)"],
  ["afternoon_2", "Afternoon · late (15–18)"],
  ["evening", "Evening (18–21)"],
  ["night", "Night (21–5)"],
];

// Quick time presets for the preview (representative hour per slot).
const TIME_PRESETS: [string, number][] = [
  ["Morning", 8], ["Midday", 13], ["Afternoon", 16], ["Evening", 19], ["Night", 23],
];

export default function NudgeOnlineTab({
  initialAccountId = null,
}: {
  /** The Creator to open on, where a page's own creator control already picked
   *  one (Smart Messages' Nudge row). Without it the tab opens on the first. */
  initialAccountId?: string | null;
} = {}) {
  const accounts = useActiveAccounts();
  const [state, dispatch] = useReducer(
    nudgeOnlineReducer, { ...initialNudgeOnlineState, accountId: initialAccountId },
  );
  // The picker's one copy: every pick is an `account` dispatch, which resets
  // the old account's draft and lines in the same update.
  const { accountId } = state;
  useEffect(() => {
    if (!accountId && accounts.length > 0) dispatch({ type: "account", accountId: accounts[0].id });
  }, [accounts, accountId]);

  const rulesQ = useAutomationRules(accountId);
  const rule = useMemo(
    () => (rulesQ.data ?? []).find((r) => r.kind === "nudge_online") ?? null,
    [rulesQ.data],
  );
  const cfgQ = useNudgeConfig(accountId);

  const runM = useRunRuleNow(accountId);
  const saveCfgM = useSaveNudgeConfig();
  const bulkM = useBulkApplyNudgeConfig();
  const previewM = useNudgePreview();

  /** THE save gate and its note — one value for the in-flow Save and the
   *  pinned bar. Why each half is there: nudgeOnlineReducer `canSave`. */
  const gate = {
    accountId, drafted: state.base !== null, cfgError: cfgQ.isError,
    rulesHasData: rulesQ.data !== undefined, rulesPlaceholder: rulesQ.isPlaceholderData,
    rulesError: rulesQ.isError,
  };
  const saveAllowed = canSave(gate);
  const { form, slots, jsonDraft, jsonErr, save: saved, runMsg, previewErr, bulkMsg } = state;
  /** THE save verdict, read once: the in-flow lines and the pinned bar. */
  const savedOk = saved?.ok === true;
  const saveErr = saved?.ok === false ? saved.err : null;
  /** A save PUT in flight for the SHOWN account: after a switch the PUT is the
   *  other account's (B is not "Saving…"), and back on A it is A's again — a
   *  second whole-blob PUT must not overlap it. */
  const busy = useNudgeSavePending(accountId);
  const saveDisabled = busy || !saveAllowed;
  /** …and THE label, hoisted for the same reason the gate is: it is a statement
   *  about which branch save() will take, and the two controls must not answer
   *  it differently. */
  const saveLabel = rule ? "Save changes" : "Create automation";
  const note = gateNote(gate);

  const [advOpen, setAdvOpen] = useState(false);

  // Roll-out checklist (every model checked by default, founder included).
  const allIds = accounts.map((a) => a.id);
  const picked = pickedIds(state.selected, allIds);

  // Preview controls.
  const [previewFan, setPreviewFan] = useState("");
  const [previewHour, setPreviewHour] = useState<number | "">("");

  // Image picking: which slot's picker is open + a cache of picked media so we
  // can render thumbnails by id (in the slot editor AND the preview).
  const [pickerSlot, setPickerSlot] = useState<string | null>(null);
  const [mediaCache, setMediaCache] = useState<Record<number, VaultMedia>>({});

  // Load the effective config into the draft when it arrives — a refetch
  // while the draft has unsaved edits keeps them, and a config from before
  // this account's last save (or one arriving while it is pending) is ignored
  // (the reducer's `hydrate`). Re-run when `busy` drops: the cache may then
  // hold that pre-save config, which must not seed the form.
  // The account's kept draft (a tab closed mid-edit / mid-save) rides along.
  useEffect(() => {
    if (!cfgQ.data) return;
    dispatch({
      type: "hydrate", eff: effectiveConfig(cfgQ.data), accountId,
      fetchedAt: cfgQ.dataUpdatedAt, pending: busy,
      draft: accountId ? readDraft<NudgeConfig>(nudgeDraftKey(accountId)) : null,
    });
  }, [cfgQ.data, cfgQ.dataUpdatedAt, accountId, busy]);

  // Keep the dirty (or saving) draft in localStorage until a PUT acks it
  // (useSaveNudgeConfig); not before the form is seeded — a kept draft is the
  // hydrate's to read first.
  usePendingDraft(state.base !== null && accountId ? nudgeDraftKey(accountId) : null, keptDraft(state));
  const restored = restoredNote(state);
  const discardDraft = () => {
    dispatch({ type: "discardDraft" });
    if (accountId) clearDraft(nudgeDraftKey(accountId));
  };

  const set = <K extends FormKey>(k: K, v: NudgeConfig[K]) => dispatch({ type: "field", k, v });
  const num = (k: FormKey, fallback = 0): number => {
    const v = form[k];
    return typeof v === "number" ? v : fallback;
  };

  // Friendly slot edits keep the JSON view in sync (single source = `slots`).
  const setDefaultSlot = (key: string, entry: NudgeSlotEntry) => {
    const def = { ...(slots.default ?? {}) };
    def[key] = entry;
    dispatch({ type: "slots", slots: { ...slots, default: def } });
  };

  // Bulk "Roll out to models" applies the in-memory config to OTHER accounts, so
  // require the active account's edits to be saved (and valid) first — otherwise
  // we'd push unsaved/partial changes the operator hasn't committed here.
  const block = rolloutBlock(state, picked);

  async function save() {
    // Belt to the buttons' braces: a save here is a whole-blob REPLACE, so
    // never write from a form that was never seeded. The same guard
    // `useSellerConfig` keeps inside saveCfg for the seller tabs. One PUT per
    // account at a time: `busy`, plus `state.saving` for a second click before
    // the mutation cache reports the first one pending.
    if (!accountId || !saveAllowed || busy || state.saving) return;
    const cfg = buildConfig(state);
    dispatch({ type: "saveStart", cfg, accountId });
    try {
      // The PUT is the only switch: it syncs the 60s detector rule (created /
      // woken / parked from `enabled`) in the same write as the config.
      await saveCfgM.mutateAsync({ account_id: accountId, config: cfg });
      dispatch({ type: "saveOk", accountId, at: Date.now() });
    } catch (e) {
      dispatch({ type: "saveErr", msg: (e as Error)?.message || "Save failed", accountId, at: Date.now() });
    }
  }

  async function runPreview() {
    if (!accountId) return;
    const p = previewPayload(previewFan, previewHour);
    if ("error" in p) {
      dispatch({ type: "previewErr", msg: `Preview failed: ${p.error}` });
      return;
    }
    dispatch({ type: "previewErr", msg: null });
    try {
      await previewM.mutateAsync({ account_id: accountId, config: buildConfig(state), ...p });
    } catch (e) {
      dispatch({ type: "previewErr", msg: `Preview failed: ${(e as Error)?.message || "unknown"}` });
    }
  }

  async function applyToModels() {
    dispatch({ type: "bulkMsg", msg: block });
    if (block) return;
    try {
      const r = await bulkM.mutateAsync({ account_ids: picked, config: buildConfig(state), enable: true });
      dispatch({ type: "bulkMsg", msg: `Enabled nudge online (text-only) on ${r.count} model${r.count === 1 ? "" : "s"}.` });
    } catch (e) {
      dispatch({ type: "bulkMsg", msg: `Failed: ${(e as Error)?.message || "unknown error"}` });
    }
  }

  async function runNow() {
    if (!rule) return;
    dispatch({ type: "runMsg", msg: null });
    try {
      await runM.mutateAsync(rule.id);
      dispatch({ type: "runMsg", msg: "Ran one detector pass — nudges fire after their delay." });
    } catch (e) {
      dispatch({ type: "runMsg", msg: `Run failed: ${(e as Error)?.message || "unknown error"}` });
    }
  }

  const last = rule?.last_run;

  return (
    <div className="space-y-6 text-[14px]">
      <header className="flex items-center gap-4">
        <h2 className="font-medium">Nudge online</h2>
        <IfLearn tip={<>
          Every ~60 seconds it asks OnlyFans who is online. A fan who just came online (offline at least the online
          gap) gets a nudge delay + jitter minutes later, if he is still online recently, has no live conversation,
          was not nudged within the min hours and it is outside quiet hours. It sends one time-of-day greeting; of a
          slot&apos;s images one is sent, rotated. It only messages fans you have welcomed who are not mid-thread,
          and never pauses AI chat. Roll out to models is text-only.
        </>} />
        <div className="ml-auto shrink-0">
          <EditRawJsonButton surface="nudge-config" accountId={accountId} />
        </div>
      </header>
      <IfHelp className="-mt-4">Messages a fan a few minutes after they come online: a time-of-day tease.</IfHelp>

      {accounts.length > 1 && (
        <Field label="Account">
          {(id) => (
            <IfNativeSelect id={id} className="w-full" value={accountId ?? ""}
              onChange={(e) => dispatch({ type: "account", accountId: e.target.value })}>
              {accounts.map((a) => (
                <option key={a.id} value={a.id}>{a.nickname || a.id}</option>
              ))}
            </IfNativeSelect>
          )}
        </Field>
      )}

      {/* Drawn only once the draft is seeded (the gate's `drafted`) — also not
       *  while a cached config is ignored as pre-save: fields drawn from the
       *  unseeded draft would show fallbacks, and an edit typed there would be
       *  wiped by the hydrate. A failed load says so instead of loading forever;
       *  no account (none connected) has nothing to load, so nothing is drawn. */}
      {!gate.drafted ? (
        !accountId ? null
          : note?.failed
            ? <div className="text-err">{note.text}</div>
            : <div className="text-fg-dim">Loading…</div>
      ) : (
        <div className="space-y-6">
          {restored && (
            <div className="flex items-start gap-3 rounded-md border border-warn/40 p-3">
              <div className="flex-1">
                <div>{RESTORED_NOTE}</div>
                {restored.moved && <div className="text-warn mt-1">{RESTORED_MOVED_NOTE}</div>}
              </div>
              {/* Off mid-save: the PUT's ack would land under a form already put back. */}
              <IfButton onClick={discardDraft} disabled={busy || !!state.saving}>Discard</IfButton>
            </div>
          )}
          <IfSwitch label="Enabled" checked={form.enabled !== false} onChange={(on) => set("enabled", on)} />

          {/* What gets sent — one message: the time-of-day greeting. */}
          <Section title="What gets sent">
            <div className="flex flex-wrap gap-6">
              <IfSwitch label="Include text (off = image only)" checked={form.nudge_line_text !== false}
                onChange={(on) => set("nudge_line_text", on)} />
              <IfSwitch label="Attach image" checked={form.nudge_line_image !== false}
                onChange={(on) => set("nudge_line_image", on)} />
            </div>
            <IfHelp className="mt-0">One time-of-day greeting; by default with an image.</IfHelp>
            <div className="max-w-xs">
              <Field label="On re-engagement">
                {(id) => (
                  <IfNativeSelect id={id} className="w-full" value={form.repeat_mode ?? "new"}
                    onChange={(e) => set("repeat_mode", e.target.value as "new" | "same")}>
                    <option value="new">New line each time</option>
                    <option value="same">Same line again</option>
                  </IfNativeSelect>
                )}
              </Field>
              <IfHelp>What a returning fan gets the next time he re-qualifies.</IfHelp>
            </div>
          </Section>

          <Section title="Timing">
            <div className="grid grid-cols-2 gap-4 md:grid-cols-3">
              <NumField label="Delay (min)" value={num("delay_minutes", 4)}
                onChange={(v) => set("delay_minutes", v)} min={0} />
              <NumField label="Jitter (min)" value={num("jitter_minutes", 3)}
                onChange={(v) => set("jitter_minutes", v)} min={0} />
              <NumField label="Online gap (min)" value={num("gap_minutes", 5)}
                onChange={(v) => set("gap_minutes", v)} min={1} />
            </div>
            <IfHelp className="mt-0">
              Wait the delay plus 0 to jitter minutes after a fan comes online; offline for the gap before a return counts again.
            </IfHelp>
          </Section>

          <Section title="Limits">
            <div className="grid grid-cols-2 gap-4 md:grid-cols-3">
              <NumField label="Min hours between" value={num("min_hours_between_nudges", 12)}
                onChange={(v) => set("min_hours_between_nudges", v)} min={0} />
              <NumField label="Max per tick" value={num("max_per_tick", 25)}
                onChange={(v) => set("max_per_tick", v)} min={1} />
              <NumField label="Online recent (min)" value={num("online_recent_minutes", 5)}
                onChange={(v) => set("online_recent_minutes", v)} min={1} />
            </div>
            <IfHelp className="mt-0">
              One nudge per fan per min hours; max fans started per 60s scan (extras roll over); skipped if he left during the delay.
            </IfHelp>
          </Section>

          <Section title="Spend">
            <div className="grid grid-cols-2 gap-4">
              <DollarField label="Min lifetime spend ($)" cents={num("min_lifetime_spend_cents", 0)}
                onChange={(c) => set("min_lifetime_spend_cents", c)} />
              <DollarField label="Max lifetime spend ($)" cents={num("max_lifetime_spend_cents", 0)}
                onChange={(c) => set("max_lifetime_spend_cents", c)} />
            </div>
            <div className="grid grid-cols-2 gap-4 md:grid-cols-3">
              <NumField label="Recent window (days)" value={num("recent_spend_days", 30)}
                onChange={(v) => set("recent_spend_days", v)} min={1} />
              <DollarField label="Min recent spend ($)" cents={num("min_recent_spend_cents", 0)}
                onChange={(c) => set("min_recent_spend_cents", c)} />
              <DollarField label="Max recent spend ($)" cents={num("max_recent_spend_cents", 0)}
                onChange={(c) => set("max_recent_spend_cents", c)} />
            </div>
            <IfHelp className="mt-0">Only fans in this spend band; blank or 0 = off. Recent sums the last N days.</IfHelp>
          </Section>

          <div>
            <Field label="Quiet hours">
              {(id) => (
                <div className="flex items-center gap-2">
                  <IfInput id={id} type="number" min={0} max={23} className="w-20"
                    value={form.quiet_hours?.[0] ?? 0}
                    onChange={(e) => set("quiet_hours", [Number(e.target.value), form.quiet_hours?.[1] ?? 0])} />
                  <span>to</span>
                  <IfInput type="number" min={0} max={23} className="w-20" aria-label="Quiet hours end"
                    value={form.quiet_hours?.[1] ?? 0}
                    onChange={(e) => set("quiet_hours", [form.quiet_hours?.[0] ?? 0, Number(e.target.value)])} />
                </div>
              )}
            </Field>
            <IfHelp>No nudges in this window, creator-local time; equal = off.</IfHelp>
          </div>

          {/* ── Preview ─────────────────────────────────────────────── */}
          <Section title="Preview">
            <div className="flex flex-wrap items-end gap-3">
              <Field label="Fan id">
                {(id) => (
                  <IfInput id={id} className="w-40" placeholder="Sample fan"
                    value={previewFan} onChange={(e) => setPreviewFan(e.target.value)} />
                )}
              </Field>
              <Field label="Hour">
                {(id) => (
                  <IfInput id={id} type="number" min={0} max={23} className="w-24" placeholder="Now"
                    value={previewHour} onChange={(e) =>
                      setPreviewHour(e.target.value === "" ? "" : Number(e.target.value))} />
                )}
              </Field>
              <IfSegmented aria-label="Preview time" className="mb-px"
                options={TIME_PRESETS.map(([label, h]) => ({ value: String(h), label }))}
                value={String(previewHour)} onChange={(h) => setPreviewHour(Number(h))} />
              <IfButton onClick={runPreview} disabled={previewM.isPending || !accountId}>
                {previewM.isPending ? "…" : "Preview"}
              </IfButton>
            </div>
            {previewM.data && (
              <div className="space-y-2">
                {previewM.data.messages.length === 0 ? (
                  <div className="text-fg-dim">
                    Nothing would be sent — turn on the text or give the slot an image.
                  </div>
                ) : (
                  previewM.data.messages.map((m, i) => (
                    <PreviewBox
                      key={i}
                      label="Nudge line"
                      one={{ text: m.text, slot: previewM.data!.slot, media: m.media }}
                      accountId={accountId}
                      mediaCache={mediaCache}
                    />
                  ))
                )}
                <IfHelp>
                  {"{name}"} becomes <span className="text-fg">{previewM.data.name}</span>: the first name or nickname, never the full label.
                </IfHelp>
              </div>
            )}
          </Section>

          {/* ── Tease pools: friendly editor ────────────────────────── */}
          <Section title="Message lines (default times)">
            <IfHelp className="mt-0">
              {"{name} {city} {age} {job} {hobby} {pet}"} fill from the fan&apos;s profile. One image per nudge; several rotate.
            </IfHelp>
            {SLOT_DEFS.map(([key, label]) => (
              <SlotEditor
                key={key}
                label={label}
                entry={slots.default?.[key] ?? { text: [], image: [] }}
                onChange={(entry) => setDefaultSlot(key, entry)}
                accountId={accountId}
                mediaCache={mediaCache}
                onPickImages={() => setPickerSlot(key)}
              />
            ))}
          </Section>

          {/* Advanced JSON (copy in/out, weekend/friday, full control) */}
          <Collapsible open={advOpen} onToggle={() => setAdvOpen((v) => !v)}
            title="Advanced: edit pools as JSON">
            <div className="space-y-2">
              <IfTextArea
                className="h-56 font-mono text-[13px]"
                value={jsonDraft} onChange={(e) => dispatch({ type: "jsonDraft", text: e.target.value })} spellCheck={false} />
              <div className="flex items-center gap-4">
                <IfButton onClick={() => dispatch({ type: "applyJson" })}>Apply JSON</IfButton>
                <IfButton variant="link"
                  onClick={() => navigator.clipboard?.writeText(jsonDraft)}>Copy</IfButton>
                {jsonErr && <span className="text-err">{jsonErr}</span>}
              </div>
              <IfHelp>
                {"Bucket → slot → { text: [...], image: [...] }"}; buckets default, weekend, weekday or a day name (most specific wins).
              </IfHelp>
            </div>
          </Collapsible>

          {(previewErr ?? saveErr) && <div className="text-err">{previewErr ?? saveErr}</div>}

          {(runMsg ?? savedOk) && (
            <div className="text-accent">{runMsg ?? "Saved."}</div>
          )}

          {rule && last && (
            <div className="text-[12px] text-muted">
              Last run: <span className="text-fg">{last.status}</span>
              {typeof last.stats?.enqueued === "number" && (
                <span className="text-fg"> · {last.stats.enqueued as number} nudges queued</span>
              )}
              {typeof last.stats?.online === "number" && (
                <span> · {last.stats.online as number} online</span>
              )}
              {last.stats?.warmup === true && <span> · warm-up (no sends)</span>}
              {last.started_at && ` · ${new Date(last.started_at).toLocaleString()}`}
              {rule.has_pending_job && " · job queued"}
              {last.error_text && <span className="text-err"> · {last.error_text}</span>}
            </div>
          )}
        </div>
      )}

      {/* Roll out to all models at once (text-only — no vault images needed) */}
      {accounts.length > 1 && (
        <Section title="Roll out to models" extra={(
          <span className="flex gap-4">
            <IfButton variant="link" onClick={() => dispatch({ type: "setModels", ids: null })}>All</IfButton>
            <IfButton variant="link" onClick={() => dispatch({ type: "setModels", ids: [] })}>None</IfButton>
          </span>
        )}>
          <IfHelp className="mt-0">Applies the config above to every checked model and turns it on; text only.</IfHelp>
          <div className="grid grid-cols-2 gap-x-4 gap-y-2 max-h-56 overflow-auto rounded-md border border-border p-3">
            {accounts.map((a) => (
              <IfSwitch key={a.id} className="min-w-0" label={<span className="block truncate">{a.nickname || a.id}</span>}
                checked={picked.includes(a.id)} onChange={() => dispatch({ type: "toggleModel", id: a.id, all: allIds })} />
            ))}
          </div>
          <div className="flex flex-wrap items-center gap-3">
            <IfButton onClick={applyToModels} disabled={bulkM.isPending || !!block} title={block ?? undefined}>
              {bulkM.isPending ? "Applying…" : `Apply and enable on ${picked.length} model${picked.length === 1 ? "" : "s"}`}
            </IfButton>
            <span className="text-[12px] text-muted">{block ?? "enables the 60s rule live on each"}</span>
          </div>
          {bulkMsg && <div className="text-accent">{bulkMsg}</div>}
        </Section>
      )}

      {/* Vault image picker for a slot (opened from a slot's "Add image"). */}
      {pickerSlot && accountId && (
        <VaultPicker
          open
          onClose={() => setPickerSlot(null)}
          accountId={accountId}
          fanId={null}
          initialSelectedIds={slots.default?.[pickerSlot]?.image ?? []}
          onConfirm={(picked) => {
            setMediaCache((prev) => {
              const next = { ...prev };
              picked.forEach((m) => { next[m.id] = m; });
              return next;
            });
            const cur = slots.default?.[pickerSlot] ?? { text: [], image: [] };
            setDefaultSlot(pickerSlot, { ...cur, image: picked.map((m) => m.id) });
            setPickerSlot(null);
          }}
        />
      )}
      {/* The one Save, in the dialog's footer (`EditorFooter`: `AutomatedEditor`'s IfModal). Drawn outside the
       *  `drafted` ternary, so it reads the full `canSave` gate — load half included — and says why it is off. It
       *  shows only the save's own verdict, never Run now's or Preview's line. */}
      <EditorFooter>
      <div data-testid="sticky-save-bar" className="contents">
        <div className="mr-auto flex flex-col text-[12px]">
          {note && <span className={note.failed ? "text-err" : "text-muted"}>{note.text}</span>}
          {saveErr && <span className="text-err">{saveErr}</span>}
        </div>
        {rule && (
          <IfButton icon={Play} onClick={runNow} disabled={runM.isPending}
            title="Run one detector pass now (bypasses the 60s timer)">
            {runM.isPending ? "Running…" : "Run now"}
          </IfButton>
        )}
        <IfButton variant="primary" onClick={save} disabled={saveDisabled}>
          {busy ? "Saving…" : saveLabel}
        </IfButton>
      </div>
      </EditorFooter>
    </div>
  );
}

// ── small bits ────────────────────────────────────────────────────────

/** A labelled field: the kit label above its control, tied by an id. */
function Field({ label, children }: { label: string; children: (id: string) => ReactNode }) {
  const id = useId();
  return (
    <div>
      <IfLabel htmlFor={id}>{label}</IfLabel>
      {children(id)}
    </div>
  );
}

/** A titled group of the form; `extra` sits at the title row's right. */
function Section({ title, extra, children }: { title: string; extra?: ReactNode; children: ReactNode }) {
  return (
    <section className="space-y-3">
      <div className="flex items-center justify-between gap-3">
        <h3 className="font-medium">{title}</h3>
        {extra}
      </div>
      {children}
    </section>
  );
}

function NumField({
  label, value, onChange, min,
}: { label: string; value: number; onChange: (v: number) => void; min?: number }) {
  return (
    <Field label={label}>
      {(id) => (
        <IfInput id={id} type="number" min={min} value={value} className="w-full"
          onChange={(e) => { const n = Number(e.target.value); if (Number.isFinite(n)) onChange(n); }} />
      )}
    </Field>
  );
}

/** Dollar input that stores CENTS; 0/empty saves `null` (= off), so a bound of
 *  0 never accidentally means "skip every paying fan". */
function DollarField({
  label, cents, onChange,
}: { label: string; cents: number; onChange: (cents: number | null) => void }) {
  const dollars = cents > 0 ? cents / 100 : 0;
  return (
    <Field label={label}>
      {(id) => (
        <IfInput id={id} type="number" min={0} step="0.01" placeholder="off" className="w-full"
          value={dollars || ""}
          onChange={(e) => {
            const d = Number(e.target.value);
            if (!Number.isFinite(d)) return;
            onChange(d > 0 ? Math.round(d * 100) : null);
          }} />
      )}
    </Field>
  );
}

function thumbSrc(media: VaultMedia | undefined, accountId: string | null): string {
  const raw = media?.files?.thumb?.url || media?.files?.squarePreview?.url
    || media?.files?.preview?.url || "";
  return raw ? proxyImage(raw, accountId) : "";
}

function MediaThumb({
  id, media, accountId, onRemove,
}: { id: number; media?: VaultMedia; accountId: string | null; onRemove?: () => void }) {
  const url = thumbSrc(media, accountId);
  return (
    <div className="relative w-12 h-12 rounded md:overflow-hidden border border-border bg-bg shrink-0">
      {url
        ? <img src={url} alt="" loading="lazy" className="w-full h-full object-cover rounded md:rounded-none" />
        : <span className="w-full h-full grid place-items-center text-[12px] text-fg-dim">#{id}</span>}
      {onRemove && (
        <button type="button" onClick={onRemove} title="Remove" aria-label="Remove image"
          className="absolute -top-2 -right-2 md:-top-1 md:-right-1 bg-panel border border-border rounded-full w-7 h-7 md:w-4 md:h-4 grid place-items-center hover:text-err"><X className="size-3 md:size-2.5" aria-hidden /></button>
      )}
    </div>
  );
}

function PreviewBox({
  label, one, accountId, mediaCache,
}: {
  label: string;
  one: { text: string; slot: string; media: number[] };
  accountId: string | null;
  mediaCache: Record<number, VaultMedia>;
}) {
  return (
    <div className="rounded-md border border-border p-3">
      <div className="flex items-center justify-between text-[12px] text-fg-dim mb-1">
        <span className="font-medium text-fg">{label}</span>
        <span>slot: {one.slot}</span>
      </div>
      {one.text
        ? <div>{one.text}</div>
        : <div className="text-fg-dim">(image only — no text)</div>}
      {one.media.length > 0 && (
        <div className="flex flex-wrap gap-1.5 mt-1.5">
          {one.media.map((id) => (
            <MediaThumb key={id} id={id} media={mediaCache[id]} accountId={accountId} />
          ))}
        </div>
      )}
    </div>
  );
}

/** One time-slot's editable list of message lines + a vault image picker. */
function SlotEditor({
  label, entry, onChange, accountId, mediaCache, onPickImages,
}: {
  label: string;
  entry: NudgeSlotEntry;
  onChange: (e: NudgeSlotEntry) => void;
  accountId: string | null;
  mediaCache: Record<number, VaultMedia>;
  onPickImages: () => void;
}) {
  const texts = entry.text ?? [];
  const images = entry.image ?? [];
  const setLine = (i: number, v: string) => {
    const next = [...texts]; next[i] = v;
    onChange({ ...entry, text: next });
  };
  const removeLine = (i: number) => onChange({ ...entry, text: texts.filter((_, j) => j !== i) });
  const addLine = () => onChange({ ...entry, text: [...texts, ""] });
  const removeImage = (id: number) => onChange({ ...entry, image: images.filter((x) => x !== id) });

  return (
    <div className="rounded-md border border-border p-3 space-y-2">
      <div className="font-medium">{label}</div>
      {texts.length === 0 && <div className="text-[12px] text-muted">No lines yet.</div>}
      {texts.map((t, i) => (
        <div key={i} className="flex items-center gap-2">
          <IfInput className="flex-1" value={t} onChange={(e) => setLine(i, e.target.value)}
            placeholder="e.g. hey {name}" />
          <button type="button" className="text-fg-dim hover:text-err" title="Remove" aria-label="Remove line"
            onClick={() => removeLine(i)}><X className="size-4" /></button>
        </div>
      ))}
      <div className="flex flex-wrap items-center gap-4">
        <IfButton variant="link" onClick={addLine}>Add line</IfButton>
        <ImportCaptionsButton current={texts}
          onImport={(items) => onChange({ ...entry, text: mergeCaptions(texts, items).pool })} />
      </div>
      {/* Images: thumbnails + an add-from-vault tile (the "Add script" media tile). Sends ONE (rotated) if several. */}
      <div className="flex flex-wrap items-center gap-4 md:gap-2">
        {images.map((id) => (
          <MediaThumb key={id} id={id} media={mediaCache[id]} accountId={accountId}
            onRemove={() => removeImage(id)} />
        ))}
        <button type="button" onClick={onPickImages} title="Add image from vault" aria-label="Add image from vault"
          className="w-12 h-12 rounded-md border border-dashed border-border grid place-items-center text-fg-dim hover:border-accent hover:text-accent">
          <ImageIcon className="size-4" />
        </button>
      </div>
    </div>
  );
}

function Collapsible({
  open, onToggle, title, children,
}: { open: boolean; onToggle: () => void; title: string; children: React.ReactNode }) {
  return (
    <div className="rounded-md border border-border">
      <button type="button" onClick={onToggle} aria-expanded={open}
        className="w-full flex items-center justify-between rounded-md px-3 h-10 font-medium hover:bg-bg-elev-1">
        <span>{title}</span>
        <ChevronDown className={`size-4 transition-transform ${open ? "rotate-180" : ""}`} />
      </button>
      {open && <div className="px-3 pb-3 pt-1">{children}</div>}
    </div>
  );
}
