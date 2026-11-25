"use client";

/**
 * Full AI Chat's settings column (spec phase-03a, 03b). On top Make draft live / Roll back / JSON with their errors
 * (owner 2026-11-15: seen without scrolling) and a status line saying whether the Draft (what the switches edit, only
 * the Test chat uses it) differs from the Live settings (the checkpoint, what fans get; `draftDiffLine`). Then, apart
 * from the bot config: the Mode control (Off / Live, `FullAiModeControl`; Make draft live / Roll back / JSON never move it). "Who Full AI answers when Live" (`FullAiAudience` in
 * `FullAiFans.tsx`: Fans and Top spend limit, their own write) sits on the page, above the Test chat.
 * Then the bot config, controls in a list named "Settings" (numbered as before; 1, 17 and 18 moved up):
 *   2. LLM keys: whether each provider the Writers run on (draft and checkpoint; the config GET's `writer_providers`)
 *   and, while Read his photos is on, DeepInfra is set on the Creator's owner's keys (the GET's `owner_keys`, what Live checks) (never a value or hint; "not set" in red, no DeepInfra key a
 *   warning, not a Live blocker), linking to the agency keys form;
 *   3. reply speed ("0-2 min" / "0-15-60 min"), 4. Human style (every `style` layer; mixed when they differ), 5. Typos
 *   (the typos layer alone; on, a "%" box sets `typo_pct`, empty = auto), 6. Writers (a checklist over `writers`: tick / untick, "Make Writer" moves one first), 7. GIFs
 *   (on, a "%" box sets `gif_pct`, empty = auto);
 *   8. Sexting (`sext_on`), 9. Lead-in questions (`lead_in`), 10. Questions (`info_questions`: Pick one / Whole list),
 *   11. Read his photos (`describe_fan_photos`), 12. Strip emojis (`strip_emojis`): plain switches (`chatSwitch`), owner 2026-11-15;
 *   13. Sell (on, the "Sell settings" group under it: eight switches, all on by default, owner 2026-11-14/15: Unasked
 *   offers, Chat tease, Implied asks, Nearest piece, Fill the set, Match his count, Spacing, He likes; `sellSwitches`),
 *   14. PPV caption (`caption_writer`: Last bubble / Own call). 15. Content folders and 16. Prepare content
 *   (`FullAiSellSettings.tsx`, ticket 49) sit on the page, above the Test chat. The Questions / PPV caption options are the server's (`limits`).
 * Controls 3-15 edit the draft config and store it at once (`useFullAiConfig.edit`); the Test chat's Send waits meanwhile.
 * Above them: Make draft live (draft → checkpoint), Roll back (swap checkpoint and previous), JSON (Live + Draft: checkpoint
 * and draft side by side, each editable and saved on its own, validated by the server; under them the read-only "All
 * settings" table off the GET's `reference`: every key's default, the Live and the draft's value, what it accepts and
 * does), then right under them the field
 * errors (a 409 without `rev` shows its words), and on a stale rev a reload message. Reload shows with either: it reads the stored config again, the way back from a refused edit or a failed read.
 * A draft stored elsewhere (the assistant's Apply) while an edit is unsaved raises the Keep mine / Take theirs bar on
 * top (ticket 57); controls, Make draft live and Send wait until one is picked.
 * State lives in the Test chat reducer (`fullAiTestChat.ts`); this file renders and calls the hook.
 */

import Link from "next/link";
import { useReducer, useState } from "react";

import { ROW, SwitchRow } from "@/components/automations/automationPage";
import { FullAiModeControl } from "@/components/automations/FullAiModeControl";
import {
  captionLabel, chatSwitch, draftDiffLine, humanStyle, humanStylePatch, infoQuestionsLabel, layersOff, sellSwitches, speedLabel,
  styleLayers, gifPct, gifPctPatch, sellSwitchPatch, settingRows, toggleWriterPatch,
  typoPct, typoPctPatch, typosPatch, writerPatch, type ChatSwitchKey, type FullAiConfig, type SettingRow,
} from "@/components/automations/fullAiConfig";
import { keyRows, photoKeyMissing } from "@/components/automations/fullAiKeys";
import {
  jsonEditInit, jsonEditReducer, jsonMoved, jsonTyped, prettyJson, type JsonSide,
} from "@/components/automations/fullAiConfigJson";
import { canEdit, canRollback, canSave, keepMineSave, STALE_TEXT, type TestChatState } from "@/components/automations/fullAiTestChat";
import { RawJsonActions, RawJsonEditor } from "@/components/automations/RawJsonModal";
import { IF_TABLE, IfButton, IfHelp, IfInput, IfModal, IfSegmented, IfSwitch } from "@/components/ui/infloww";
import { Badge } from "@/components/ui/primitives";
import { type FullAiConfigApi } from "@/hooks/useFullAiConfig";
import { errText } from "@/lib/errText";
import { parseJsonObject } from "@/lib/rawJsonReducer";
import { cn } from "@/lib/utils";


export function FullAiSettings({ state, cfg, accountId }: {
  state: TestChatState; cfg: FullAiConfigApi; accountId: string;
}) {
  const [jsonOpen, setJsonOpen] = useState(false);
  const draft = state.draft;
  const editable = canEdit(state);
  const off = !editable;
  const diff = draftDiffLine(state.checkpoint, draft, cfg.reference.map((r) => r.key));

  return (
    <div className="space-y-3">
      {state.conflict && <ConflictBar cfg={cfg} canKeep={keepMineSave(state) !== null} />}
      {/* On top, so it is seen without scrolling the list (owner 2026-11-15). */}
      <div className="flex flex-wrap items-center gap-2">
        <IfButton variant="primary" disabled={!canSave(state)} onClick={cfg.save}>Make draft live</IfButton>
        <IfButton disabled={!canRollback(state)} onClick={cfg.rollback}>Roll back</IfButton>
        <IfButton disabled={off} onClick={() => setJsonOpen(true)}>JSON (Live + Draft)</IfButton>
        {state.savingDraft && <span role="status" className="text-[12px] text-muted">Saving draft…</span>}
      </div>
      {diff && <p role="status" className={cn("text-[12px]", diff.differs ? "text-warn" : "text-muted")}>{diff.text}</p>}
      {/* Right under Make draft live: a refused Make draft live / Roll back / edit shows where it was tapped. */}
      {state.stale && <p role="alert" className="text-[12px] text-warn">{STALE_TEXT}</p>}
      {state.errors.length > 0 && !jsonOpen && (
        <ul aria-label="Config errors" className="space-y-1 text-[12px] text-err">
          {state.errors.map((e) => <li key={e}>{e}</li>)}
        </ul>
      )}
      {(state.stale || state.errors.length > 0) && (
        <div className="flex flex-wrap items-center gap-2">
          <IfButton onClick={() => void cfg.reload()}>Reload</IfButton>
          <span className="text-[12px] text-muted">Reads the stored config again; an edit not stored is dropped.</span>
        </div>
      )}
      <p className="text-[12px] text-muted">
        The switches below change the Draft: only the Test chat uses it. Make draft live copies it to the Live settings, the
        ones fans get. Roll back brings the previous Live settings back; tap it again to undo.
      </p>

      {/* Live or not: apart from the bot config below (its Make draft live / Roll back never move it). */}
      <p className="text-[14px] text-fg">
        Live: replies to the fans on its Fans list on OnlyFans. Off: sends nothing.
      </p>
      <FullAiModeControl accountId={accountId} />
      <ul aria-label="Settings" className="space-y-2">
        <li><KeysRow state={state} cfg={cfg} /></li>
        {cfg.limits && (
          <li className={ROW}>
            <div className="flex min-h-14 flex-wrap items-center justify-between gap-2 py-2">
              <span className="text-[14px] text-fg">Reply speed</span>
              <IfSegmented aria-label="Reply speed" value={draft?.reply_speed ?? cfg.limits.default_reply_speed}
                options={cfg.limits.reply_speeds.map((value) => ({ value, label: speedLabel(value), disabled: off }))}
                onChange={(reply_speed) => cfg.edit({ reply_speed })} />
            </div>
          </li>
        )}
        <li>
          <SwitchRow label="Human style" disabled={off} checked={humanStyle(draft) !== "off"}
            hint={humanStyle(draft) === "mixed" ? `Mixed: ${layersOff(draft)} off. Tap for all off.`
              : "Lowercase, short bubbles, light typos. Off: formal."}
            onChange={(on) => cfg.edit(humanStylePatch(on))} />
        </li>
        <li>
          <SwitchRow label="Typos" hint="Thumb slips and a *fix bubble." checked={styleLayers(draft).typos} disabled={off}
            onChange={(on) => cfg.edit(typosPatch(draft, on))}>
            {styleLayers(draft).typos && <TypoPctBox draft={draft} off={off} cfg={cfg} />}
          </SwitchRow>
        </li>
        {cfg.limits && <li><WriterRow draft={draft} off={off} cfg={cfg} max={cfg.limits.max_writers} /></li>}
        <li>
          <SwitchRow label="GIFs" checked={draft?.gifs === true} disabled={off} onChange={(gifs) => cfg.edit({ gifs })}>
            {draft?.gifs === true && <GifPctBox draft={draft} off={off} cfg={cfg} />}
          </SwitchRow>
        </li>
        <li><ChatSwitchRow k="sext_on" draft={draft} off={off} cfg={cfg} /></li>
        <li><ChatSwitchRow k="lead_in" draft={draft} off={off} cfg={cfg} /></li>
        {cfg.limits && (
          <li>
            <ChoiceRow label="Questions" hint="Pick one: Jev asks one thing. Whole list: the whole still-need list."
              value={draft?.info_questions ?? cfg.limits.info_questions[0]} values={cfg.limits.info_questions}
              toLabel={infoQuestionsLabel} off={off} onChange={(info_questions) => cfg.edit({ info_questions })} />
          </li>
        )}
        <li><ChatSwitchRow k="describe_fan_photos" draft={draft} off={off} cfg={cfg} /></li>
        <li><ChatSwitchRow k="strip_emojis" draft={draft} off={off} cfg={cfg} /></li>
        <li>
          <SwitchRow label="Sell" hint="Offer PPVs from the content folders. Off: the AI never sells." checked={draft?.sell_on === true}
            disabled={off} onChange={(sell_on) => cfg.edit({ sell_on })}>
            {draft?.sell_on === true && <SellGroup draft={draft} off={off} cfg={cfg} />}
          </SwitchRow>
        </li>
        {cfg.limits && (
          <li>
            <ChoiceRow label="PPV caption" hint="Last bubble: the reply's last bubble is the caption. Own call: a separate caption call."
              value={draft?.caption_writer ?? cfg.limits.caption_writers[0]} values={cfg.limits.caption_writers}
              toLabel={captionLabel} off={off} onChange={(caption_writer) => cfg.edit({ caption_writer })} />
          </li>
        )}
      </ul>

      {jsonOpen && draft && <ConfigJson state={state} cfg={cfg} onClose={() => setJsonOpen(false)} />}
    </div>
  );
}

/** The Sell settings: compact switches nested under Sell (only while it is on), each storing its on / off value. */
function SellGroup({ draft, off, cfg }: { draft: FullAiConfig | null; off: boolean; cfg: FullAiConfigApi }) {
  return (
    <div className="space-y-1.5">
      <ul aria-label="Sell settings" className="divide-y divide-border border-l-2 border-border pl-3">
        {sellSwitches(draft).map((s) => (
          <li key={s.key} className="flex min-h-12 items-center justify-between gap-4 py-2">
            <div className="min-w-0">
              <div className="text-[14px] text-fg">{s.label}</div>
              <div className="mt-0.5 text-[12px] text-muted">{s.hint}</div>
            </div>
            <IfSwitch aria-label={s.label} checked={s.checked} disabled={off}
              onChange={(on) => cfg.edit(sellSwitchPatch(s.key, on))} />
          </li>
        ))}
      </ul>
      <p className="text-[12px] text-muted">Test chat + live.</p>
    </div>
  );
}

function ChatSwitchRow({ k, draft, off, cfg }: { k: ChatSwitchKey; draft: FullAiConfig | null; off: boolean; cfg: FullAiConfigApi }) {
  const s = chatSwitch(draft, k);
  return <SwitchRow label={s.label} hint={s.hint} checked={s.checked} disabled={off} onChange={(on) => cfg.edit({ [k]: on })} />;
}

function ChoiceRow({ label, hint, value, values, toLabel, off, onChange }: {
  label: string; hint: string; value: string; values: string[]; toLabel: (v: string) => string; off: boolean;
  onChange: (v: string) => void;
}) {
  return (
    <div className={ROW}>
      <div className="flex min-h-14 flex-wrap items-center justify-between gap-2 py-2">
        <div className="min-w-0">
          <div className="text-[14px] text-fg">{label}</div>
          <div className="mt-0.5 text-[12px] text-muted">{hint}</div>
        </div>
        <IfSegmented aria-label={label} value={value}
          options={values.map((v) => ({ value: v, label: toLabel(v), disabled: off }))} onChange={onChange} />
      </div>
    </div>
  );
}

function TypoPctBox({ draft, off, cfg }: { draft: FullAiConfig | null; off: boolean; cfg: FullAiConfigApi }) {
  return <PctBox pct={typoPct(draft)} toPatch={typoPctPatch} off={off} cfg={cfg} label="Typos %"
    text="Replies with a typo" note="~1 per 5 sentences" />;
}

function GifPctBox({ draft, off, cfg }: { draft: FullAiConfig | null; off: boolean; cfg: FullAiConfigApi }) {
  return <PctBox pct={gifPct(draft)} toPatch={gifPctPatch} off={off} cfg={cfg} label="GIFs %"
    text="GIF when one fits" note="share of the replies a GIF suits, not of all replies" />;
}

function PctBox({ pct, toPatch, off, cfg, label, text, note }: {
  pct: number | null; toPatch: (text: string) => Partial<FullAiConfig> | null; off: boolean; cfg: FullAiConfigApi;
  label: string; text: string; note: string;
}) {
  const commit = (el: HTMLInputElement) => {
    const patch = toPatch(el.value);
    if (patch === null) el.value = pct === null ? "" : String(pct);
    else if (Object.values(patch)[0] !== pct) cfg.edit(patch);
  };
  return (
    <label className="flex flex-wrap items-center gap-2 text-[14px] text-fg">
      <span>{text}</span>
      <IfInput key={pct ?? "auto"} type="number" inputMode="numeric" min={0} max={100} step={1} aria-label={label}
        className="w-20" placeholder="auto" disabled={off} defaultValue={pct ?? ""}
        onBlur={(e) => commit(e.currentTarget)}
        onKeyDown={(e) => { if (e.key === "Enter") e.currentTarget.blur(); }} />
      <span className="text-[12px] text-muted">% · empty = auto ({note})</span>
    </label>
  );
}

function WriterRow({ draft, off, cfg, max }: { draft: FullAiConfig | null; off: boolean; cfg: FullAiConfigApi; max: number }) {
  const writers = draft?.writers ?? [];
  const options = [...new Set([...writers, ...cfg.writerModels])];
  return (
    <div className={ROW}>
      <fieldset className="space-y-1.5 py-3">
        <legend className="text-[14px] text-fg">Writers</legend>
        <p className="text-[12px] text-muted">Tick to add, untick to drop (1 to {max}). Tried in order: the first answers, the rest are fallbacks.</p>
        {options.map((m) => {
          const at = writers.indexOf(m);
          const patch = toggleWriterPatch(draft, m, max);
          return (
            <div key={m} className="flex min-h-9 items-center gap-2">
              <label className="flex min-w-0 flex-1 items-center gap-2 text-[14px]">
                <input type="checkbox" aria-label={m} checked={at >= 0} disabled={off || patch === null}
                  onChange={() => { if (patch) cfg.edit(patch); }} />
                <span className={at >= 0 ? "truncate text-fg" : "truncate text-muted"}>{m}</span>
                {at >= 0 && <span className="text-[12px] tabular-nums text-muted">{at === 0 ? "Writer" : `#${at + 1}`}</span>}
              </label>
              {at > 0 && (
                <IfButton variant="link" disabled={off} onClick={() => cfg.edit(writerPatch(draft, m, max))}>Make Writer</IfButton>
              )}
            </div>
          );
        })}
      </fieldset>
    </div>
  );
}

function ConflictBar({ cfg, canKeep }: { cfg: FullAiConfigApi; canKeep: boolean }) {
  return (
    <div role="group" aria-label="Draft changed elsewhere" className="space-y-2 rounded-lg border border-warn/40 px-4 py-3">
      <p className="text-sm text-fg">The draft changed elsewhere (an assistant Apply) while you had an unsaved edit.</p>
      <div className="flex flex-wrap items-center gap-2">
        <IfButton variant="primary" disabled={!canKeep} onClick={cfg.keepMine}>Keep mine</IfButton>
        <IfButton onClick={cfg.takeTheirs}>Take theirs</IfButton>
      </div>
      <p className="text-xs text-muted">Keep mine stores your edit over it; Take theirs drops your edit. Send and Make draft live wait until you pick.</p>
    </div>
  );
}

function KeysRow({ state, cfg }: { state: TestChatState; cfg: FullAiConfigApi }) {
  const providers = cfg.ownerKeys ?? undefined;
  const sides = [state.draft, state.checkpoint];
  const rows = keyRows(sides, cfg.writerProviders, cfg.providerLabels);
  return (
    <div className={ROW}>
      <div className="flex min-h-14 flex-wrap items-center justify-between gap-2 py-2">
        <div className="min-w-0">
          <div className="text-[14px] text-fg">LLM keys</div>
          <div className="mt-0.5 flex flex-wrap gap-x-3 text-[12px] text-muted">
            {cfg.ownerKeys === null ? <span className="text-err">Couldn&apos;t read the keys.</span> : !rows ? <span>…</span> : rows.map((k) => {
              const set = providers?.[k.id]?.set;
              return <span key={k.id} className={providers && !set ? "text-err" : undefined}>
                {providers ? `${k.label} ${set ? "set" : "not set"}` : `${k.label} …`}</span>;
            })}
          </div>
          {photoKeyMissing(sides, providers) && (
            <p role="status" className="mt-1 text-[12px] text-warn">
              Read his photos is on but there is no DeepInfra key: photos he sends won&apos;t be read. Add one in Settings → AI
              keys, or switch it off.
            </p>
          )}
        </div>
        <Link href="/settings/ai-keys" className="text-[14px] text-accent hover:text-accent-hover">Open keys form</Link>
      </div>
    </div>
  );
}

const JSON_TITLE: Record<JsonSide, string> = { checkpoint: "Live settings · what fans get", draft: "Draft · Test chat only" };
const JSON_SAVE: Record<JsonSide, string> = { checkpoint: "Save Live settings", draft: "Save draft" };

function ConfigJson({ state, cfg, onClose }: { state: TestChatState; cfg: FullAiConfigApi; onClose: () => void }) {
  const [ed, dispatch] = useReducer(jsonEditReducer, state, jsonEditInit);
  const text = ed.text;
  const setText = (side: JsonSide, t: string) => dispatch({ type: "type", side, text: t });
  const busy = state.savingDraft || state.committing;
  // Moved underneath: storing these boxes would 409, so Store is off.
  const moved = jsonMoved(ed, state);
  const typed = jsonTyped(ed);
  const serverError = state.stale ? STALE_TEXT : state.errors.length > 0 ? state.errors.join("\n") : null;
  const parse = (side: JsonSide): { v: Record<string, unknown> | null; err: string | null } => {
    try { return { v: parseJsonObject(text[side], "The config", '{"gifs": true}'), err: null }; }
    catch (e) { return { v: null, err: errText(e) }; }
  };
  const store = async (side: JsonSide) => {
    const { v } = parse(side);
    if (v && await (side === "draft" ? cfg.putDraft(v, ed.baseRev) : cfg.putCheckpoint(v, ed.baseRev))) onClose();
  };

  return (
    <IfModal width={1200} size="editor" title="Full AI config JSON" onClose={onClose} keyboard={!busy && !typed}
      footer={<IfButton onClick={onClose}>Cancel</IfButton>}>
      <IfHelp className="-mt-3 mb-3">Left: the Live settings, what fans get. Right: the Draft, used only by the Test chat. Each box saves on its own. Unknown keys are refused. fans and top_spend_cents are set above (Who Full AI answers); edits of them here are ignored.</IfHelp>
      {moved && !state.stale && (
        <p role="alert" className="-mt-1 mb-3 text-[12px] text-warn">
          The config changed elsewhere since you opened this (an assistant Apply), so these boxes can&apos;t be stored. Copy
          your text before Cancel (Cancel drops it), then open JSON again to edit the newer one.
        </p>
      )}
      <div className="grid gap-4 md:grid-cols-2">
        {(["checkpoint", "draft"] as const).map((side) => {
          const { v, err } = parse(side);
          return (
            <section key={side} aria-label={JSON_TITLE[side]} className="flex min-w-0 flex-col gap-2">
              <h3 className="text-[14px] font-semibold text-fg">{JSON_TITLE[side]}</h3>
              <RawJsonEditor label={`${JSON_TITLE[side]} JSON`} text={text[side]} onText={(t) => setText(side, t)}
                error={err} className="h-[48vh] text-[12px]" />
              <div className="flex flex-wrap items-center gap-2">
                <RawJsonActions onReformat={() => { if (v) setText(side, prettyJson(v)); }} reformatDisabled={!v}
                  onSave={() => void store(side)} saveDisabled={!v || busy || moved || !canEdit(state)} busy={busy}
                  saveLabel={JSON_SAVE[side]} busyLabel="Saving…" />
              </div>
            </section>
          );
        })}
      </div>
      {serverError && <div className="mt-3 whitespace-pre-wrap text-[12px] text-err">{serverError}</div>}
      <AllSettings rows={settingRows(cfg.reference, state.checkpoint, state.draft)} />
    </IfModal>
  );
}

const SETTING_COLS = ["Setting", "Default", "Live", "Draft", "Allowed", "What it does", "Where"] as const;
const CELL = cn(IF_TABLE.td, "px-3 py-2 align-top text-[12px]");
const CODE = cn(CELL, "break-all font-mono");

function AllSettings({ rows }: { rows: SettingRow[] }) {
  if (rows.length === 0) return null;
  return (
    <section className="mt-6 flex min-w-0 flex-col gap-2">
      <h3 className="text-[14px] font-semibold text-fg">All settings</h3>
      <IfHelp>
        Every key the JSON takes: its default, the values it accepts and what it does. &quot;Changed&quot; marks a draft value
        that differs from the Live one.
      </IfHelp>
      <div className="max-w-full overflow-x-auto rounded-lg border border-border">
        <table aria-label="All settings" className={cn(IF_TABLE.table, "min-w-[1120px]")}>
          <thead>
            <tr>
              {SETTING_COLS.map((c) => (
                <th key={c} scope="col" className={cn(IF_TABLE.th, IF_TABLE.thDivider, "h-10 px-3 text-[12px]")}>{c}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => (
              <tr key={r.key} className={IF_TABLE.row}>
                <td className={cn(CELL, "whitespace-nowrap font-mono")}>{r.key}</td>
                <td className={cn(CODE, "w-[160px] text-muted")}>{r.def}</td>
                <td className={cn(CODE, "w-[160px]")}>{r.live}</td>
                <td className={cn(CODE, "w-[180px]")}>
                  {r.value}
                  {r.changed && <Badge color="warn" className="ml-1.5 font-sans">Changed</Badge>}
                </td>
                <td className={cn(CELL, "w-[160px] text-muted")}>{r.allowed}</td>
                <td className={CELL}>{r.about}</td>
                <td className={cn(CELL, "whitespace-nowrap", r.where === "JSON" && "text-muted")}>{r.where}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}
