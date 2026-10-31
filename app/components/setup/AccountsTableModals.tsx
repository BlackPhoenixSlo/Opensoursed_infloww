"use client";

/**
 * AccountsTableModals — AccountsTable's Creator row with no account (DraftRow) and its two confirm modals, the Delete
 * modal (DeleteCreatorModal, two steps) and the Deactivate / Activate modal (ActiveCreatorModal), with the row and ⋮
 * menu styles (every MENU_*) the table's own rows share. Moved out of AccountsTable.tsx as is.
 */

import { ArrowLeft, EllipsisVertical, Pencil, Plus, Trash2, type LucideIcon } from "lucide-react";
import { useState, type ReactNode } from "react";

import { HB_TABLE } from "@/components/ui/infloww";
import { useOutsideClose } from "@/components/ui/Menu";
import { ROW_LINK_TITLE as ROW_LINK } from "@/components/setup/AddCreatorModal";
import {
  FIELD, FlowButton, FlowModal, HB_DIM, RADIO, RADIO_GROUP, RADIO_ITEM, StepIndicator, T,
} from "@/components/setup/creatorFlow";
import type { DraftCreator } from "@/lib/creatorProfiles";
import { cn } from "@/lib/utils";

/** The house Not wired marker. */
export const NOT_WIRED = "not wired";
/** The Action cell's buttons: 28px, a white 16px icon inside 6px, 6px corners (creators-manage#49), filled #2c2c2c and
 *  borderless (01-home.png). */
const FILL = cn(
  "bg-[#2c2c2c] hover:bg-[#383838] disabled:opacity-50 disabled:cursor-not-allowed disabled:hover:bg-[#2c2c2c]",
  "text-white [html[data-theme=light]_&]:bg-black/[.09] [html[data-theme=light]_&]:text-fg",
);
export const ACT = cn("inline-flex h-7 w-7 items-center justify-center rounded-md", FILL);
/** The ⋮ menu (creators-manage#81): HB's panel #171717 with a 9%-white hairline, 4px padding, 8px corners; items 32px,
 *  5px 12px, 14px white on a 22px line, 4px corners, hover 5.5% white; a disabled item 38% white. */
export const MENU_BOX = cn(
  "fixed z-50 w-max min-w-48 rounded-lg border border-white/[.09] bg-panel p-1 shadow-lg",
  "[html[data-theme=light]_&]:border-black/[.09]",
);
export const MENU_ROW = "block w-full rounded px-3 py-[5px] text-left text-sm leading-[22px]";
export const MENU_ON = "text-white hover:bg-white/[.055] [html[data-theme=light]_&]:text-fg [html[data-theme=light]_&]:hover:bg-black/[.055]";
export const MENU_OFF = "cursor-not-allowed text-white/[.38] [html[data-theme=light]_&]:text-black/[.38]";
/** A group of ⋮ items under a hairline (Recovery, the Inflowwww extras). */
export const MENU_RULE = "mt-1 border-t border-white/[.09] pt-1 [html[data-theme=light]_&]:border-black/[.09]";
/** The fixed Action column: #171717 for head and cells, a 1px #2c2c2c rule at its left (01-home.png). */
export const STICKY = cn(
  "md:sticky md:right-0 bg-panel border-l border-[#2c2c2c] [html[data-theme=light]_&]:border-black/[.09]",
);

/** A Creator saved with Done and no account yet (Infloww's Creator row with no account): its name and image,
 *  "Pending connection", "Link creator account" (the Add creator modal at select-platform) and ⋮ [Edit, Delete]. */
export function DraftRow({ columns, draft, onLink, onEdit, onDelete }: {
  /** The table's columns (AccountsTable's COLUMNS): the row draws one cell per column, in their order. */
  columns: ReadonlyArray<{ key: string; sticky?: boolean }>;
  draft: DraftCreator;
  onLink?: () => void;
  onEdit: () => void;
  onDelete: () => void;
}) {
  const { open, setOpen, ref } = useOutsideClose();
  const [pos, setPos] = useState<{ top: number; right: number } | null>(null);
  const menuItem = (text: string, run: () => void, Icon: LucideIcon, danger?: boolean) => (
    <button
      type="button" role="menuitem" onClick={() => { setOpen(false); run(); }}
      className={cn(MENU_ROW, "flex items-center gap-2", MENU_ON, danger && "text-err")}
    >
      <Icon className="h-4 w-4 shrink-0" aria-hidden />{text}
    </button>
  );
  const cell = (key: string): ReactNode => {
    switch (key) {
      case "creators-manage#30":
        return (
          <div className="flex items-center gap-3">
            {draft.avatar
              ? <img src={draft.avatar} alt="" aria-hidden className="h-6 w-6 shrink-0 rounded-full object-cover" />
              : <span aria-hidden className="h-6 w-6 shrink-0 rounded-full bg-white/[.09]" />}
            <span className="truncate">{draft.name}</span>
          </div>
        );
      case "creators-manage#39":
        return <span className={HB_DIM}>Pending connection</span>;
      case "creators-manage#43":
        return (
          <div ref={ref} className="flex items-center gap-2">
            <button
              type="button" aria-label={ROW_LINK} title={onLink ? ROW_LINK : NOT_WIRED} disabled={!onLink}
              onClick={onLink} className={ACT}
            >
              <Plus className="h-4 w-4" aria-hidden />
            </button>
            <button
              type="button" aria-label={`More actions for ${draft.name}`} aria-haspopup="menu" aria-expanded={open}
              onClick={(e) => {
                const r = e.currentTarget.getBoundingClientRect();
                setPos({ top: r.bottom + 4, right: Math.max(8, window.innerWidth - r.right) });
                setOpen((o) => !o);
              }}
              className={ACT}
            >
              <EllipsisVertical className="h-4 w-4" aria-hidden />
            </button>
            {open && pos && (
              <div role="menu" aria-label={`Actions for ${draft.name}`} className={MENU_BOX} style={{ top: pos.top, right: pos.right }}>
                {menuItem("Edit", onEdit, Pencil)}
                {menuItem("Delete", onDelete, Trash2, true)}
              </div>
            )}
          </div>
        );
      default:
        return null;
    }
  };
  return (
    <tr className={HB_TABLE.row}>
      {columns.map((c) => (
        <td key={c.key} className={cn(HB_TABLE.td, c.sticky && STICKY)}>{cell(c.key)}</td>
      ))}
    </tr>
  );
}

/**
 * The Delete modal, `DeleteCreatorsWithSurvey` (creators-manage#78), in Infloww's words: "Delete {creator}" (a
 * Creator) or "Delete {creator} / {nickname}" (an account under one), its message, then the survey, "Why are you
 * deleting the creator's account?" (Optional), with Infloww's five reasons and, for Others, a 120-character reason.
 * The footer is the two-step footer (`footerType:"stepButton"`, `stepTotal:2`): Back (disabled on step 1), the dots
 * and "Step N of 2", then "Delete creator" and, on step 2, Submit, which deletes. The backdrop does not close it;
 * Escape does. Infloww sends the answer with its delete; the Relay has no field for it, so the answer stays here.
 */
export function DeleteCreatorModal({ creator, nickname, pending, error, onClose, onDelete }: {
  creator: string;
  nickname?: string;
  pending: boolean;
  error: Error | null;
  onClose: () => void;
  onDelete: () => void;
}) {
  const [step, setStep] = useState<0 | 1>(0);
  const [reason, setReason] = useState<string | null>(null);
  const [other, setOther] = useState("");
  const others = T.surveyReasons[T.surveyReasons.length - 1];
  return (
    <FlowModal
      title={T.deleteTitle(creator, nickname)}
      onClose={onClose}
      footer={
        <div className="flex w-full items-center justify-between gap-2">
          <FlowButton disabled={step === 0} onClick={() => setStep(0)}>
            <ArrowLeft className="h-4 w-4" aria-hidden />{T.back}
          </FlowButton>
          <StepIndicator active={step} count={2}>
            {step === 0
              ? <FlowButton stop onClick={() => setStep(1)}>{T.deleteCreator}</FlowButton>
              : <FlowButton stop disabled={pending} onClick={onDelete}>{T.submit}</FlowButton>}
          </StepIndicator>
        </div>
      }
    >
      <div className="text-sm">
        {step === 0 ? (
          <p>{T.deleteMessage(creator, nickname)}</p>
        ) : (
          <fieldset className={RADIO_GROUP}>
            <legend className="mb-4 text-[16px] font-medium">
              {T.surveyTitle} <span className={cn("font-normal", HB_DIM)}>{T.optional}</span>
            </legend>
            {T.surveyReasons.map((r) => (
              <label key={r} className={RADIO_ITEM}>
                <input type="radio" name="delete-reason" checked={reason === r} onChange={() => setReason(r)} className={RADIO} />
                {r}
              </label>
            ))}
            {reason === others && (
              <textarea
                aria-label={T.surveyOther} placeholder={T.surveyOther} maxLength={120} value={other}
                onChange={(e) => setOther(e.target.value)}
                className={cn(FIELD, "h-auto min-h-20 py-2")}
              />
            )}
          </fieldset>
        )}
        {error && <p className="mt-2 text-err">{error.message}</p>}
      </div>
    </FlowModal>
  );
}

/**
 * The Deactivate modal, `DisableCreator` (creators-manage#77): 600px, "Deactivate {creator}", what stops, and Infloww's
 * warning that fees still apply (creators0152); its confirm is the red stop button, or the primary one to activate.
 * The Relay keeps the creator's history and every report row; only the switcher, inbox and background work drop it.
 */
export function ActiveCreatorModal({ creator, activate, pending, error, onClose, onConfirm }: {
  creator: string;
  /** True: the creator is deactivated and this activates it. */
  activate: boolean;
  pending: boolean;
  error: Error | null;
  onClose: () => void;
  onConfirm: () => void;
}) {
  const verb = activate ? "Activate" : "Deactivate";
  return (
    <FlowModal
      title={`${verb} ${creator}`}
      onClose={onClose}
      footer={
        <div className="flex w-full justify-end gap-3">
          <FlowButton onClick={onClose}>{T.cancel}</FlowButton>
          <FlowButton primary={activate} stop={!activate} disabled={pending} onClick={onConfirm}>{verb}</FlowButton>
        </div>
      }
    >
      <p className="text-sm">
        {activate
          ? `${creator}'s chats, sales and automations start syncing again, and it returns to the inbox and the creator switcher.`
          : `${creator}'s chats, sales and automations stop syncing, and it leaves the inbox and the creator switcher. `
            + "Its history and reports are kept. Fees still apply while it is deactivated."}
      </p>
      {error && <p className="mt-2 text-sm text-err">{error.message}</p>}
    </FlowModal>
  );
}
