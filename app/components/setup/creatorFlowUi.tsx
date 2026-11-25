"use client";


import { CircleCheck } from "lucide-react";
import type { ReactNode } from "react";

import { HB_TEXT } from "@/components/ui/ifSelect";
import { HbModal } from "@/components/ui/infloww";
import { cn } from "@/lib/utils";
import { BRAND_NAME } from "@/lib/brand";

export const T = {
  addCreator: "Add creator",
  linkCreatorAccount: "Link creator account",
  creatorDetails: "Creator details",
  displayImage: "Display image",
  creatorName: "Creator name",
  enterName: "Please enter a name",
  namePattern: "Please input [0-9] or [a-z] or [A-Z]",
  gender: "Gender",
  done: "Done",
  nextLink: "Next: Link creator account",
  next: "Next",
  newCreatorAdded: "New creator added",
  whichPlatform: "Which platform’s account would you like to link?",
  onePerPlatform: (platform: string) =>
    `Each creator can only link one account from each platform. This creator already has an account from ${platform} linked.`,
  proxySelection: "Proxy selection",
  proxyRequired: `Using a proxy is required to manage the creator’s account on ${BRAND_NAME} and allow employees to chat with fans, without revealing the creator’s login information. All your data is safe with us.`,
  customProxy: "Custom proxy",
  useOwnProxy: "Use your own proxy",
  newProxy: "New proxy",
  checking: "Loading...",
  proxyError: "Error message",
  connectOnlyFans: "Connect OnlyFans",
  linkPlatformAccount: (platform: string) => `Link ${platform} account`,
  linked: `Creator account is linked to ${BRAND_NAME}`,
  accountDetails: "Account details",
  nickname: "Nickname",
  tagOptional: "Tag (Optional)",
  tag: "Tag",
  assignedEmployees: "Assigned employees (Optional)",
  selectEmployee: "Select employee",
  notesOptional: "Internal notes (Optional)",
  notesPlaceholder: "Add notes about creator account",
  updateSuccess: "Update Success",
  stepOf: (i: number, n: number) => `Step ${i} of ${n}`,
  cancel: "Cancel",
  save: "Save",
  editAccountDetails: "Edit account details",
  editCreatorDetails: "Edit creator details",
  platform: "Platform",
  linkedAccount: "Linked account",
  connectedAccount: "Connected account",
  notConnected: "Not connected",
  disconnected: "Disconnected",
  linkAccount: "Link account",
  unlink: "Unlink",
  proxyConnection: "Proxy connection",
  connection: "Connection",
  change: "Change",
  del: "Delete",
  changeProxy: "Change proxy",
  switchProxySuccess: "Switch Proxy Success",
  faceIdTitle: "Face ID Verification",
  selectRoleTitle: "Select your role",
  altMethodTitle: "Linking OnlyFans account (Alternative method)",
  stillUnable: `Still unable to perform verification and link OnlyFans account to ${BRAND_NAME}?`,
  learnMore: "Learn More",
  copy: "Copy",
  copied: "Copy successfully",
  deleteCreator: "Delete creator",
  submit: "Submit",
  back: "Back",
  deleteTitle: (creator: string, nickname?: string) =>
    nickname ? `Delete ${creator} / ${nickname}` : `Delete ${creator}`,
  deleteMessage: (creator: string, nickname?: string) =>
    nickname
      ? `All data under ${nickname} will be permanently deleted from ${BRAND_NAME}. This action cannot be undone.`
      : `All platform accounts and related data under ${creator} will be permanently deleted from ${BRAND_NAME}. This action cannot be undone.`,
  surveyTitle: "Why are you deleting the creator's account?",
  optional: "Optional",
  surveyReasons: [
    "Creator is no longer with our agency",
    "Transferred creator to a partner agency",
    "Creator was added for testing purposes only",
    "Migrating creator to another software/CRM/internal solution",
    "Others",
  ],
  surveyOther: "Reason for deleting creator",
  deleted: (name: string) => `${name} deleted`,
} as const;


export const HB_DIM = "text-white/[.62] [html[data-theme=light]_&]:text-black/[.62]";

export function FlowModal({ title, onClose, footer, children, closable = true }: {
  title?: string;
  onClose: () => void;
  footer?: ReactNode;
  children: ReactNode;
  closable?: boolean;
}) {
  return (
    <HbModal title={title} width={600} onClose={onClose} footer={footer} closable={closable} className="max-md:max-h-[calc(100dvh-2rem)]">
      <div className={cn("text-[14px] leading-normal", HB_TEXT)}>{children}</div>
    </HbModal>
  );
}

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
export const STEP_TITLE = "mb-4 text-[20px] font-medium leading-6";

export function LinkedLine({ text = T.linked }: { text?: string }) {
  return (
    <p className="flex items-center gap-2 text-base font-medium">
      <CircleCheck className="h-5 w-5 text-ok" aria-hidden />
      {text}
    </p>
  );
}

export const FIELD = cn(
  "h-9 w-full rounded-lg border-0 bg-[#161616] px-3 text-sm text-white placeholder:text-[#a6a6a6] outline-none",
  "focus-visible:ring-1 focus-visible:ring-border-light [html[data-theme=light]_&]:bg-black/5 [html[data-theme=light]_&]:text-fg",
);
