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

import { useEffect, useMemo, useReducer, useState } from "react";
import { Radio, Play, Rocket, Eye, ChevronDown, Plus, Save, X, Image as ImageIcon } from "lucide-react";

import { Button, Card, Input } from "@/components/ui/primitives";
import { EditRawJsonButton } from "@/components/settings/JsonConfigModal";
import { VaultPicker } from "@/components/chat/VaultPicker";
import { ImportCaptionsButton } from "@/components/compose/ImportCaptionsButton";
import { mergeCaptions } from "@/lib/parseCaptions";
import { type VaultMedia } from "@/lib/relay";
import { proxyImage } from "@/lib/mediaUrl";
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
  type NudgeConfig,
  type NudgeSlotEntry,
} from "@/hooks/useNudgeConfig";
import StickySaveBar from "@/components/settings/StickySaveBar";
import {
  buildConfig,
  canSave,
  effectiveConfig,
  gateNote,
  initialNudgeOnlineState,
  nudgeOnlineReducer,
  pickedIds,
  previewPayload,
  rolloutBlock,
  type FormKey,
} from "@/components/settings/nudgeOnlineReducer";

const SELECT_CLS =
  "w-full bg-bg border border-border rounded-lg px-3 py-2 text-sm focus:outline-none focus:border-accent";

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
  const [helpOpen, setHelpOpen] = useState(false);

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
  useEffect(() => {
    if (!cfgQ.data) return;
    dispatch({
      type: "hydrate", eff: effectiveConfig(cfgQ.data), accountId,
      fetchedAt: cfgQ.dataUpdatedAt, pending: busy,
    });
  }, [cfgQ.data, cfgQ.dataUpdatedAt, accountId, busy]);

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
      dispatch({ type: "bulkMsg", msg: `✓ Enabled nudge online (text-only) on ${r.count} model${r.count === 1 ? "" : "s"}.` });
    } catch (e) {
      dispatch({ type: "bulkMsg", msg: `Failed: ${(e as Error)?.message || "unknown error"}` });
    }
  }

  async function runNow() {
    if (!rule) return;
    dispatch({ type: "runMsg", msg: null });
    try {
      await runM.mutateAsync(rule.id);
      dispatch({ type: "runMsg", msg: "✓ Ran one detector pass — nudges fire after their delay." });
    } catch (e) {
      dispatch({ type: "runMsg", msg: `Run failed: ${(e as Error)?.message || "unknown error"}` });
    }
  }

  const last = rule?.last_run;

  return (
    <div className="space-y-5 max-w-2xl">
      <header className="flex items-start gap-2">
        <Radio className="size-5 text-accent" />
        <div>
          <h2 className="text-lg font-semibold">Nudge online</h2>
          <p className="text-sm text-fg-dim">
            Message a fan a few minutes after they come online — a personalized,
            time-of-day tease. Runs in the
            background; it never pauses AI chat.
          </p>
        </div>
        <div className="ml-auto shrink-0">
          <EditRawJsonButton surface="nudge-config" accountId={accountId} />
        </div>
      </header>

      {accounts.length > 1 && (
        <Field label="Account">
          <select className={SELECT_CLS} value={accountId ?? ""}
            onChange={(e) => dispatch({ type: "account", accountId: e.target.value })}>
            {accounts.map((a) => (
              <option key={a.id} value={a.id}>{a.nickname || a.id}</option>
            ))}
          </select>
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
            ? <div className="text-sm text-err">{note.text}</div>
            : <div className="text-sm text-fg-dim">Loading…</div>
      ) : (
        <Card className="p-4 space-y-5">
          {/* Enable */}
          <div>
            <label className="flex items-center gap-2 text-sm cursor-pointer">
              <input type="checkbox" checked={form.enabled !== false}
                onChange={(e) => set("enabled", e.target.checked)} />
              Enabled
            </label>
          </div>

          {/* What gets sent — one message: the time-of-day greeting. */}
          <div className="space-y-3">
            <div className="text-sm font-semibold">What gets sent</div>
            <Hint>
              A nudge sends one message: a time-of-day greeting. Default: the greeting{" "}
              <b>with image</b>.
            </Hint>

            <div className="border border-border rounded-lg p-3 space-y-2">
              <div className="text-sm font-medium">Nudge line (time-of-day greeting)</div>
              <div className="flex flex-wrap gap-4">
                <label className="flex items-center gap-2 text-sm cursor-pointer">
                  <input type="checkbox" checked={form.nudge_line_text !== false}
                    onChange={(e) => set("nudge_line_text", e.target.checked)} />
                  Include text (off = image only)
                </label>
                <label className="flex items-center gap-2 text-sm cursor-pointer">
                  <input type="checkbox" checked={form.nudge_line_image !== false}
                    onChange={(e) => set("nudge_line_image", e.target.checked)} />
                  Attach image
                </label>
              </div>
            </div>

            <div className="max-w-xs">
              <Field label="On re-engagement">
                <select className={SELECT_CLS} value={form.repeat_mode ?? "new"}
                  onChange={(e) => set("repeat_mode", e.target.value as "new" | "same")}>
                  <option value="new">New line each time</option>
                  <option value="same">Same line again</option>
                </select>
              </Field>
              <Hint>What a returning fan gets the next time they re-qualify.</Hint>
            </div>
          </div>

          {/* Timing */}
          <div>
            <div className="grid grid-cols-2 gap-3 md:grid-cols-3 md:gap-4">
              <NumField label="Delay (min)" value={num("delay_minutes", 4)}
                onChange={(v) => set("delay_minutes", v)} min={0} />
              <NumField label="Jitter (min)" value={num("jitter_minutes", 3)}
                onChange={(v) => set("jitter_minutes", v)} min={0} />
              <NumField label="Online gap (min)" value={num("gap_minutes", 5)}
                onChange={(v) => set("gap_minutes", v)} min={1} />
            </div>
            <Hint>
              <b>Delay</b>: wait this long after a fan comes online before messaging (so it
              doesn’t look instant/bot-like). <b>Jitter</b>: add a random 0–N min on top so
              sends aren’t all at the exact same offset. <b>Online gap</b>: how long a fan
              must have been <i>offline</i> before coming back counts as “newly online” again
              (stops flapping from re-triggering).
            </Hint>
          </div>

          {/* Caps */}
          <div>
            <div className="grid grid-cols-2 gap-3 md:grid-cols-3 md:gap-4">
              <NumField label="Min hours between" value={num("min_hours_between_nudges", 12)}
                onChange={(v) => set("min_hours_between_nudges", v)} min={0} />
              <NumField label="Max per tick" value={num("max_per_tick", 25)}
                onChange={(v) => set("max_per_tick", v)} min={1} />
              <NumField label="Online recent (min)" value={num("online_recent_minutes", 5)}
                onChange={(v) => set("online_recent_minutes", v)} min={1} />
            </div>
            <Hint>
              <b>Min hours between</b>: never nudge the same fan more than once per this many
              hours (re-engagement cap). <b>Max per tick</b>: most fans to start per 60s scan —
              extras roll to the next tick (never dropped). <b>Online recent</b>: at send time
              the fan must have been seen online within this many minutes, else the nudge is
              skipped (they left during the delay).
            </Hint>
          </div>

          {/* Spend targeting (optional) */}
          <div>
            <div className="grid grid-cols-2 gap-4">
              <DollarField label="Min lifetime spend ($)" cents={num("min_lifetime_spend_cents", 0)}
                onChange={(c) => set("min_lifetime_spend_cents", c)} />
              <DollarField label="Max lifetime spend ($)" cents={num("max_lifetime_spend_cents", 0)}
                onChange={(c) => set("max_lifetime_spend_cents", c)} />
            </div>
            <div className="grid grid-cols-2 gap-3 md:grid-cols-3 md:gap-4 mt-3">
              <NumField label="Recent window (days)" value={num("recent_spend_days", 30)}
                onChange={(v) => set("recent_spend_days", v)} min={1} />
              <DollarField label="Min recent spend ($)" cents={num("min_recent_spend_cents", 0)}
                onChange={(c) => set("min_recent_spend_cents", c)} />
              <DollarField label="Max recent spend ($)" cents={num("max_recent_spend_cents", 0)}
                onChange={(c) => set("max_recent_spend_cents", c)} />
            </div>
            <Hint>
              Only nudge fans in a spend tier (<b>0 = off</b>). <b>Lifetime</b> uses total spend;{" "}
              <b>recent</b> sums the last <i>N days</i> of transactions. Set a <b>max</b> to target
              low / keep-warm fans, a <b>min</b> to target spenders, or both for a band.
            </Hint>
          </div>

          {/* Quiet hours */}
          <div>
            <Field label="Quiet hours (creator-local) — start / end">
              <div className="flex items-center gap-2 text-sm">
                <Input type="number" min={0} max={23} className="w-20"
                  value={form.quiet_hours?.[0] ?? 0}
                  onChange={(e) => set("quiet_hours", [Number(e.target.value), form.quiet_hours?.[1] ?? 0])} />
                <span>to</span>
                <Input type="number" min={0} max={23} className="w-20"
                  value={form.quiet_hours?.[1] ?? 0}
                  onChange={(e) => set("quiet_hours", [form.quiet_hours?.[0] ?? 0, Number(e.target.value)])} />
                <span className="text-muted">(equal = off)</span>
              </div>
            </Field>
            <Hint>No nudges during this window, in the creator’s local time. Set both equal to disable.</Hint>
          </div>

          {/* ── Preview ─────────────────────────────────────────────── */}
          <div className="border border-border rounded-lg p-3 space-y-3 bg-bg/40">
            <div className="flex items-center gap-1.5 text-sm font-semibold">
              <Eye className="size-4 text-accent" /> Preview
            </div>
            <div className="flex flex-wrap items-end gap-2">
              <label className="block">
                <span className="text-xs text-fg-dim block mb-1">Fan id (blank = sample)</span>
                <Input className="w-40" placeholder="e.g. 123456789"
                  value={previewFan} onChange={(e) => setPreviewFan(e.target.value)} />
              </label>
              <label className="block">
                <span className="text-xs text-fg-dim block mb-1">Hour (blank = now)</span>
                <Input type="number" min={0} max={23} className="w-24"
                  value={previewHour} onChange={(e) =>
                    setPreviewHour(e.target.value === "" ? "" : Number(e.target.value))} />
              </label>
              <div className="flex flex-wrap gap-1">
                {TIME_PRESETS.map(([lbl, h]) => (
                  <button key={lbl} type="button"
                    onClick={() => setPreviewHour(h)}
                    className="text-xs px-2 py-1 rounded border border-border hover:border-accent">
                    {lbl}
                  </button>
                ))}
              </div>
              <Button onClick={runPreview} disabled={previewM.isPending || !accountId}>
                {previewM.isPending ? "…" : "Preview"}
              </Button>
            </div>
            {previewM.data && (
              <div className="space-y-2">
                {previewM.data.messages.length === 0 ? (
                  <div className="text-sm text-fg-dim italic">
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
                <p className="text-[11px] text-muted">
                  Resolved name: <b>{previewM.data.name}</b> — this is what{" "}
                  <code>{"{name}"}</code> becomes (their first name / nickname, not the full
                  “name/age/city” string).
                </p>
              </div>
            )}
          </div>

          {/* ── Tease pools: friendly editor ────────────────────────── */}
          <div className="space-y-3">
            <div>
              <span className="text-sm font-semibold">Message lines (default times)</span>
              <Hint>
                Lines for each time of day. <code>{"{name}"}</code>, <code>{"{city}"}</code>,{" "}
                <code>{"{age}"}</code>, <code>{"{job}"}</code>, <code>{"{hobby}"}</code>,{" "}
                <code>{"{pet}"}</code> are filled from the fan’s profile (empty ones vanish).
                Weekend/Friday overrides live in the Advanced JSON below.
              </Hint>
            </div>
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
          </div>

          {/* Advanced JSON (copy in/out, weekend/friday, full control) */}
          <Collapsible open={advOpen} onToggle={() => setAdvOpen((v) => !v)}
            title="Advanced — edit pools as JSON (copy in / out)">
            <div className="space-y-2">
              <textarea
                className="w-full bg-bg border border-border rounded-lg px-3 py-2 text-xs font-mono h-56 focus:outline-none focus:border-accent"
                value={jsonDraft} onChange={(e) => dispatch({ type: "jsonDraft", text: e.target.value })} spellCheck={false} />
              <div className="flex items-center gap-2">
                <Button variant="ghost" onClick={() => dispatch({ type: "applyJson" })}>Apply JSON</Button>
                <Button variant="ghost"
                  onClick={() => navigator.clipboard?.writeText(jsonDraft)}>Copy</Button>
                {jsonErr && <span className="text-sm text-err">{jsonErr}</span>}
              </div>
              <Hint>
                Shape: day-bucket → slot → <code>{`{ text: [...], image: [...] }`}</code>.
                Buckets: <code>default</code>, <code>weekend</code>, <code>weekday</code>, or a
                weekday name like <code>friday</code> (a per-day bucket wins over weekend/weekday,
                which win over default). “Apply JSON” pulls your edits back into the friendly
                editor above.
              </Hint>
            </div>
          </Collapsible>

          {(previewErr ?? saveErr) && <div className="text-sm text-err">{previewErr ?? saveErr}</div>}

          <div className="flex items-center gap-2 pt-1">
            {/* Same gate, same label and same pending word as the pinned twin
             *  below — the two are one control rendered twice. (The row itself
             *  is not a SaveRow: its feedback lives in the error / message
             *  blocks above and below, which a SaveRow would duplicate ~8px
             *  away from where they already are.) */}
            <Button onClick={save} disabled={saveDisabled}>
              <Save size={14} />
              {busy ? "Saving…" : saveLabel}
            </Button>
            {rule && (
              <Button variant="ghost" onClick={runNow} disabled={runM.isPending}
                title="Run one detector pass now (bypasses the 60s timer)">
                <Play className="size-4" /> {runM.isPending ? "Running…" : "Run now"}
              </Button>
            )}
          </div>

          {(runMsg ?? savedOk) && (
            <div className="text-sm text-accent border-t border-border pt-3">{runMsg ?? "✓ Saved."}</div>
          )}

          {rule && last && (
            <div className="text-xs text-fg-dim border-t border-border pt-3">
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
        </Card>
      )}

      {/* Roll out to all models at once (text-only — no vault images needed) */}
      {accounts.length > 1 && (
        <Card className="p-4 space-y-3">
          <div className="flex items-start justify-between gap-2">
            <div>
              <h3 className="text-sm font-semibold flex items-center gap-1.5">
                <Rocket className="size-4 text-accent" /> Roll out to models
              </h3>
              <p className="text-xs text-fg-dim mt-0.5">
                Apply the config above to every checked model and turn it on live.
                Text-only (no images), so it behaves identically across accounts.
              </p>
            </div>
            <div className="flex gap-2 text-xs shrink-0">
              <button className="text-accent hover:underline"
                onClick={() => dispatch({ type: "setModels", ids: null })}>All</button>
              <button className="text-fg-dim hover:underline"
                onClick={() => dispatch({ type: "setModels", ids: [] })}>None</button>
            </div>
          </div>
          <div className="grid grid-cols-2 gap-x-4 gap-y-0.5 max-h-56 overflow-auto border border-border rounded-lg p-2">
            {accounts.map((a) => (
              <label key={a.id} className="flex items-center gap-2 text-sm py-0.5 cursor-pointer">
                <input type="checkbox" checked={picked.includes(a.id)}
                  onChange={() => dispatch({ type: "toggleModel", id: a.id, all: allIds })} />
                <span className="truncate">{a.nickname || a.id}</span>
              </label>
            ))}
          </div>
          <div className="flex items-center gap-2">
            <Button onClick={applyToModels} disabled={bulkM.isPending || !!block} title={block ?? undefined}>
              <Rocket className="size-4" />
              {bulkM.isPending ? "Applying…" : `Apply + enable on ${picked.length} model${picked.length === 1 ? "" : "s"}`}
            </Button>
            <span className="text-xs text-muted">{block ?? "enables the 60s rule live on each"}</span>
          </div>
          {bulkMsg && <div className="text-sm text-accent border-t border-border pt-3">{bulkMsg}</div>}
        </Card>
      )}

      {/* How it works — long explanation */}
      <Collapsible open={helpOpen} onToggle={() => setHelpOpen((v) => !v)}
        title="How nudge online works (full explanation)">
        <div className="text-sm text-fg-dim space-y-2 leading-relaxed">
          <p>
            Every ~60 seconds the automation asks OnlyFans who is online right now. A fan who
            just came online (after being offline at least the <b>online gap</b>) is queued for
            a nudge <b>delay + jitter</b> minutes later. Just before sending it re-checks: still
            online recently (<b>online recent</b>), no live conversation, not nudged within the
            last <b>min hours between</b>, and outside <b>quiet hours</b>. If all good, it sends.
          </p>
          <p>
            <b>What gets sent.</b> One message: a time-of-day greeting from the slot pools (turn
            its text off for an image-only opener). Placeholders like <code>{"{name}"}</code> fill from the fan — <code>{"{name}"}</code>{" "}
            is their first name or nickname only (never the full “name/age/city” label).
          </p>
          <p>
            <b>Images.</b> “Attach image” sends the slot image with the greeting (on by
            default). If a slot lists several images, <b>one</b> is sent
            (rotated), not all. The bulk “Roll out to models” is always text-only so it works
            identically on every account without per-account vault ids.
          </p>
          <p>
            <b>Fully async.</b> Nudges never pause AI chat — if a chat automation already holds a
            fan, the nudge yields. It only sends to fans you’ve welcomed and who aren’t mid-thread,
            so it reads as a natural “hey, saw you’re around” rather than a bot blast.
          </p>
        </div>
      </Collapsible>

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
      {/* Pinned Save. The in-flow row above stays exactly where it is; this is
       *  a second control on the same handler, for a form that runs several
       *  screens deep.
       *
       *  It reads the SAME `canSave` the in-flow button does, and that gate
       *  carries the load half — see the const's own note. This bar is a
       *  sibling of the `!drafted ? … : <Card>` ternary, so unlike the
       *  in-flow button it is on screen during the fetch, which is exactly how
       *  it once shipped live over an unseeded form.
       *
       *  It shows only the save's own verdict (`save`), never Run now's or
       *  Preview's line: a bar labelled Save that turns red because a preview
       *  failed narrates someone else's action. */}
      <StickySaveBar
        hostPadding={0}
        onSave={save}
        saving={busy}
        canSave={saveAllowed}
        label={saveLabel}
        saved={savedOk}
        error={saveErr}
        gateNote={note}
      />
    </div>
  );
}

// ── small bits ────────────────────────────────────────────────────────

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <label className="block">
      <span className="text-xs font-medium text-fg-dim block mb-1">{label}</span>
      {children}
    </label>
  );
}

function NumField({
  label, value, onChange, min,
}: { label: string; value: number; onChange: (v: number) => void; min?: number }) {
  return (
    <Field label={label}>
      <Input type="number" min={min} value={value}
        onChange={(e) => { const n = Number(e.target.value); if (Number.isFinite(n)) onChange(n); }} />
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
      <Input type="number" min={0} step="0.01" placeholder="off"
        value={dollars || ""}
        onChange={(e) => {
          const d = Number(e.target.value);
          if (!Number.isFinite(d)) return;
          onChange(d > 0 ? Math.round(d * 100) : null);
        }} />
    </Field>
  );
}

function Hint({ children }: { children: React.ReactNode }) {
  return <p className="text-[11px] text-muted leading-snug mt-1">{children}</p>;
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
        : <span className="w-full h-full grid place-items-center text-[9px] text-fg-dim">#{id}</span>}
      {onRemove && (
        <button type="button" onClick={onRemove} title="Remove" aria-label="Remove image"
          className="absolute -top-2 -right-2 md:-top-1 md:-right-1 bg-panel border border-border rounded-full w-7 h-7 md:w-4 md:h-4 grid place-items-center text-[10px] leading-none hover:text-err">×</button>
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
    <div className="rounded-lg border border-border p-2 text-sm bg-panel">
      <div className="flex items-center justify-between text-[11px] text-fg-dim mb-1">
        <span className="font-medium text-fg">{label}</span>
        <span>slot: {one.slot}</span>
      </div>
      {one.text
        ? <div>{one.text}</div>
        : <div className="text-fg-dim italic">(image only — no text)</div>}
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
    <div className="border border-border rounded-lg p-2.5 space-y-1.5">
      <div className="text-xs font-medium text-fg-dim">{label}</div>
      {texts.length === 0 && <div className="text-[11px] text-muted">No lines yet.</div>}
      {texts.map((t, i) => (
        <div key={i} className="flex items-center gap-1.5">
          <Input className="flex-1 text-base md:text-sm" value={t} onChange={(e) => setLine(i, e.target.value)}
            placeholder="message line, e.g. hey {name} 👀" />
          <button type="button" className="text-fg-dim hover:text-err" title="Remove"
            onClick={() => removeLine(i)}><X className="size-4" /></button>
        </div>
      ))}
      <div className="flex flex-wrap items-center gap-3">
        <Button variant="ghost" type="button" onClick={addLine}>
          <Plus className="size-3.5" /> Add line
        </Button>
        <ImportCaptionsButton current={texts}
          onImport={(items) => onChange({ ...entry, text: mergeCaptions(texts, items).pool })} />
      </div>
      {/* Images: thumbnails + an add-from-vault tile. Sends ONE (rotated) if several. */}
      <div className="flex flex-wrap items-center gap-4 md:gap-2 pt-1">
        {images.map((id) => (
          <MediaThumb key={id} id={id} media={mediaCache[id]} accountId={accountId}
            onRemove={() => removeImage(id)} />
        ))}
        <button type="button" onClick={onPickImages} title="Add image from vault"
          className="w-12 h-12 rounded border border-dashed border-border grid place-items-center text-fg-dim hover:border-accent hover:text-accent">
          <ImageIcon className="size-4" />
        </button>
      </div>
      <p className="text-[11px] text-muted">Only <b>one</b> image is sent per nudge — add more and they rotate between sends.</p>
    </div>
  );
}

function Collapsible({
  open, onToggle, title, children,
}: { open: boolean; onToggle: () => void; title: string; children: React.ReactNode }) {
  return (
    <div className="border border-border rounded-lg">
      <button type="button" onClick={onToggle}
        className="w-full flex items-center justify-between px-3 py-2 text-sm font-medium hover:bg-bg-elev-1">
        <span>{title}</span>
        <ChevronDown className={`size-4 transition-transform ${open ? "rotate-180" : ""}`} />
      </button>
      {open && <div className="px-3 pb-3 pt-1">{children}</div>}
    </div>
  );
}
