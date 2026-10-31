"use client";

/**
 * The UI kit of Infloww's Creators flows (re-exported by `creatorFlow.tsx`): the en strings `T`, the modal shell, the
 * buttons, step dots, radios and field box, rebuilt from the Dashboard bundle
 * (`~/Downloads/infloww-remote-web/index.9f50f370.js`, offsets cited per piece) with the English from Infloww's own en
 * locale chunk (`index.526c4a9d.js`; the key is cited beside each string). "Infloww" in a string reads "Inflowwww".
 */

import { CircleCheck } from "lucide-react";
import type { ReactNode } from "react";

import { HB_TEXT } from "@/components/ui/ifSelect";
import { HbModal } from "@/components/ui/infloww";
import { cn } from "@/lib/utils";
import { BRAND_NAME } from "@/lib/brand";

/** The en locale's strings, by key. */
export const T = {
  addCreator: "Add creator", //                                   leaderboard0002
  linkCreatorAccount: "Link creator account", //                  creators0174
  creatorDetails: "Creator details", //                           creators0076
  displayImage: "Display image", //                               creators0104
  creatorName: "Creator name", //                                 growth0094
  enterName: "Please enter a name", //                            employee0118
  namePattern: "Please input [0-9] or [a-z] or [A-Z]", //         employee0121
  gender: "Gender", //                                            tp-manager0033
  done: "Done", //                                                creators0108
  nextLink: "Next: Link creator account", //                      creators0200
  next: "Next", //                                                growth0251
  newCreatorAdded: "New creator added", //                        creators0195
  whichPlatform: "Which platform’s account would you like to link?", // creators0307
  onePerPlatform: (platform: string) => //                        creators0408
    `Each creator can only link one account from each platform. This creator already has an account from ${platform} linked.`,
  proxySelection: "Proxy selection", //                           creators0240
  proxyRequired: `Using a proxy is required to manage the creator’s account on ${BRAND_NAME} and allow employees to chat with fans, without revealing the creator’s login information. All your data is safe with us.`, // creators0301
  customProxy: "Custom proxy", //                                 router_config_0017
  useOwnProxy: "Use your own proxy", //                           creators0298
  newProxy: "New proxy", //                                       creators0196
  checking: "Loading...", //                                      creators0183 ("Loding...")
  proxyError: "Error message", //                                 creators0121
  connectOnlyFans: "Connect OnlyFans", //                         creators0057
  linkPlatformAccount: (platform: string) => `Link ${platform} account`, // creators0169
  linked: `Creator account is linked to ${BRAND_NAME}`, //            creators0075
  accountDetails: "Account details", //                           creators0021
  nickname: "Nickname", //                                        creators0201
  tagOptional: "Tag (Optional)", //                               creators0276
  tag: "Tag", //                                                  creators0275
  assignedEmployees: "Assigned employees (Optional)", //          creators0041
  selectEmployee: "Select employee", //                           creators0252
  notesOptional: "Internal notes (Optional)", //                  fansly0027
  notesPlaceholder: "Add notes about creator account", //         creators0032
  updateSuccess: "Update Success", //                             creators0296
  stepOf: (i: number, n: number) => `Step ${i} of ${n}`, //       step_of_total
  cancel: "Cancel", //                                            s4s0123
  save: "Save", //                                                tp-manager0055
  editAccountDetails: "Edit account details", //                  creators0112
  editCreatorDetails: "Edit creator details", //                  creators0113
  platform: "Platform", //                                        settings0125
  linkedAccount: "Linked account", //                             creators0181
  connectedAccount: "Connected account", //                       creators0060
  notConnected: "Not connected", //                               creators0202
  disconnected: "Disconnected", //                                creators0103
  linkAccount: "Link account", //                                 creators0172
  unlink: "Unlink", //                                            creators0290
  proxyConnection: "Proxy connection", //                         creators0238
  connection: "Connection", //                                    connection_index (one connection: no index)
  change: "Change", //                                            creators0053
  del: "Delete", //                                               tp-manager0027
  changeProxy: "Change proxy", //                                 creators0054
  switchProxySuccess: "Switch Proxy Success", //                  creators0271
  faceIdTitle: "Face ID Verification", //                         ModalTitleMaps (index.9f50f370.js @12438097)
  selectRoleTitle: "Select your role", //                         ModalTitleMaps
  altMethodTitle: "Linking OnlyFans account (Alternative method)", // ModalTitleMaps
  stillUnable: `Still unable to perform verification and link OnlyFans account to ${BRAND_NAME}?`, // @12434760
  learnMore: "Learn More", //                                     creators0164
  copy: "Copy", //                                                creators0068
  copied: "Copy successfully", //                                 creators0069
  deleteCreator: "Delete creator", //                             creators0097
  submit: "Submit", //                                            employee0173
  back: "Back", //                                                settings0024
  deleteTitle: (creator: string, nickname?: string) => //        delete_creator_title / delete_child_title
    nickname ? `Delete ${creator} / ${nickname}` : `Delete ${creator}`,
  deleteMessage: (creator: string, nickname?: string) => //      delete_creator_step1_message / delete_child_step1_message
    nickname
      ? `All data under ${nickname} will be permanently deleted from ${BRAND_NAME}. This action cannot be undone.`
      : `All platform accounts and related data under ${creator} will be permanently deleted from ${BRAND_NAME}. This action cannot be undone.`,
  surveyTitle: "Why are you deleting the creator's account?", //  delete_creator_step2_title
  optional: "Optional", //                                        optional_text
  surveyReasons: [ //                                             delete_survey_reason_1..4, _other
    "Creator is no longer with our agency",
    "Transferred creator to a partner agency",
    "Creator was added for testing purposes only",
    "Migrating creator to another software/CRM/internal solution",
    "Others",
  ],
  surveyOther: "Reason for deleting creator", //                  delete_survey_other_placeholder
  deleted: (name: string) => `${name} deleted`, //               delete_success
} as const;

// ── Modal shell: HBModal, `size:"medium",width:600`, `maskClosable:false` ────────────────────────────────────────

/** HB's 62% text (`element-emphasis-01`). */
export const HB_DIM = "text-white/[.62] [html[data-theme=light]_&]:text-black/[.62]";

/** The flows' one modal: ticket 00's `HbModal` at 600px (#54: the 24px / 500 title over a hairline, the footer under
 *  one). The mask does not close it; Escape and the × do. */
export function FlowModal({ title, onClose, footer, children, closable = true }: {
  title?: string;
  onClose: () => void;
  footer?: ReactNode;
  children: ReactNode;
  /** `closable:false` modals draw no × and Escape does not close them (Infloww's `closable:false`). */
  closable?: boolean;
}) {
  // The steps read white on the modal (`._content-wrap`: `color:var(--element-emphasis-00)`), not HbModal's 62% body.
  return (
    // On a phone the modal may take the whole screen (less HbModal's 16px frame), not 80% of it.
    <HbModal title={title} width={600} onClose={onClose} footer={footer} closable={closable} className="max-md:max-h-[calc(100dvh-2rem)]">
      <div className={cn("text-[14px] leading-normal", HB_TEXT)}>{children}</div>
    </HbModal>
  );
}

/** HBButton at `size:"generous"`: 36px, 8px 12px, 8px corners; `primary` the orange action fill with black text,
 *  `stop` the red signal, else HB's secondary #2c2c2c with white text. */
export function FlowButton({ primary, stop, className, ...p }: React.ButtonHTMLAttributes<HTMLButtonElement> & {
  primary?: boolean; stop?: boolean;
}) {
  return (
    <button
      type="button"
      {...p}
      className={cn(
        "inline-flex h-9 items-center justify-center gap-2 rounded-lg px-3 text-sm font-medium transition-opacity disabled:cursor-not-allowed disabled:opacity-50",
        primary ? "bg-cta text-black hover:opacity-90"
          : stop ? "bg-err text-white hover:opacity-90"
          : cn("bg-[#2c2c2c] hover:bg-[#383838] [html[data-theme=light]_&]:bg-black/[.09]", HB_TEXT),
        className,
      )}
    />
  );
}

/** `StepIndicator` (index.9f50f370.js @12455900): a spacer, then centred the dots (8px apart, the active one white,
 *  the rest `element-emphasis-03`) over "Step N of M" (14px, `element-emphasis-01`), then the button at the right. */
export function StepIndicator({ active, count, children }: { active: number; count: number; children: ReactNode }) {
  return (
    <div className="flex w-full items-center gap-2">
      <div className="flex-1" />
      <div className="flex flex-col items-center gap-2">
        <span aria-hidden className="flex gap-2">
          {Array.from({ length: count }, (_, i) => (
            <span key={i} className={cn("h-2 w-2 rounded-full",
              i === active ? "bg-white [html[data-theme=light]_&]:bg-black" : "bg-white/[.235] [html[data-theme=light]_&]:bg-black/[.235]")} />
          ))}
        </span>
        <span className={cn("text-[14px] leading-4", HB_DIM)}>{T.stepOf(active + 1, count)}</span>
      </div>
      <div className="flex flex-1 items-center justify-end gap-3">{children}</div>
    </div>
  );
}

/** `HBRadioGroup` (index.9fc9db54.css `.hb-radio-group`, `.hb-radio`): a column of items 16px apart, each the 16px
 *  radio 16px before its 16px white label; the radio a 9%-white disc, checked a 4px orange ring around white. */
export const RADIO_GROUP = "flex flex-col gap-4";
export const RADIO_ITEM = cn(
  "flex cursor-pointer items-start gap-4 text-[16px] leading-5 has-[:disabled]:cursor-not-allowed has-[:disabled]:opacity-40",
  HB_TEXT,
);
export const RADIO = cn(
  "mt-0.5 h-4 w-4 shrink-0 cursor-pointer appearance-none rounded-full border border-white/[.09] bg-white/[.09] transition-all",
  "hover:bg-white/[.62] checked:border-4 checked:border-cta checked:bg-white checked:hover:bg-white",
  "disabled:cursor-not-allowed",
  "[html[data-theme=light]_&]:border-black/[.09] [html[data-theme=light]_&]:bg-black/[.09]",
  "[html[data-theme=light]_&]:checked:border-cta [html[data-theme=light]_&]:checked:bg-white",
  "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-cta/50",
);
/** A step's title (`._title`: heading4-strong, 20px / 500, 16px under it). */
export const STEP_TITLE = "mb-4 text-[20px] font-medium leading-6";

/** The green check and its line (`HBIconWrapper color:"go"` + `CheckCircleSolid`). */
export function LinkedLine({ text = T.linked }: { text?: string }) {
  return (
    <p className="flex items-center gap-2 text-base font-medium">
      <CircleCheck className="h-5 w-5 text-ok" aria-hidden />
      {text}
    </p>
  );
}

/** HB's input at `size:"generous"`: 36px, 8px corners, filled #161616 with no border, #a6a6a6 placeholder. */
export const FIELD = cn(
  "h-9 w-full rounded-lg border-0 bg-[#161616] px-3 text-sm text-white placeholder:text-[#a6a6a6] outline-none",
  "focus-visible:ring-1 focus-visible:ring-border-light [html[data-theme=light]_&]:bg-black/5 [html[data-theme=light]_&]:text-fg",
);
