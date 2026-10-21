"use client";

/**
 * TemplateDraftEditor — the one draft editor behind both template kinds:
 *   • `welcome` → the OF welcome slot (`reply_on_subscribe`).
 *   • `reply`   → a local saved reply (/admin/saved-replies/*), saved through
 *     `useSavedReplyEditor` (Growth > Scripts).
 *
 * The editor is identical for both kinds; `draft.kind` hides the reply-only
 * controls (title, GIF, tags, FREE/PPV tiles, script). The host owns the draft
 * and the save; this file owns the form, its pickers and the helpers both
 * hosts share.
 */

import { useState, type Dispatch, type SetStateAction } from "react";
import { Library } from "lucide-react";

import { VaultPicker } from "@/components/chat/VaultPicker";
import { TagCreatorsPicker, TaggedCreatorChips, type TaggedCreatorChoice } from "@/components/chat/TagCreatorsPicker";
import { EmojiPickerButton, EmojiQuickRow, insertAtCursor } from "@/components/chat/EmojiBar";
import { GifPickerButton, GifPickerStrip, type PickedGif } from "@/components/chat/GifPicker";
import { Button, Input, Textarea } from "@/components/ui/primitives";
import { EXTRA_LABEL } from "@/lib/openinflowwwwExtras";
import { RelayError, type SavedReply, type VaultMedia } from "@/lib/relay";
import { proxyImage } from "@/lib/mediaUrl";
import { useSensitiveHits } from "@/lib/sensitiveWords";
import { priceNote } from "@/lib/sendGuards";
import { SensitiveWordWarning } from "@/components/chat/SensitiveWordWarning";
import { cn } from "@/lib/utils";

/** Pull OF's `error.message` out of the relay's wrapped 4xx/5xx body so
 *  the editor can show a human reason instead of just "HTTP 400". */
export function extractError(err: unknown): string {
  if (err instanceof RelayError) {
    const body = err.body as { detail?: { upstream_body?: string } } | undefined;
    const raw = body?.detail?.upstream_body;
    if (typeof raw === "string") {
      try {
        const parsed = JSON.parse(raw) as { error?: { message?: string } };
        if (parsed?.error?.message) return parsed.error.message;
      } catch { /* fall through */ }
    }
    return `HTTP ${err.status} — ${err.message}`;
  }
  return (err as Error)?.message || "unknown error";
}

type DraftKind = "welcome" | "reply";

export interface TemplateDraft {
  kind: DraftKind;
  /** Welcome IDs are OF strings; reply IDs are local-DB numeric. */
  id: string | number | null;
  title: string;
  text: string;
  price: string;
  lockedText: boolean;
  attached: VaultMedia[];
  /** Vault ids inside `attached` that ride along UNLOCKED when price > 0. */
  previews: number[];
  /** Creators to @-tag on send. Reply-only — OF welcome templates can't
   *  carry userTags, so the welcome editor keeps this empty. */
  taggedCreators: TaggedCreatorChoice[];
  /** Optional GIF on this template. Reply-only — OF welcome templates
   *  don't carry GIFs through the welcome slot. */
  gif: PickedGif | null;
  /** Script grouping (reply-only). When both `scriptId` and `scriptStep`
   *  are set, the chat composer surfaces this template's successor (same
   *  `scriptId`, `scriptStep + 1`) as a one-tap suggestion after this
   *  template fires. Empty `scriptId` opts out of the script flow. */
  scriptId: string;
  scriptStep: string;
  /** Growth > Scripts' tags and internal notes (reply-only). */
  tags: string[];
  notes: string;
}

export const EMPTY_REPLY: TemplateDraft = {
  kind: "reply",
  id: null,
  title: "",
  text: "",
  price: "",
  lockedText: false,
  attached: [],
  previews: [],
  taggedCreators: [],
  gif: null,
  scriptId: "",
  scriptStep: "",
  tags: [],
  notes: "",
};

/** Phone-only: the draft editor mounts at the TOP of the card, so tapping
 *  Edit on a row far down the list looks like nothing happened. Bail out
 *  at >=768px so desktop scroll behaviour is exactly what it is today. */
export function revealDraft() {
  if (typeof window === "undefined") return;
  if (window.matchMedia("(min-width: 768px)").matches) return;
  requestAnimationFrame(() => {
    document.getElementById("tpl-draft")?.scrollIntoView({ block: "nearest", behavior: "smooth" });
  });
}

/** Growth > Scripts' editor fields (`docs/infloww-layouts/growth-scripts.md` #73 to #79): Name required at 64
 *  characters, Text at 6500, a priced script at least $3. */
export const SCRIPT_NAME_MAX = 64;
export const SCRIPT_TEXT_MAX = 6500;
/** The tag name modal's limit (#81) and the notes field's (#79). */
export const SCRIPT_TAG_MAX = 32;
export const SCRIPT_NOTES_MAX = 256;

/** The script editor's "Tags" (#74): several, "Select or create a tag". Enter or a comma adds the typed name; the
 *  list offers the Creator's existing tags. */
function ScriptTagsField({
  tags, options, onChange,
}: {
  tags: string[];
  options: string[];
  onChange: (next: string[]) => void;
}) {
  const [text, setText] = useState("");
  const add = (raw: string) => {
    const name = raw.trim().slice(0, SCRIPT_TAG_MAX);
    if (name && !tags.includes(name)) onChange([...tags, name]);
    setText("");
  };
  return (
    <div className="flex flex-wrap items-center gap-1.5 rounded-md border border-border px-2 py-1 min-h-9">
      {tags.map((t) => (
        <span key={t} className="inline-flex items-center gap-1 rounded bg-bg-elev-1 px-1.5 py-0.5 text-xs">
          {t}
          <button
            type="button"
            aria-label={`Remove tag ${t}`}
            onClick={() => onChange(tags.filter((x) => x !== t))}
            className="text-fg-dim hover:text-fg"
          >
            ×
          </button>
        </span>
      ))}
      <input
        id="script-tags"
        type="text"
        list="script-tag-options"
        value={text}
        maxLength={SCRIPT_TAG_MAX}
        placeholder={tags.length ? "" : "Select or create a tag"}
        onChange={(e) => {
          const v = e.target.value;
          // Picking from the list fills the whole name at once: take it as chosen.
          if (options.includes(v)) add(v);
          else setText(v);
        }}
        onKeyDown={(e) => {
          if (e.key === "Enter" || e.key === ",") {
            e.preventDefault();
            add(text);
          } else if (e.key === "Backspace" && !text && tags.length) {
            onChange(tags.slice(0, -1));
          }
        }}
        onBlur={() => text.trim() && add(text)}
        className="flex-1 min-w-[8rem] bg-transparent text-sm outline-none"
      />
      <datalist id="script-tag-options">
        {options.filter((o) => !tags.includes(o)).map((o) => <option key={o} value={o} />)}
      </datalist>
    </div>
  );
}

const FIELD_LABEL = "block text-sm mb-1";

export function TemplateDraftEditor({
  draft, setDraft, accountId, saving, saveErr, onSave, script = false, tagOptions = [], sequenceOptions = [],
}: {
  draft: TemplateDraft;
  setDraft: Dispatch<SetStateAction<TemplateDraft | null>>;
  accountId: string | null;
  saving: boolean;
  saveErr: string | null;
  onSave: () => void;
  /** Growth > Scripts lays the reply editor out as the bundle's script editor (`ScriptEditModal`, index.9f50f370.js
   *  @9318571), inside its own modal: no frame and no title row of its own, the capture's field labels and limits,
   *  Tags and Internal notes (stored on the saved reply), and Cancel and OK in a footer. The editor's own
   *  controls follow the bundle: the emoji row stays (the Text field's `Emojis$2`), the media tiles take the
   *  bundle's "Paid" checks and PPV count, Tag other Creators moves after Media (#78), and GIF and "Lock text
   *  behind price", which the bundle's script lacks, carry the Inflowwww extra label. Sequence and Step place the
   *  script in a sequence: the bundle builds sequences in a separate editor (`AddSequence`); here a sequence is
   *  the scripts sharing a name, ordered by step, so the fields carry the Inflowwww extra label. */
  script?: boolean;
  /** Scripts: the Creator's existing tags and sequences, offered in the Tags and Sequence fields. */
  tagOptions?: string[];
  sequenceOptions?: string[];
}) {
  const [pickerOpen, setPickerOpen] = useState(false);
  const [gifPickerOpen, setGifPickerOpen] = useState(false);
  const priceNum = Number(draft.price);
  const belowMin = script && priceNote(priceNum) !== null;
  // Growth > Sensitive words: Infloww's script editor shows the hits under the
  // text and disables Save until it is clean.
  const sensitiveHits = useSensitiveHits(draft.text, accountId);
  const saveDisabled =
    !draft.text.trim() || saving || sensitiveHits.length > 0 ||
    (script && (!draft.title.trim() || belowMin || (!!draft.scriptId.trim() && !/^\d+$/.test(draft.scriptStep.trim()))));
  const saveButton = (
    <Button size="sm" onClick={onSave} disabled={saveDisabled}>
      {/* The bundle's footer is antd Modal's Cancel / OK (`onOk`, @9318571). */}
      {script ? "OK" : saving ? "Saving…" : "Save"}
    </Button>
  );

  const tagCreators = (
    <>
      <TagCreatorsPicker
        accountId={accountId}
        selected={draft.taggedCreators}
        onChange={(next) => setDraft((d) => d && { ...d, taggedCreators: next })}
      />
      {draft.taggedCreators.length > 0 && (
        <div className="flex-1 min-w-0">
          <TaggedCreatorChips
            selected={draft.taggedCreators}
            onChange={(next) => setDraft((d) => d && { ...d, taggedCreators: next })}
          />
        </div>
      )}
    </>
  );
  const togglePreview = (id: number) =>
    setDraft((d) => {
      if (!d) return d;
      const has = d.previews.includes(id);
      return { ...d, previews: has ? d.previews.filter((x) => x !== id) : [...d.previews, id] };
    });
  const paidCount = draft.attached.filter((m) => !draft.previews.includes(m.id)).length;

  const priceRow = (
    <div className="flex items-center gap-4 flex-wrap">
      <label className="text-xs text-fg-dim flex items-center gap-2">
        {script ? "Message price" : "Price $"}
        <Input
          type="text"
          inputMode="decimal"
          value={draft.price}
          onChange={(e) => setDraft((d) => d && { ...d, price: e.target.value })}
          className="w-24 py-1 text-sm"
          placeholder="0.00"
        />
      </label>
      {/* The bundle's Media line (`Media$2`, index.9f50f370.js @9257668, @9257783): "N of M selected as PPV", then
       *  "All", which marks every tile Paid or none. Shown, as the tiles' checks are, once the script is priced. */}
      {script && Number(draft.price) > 0 && draft.attached.length > 0 && (
        <span className="text-xs text-fg-dim flex items-center gap-2">
          <span><span className="text-accent">{paidCount}</span> of {draft.attached.length} selected as PPV</span>
          <span aria-hidden>|</span>
          <label className="flex items-center gap-1 cursor-pointer select-none">
            <input
              type="checkbox"
              checked={paidCount === draft.attached.length}
              onChange={(e) =>
                setDraft((d) => d && { ...d, previews: e.target.checked ? [] : d.attached.map((m) => m.id) })
              }
              className="accent-accent"
            />
            All
          </label>
        </span>
      )}
      <label
        title={script ? EXTRA_LABEL : undefined}
        className="text-xs text-fg-dim flex items-center gap-1.5 cursor-pointer select-none"
      >
        <input
          type="checkbox"
          checked={draft.lockedText}
          disabled={!(Number(draft.price) > 0)}
          onChange={(e) => setDraft((d) => d && { ...d, lockedText: e.target.checked })}
          className="accent-accent"
        />
        Lock text behind price
      </label>
      {!script && <div className="ml-auto flex items-center gap-2">{saveButton}</div>}
    </div>
  );

  return (
    <>
      <div
        id="tpl-draft"
        className={script ? "space-y-3" : "border border-accent/40 rounded-lg p-3 mb-4 space-y-3 bg-bg/40"}
      >
        {!script && (
          <div className="flex items-center justify-between">
            <div className="text-sm font-medium">
              {draft.id != null
                ? (draft.kind === "welcome" ? "Edit welcome message" : "Edit saved reply")
                : (draft.kind === "welcome" ? "New welcome message" : "New saved reply")}
              {draft.kind === "welcome" && (
                <span className="ml-2 text-[10px] px-1.5 py-0.5 rounded bg-accent/15 text-accent">👋 welcome (OF)</span>
              )}
              {draft.kind === "reply" && (
                <span className="ml-2 text-[10px] px-1.5 py-0.5 rounded bg-bg-elev-1 text-fg-dim">local</span>
              )}
            </div>
            <button
              type="button"
              onClick={() => setDraft(null)}
              className="text-xs text-fg-dim hover:text-fg"
            >
              Cancel
            </button>
          </div>
        )}

        {script && (
          <>
            <div>
              <label htmlFor="script-name" className={FIELD_LABEL}>
                Name<span aria-hidden className="text-err ml-0.5">*</span>
              </label>
              <Input
                id="script-name"
                type="text"
                required
                maxLength={SCRIPT_NAME_MAX}
                value={draft.title}
                onChange={(e) => setDraft((d) => d && { ...d, title: e.target.value })}
                placeholder="Enter name"
                className="text-sm"
              />
            </div>
            <div>
              <label htmlFor="script-tags" className={FIELD_LABEL}>Tags</label>
              <ScriptTagsField
                tags={draft.tags}
                options={tagOptions}
                onChange={(tags) => setDraft((d) => d && { ...d, tags })}
              />
            </div>
            <div title={EXTRA_LABEL} className="flex items-end gap-2">
              <div className="flex-1">
                <label htmlFor="script-sequence" className={FIELD_LABEL}>Sequence</label>
                <Input
                  id="script-sequence"
                  type="text"
                  list="script-sequence-options"
                  maxLength={SCRIPT_NAME_MAX}
                  value={draft.scriptId}
                  onChange={(e) => setDraft((d) => d && { ...d, scriptId: e.target.value })}
                  placeholder="None"
                  className="text-sm"
                />
                <datalist id="script-sequence-options">
                  {sequenceOptions.map((o) => <option key={o} value={o} />)}
                </datalist>
              </div>
              <div className="w-20">
                <label htmlFor="script-step" className={FIELD_LABEL}>Step</label>
                <Input
                  id="script-step"
                  type="text"
                  inputMode="numeric"
                  value={draft.scriptStep}
                  onChange={(e) =>
                    setDraft((d) => d && { ...d, scriptStep: e.target.value.replace(/[^\d]/g, "") })
                  }
                  disabled={!draft.scriptId.trim()}
                  placeholder="1"
                  className="text-sm"
                />
              </div>
            </div>
            {draft.scriptId.trim() && !/^\d+$/.test(draft.scriptStep.trim()) && (
              <div className="text-xs text-err -mt-2">Enter a step</div>
            )}
          </>
        )}

        {draft.kind === "reply" && !script && (
          <Input
            type="text"
            value={draft.title}
            onChange={(e) => setDraft((d) => d && { ...d, title: e.target.value })}
            placeholder="Title (optional — shows in picker)"
            className="text-sm"
          />
        )}

        <div className="space-y-1.5">
          {script && (
            <label htmlFor="reply-textarea" className={FIELD_LABEL}>
              Text<span aria-hidden className="text-err ml-0.5">*</span>
            </label>
          )}
          <Textarea
            id={draft.kind === "reply" ? "reply-textarea" : "welcome-textarea"}
            value={draft.text}
            onChange={(e) => setDraft((d) => d && { ...d, text: e.target.value })}
            required={script}
            maxLength={script ? SCRIPT_TEXT_MAX : undefined}
            placeholder={script ? "Enter your message..." : "Template text"}
            className="min-h-24 text-sm font-sans"
          />
          <SensitiveWordWarning hits={sensitiveHits} />
          {/* Editor toolbar — emoji is universal; tag-creators only for
           *  local replies since OF welcome templates don't carry
           *  userTags on the template object itself. */}
          <div className="flex items-center gap-1.5 flex-wrap">
            <EmojiQuickRow
              onInsert={(em) => {
                const ta = document.getElementById(
                  draft.kind === "reply" ? "reply-textarea" : "welcome-textarea",
                ) as HTMLTextAreaElement | null;
                if (ta) {
                  insertAtCursor(ta, draft.text, em, (s) =>
                    setDraft((d) => d && { ...d, text: s }),
                  );
                } else {
                  setDraft((d) => d && { ...d, text: (d.text || "") + em });
                }
              }}
            />
            <EmojiPickerButton
              align="left"
              onInsert={(em) => {
                const ta = document.getElementById(
                  draft.kind === "reply" ? "reply-textarea" : "welcome-textarea",
                ) as HTMLTextAreaElement | null;
                if (ta) {
                  insertAtCursor(ta, draft.text, em, (s) =>
                    setDraft((d) => d && { ...d, text: s }),
                  );
                } else {
                  setDraft((d) => d && { ...d, text: (d.text || "") + em });
                }
              }}
            />
            {draft.kind === "reply" && (
              // The bundle's script carries no GIF, so on Scripts it is labelled.
              <span title={script ? EXTRA_LABEL : undefined} className="contents">
                <GifPickerButton
                  open={gifPickerOpen}
                  onToggle={() => setGifPickerOpen((v) => !v)}
                />
              </span>
            )}
            {draft.kind === "reply" && !script && tagCreators}
          </div>
          {draft.kind === "reply" && gifPickerOpen && (
            <GifPickerStrip
              accountId={accountId}
              onClose={() => setGifPickerOpen(false)}
              onPick={(g) => {
                setDraft((d) => d && { ...d, gif: g });
                setGifPickerOpen(false);
              }}
            />
          )}
          {draft.kind === "reply" && draft.gif && (
            <div className="flex items-center gap-2 bg-bg/60 border border-border rounded-md px-2 py-2">
              <span className="text-[10px] uppercase tracking-wide text-fg-dim">gif</span>
              <div className="relative w-14 h-14 rounded-md overflow-hidden border border-border bg-bg-elev-1">
                {/* eslint-disable-next-line @next/next/no-img-element */}
                <img
                  src={draft.gif.thumbUrl || draft.gif.fullUrl}
                  alt={draft.gif.title || "GIF"}
                  className="w-full h-full object-cover"
                />
              </div>
              <button
                type="button"
                onClick={() => setDraft((d) => d && { ...d, gif: null })}
                className="text-[11px] text-fg-dim hover:text-fg ml-auto"
              >
                Remove GIF
              </button>
            </div>
          )}
        </div>

        {script && <div className={FIELD_LABEL}>Media</div>}
        {script && priceRow}
        <div className="flex items-center gap-2 flex-wrap">
          {draft.attached.map((m) => {
            const rawThumb =
              m.files?.thumb?.url ||
              m.files?.squarePreview?.url ||
              m.files?.preview?.url ||
              null;
            const thumb = proxyImage(rawThumb, accountId);
            const isPpv = Number(draft.price) > 0;
            const isFree = isPpv && draft.previews.includes(m.id);
            return (
              <div
                key={m.id}
                className="relative w-14 h-14 rounded-md overflow-hidden border border-border bg-bg-elev-1 group"
              >
                {thumb ? (
                  <img src={thumb} alt="" loading="lazy" decoding="async" className="w-full h-full object-cover" />
                ) : (
                  <div className="w-full h-full grid place-items-center text-[10px] text-fg-dim">
                    {m.type}
                  </div>
                )}
                {/* FREE/PPV toggle — click to flip whether this tile is
                 *  unlocked when the template fires at price > 0. The
                 *  reply editor only; OF welcome templates ignore
                 *  per-media preview flags. */}
                {/* Scripts: the bundle's tile check (`MediaItem$4`, index.9f50f370.js @9174157, "Paid" @9175174),
                 *  checked while the tile is locked behind the price. */}
                {isPpv && script && (
                  <label className="absolute bottom-0 left-0 right-0 flex items-center justify-center gap-1 bg-black/60 py-0.5 text-[9px] font-bold text-white cursor-pointer">
                    <input
                      type="checkbox"
                      checked={!isFree}
                      onChange={() => togglePreview(m.id)}
                      className="w-2.5 h-2.5 accent-accent"
                    />
                    Paid
                  </label>
                )}
                {isPpv && draft.kind === "reply" && !script && (
                  <button
                    type="button"
                    onClick={() => togglePreview(m.id)}
                    title={isFree ? "Unlocked preview — click to lock" : "PPV-locked — click to unlock as preview"}
                    className={cn(
                      "absolute bottom-0 left-0 right-0 text-[9px] font-bold leading-tight text-white py-0.5 text-center",
                      isFree ? "bg-fg-dim" : "bg-err",
                    )}
                  >
                    {isFree ? "FREE" : "PPV"}
                  </button>
                )}
                <button
                  type="button"
                  onClick={() =>
                    setDraft((d) => {
                      if (!d) return d;
                      return {
                        ...d,
                        attached: d.attached.filter((x) => x.id !== m.id),
                        previews: d.previews.filter((x) => x !== m.id),
                      };
                    })
                  }
                  className="absolute top-0.5 right-0.5 w-4 h-4 max-md:w-6 max-md:h-6 rounded-full bg-black/70 text-white grid place-items-center text-[10px] max-md:text-xs opacity-80 hover:opacity-100"
                  aria-label="Remove attachment"
                >
                  ✕
                </button>
              </div>
            );
          })}
          <button
            type="button"
            onClick={() => setPickerOpen(true)}
            disabled={!accountId}
            className="w-14 h-14 rounded-md border border-dashed border-border bg-transparent hover:bg-bg-elev-1 text-fg-dim hover:text-fg grid place-items-center text-xs gap-0.5"
            title="Attach media from vault"
          >
            <Library size={18} aria-hidden />
            <span aria-hidden>+</span>
          </button>
        </div>
        {draft.kind === "reply" && !script && Number(draft.price) > 0 && draft.attached.length > 0 && (
          <div className="text-[10px] text-fg-dim -mt-1">
            Click FREE/PPV on a tile to choose which media unlocks before the fan pays.
            {draft.previews.length === 0 && " · all locked (fan pays to see any)"}
          </div>
        )}

        {/* Script / step groups replies into a sequence; the script modal shows it as Sequence and Step above. */}
        {draft.kind === "reply" && !script && (
          <div className="flex items-center gap-2 flex-wrap text-xs text-fg-dim">
            <span title="Group templates into an ordered sequence. The chat composer suggests the next step after this one fires.">
              Script
            </span>
            <Input
              type="text"
              value={draft.scriptId}
              onChange={(e) => setDraft((d) => d && { ...d, scriptId: e.target.value })}
              placeholder="name (e.g. welcome-flow)"
              className="w-44 py-1 text-sm"
            />
            <span>step</span>
            <Input
              type="text"
              inputMode="numeric"
              value={draft.scriptStep}
              onChange={(e) =>
                setDraft((d) =>
                  d && { ...d, scriptStep: e.target.value.replace(/[^\d]/g, "") },
                )
              }
              placeholder="1"
              className="w-16 py-1 text-sm"
              disabled={!draft.scriptId.trim()}
            />
            {draft.scriptId.trim() && !/^\d+$/.test(draft.scriptStep.trim()) && (
              <span className="text-warn">step needed to enable the next-step bubble</span>
            )}
          </div>
        )}

        {!script && priceRow}
        {belowMin && <div className="text-xs text-err -mt-2">Minimum $3 USD</div>}

        {/* #78: the bundle's "Tag other Creator(s)" is its own field after Media. */}
        {script && <div className="flex items-center gap-1.5 flex-wrap">{tagCreators}</div>}

        {script && (
          <>
            <div>
              <label htmlFor="script-notes" className={FIELD_LABEL}>Internal notes</label>
              <Input
                id="script-notes"
                type="text"
                maxLength={SCRIPT_NOTES_MAX}
                value={draft.notes}
                onChange={(e) => setDraft((d) => d && { ...d, notes: e.target.value })}
                className="text-sm"
              />
            </div>
            <div className="flex items-center justify-end gap-2 pt-1">
              <Button size="sm" variant="secondary" onClick={() => setDraft(null)}>Cancel</Button>
              {saveButton}
            </div>
          </>
        )}

        {saveErr && (
          <div className="text-[11px] px-2.5 py-1.5 rounded-md border bg-err/10 border-err/30 text-err">
            ⚠ Save failed: {saveErr}
          </div>
        )}
      </div>

      {/* Portalled modal: renders nothing until opened, so where it sits in
       *  the tree changes no layout. */}
      <VaultPicker
        open={pickerOpen}
        onClose={() => setPickerOpen(false)}
        accountId={accountId}
        initialSelectedIds={draft.attached.map((m) => m.id)}
        onConfirm={(picked) => {
          // Fresh-claim dicts (negative ids) are ephemeral and useless for
          // persistence — drop them. The numeric vault ids work for both
          // OF welcome msg and local saved replies.
          const vaultOnly = picked.filter((m) => m.id > 0);
          const stillAttached = new Set(vaultOnly.map((m) => m.id));
          setDraft((d) =>
            d && {
              ...d,
              attached: vaultOnly,
              previews: d.previews.filter((id) => stillAttached.has(id)),
            },
          );
        }}
      />
    </>
  );
}

export function MediaStrip({
  media, accountId,
}: {
  media: Array<{ id: number; type?: string; files?: SavedReply["media"][number]["files"] }>;
  accountId: string | null;
}) {
  return (
    <div className="flex items-center gap-1.5 mt-2 flex-wrap">
      {media.slice(0, 6).map((m) => {
        const rawThumb =
          m.files?.thumb?.url ||
          m.files?.squarePreview?.url ||
          m.files?.preview?.url ||
          null;
        const thumb = proxyImage(rawThumb, accountId);
        return (
          <div key={m.id} className="w-10 h-10 rounded border border-border overflow-hidden bg-bg-elev-1">
            {thumb ? (
              <img src={thumb} alt="" loading="lazy" decoding="async" className="w-full h-full object-cover" />
            ) : (
              <div className="w-full h-full grid place-items-center text-[9px] text-fg-dim">
                {m.type ?? "?"}
              </div>
            )}
          </div>
        );
      })}
      {media.length > 6 && (
        <span className="text-[10px] text-fg-dim">+{media.length - 6}</span>
      )}
    </div>
  );
}
