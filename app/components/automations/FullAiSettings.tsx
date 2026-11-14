"use client";

/**
 * Full AI Chat's settings column (spec phase-03a, 03b): ten controls in a list named "Settings":
 *   1. on/off, the Off / Shadow switch over the `full_ai_chat` rule (the page wires its one write);
 *   2. LLM keys: whether NanoGPT and OpenRouter are set (never a value or hint), linking to the agency keys form;
 *   3. reply speed ("0-2 min" / "0-15-60"), 4. Human style (every `style` layer; mixed when they differ), 5. Typos
 *   (the typos layer alone), 6. Writer (moves a model to the front of `writers`), 7. GIFs;
 *   8. Sell, 9. Content folders, 10. Prepare content (`FullAiSellSettings.tsx`, ticket 49).
 * Controls 3-9 edit the draft config and store it at once (`useFullAiConfig.edit`); the Test chat's Send waits meanwhile.
 * Under them: Save (draft → checkpoint), Roll back (swap checkpoint and previous), JSON (the full draft in the house
 * raw JSON editor, validated by the server on save), the field errors, and on a stale rev a reload message. Reload
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
  canEdit, canRollback, canSave, DEFAULT_SPEED, humanStyle, humanStylePatch, layersOff, REPLY_SPEEDS, styleLayers,
  typosPatch, writerPatch, type FullAiConfig, type TestChatState,
} from "@/components/automations/fullAiTestChat";
import { RawJsonModal } from "@/components/automations/RawJsonModal";
import { IfButton, IfNativeSelect, IfSegmented } from "@/components/ui/infloww";
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
        <IfButton disabled={off} onClick={() => setJsonOpen(true)}>JSON</IfButton>
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

      {jsonOpen && draft && (
        <ConfigJson draft={draft} state={state} cfg={cfg} onClose={() => setJsonOpen(false)} />
      )}
    </div>
  );
}

/** The Writer: the first of `writers`; picking one moves it to the front, the rest stay as fallbacks in order. */
function WriterRow({ draft, off, cfg }: { draft: FullAiConfig | null; off: boolean; cfg: FullAiConfigApi }) {
  const writers = draft?.writers ?? [];
  const options = [...new Set([...writers.slice(0, 1), ...cfg.writerModels])];
  return (
    <div className={ROW}>
      <div className="flex min-h-14 flex-wrap items-center justify-between gap-2 py-2">
        <div className="min-w-0">
          <div className="text-[14px] text-fg">Writer</div>
          <div className="mt-0.5 text-[12px] text-muted">
            {writers.length > 1 ? `Then: ${writers.slice(1).join(", ")}` : "No fallback"}
          </div>
        </div>
        <IfNativeSelect aria-label="Writer" value={writers[0] ?? ""} disabled={off || options.length === 0}
          onChange={(e) => cfg.edit(writerPatch(draft, e.target.value))}>
          {options.map((m) => <option key={m} value={m}>{m}</option>)}
        </IfNativeSelect>
      </div>
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

/** The full draft as raw JSON. Bad JSON never leaves the box; the server checks the keys and answers field errors. */
function ConfigJson({ draft, state, cfg, onClose }: {
  draft: FullAiConfig; state: TestChatState; cfg: FullAiConfigApi; onClose: () => void;
}) {
  const [text, setText] = useState(() => pretty(draft));
  let parsed: Record<string, unknown> | null = null;
  let parseError: string | null = null;
  try { parsed = parseJsonObject(text, "The config", '{"gifs": true}'); } catch (e) { parseError = errText(e); }

  return (
    <RawJsonModal
      name="Full AI config (draft)"
      subtitle="Every key of the draft. Unknown keys are refused."
      text={text}
      onText={setText}
      error={parseError ?? (state.stale ? STALE : state.errors.length > 0 ? state.errors.join("\n") : null)}
      busy={state.savingDraft}
      onReformat={() => { if (parsed) setText(pretty(parsed)); }}
      onSave={async () => {
        if (parsed && await cfg.putDraft(parsed)) onClose();
      }}
      onClose={onClose}
    />
  );
}
