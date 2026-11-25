"use client";


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
import { useCan } from "@/hooks/useCan";
import { DiscountSubmenu } from "./DiscountSubmenu";
import { MENU, MENU_ROW, MenuStatusLine, useMenuStatus } from "./MenuParts";

function subscriptionStatus(sub: OFSubscribedOnData | undefined): string {
  if (sub?.status) return sub.status;
  const expiry = sub?.expiredAt ? new Date(sub.expiredAt).getTime() : NaN;
  return expiry < Date.now() ? "Expired" : "—";
}

function earnings(sub: OFSubscribedOnData | undefined): string {
  return typeof sub?.totalSumm === "number" ? fmtCents(Math.round(sub.totalSumm * 100)) : "—";
}

export function FanAvatarMenu({ id, accountId, fanId }: { id: string; accountId: string; fanId: FanId }) {
  const fan = useOFUser(accountId, fanId).data;
  const sub = fan?.subscribedOnData;
  useAllChatFolders(accountId);
  const listsShown = useCan(accountId, "filter_folders");
  const offersShown = useCan(accountId, "discount");
  const { subscribePrice: price } = usePaidPage(offersShown ? accountId : null);
  const loaded = !!fan && price !== null;
  const canDiscount = offersShown && loaded && discountShown(fan, price);
  const [submenu, setSubmenu] = useState<"lists" | "discount" | null>(null);
  const { status, flash } = useMenuStatus();

  return (
    <div
      id={id}
      role="menu"
      aria-label="Avatar menu"
      className={cn(MENU, MP.ours.FanAvatarMenu.place)}
    >
      {submenu === "lists" && listsShown ? (
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
          {offersShown && (
            <button
              type="button"
              aria-disabled={!canDiscount}
              title={canDiscount ? undefined : loaded
                ? "OF offers a discount only to a current or past subscriber, not blocked, on a paid page"
                : "Loading…"}
              onClick={() => canDiscount && setSubmenu("discount")}
              className={cn(MENU_ROW, canDiscount ? "hover:bg-bg-elev-1" : "text-fg-dim cursor-not-allowed")}
            >
              Special offers ▸
            </button>
          )}
          {listsShown && (
            <button
              type="button"
              onClick={() => setSubmenu("lists")}
              className={cn(MENU_ROW, "hover:bg-bg-elev-1")}
            >
              Add to lists ▸
            </button>
          )}
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
  const foldersQ = useAllChatFolders(accountId);
  const [busy, setBusy] = useState<Set<string>>(new Set());
  // OF's users[] preview is capped, so membership isn't always known up front.
  const [override, setOverride] = useState<Map<string, boolean>>(new Map());

  // /chats/folders, not the OF /users listsStates: that only returns system buckets with canAddUser=false.
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
      qc.invalidateQueries({ queryKey: ["chat-folders", accountId] });
      qc.invalidateQueries({ queryKey: ["fan-lists", accountId] });
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
