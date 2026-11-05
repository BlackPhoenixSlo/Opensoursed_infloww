"use client";

/**
 * The free trial in the chrome: the top bar's "You're on a free trial / N days
 * left" next to the sidebar toggle (Infloww's header FreeTrialRender, hidden
 * once the trial ends), the "Your 7-day free trial has started." banner under
 * the top bar while the trial runs (Infloww's `free_trial_started` global
 * banner; its close is remembered per principal), and the expired-trial nag
 * shown once per app start.
 * The nag never blocks: closing it carries on as normal, and nothing
 * remembers the close, so the next page load shows it again. Settings ›
 * Preferences "Disable free trial popup" (Applied `hide_trial_popup`) turns it
 * off; it waits for this load's own read of it (or its failure), never the
 * saved snapshot's, so it never flashes and a pre-save answer never shows it.
 */

import { useState, useSyncExternalStore } from "react";
import * as Dialog from "@radix-ui/react-dialog";
import { X } from "lucide-react";

import { useAppliedSettingsAfterMount } from "@/lib/appliedSettings";
import { useUser } from "@/contexts/UserContext";
import { useChatter } from "@/contexts/ChatterContext";
import { IfButton } from "@/components/ui/infloww";
import { IF_MODAL_BOX, IF_MODAL_MASK } from "@/components/ui/ifModal";
import { InfoCircleSolid } from "@/components/shell/inflowwIcons";
import { BUY_URL, trialDaysLeft } from "@/lib/freeTrial";
import { subscribeToStorage } from "@/lib/storageSync";

/** Days left on the signed-in principal's trial (the User cookie wins, as
 *  everywhere), 0 once over, null while unknown. */
export function useTrialDaysLeft(): number | null {
  const { user } = useUser();
  const { chatter } = useChatter();
  return trialDaysLeft(user ? user.created_at : chatter?.created_at);
}

export function FreeTrialBadge() {
  const days = useTrialDaysLeft();
  if (!days) return null;
  return (
    <div className="hidden md:flex flex-col justify-center leading-tight shrink-0">
      <span className="text-xs font-medium text-nav-fg-active">You&rsquo;re on a free trial</span>
      <span className="text-sm font-medium text-nav-fg">
        {days} {days === 1 ? "day" : "days"} left
      </span>
    </div>
  );
}

const BANNER_CLOSED_EVENT = "trial-started-banner-closed";
const subscribeBannerClosed = subscribeToStorage(BANNER_CLOSED_EVENT);
const bannerClosedKey = (id: string) => `trial-started-banner-closed:${id}`;

/** "Your 7-day free trial has started.": 40px under the top bar while the
 *  trial runs, until closed. `data-trial-banner` grows `--chrome-top` by its
 *  48px (globals.css). The server render has no storage, so it shows after
 *  hydration. */
export function FreeTrialBanner() {
  const days = useTrialDaysLeft();
  const { user } = useUser();
  const { chatter } = useChatter();
  const id = user ? user.user_id : chatter?.chatter_id;
  const closed = useSyncExternalStore(
    subscribeBannerClosed,
    () => !id || localStorage.getItem(bannerClosedKey(id)) === "1",
    () => true,
  );
  if (!days || closed) return null;
  const close = () => {
    if (!id) return;
    localStorage.setItem(bannerClosedKey(id), "1");
    window.dispatchEvent(new Event(BANNER_CLOSED_EVENT));
  };
  return (
    <div
      data-trial-banner
      role="status"
      className="mx-3 mb-2 h-10 px-3 rounded-lg bg-info/[14.5%] flex items-center gap-2 text-sm text-nav-fg-active"
    >
      <InfoCircleSolid aria-hidden className="w-4 h-4 shrink-0 text-info" />
      <span className="flex-1 min-w-0 truncate">Your 7-day free trial has started.</span>
      <button
        type="button"
        onClick={close}
        className="w-[26px] h-[26px] shrink-0 rounded-md bg-nav-surface hover:bg-nav-hover grid place-items-center text-nav-fg-active"
        aria-label="Close banner"
      >
        <X aria-hidden className="w-3 h-3" />
      </button>
    </div>
  );
}

export function FreeTrialExpiredModal() {
  const expired = useTrialDaysLeft() === 0;
  // Unknown until this load's Applied read answers; a failed read shows the nag (the default).
  const { settings, failed } = useAppliedSettingsAfterMount(expired);
  const allowed = settings ? settings.preferences?.hide_trial_popup !== true : failed;
  // Per mount: AppShell mounts once per page load, so this is per app start.
  const [closed, setClosed] = useState(false);
  return (
    <Dialog.Root open={expired && allowed && !closed} onOpenChange={(o) => { if (!o) setClosed(true); }}>
      <Dialog.Portal>
        {/* IfModal's look (antd's modal), kept on Radix: the 70% mask, the kit box, the × 16px in. */}
        <Dialog.Overlay className={`fixed inset-0 z-[60] ${IF_MODAL_MASK}`} />
        <Dialog.Content
          className={`fixed left-1/2 top-1/2 z-[60] w-[416px] max-w-[calc(100vw-32px)] -translate-x-1/2 -translate-y-1/2 ${IF_MODAL_BOX}`}
        >
          <Dialog.Title className="px-6 pr-12 pt-[22px] text-[16px] font-semibold">Free trial exceeded</Dialog.Title>
          <Dialog.Close
            className="absolute right-4 top-4 grid h-6 w-6 place-items-center rounded text-muted hover:text-fg"
            aria-label="Close"
          >
            <X aria-hidden className="h-4 w-4" />
          </Dialog.Close>
          <Dialog.Description className="p-6 text-[14px] text-fg-dim">
            Your free trial has expired. Please{" "}
            <a href={BUY_URL} target="_blank" rel="noopener noreferrer" className="text-accent underline">
              click here to buy
            </a>
            .
          </Dialog.Description>
          <div className="flex justify-end gap-2 px-6 pb-5">
            <Dialog.Close asChild>
              <IfButton>Continue</IfButton>
            </Dialog.Close>
            <IfButton variant="primary" onClick={() => window.open(BUY_URL, "_blank", "noopener,noreferrer")}>
              Buy now
            </IfButton>
          </div>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}
