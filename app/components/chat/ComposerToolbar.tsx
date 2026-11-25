"use client";


import { useEffect, useId, useRef, useState, type ReactNode } from "react";
import { Briefcase, CalendarDays, CircleDollarSign, Image as ImageIcon, Languages, SkipForward } from "lucide-react";

import { MP } from "@/lib/messagesPro";
import { UPLOAD_ACCEPT } from "@/hooks/useComposerUploads";
import { cn } from "@/lib/utils";
import { MENU_PANEL } from "./MenuParts";
import { useEffectiveTranslateMode } from "@/hooks/useTranslateMode";

export const PILL = cn(
  MP.composer.pill,
  MP.ours.ComposerToolbar.pill,
  "flex items-center bg-accent/15 text-accent disabled:opacity-40 disabled:cursor-not-allowed",
);
export const PILL_ICON = { className: MP.composer.pillIcon, strokeWidth: 1.6, "aria-hidden": true } as const;
export const PILL_LABEL = MP.composer.pillLabel;

export const ROW_ICON = cn(
  MP.composer.buttonRowButton,
  "grid place-items-center hover:bg-bg-elev-1 disabled:opacity-40 disabled:cursor-not-allowed",
);

export const TOOLBAR_ICON = cn(
  MP.composer.toolbarButton,
  "grid place-items-center hover:bg-bg-elev-1 disabled:opacity-40 disabled:cursor-not-allowed",
);

export interface ComposerToolbarProps {
  emoji: ReactNode;
  favourites: ReactNode;
  quick: ReactNode;
  input: ReactNode;
  ai: ReactNode;
  scripts: ReactNode;
  timed: ReactNode;
  gif: ReactNode;
  tag: ReactNode;
  children?: ReactNode;
  vaultOn: boolean;
  ppvOpen: boolean;
  ppvHeld: boolean;
  vaultDisabled: boolean;
  scheduleOn: boolean;
  canSend: boolean;
  sendBlockedReason?: string | null;
  sendLabel: string;
  inflight: number;
  disabled?: boolean;
  onTogglePpv: () => void;
  onUploadFiles: (files: File[]) => void;
  onVault: () => void;
  onCalendar: () => void;
  onSend: () => void;
  onClear?: () => void;
  onSendNext?: () => void;
  accountId: string | null;
  onToggleOutbound?: () => void;
  aa?: { on: boolean; onToggle: () => void } | null;
}

export function ComposerToolbar({
  emoji, favourites, quick, input, ai, scripts, timed, gif, tag, children,
  vaultOn, ppvOpen, ppvHeld, vaultDisabled, scheduleOn, canSend, sendBlockedReason, sendLabel, inflight, disabled,
  onTogglePpv, onUploadFiles, onVault, onCalendar, onSend, onClear, onSendNext, accountId, onToggleOutbound, aa,
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
            onClick={ppvHeld ? undefined : onTogglePpv}
            disabled={disabled}
            // aria-disabled, not disabled: hover and focus still show why.
            aria-disabled={ppvHeld || undefined}
            aria-pressed={ppvOpen}
            title={ppvHeld
              ? "The PPV row stays open while it holds something; Clear empties and closes it"
              : "Price, lock text, attachments and send time for this message"}
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
            e.target.value = "";
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
        {aa && (
          <button
            type="button"
            onClick={aa.onToggle}
            onMouseDown={(e) => e.preventDefault()}
            disabled={disabled}
            aria-pressed={aa.on}
            title={aa.on ? "Hide text formatting" : "Text formatting (bold, italic, colour, size)"}
            className={cn(TOOLBAR_ICON, MP.composer.aa,
              aa.on ? "text-[var(--inf-accent-text,var(--color-accent))] bg-accent/10" : "text-[var(--inf-composer-glyph,var(--color-fg-dim))]")}
          >
            Aa
          </button>
        )}
        <TranslatePopover accountId={accountId} onToggleOutbound={onToggleOutbound} />
        <div className="ml-auto self-end flex items-center gap-2">
          {inflight > 0 && (
            <span className={cn(MP.ours.ComposerToolbar.inflight, "text-fg-dim")}>{inflight} sending…</span>
          )}
          {onClear && (
            <button
              type="button"
              onClick={onClear}
              disabled={disabled}
              aria-label="Clear message"
              title="Clear the message"
              className={cn(
                MP.composer.send,
                MP.ours.ComposerToolbar.send,
                MP.ours.ComposerToolbar.clear,
                "border-accent text-[var(--inf-accent-text,var(--color-accent))] bg-transparent hover:bg-accent/10",
                "focus:outline-none focus-visible:ring-2 focus-visible:ring-accent/40",
              )}
            >
              Clear
            </button>
          )}
          {onSendNext && (
            <button
              type="button"
              onClick={onSendNext}
              disabled={!canSend}
              data-testid="send-next"
              aria-label={`${sendLabel} & next`}
              title={sendBlockedReason || `${sendLabel}, then the next fan (⌘/Ctrl+Enter)`}
              className={cn(
                MP.composer.send,
                MP.ours.ComposerToolbar.send,
                MP.ours.ComposerToolbar.sendNext,
                "inline-flex items-center justify-center",
                "focus:outline-none focus-visible:ring-2 focus-visible:ring-accent/40",
                canSend
                  ? "bg-accent/15 text-[var(--inf-accent-text,var(--color-accent))] hover:bg-accent/25"
                  : "bg-[var(--inf-send-idle,var(--color-bg-elev-2))] text-[var(--inf-send-idle-text,var(--color-fg-dim))] cursor-not-allowed",
              )}
            >
              <SkipForward aria-hidden data-testid="send-next-icon" className="size-4 lg:hidden" />
              <span aria-hidden className="hidden lg:inline">{sendLabel} &amp; next</span>
            </button>
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

export const POP = cn(MENU_PANEL, MP.ours.ComposerToolbar.pop, "absolute bottom-full z-50 origin-bottom");
export const POP_START = cn(MENU_PANEL, MP.ours.ComposerToolbar.popStart, "absolute bottom-full z-50 origin-bottom-left");
export const POP_HEAD = cn(MP.menu.head, "uppercase text-fg-dim");
export const POP_ROW = cn(MP.menu.row, "flex items-center");
export const POP_PRIMARY = cn(
  MP.ours.ComposerToolbar.popPrimary,
  "bg-accent text-white hover:bg-accent-hover disabled:bg-bg-elev-2 disabled:text-fg-dim disabled:cursor-not-allowed",
);
const TURNED_OFF = "Turned off by your organization";

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
        title="Translate: fan messages into English, or your reply into the fan's language"
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
          {onToggleOutbound && (
            <button
              type="button"
              disabled={locked}
              title={locked ? TURNED_OFF : "Write in English, send in the fan's language (Alt+T)"}
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
