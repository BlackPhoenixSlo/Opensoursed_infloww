"use client";

/**
 * ComposerToolbar — the Composer's three Infloww rows (docs/spec/
 * messages-pro-look-and-feel/phase-05-composer.md, Gap rows C1–C8,
 * Interfaces; first built by docs/spec/phase-04-composer-ppv-vault.md):
 *
 *   row 1, "Composer buttons": emoji, ⚙ emoji favourites and the quick
 *     emoji row (`quick`) at the left, then at the right the AI and Scripts
 *     slots, the "PPV" pill and the ⏱ Timed slot, under a full-width rule; no
 *     input. The "+" Extras overflow is gone (TODO.md A2, 2026-10-16): free
 *     previews sit in the PPV row, the "at" presets in ⏱, the quick emojis here.
 *   row 2: the `input` slot alone
 *   (children: whatever sits between rows 2 and 3 — the reply strip, the PPV row)
 *   row 3, "Composer toolbar": Upload (the computer's file chooser), GIF,
 *     Vault, Schedule, @ Tag other Creators (the `tag` slot; it replaced
 *     "Mention this fan", TODO.md A5), "Aa" (Not wired: a click says why), Translate (its
 *     popover, below), then a round Send at the right end
 *
 * It holds no send state. The Composer keeps every piece of draft state and
 * `submit`; this module receives the stateful pickers as slot nodes, state
 * flags, and one callback per plain control it owns (PPV, Upload, Vault,
 * Schedule, Send).
 *
 * Its Geometry is the Infloww capture's, over the deleted Clone's
 * (messages.html :77, :270, :279–284, tag legacy-ui-final), from `MP.composer`
 * (CP2–CP12); its popovers are `.pop`s (`MP.menu`).
 */

import { useEffect, useId, useRef, useState, type ReactNode } from "react";
import { Briefcase, CalendarDays, CircleDollarSign, Image as ImageIcon, Languages } from "lucide-react";

import { MP } from "@/lib/messagesPro";
import { UPLOAD_ACCEPT } from "@/hooks/useComposerUploads";
import { cn } from "@/lib/utils";
import { MENU_PANEL } from "./MenuParts";
import { NotWiredButton } from "./NotWired";
import { useEffectiveTranslateMode } from "@/hooks/useTranslateMode";

/** A button-row pill (Infloww's flat pill, `MP.composer.pill`, CP5,
 *  look-and-feel C5): accent at 15% fill with accent text (spec, Colours);
 *  "AI" and "Scripts" lay Infloww's own fills over it (`--inf-ai-pill`,
 *  `--inf-scripts-pill`, CP9).
 *  Exported for the pickers whose Messages Pro trigger is a pill ("AI",
 *  "Scripts"); the lucide icon inside spreads `PILL_ICON` (16px, CP6, stroke
 *  1.6) and the word sits in a `PILL_LABEL` span, screen-reader text only
 *  below the row-1 label threshold so the button keeps its name. */
export const PILL = cn(
  MP.composer.pill,
  MP.ours.ComposerToolbar.pill,
  "flex items-center bg-accent/15 text-accent disabled:opacity-40 disabled:cursor-not-allowed",
);
export const PILL_ICON = { className: MP.composer.pillIcon, strokeWidth: 1.6, "aria-hidden": true } as const;
export const PILL_LABEL = MP.composer.pillLabel;

/** Borderless 26px button-row icon (Clone `.comp-r1 .icon-btn`, CP3; its svg
 *  is `MP.composer.buttonRowIcon`). Exported for the ⏱ Timed message trigger. */
export const ROW_ICON = cn(
  MP.composer.buttonRowButton,
  "grid place-items-center hover:bg-bg-elev-1 disabled:opacity-40 disabled:cursor-not-allowed",
);

/** Borderless 34px toolbar icon (Clone `.comp-r2 .icon-btn`, CP9; its svg is
 *  `MP.composer.toolbarIcon`). Exported for the GIF and "Tag other Creators"
 *  triggers. */
export const TOOLBAR_ICON = cn(
  MP.composer.toolbarButton,
  "grid place-items-center hover:bg-bg-elev-1 disabled:opacity-40 disabled:cursor-not-allowed",
);

export interface ComposerToolbarProps {
  /** Button-row slots, in row order. */
  emoji: ReactNode;
  /** ⚙ Emoji favourites, after the emoji picker at row 1's left end. */
  favourites: ReactNode;
  /** The quick emoji row, after ⚙. */
  quick: ReactNode;
  input: ReactNode;
  ai: ReactNode;
  scripts: ReactNode;
  /** ⏱ Timed message, after the "PPV" pill. */
  timed: ReactNode;
  /** Bottom-toolbar slots. GIF stays hidden below md. */
  gif: ReactNode;
  /** @ Tag other Creators. */
  tag: ReactNode;
  /** Rendered between row 2 (the input) and row 3. */
  children?: ReactNode;
  /** Attachments are on the draft (the Vault icon shows it). */
  vaultOn: boolean;
  /** The PPV row is showing (the "PPV" pill's pressed state). */
  ppvOpen: boolean;
  vaultDisabled: boolean;
  scheduleOn: boolean;
  canSend: boolean;
  /** Why Send is disabled, as its title (an upload still in flight). */
  sendBlockedReason?: string | null;
  sendLabel: string;
  inflight: number;
  disabled?: boolean;
  onTogglePpv: () => void;
  /** Upload opens the computer's file chooser (images and videos, several at
   *  once) and hands over the chosen files; restored 2026-10-16. */
  onUploadFiles: (files: File[]) => void;
  onVault: () => void;
  onCalendar: () => void;
  onSend: () => void;
  /** The chat's Creator, whose Agency's AI translation switch gates the
   *  Translator (spec phase-04, story 56). */
  accountId: string | null;
  /** Opens and closes the composer's outbound translation strip (the
   *  Translate popover's "Translate my messages"); without it the row hides. */
  onToggleOutbound?: () => void;
}

export function ComposerToolbar({
  emoji, favourites, quick, input, ai, scripts, timed, gif, tag, children,
  vaultOn, ppvOpen, vaultDisabled, scheduleOn, canSend, sendBlockedReason, sendLabel, inflight, disabled,
  onTogglePpv, onUploadFiles, onVault, onCalendar, onSend, accountId, onToggleOutbound,
}: ComposerToolbarProps) {
  const fileRef = useRef<HTMLInputElement | null>(null);
  return (
    <>
      <div
        role="toolbar"
        aria-label="Composer buttons"
        className={cn(MP.composer.buttonRow, "flex flex-nowrap items-center min-w-0 border-[var(--inf-rule,var(--color-border))]")}
      >
        {emoji}
        {favourites}
        {quick}
        <div className={cn(MP.composer.buttonRowEnd, "ml-auto flex flex-nowrap items-center")}>
          {ai}
          {scripts}
          <button
            type="button"
            onClick={onTogglePpv}
            disabled={disabled}
            aria-pressed={ppvOpen}
            title="Price, lock text, attachments and send time for this message"
            className={cn(PILL, "text-[var(--inf-accent-text,var(--color-accent))]", ppvOpen && "bg-accent/25")}
          >
            <CircleDollarSign {...PILL_ICON} /><span className={PILL_LABEL}>PPV</span>
          </button>
          <div className={cn(MP.composer.timed, "flex")}>{timed}</div>
        </div>
      </div>

      <div className="flex min-w-0">{input}</div>

      {children}

      <div
        role="toolbar"
        aria-label="Composer toolbar"
        className={cn(MP.composer.toolbar, "flex flex-wrap items-center")}
      >
        <button
          type="button"
          onClick={() => fileRef.current?.click()}
          disabled={vaultDisabled}
          aria-label="Upload"
          title="Upload from computer"
          className={cn(TOOLBAR_ICON, "text-fg-dim hover:text-fg")}
        >
          <Briefcase aria-hidden className={MP.composer.toolbarIcon} />
        </button>
        <input
          ref={fileRef}
          type="file"
          multiple
          accept={UPLOAD_ACCEPT}
          aria-label="Upload from computer"
          tabIndex={-1}
          className="hidden"
          onChange={(e) => {
            const files = Array.from(e.target.files ?? []);
            e.target.value = ""; // the same file can be chosen again
            if (files.length > 0) onUploadFiles(files);
          }}
        />
        <div className="hidden md:contents">{gif}</div>
        <button
          type="button"
          onClick={onVault}
          disabled={vaultDisabled}
          aria-label="Vault"
          title="Pick from vault"
          className={cn(TOOLBAR_ICON, vaultOn ? "text-[var(--inf-accent-text,var(--color-accent))]" : "text-fg-dim hover:text-fg")}
        >
          <ImageIcon aria-hidden className={MP.composer.toolbarIcon} />
        </button>
        <button
          type="button"
          onClick={onCalendar}
          disabled={disabled}
          aria-label="Schedule"
          title="Schedule send for later"
          className={cn(TOOLBAR_ICON, scheduleOn ? "text-[var(--inf-accent-text,var(--color-accent))]" : "text-fg-dim hover:text-fg")}
        >
          <CalendarDays aria-hidden className={MP.composer.toolbarIcon} />
        </button>
        {tag}
        {/* Not wired: OnlyFans strips markup from DM text (spec, ASSUMPTION).
         *  Drawn as Infloww's, in its neighbours' grey; a click says so. */}
        <NotWiredButton
          why="aa"
          notePlace="bottom-full left-0 mb-1"
          className={cn(TOOLBAR_ICON, MP.composer.aa, "text-[var(--inf-composer-glyph,var(--color-fg-dim))]")}
        >
          Aa
        </NotWiredButton>
        <TranslatePopover accountId={accountId} onToggleOutbound={onToggleOutbound} />
        {/* Send bottom-aligned: 16px above the Composer's bottom, as the capture (C8). */}
        <div className="ml-auto self-end flex items-center gap-2">
          {inflight > 0 && (
            <span className={cn(MP.ours.ComposerToolbar.inflight, "text-fg-dim")}>{inflight} sending…</span>
          )}
          <button
            type="button"
            onClick={onSend}
            disabled={!canSend}
            title={sendBlockedReason || "Enter to send · Shift+Enter for newline"}
            className={cn(
              MP.composer.send,
              MP.ours.ComposerToolbar.send,
              "focus:outline-none focus-visible:ring-2 focus-visible:ring-accent/40",
              canSend
                ? "bg-accent hover:bg-accent-hover text-white"
                : "bg-[var(--inf-send-idle,var(--color-bg-elev-2))] text-[var(--inf-send-idle-text,var(--color-fg-dim))] cursor-not-allowed",
            )}
          >
            {sendLabel}
          </button>
        </div>
      </div>
    </>
  );
}

/** Open state for a popover that closes on a pointerdown outside the
 *  returned root, like the per-chat scheduled popover. Shared by the ⏱ Timed
 *  message, the Translator and the ⚙ favourites. */
export function usePopover() {
  const [open, setOpen] = useState(false);
  const rootRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    if (!open) return;
    const onDown = (e: MouseEvent) => {
      if (rootRef.current && !rootRef.current.contains(e.target as Node)) setOpen(false);
    };
    window.addEventListener("pointerdown", onDown);
    return () => window.removeEventListener("pointerdown", onDown);
  }, [open]);

  return { open, setOpen, rootRef };
}

/** A button-row popover, the Clone's `.pop` box (`MENU_PANEL`, MN1) opening
 *  upward from its trigger's right edge; its `.pop .phead` (MN3) and
 *  `.pop .prow` (MN2). Shared by the ⏱ Timed message and the Translator. */
export const POP = cn(MENU_PANEL, MP.ours.ComposerToolbar.pop, "absolute bottom-full z-50");
/** The same box opening upward from its trigger's left edge (look-and-feel
 *  C13): the ⚙ favourites, at row 1's left end. */
export const POP_START = cn(MENU_PANEL, MP.ours.ComposerToolbar.popStart, "absolute bottom-full z-50");
export const POP_HEAD = cn(MP.menu.head, "uppercase text-fg-dim");
export const POP_ROW = cn(MP.menu.row, "flex items-center");
/** A `.pop`'s primary action (⏱ "Start", the ⚙ editor's "Save"). */
export const POP_PRIMARY = cn(
  MP.ours.ComposerToolbar.popPrimary,
  "bg-accent text-white hover:bg-accent-hover disabled:bg-bg-elev-2 disabled:text-fg-dim disabled:cursor-not-allowed",
);
/** The tooltip on a Translator switch the Agency turned off (spec phase-04). */
const TURNED_OFF = "Turned off by your organization";

/** The "Translate" icon between "Aa" and Send (spec, Translator; Gap row 21).
 *  Its `.pop` popover reads "Translate messages from fans into" › "English"
 *  and holds a "Use translation" switch bound to `useTranslateMode`, the same
 *  mode as the Chat header's 🌐 toggle, so the two never disagree. The mode's
 *  scope and translate endpoint are unchanged; English is the only inbound
 *  target. "Translate my messages" opens and closes the composer's outbound
 *  strip (OutboundTranslation: the Fan's language, Use / Send translation).
 *  The switch takes the Clone's `.switch` geometry (messages.html:73–74,
 *  `MP.windowHeader.switch`, WH11–WH13, as `SwitchTrack` does): a 26×14
 *  track with a 10px thumb inset 2px.
 *
 *  While the Agency's AI translation switch is off for this chatter (spec
 *  phase-04, story 56), the switch is disabled, shows off and carries the
 *  tooltip `TURNED_OFF`; the stored mode is never written, so it returns as
 *  it was when the owner turns AI translation back on. */
function TranslatePopover({ accountId, onToggleOutbound }: { accountId: string | null; onToggleOutbound?: () => void }) {
  const { open, setOpen, rootRef } = usePopover();
  const { on: translateOn, locked, setStored } = useEffectiveTranslateMode(accountId);
  const id = useId();
  const switchLabel = `${id}-use`;

  return (
    <div ref={rootRef} className="relative">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
        aria-controls={open ? id : undefined}
        aria-label="Translate"
        title="Translate"
        className={cn(TOOLBAR_ICON, open || translateOn ? "text-[var(--inf-accent-text,var(--color-accent))]" : "text-fg-dim hover:text-fg")}
      >
        <Languages aria-hidden className={MP.composer.toolbarIcon} />
      </button>
      {open && (
        <section id={id} aria-label="Translate" className={POP}>
          <div className={POP_HEAD}>Translate messages from fans into</div>
          <div className={cn(POP_ROW, MP.ours.ComposerToolbar.translateTarget)}>English</div>
          <div className={POP_ROW}>
            <span id={switchLabel} className="flex-1">Use translation</span>
            <button
              type="button"
              role="switch"
              aria-checked={translateOn}
              aria-labelledby={switchLabel}
              disabled={locked}
              title={locked ? TURNED_OFF : undefined}
              onClick={() => setStored(!translateOn)}
              className={cn(
                MP.windowHeader.switch,
                "relative shrink-0 transition-colors disabled:opacity-40 disabled:cursor-not-allowed",
                translateOn ? "bg-accent" : "bg-[var(--inf-idle-fill,var(--color-bg-elev-2))]",
              )}
            >
              <span
                aria-hidden
                className={cn(
                  MP.windowHeader.switchKnob,
                  "absolute bg-white transition-transform",
                  translateOn && MP.windowHeader.switchKnobOn,
                )}
              />
            </button>
          </div>
          {/* Outbound: the composer's strip (OutboundTranslation, 04 M15). */}
          {onToggleOutbound && (
            <button
              type="button"
              disabled={locked}
              title={locked ? TURNED_OFF : "Alt+T"}
              onClick={() => { setOpen(false); onToggleOutbound(); }}
              className={cn(POP_ROW, "w-full text-left hover:bg-bg-elev-1 disabled:opacity-40 disabled:cursor-not-allowed")}
            >
              Translate my messages
            </button>
          )}
        </section>
      )}
    </div>
  );
}
