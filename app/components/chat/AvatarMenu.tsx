"use client";

/**
 * FanAvatarMenu — the Avatar menu, opened from the Fan's avatar in the Chat
 * header (docs/spec/phase-03-chat-header-message-list.md, H3, M3, F4, F5;
 * ticket 95). Its rows, in order:
 *   • "Subscription status": the Fan's OF user's `subscribedOnData.status`;
 *     with no status but an `expiredAt` in the past, "Expired"
 *   • "Earnings": `subscribedOnData.totalSumm` (dollars this Creator was paid)
 *   • "Special offers ▸": OF's "Give user a discount" (`DiscountSubmenu`),
 *     offered as OF offers it (`discountShown`: a current or past
 *     subscriber, not blocked, on a page priced above OF's floor); else the
 *     row is disabled, its title saying why
 *   • "Add to lists ▸": the Creator's lists from `/chats/folders`, the Fan's
 *     marked; a click POSTs or DELETEs `/lists/{id}/users/{fanId}`. Moved
 *     from the Kebab menu (`ChatActionsMenu`) unchanged but for its Geometry.
 * Unknown values read "—". The Chat header owns the open state, the trigger
 * and the dismissal (`useMenuDismiss`); this module is the menu's box.
 */

import { useState } from "react";
import { useQueryClient } from "@tanstack/react-query";

import { cn } from "@/lib/utils";
import { MP } from "@/lib/messagesPro";
import { relay } from "@/lib/relay";
import { sameUserId, type FanId } from "@/lib/fanId";
import { fmtCents } from "@/lib/format";
import { discountShown } from "@/lib/fanDiscount";
import { useOFUser, type OFSubscribedOnData } from "@/hooks/useOFUser";
import { useAllChatFolders, type ChatFolder } from "@/hooks/useChatFolders";
import { usePaidPage } from "@/hooks/usePaidPage";
import { DiscountSubmenu } from "./DiscountSubmenu";
import { MENU, MENU_ROW, MenuStatusLine, useMenuStatus } from "./MenuParts";

/** The "Subscription status" value (spec F5): the status as OF reports it,
 *  else "Expired" once the expiry has passed, else "—". */
function subscriptionStatus(sub: OFSubscribedOnData | undefined): string {
  if (sub?.status) return sub.status;
  const expiry = sub?.expiredAt ? new Date(sub.expiredAt).getTime() : NaN;
  return expiry < Date.now() ? "Expired" : "—";
}

/** The "Earnings" value (spec F5): `totalSumm` is in dollars. */
function earnings(sub: OFSubscribedOnData | undefined): string {
  return typeof sub?.totalSumm === "number" ? fmtCents(Math.round(sub.totalSumm * 100)) : "—";
}

export function FanAvatarMenu({ id, accountId, fanId }: { id: string; accountId: string; fanId: FanId }) {
  // The Fan's full OF profile: no request while cached (the drawer, a prefetch's
  // prefetch); else one read (useOFUser).
  const fan = useOFUser(accountId, fanId).data;
  const sub = fan?.subscribedOnData;
  // Warm the lists so "Add to lists ▸" opens at once (shared query key).
  useAllChatFolders(accountId);
  // The Creator's subscription price (dollars), which bounds the discount.
  const { subscribePrice: price } = usePaidPage(accountId);
  const loaded = !!fan && price !== null;
  const canDiscount = loaded && discountShown(fan, price);
  const [submenu, setSubmenu] = useState<"lists" | "discount" | null>(null);
  const { status, flash } = useMenuStatus();

  return (
    <div
      id={id}
      role="menu"
      aria-label="Avatar menu"
      className={cn(MENU, MP.ours.FanAvatarMenu.place)}
    >
      {submenu === "lists" ? (
        <ToggleListsSubmenu
          accountId={accountId}
          fanId={fanId}
          onFlash={flash}
          onBack={() => setSubmenu(null)}
        />
      ) : submenu === "discount" && canDiscount ? (
        <DiscountSubmenu
          accountId={accountId}
          fanId={fanId}
          price={price}
          current={sub?.discountPercent ?? 0}
          currentPeriod={sub?.discountPeriod ?? 1}
          onFlash={flash}
          onBack={() => setSubmenu(null)}
        />
      ) : (
        <>
          <div className={MENU_ROW}>
            <span>Subscription status</span>
            <span className="ml-auto text-fg-dim">{subscriptionStatus(sub)}</span>
          </div>
          <div className={MENU_ROW}>
            <span>Earnings</span>
            <span className="ml-auto text-fg-dim">{earnings(sub)}</span>
          </div>
          <button
            type="button"
            // aria-disabled, not disabled, so the title still shows (as `NotWiredMenuRow`).
            aria-disabled={!canDiscount}
            title={canDiscount ? undefined : loaded
              ? "OF offers a discount only to a current or past subscriber, not blocked, on a paid page"
              : "Loading…"}
            onClick={() => canDiscount && setSubmenu("discount")}
            className={cn(MENU_ROW, canDiscount ? "hover:bg-bg-elev-1" : "text-fg-dim cursor-not-allowed")}
          >
            Special offers ▸
          </button>
          <button
            type="button"
            onClick={() => setSubmenu("lists")}
            className={cn(MENU_ROW, "hover:bg-bg-elev-1")}
          >
            Add to lists ▸
          </button>
        </>
      )}
      <MenuStatusLine status={status} />
    </div>
  );
}

function ToggleListsSubmenu({
  accountId, fanId, onFlash, onBack,
}: {
  accountId: string;
  fanId: FanId;
  onFlash: (ok: boolean, msg: string) => void;
  onBack: () => void;
}) {
  const qc = useQueryClient();
  // The lists an operator can add/remove a fan to come from /chats/folders
  // (custom + close-friends lists, canAddUsers=true) — NOT the OF /users
  // listsStates, which only returns SYSTEM buckets (fans/following/…) with
  // canAddUser=false. Reading listsStates is why this menu used to say "No
  // lists you can modify" even on accounts with dozens of custom lists.
  const foldersQ = useAllChatFolders(accountId);
  // In-flight list ids so we disable just the row being toggled.
  const [busy, setBusy] = useState<Set<string>>(new Set());
  // Optimistic membership overrides — OF's users[] preview is capped so we
  // can't always know membership up front; flip it locally on click.
  const [override, setOverride] = useState<Map<string, boolean>>(new Map());

  const lists = (foldersQ.data ?? []).filter((f) => f.canAddUsers);

  function isMember(f: ChatFolder): boolean {
    const idStr = String(f.id);
    if (override.has(idStr)) return !!override.get(idStr);
    return (f.users ?? []).some((u) => sameUserId(u.id, fanId));
  }

  async function toggle(f: ChatFolder) {
    const idStr = String(f.id);
    const currentlyIn = isMember(f);
    setBusy((prev) => new Set(prev).add(idStr));
    try {
      if (currentlyIn) {
        await relay.delete(
          `/api/of/v2/lists/${encodeURIComponent(idStr)}/users/${fanId}`,
          { accountId },
        );
        onFlash(true, `Removed from "${f.name || idStr}"`);
      } else {
        await relay.post(
          `/api/of/v2/lists/${encodeURIComponent(idStr)}/users/${fanId}`,
          undefined,
          { accountId },
        );
        onFlash(true, `Added to "${f.name || idStr}"`);
      }
      setOverride((prev) => new Map(prev).set(idStr, !currentlyIn));
      // Membership changed → refresh the folder chips/counts + roster so the
      // VIP/list view reflects it immediately.
      qc.invalidateQueries({ queryKey: ["chat-folders", accountId] });
      qc.invalidateQueries({ queryKey: ["chats"] });
    } catch (e) {
      onFlash(false, (e as Error).message || "Couldn't update that list");
    } finally {
      setBusy((prev) => {
        const next = new Set(prev);
        next.delete(idStr);
        return next;
      });
    }
  }

  return (
    <>
      <button
        type="button"
        onClick={onBack}
        className={cn(MENU_ROW, "text-fg-dim hover:text-fg hover:bg-bg-elev-1")}
      >
        ← Back
      </button>
      <div role="separator" className={cn(MP.menu.divider, "bg-border")} />
      {foldersQ.isLoading && (
        <div className={cn(MENU_ROW, "text-fg-dim")}>Loading lists…</div>
      )}
      {foldersQ.isError && (
        <div className={cn(MENU_ROW, "text-err")}>
          {(foldersQ.error as Error)?.message || "Failed to load lists"}
        </div>
      )}
      {!foldersQ.isLoading && !foldersQ.isError && lists.length === 0 && (
        <div className={cn(MENU_ROW, "text-fg-dim")}>
          No custom lists on this account yet. Create one on OF first.
        </div>
      )}
      {lists.map((f) => {
        const idStr = String(f.id);
        const inList = isMember(f);
        const inflight = busy.has(idStr);
        return (
          <button
            key={idStr}
            type="button"
            disabled={inflight}
            onClick={() => toggle(f)}
            aria-pressed={inList}
            className={cn(MENU_ROW, "hover:bg-bg-elev-1 disabled:opacity-60 disabled:hover:bg-transparent")}
            title={inList ? "Remove from list" : "Add to list"}
          >
            <span
              aria-hidden
              className={cn(
                MP.ours.ToggleListsSubmenu.check,
                "grid place-items-center shrink-0",
                inList ? "bg-accent border-accent text-white" : "border-border bg-bg",
              )}
            >
              {inList ? "✓" : ""}
            </span>
            <span className="flex-1 truncate">{f.name || `list ${idStr}`}</span>
            {typeof f.usersCount === "number" && (
              <span className={cn(MP.ours.ToggleListsSubmenu.count, "text-fg-dim")}>{f.usersCount}</span>
            )}
            {inflight && <span className={cn(MP.ours.ToggleListsSubmenu.count, "text-fg-dim")}>…</span>}
          </button>
        );
      })}
    </>
  );
}
