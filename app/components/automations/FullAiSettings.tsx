"use client";

/**
 * Full AI Chat's settings column (spec phase-03a, 03b): ten controls in a list named "Settings":
 *   1. on/off, the Off / Shadow switch over the `full_ai_chat` rule (the page wires its one write);
 *   2. LLM keys: whether NanoGPT and OpenRouter are set (never a value or hint), linking to the agency keys form;
 *   3. reply speed ("0-2 min" / "0-15-60"), 4. Human style (every `style` layer; mixed when they differ), 5. Typos
 *   (the typos layer alone), 6. Writers (a checklist over `writers`: tick / untick, "Make Writer" moves one first), 7. GIFs;
 *   8. Sell, 9. Content folders, 10. Prepare content (`FullAiSellSettings.tsx`, ticket 49).
 * Controls 3-9 edit the draft config and store it at once (`useFullAiConfig.edit`); the Test chat's Send waits meanwhile.
 * Under them: Save (draft → checkpoint), Roll back (swap checkpoint and previous), JSON (checkpoint and draft side by
 * side, each editable and stored on its own, validated by the server), the field errors, and on a stale rev a reload message. Reload
 * shows with either: it reads the stored config again, the way back from a refused edit or a failed read.
 * A draft stored elsewhere (the assistant's Apply) while an edit is unsaved raises the Keep mine / Take theirs bar on
 * top (ticket 57); controls, Save and Send wait until one is picked.
 * State lives in the Test chat reducer (`fullAiTestChat.ts`); this file renders and calls the hook.
 */

import Link from "next/link";
import { useState } from "react";

import { ROW, SwitchRow } from "@/components/automations/automationPage";
import { ContentFoldersRow, PrepareRow } from "@/components/automations/FullAiSellSettings";
import {
  canEdit, canRollback, canSave, DEFAULT_SPEED, humanStyle, humanStylePatch, layersOff, MAX_WRITERS, REPLY_SPEEDS, styleLayers,
  toggleWriterPatch, typosPatch, writerPatch, type FullAiConfig, type TestChatState,
} from "@/components/automations/fullAiTestChat";
import { IfButton, IfHelp, IfModal, IfSegmented, IfTextArea } from "@/components/ui/infloww";
import { type FullAiConfigApi } from "@/hooks/useFullAiConfig";
import { useTenantKeys } from "@/hooks/useTenantKeys";
import { errText } from "@/lib/errText";
import { parseJsonObject } from "@/lib/rawJsonReducer";

const STALE = "Someone saved this config meanwhile. Reload.";
const KEY_ROWS = [{ id: "nanogpt", label: "NanoGPT" }, { id: "openrouter", label: "OpenRouter" }] as const;

export interface PowerSwitch {
  on: boolean;
  disabled: boolean;
  loading: boolean;
  onChange: (on: boolean) => void;
}

export function FullAiSettings({ state, cfg, power, accountId }: {
  state: TestChatState; cfg: FullAiConfigApi; power: PowerSwitch; accountId: string;
}) {
  const [jsonOpen, setJsonOpen] = useState(false);
  const draft = state.draft;
  const editable = canEdit(state);
  const off = !editable;

  return (
    <div className="space-y-3">
      {state.conflict && <ConflictBar cfg={cfg} />}
      <ul aria-label="Settings" className="space-y-2">
        <li>
          <SwitchRow label="Full AI Chat" hint={power.on ? "Shadow" : "Off"} checked={power.on} onChange={power.onChange}
            disabled={power.disabled} loading={power.loading} />
        </li>
        <li><KeysRow /></li>
        <li className={ROW}>
          <div className="flex min-h-14 flex-wrap items-center justify-between gap-2 py-2">
            <span className="text-[14px] text-fg">Reply speed</span>
            <IfSegmented aria-label="Reply speed" value={draft?.reply_speed ?? DEFAULT_SPEED}
              options={REPLY_SPEEDS.map((o) => ({ ...o, disabled: off }))}
              onChange={(reply_speed) => cfg.edit({ reply_speed })} />
          </div>
        </li>
        <li>
          <SwitchRow label="Human style" disabled={off} checked={humanStyle(draft) !== "off"}
            hint={humanStyle(draft) === "mixed" ? `Mixed: ${layersOff(draft)} off. Tap for all off.`
              : "Lowercase, short bubbles, light typos. Off: formal."}
            onChange={(on) => cfg.edit(humanStylePatch(on))} />
        </li>
        <li>
          <SwitchRow label="Typos" hint="Thumb slips and a *fix bubble." checked={styleLayers(draft).typos} disabled={off}
            onChange={(on) => cfg.edit(typosPatch(draft, on))} />
        </li>
        <li><WriterRow draft={draft} off={off} cfg={cfg} /></li>
        <li>
          <SwitchRow label="GIFs" checked={draft?.gifs === true} disabled={off} onChange={(gifs) => cfg.edit({ gifs })} />
        </li>
        <li>
          <SwitchRow label="Sell" hint="Offer PPVs from the content folders. Off: the AI never sells." checked={draft?.sell_on === true}
            disabled={off} onChange={(sell_on) => cfg.edit({ sell_on })} />
        </li>
        <li><ContentFoldersRow accountId={accountId} draft={draft} off={off} cfg={cfg} /></li>
        <li><PrepareRow accountId={accountId} /></li>
      </ul>

      <div className="flex flex-wrap items-center gap-2">
        <IfButton variant="primary" disabled={!canSave(state)} onClick={cfg.save}>Save</IfButton>
        <IfButton disabled={!canRollback(state)} onClick={cfg.rollback}>Roll back</IfButton>
        <IfButton disabled={off} onClick={() => setJsonOpen(true)}>JSON (old + new)</IfButton>
        {state.savingDraft && <span role="status" className="text-[12px] text-muted">Storing draft…</span>}
      </div>
      <p className="text-[12px] text-muted">
        Save makes the draft the checkpoint. Roll back swaps back; tap it again to undo.
      </p>

      {state.stale && <p role="alert" className="text-[12px] text-warn">{STALE}</p>}
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

      {jsonOpen && draft && <ConfigJson state={state} cfg={cfg} onClose={() => setJsonOpen(false)} />}
    </div>
  );
}

/** The Writer chain as a checklist: tick to add a model at the end, untick to drop it (1 to `MAX_WRITERS`); the first
 *  ticked is the Writer, the rest its fallbacks in order. "Make Writer" moves one to the front. */
function WriterRow({ draft, off, cfg }: { draft: FullAiConfig | null; off: boolean; cfg: FullAiConfigApi }) {
  const writers = draft?.writers ?? [];
  const options = [...new Set([...writers, ...cfg.writerModels])];
  return (
    <div className={ROW}>
      <fieldset className="space-y-1.5 py-3">
        <legend className="text-[14px] text-fg">Writers</legend>
        <p className="text-[12px] text-muted">Tick to add, untick to drop (1 to {MAX_WRITERS}). Tried in order: the first answers, the rest are fallbacks.</p>
        {options.map((m) => {
          const at = writers.indexOf(m);
          const patch = toggleWriterPatch(draft, m);
          return (
            <div key={m} className="flex min-h-9 items-center gap-2">
              <label className="flex min-w-0 flex-1 items-center gap-2 text-[14px]">
                <input type="checkbox" aria-label={m} checked={at >= 0} disabled={off || patch === null}
                  onChange={() => { if (patch) cfg.edit(patch); }} />
                <span className={at >= 0 ? "truncate text-fg" : "truncate text-muted"}>{m}</span>
                {at >= 0 && <span className="text-[12px] tabular-nums text-muted">{at === 0 ? "Writer" : `#${at + 1}`}</span>}
              </label>
              {at > 0 && (
                <IfButton variant="link" disabled={off} onClick={() => cfg.edit(writerPatch(draft, m))}>Make Writer</IfButton>
              )}
            </div>
          );
        })}
      </fieldset>
    </div>
  );
}

/** Keep mine (store the page's edit over the applied draft) or Take theirs (drop the edit, adopt it). */
function ConflictBar({ cfg }: { cfg: FullAiConfigApi }) {
  return (
    <div role="group" aria-label="Draft changed elsewhere" className="space-y-2 rounded-lg border border-warn/40 px-4 py-3">
      <p className="text-sm text-fg">The draft changed elsewhere (an assistant Apply) while you had an unsaved edit.</p>
      <div className="flex flex-wrap items-center gap-2">
        <IfButton variant="primary" onClick={cfg.keepMine}>Keep mine</IfButton>
        <IfButton onClick={cfg.takeTheirs}>Take theirs</IfButton>
      </div>
      <p className="text-xs text-muted">Keep mine stores your edit over it; Take theirs drops your edit. Send and Save wait until you pick.</p>
    </div>
  );
}

/** Set / not set per provider, from GET /admin/my-llm-keys; the hint (last characters) is never shown. */
function KeysRow() {
  const keysQ = useTenantKeys();
  const providers = keysQ.data?.providers;
  return (
    <div className={ROW}>
      <div className="flex min-h-14 flex-wrap items-center justify-between gap-2 py-2">
        <div className="min-w-0">
          <div className="text-[14px] text-fg">LLM keys</div>
          <div className="mt-0.5 flex flex-wrap gap-x-3 text-[12px] text-muted">
            {keysQ.isError ? <span className="text-err">Couldn&apos;t read the keys.</span> : KEY_ROWS.map((k) => (
              <span key={k.id}>{providers ? `${k.label} ${providers[k.id]?.set ? "set" : "not set"}` : `${k.label} …`}</span>
            ))}
          </div>
        </div>
        <Link href="/settings/ai-keys" className="text-[14px] text-accent hover:text-accent-hover">Open keys form</Link>
      </div>
    </div>
  );
}

const pretty = (v: unknown) => JSON.stringify(v, null, 2);

type JsonSide = "checkpoint" | "draft";
const JSON_TITLE: Record<JsonSide, string> = { checkpoint: "Checkpoint · old (saved)", draft: "Draft · new" };
const JSON_SAVE: Record<JsonSide, string> = { checkpoint: "Store checkpoint", draft: "Store draft" };

/** Both sides as raw JSON next to each other: Checkpoint (old) and Draft (new), each editable and stored on its own.
 *  Bad JSON never leaves its box; the server checks the keys and answers field errors. Storing the checkpoint keeps
 *  the old one as `previous` (Roll back undoes it). */
function ConfigJson({ state, cfg, onClose }: { state: TestChatState; cfg: FullAiConfigApi; onClose: () => void }) {
  const [text, setText] = useState<Record<JsonSide, string>>(
    () => ({ checkpoint: pretty(state.checkpoint ?? {}), draft: pretty(state.draft ?? {}) }));
  const busy = state.savingDraft || state.committing;
  // Escape closes only untouched boxes, and never mid-store.
  const typed = text.checkpoint !== pretty(state.checkpoint ?? {}) || text.draft !== pretty(state.draft ?? {});
  const serverError = state.stale ? STALE : state.errors.length > 0 ? state.errors.join("\n") : null;
  const parse = (side: JsonSide): { v: Record<string, unknown> | null; err: string | null } => {
    try { return { v: parseJsonObject(text[side], "The config", '{"gifs": true}'), err: null }; }
    catch (e) { return { v: null, err: errText(e) }; }
  };
  const store = async (side: JsonSide) => {
    const { v } = parse(side);
    if (v && await (side === "draft" ? cfg.putDraft(v) : cfg.putCheckpoint(v))) onClose();
  };

  return (
    <IfModal width={1200} size="editor" title="Full AI config JSON" onClose={onClose} keyboard={!busy && !typed}
      footer={<IfButton onClick={onClose}>Cancel</IfButton>}>
      <IfHelp className="-mt-3 mb-3">Old (checkpoint) left, new (draft) right: what the Test chat split-tests. Unknown keys are refused.</IfHelp>
      <div className="grid gap-4 md:grid-cols-2">
        {(["checkpoint", "draft"] as const).map((side) => {
          const { v, err } = parse(side);
          return (
            <section key={side} aria-label={JSON_TITLE[side]} className="flex min-w-0 flex-col gap-2">
              <h3 className="text-[14px] font-semibold text-fg">{JSON_TITLE[side]}</h3>
              <IfTextArea aria-label={`${JSON_TITLE[side]} JSON`} value={text[side]} spellCheck={false}
                onChange={(e) => setText((t) => ({ ...t, [side]: e.target.value }))}
                className="h-[48vh] resize-none font-mono text-[12px]" />
              {err && <div className="whitespace-pre-wrap text-[12px] text-err">{err}</div>}
              <div className="flex flex-wrap items-center gap-2">
                <IfButton variant="link" disabled={!v} onClick={() => { if (v) setText((t) => ({ ...t, [side]: pretty(v) })); }}>
                  Reformat
                </IfButton>
                <IfButton variant="primary" disabled={!v || busy} onClick={() => void store(side)}>
                  {busy ? "Storing…" : JSON_SAVE[side]}
                </IfButton>
              </div>
            </section>
          );
        })}
      </div>
      {serverError && <div className="mt-3 whitespace-pre-wrap text-[12px] text-err">{serverError}</div>}
    </IfModal>
  );
}
