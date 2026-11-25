"use client";


import { useEffect, useRef } from "react";
import { useRouter } from "next/navigation";
import { useQuery } from "@tanstack/react-query";
import { ScopeOverride, useScope } from "@/contexts/ScopeContext";
import { useAccountLabel } from "@/hooks/useAccounts";
import { useOfChat } from "@/lib/ofMirrorChat";
import { useOfCollections } from "@/lib/ofMirrorCollections";
import { useOfData } from "@/lib/ofMirrorData";
import { useOfChats } from "@/lib/ofMirrorChats";
import { useOfPinHome } from "@/lib/ofMirrorPinHome";
import { useOfNotifications } from "@/lib/ofMirrorNotifications";
import { useOfLanguage } from "@/lib/ofMirrorLanguage";
import { useOfQr } from "@/lib/ofMirrorQr";
import { useOfPhone } from "@/lib/ofMirrorPhone";
import { useOfStreamBlocked } from "@/lib/ofMirrorStreamBlocked";
import { useOfGoLiveWindow } from "@/lib/ofMirrorGoLiveWindow";
import { useOfPostActions } from "@/lib/ofMirrorHome";
import { ofMeQuery, useOfIdentity } from "@/lib/ofMirrorIdentity";
import { useOfMoney } from "@/lib/ofMirrorMoney";
import { scrollToHash, useOfOffers } from "@/lib/ofMirrorOffers";
import { useOfChatTools } from "@/lib/ofMirrorChatTools";
import { useOfChrome } from "@/lib/ofMirrorChrome";
import { useOfMessageMenu } from "@/lib/ofMirrorMessageMenu";
import { useOfPost, useOfStory } from "@/lib/ofMirrorPost";
import { useOfProfile, useStandIn } from "@/lib/ofMirrorProfile";
import { useOfQueue } from "@/lib/ofMirrorQueue";
import { useOfReleaseForms } from "@/lib/ofMirrorReleaseForms";
import { useOfStats } from "@/lib/ofMirrorStats";
import { useOfSubscription } from "@/lib/ofMirrorSubscription";
import { useOfRow } from "@/lib/ofMirrorRow";
import { useOfSettings } from "@/lib/ofMirrorSettings";
import { useOfSettingsWrites } from "@/lib/ofMirrorSettingsWrites";
import { useOfScheduleSearch } from "@/lib/ofMirrorScheduleSearch";
import { useOfStreamCopy } from "@/lib/ofMirrorStreamCopy";
import { useOfTheme } from "@/lib/ofMirrorTheme";
import { useOfTooltips } from "@/lib/ofMirrorTooltip";
import { useOfVault } from "@/lib/ofMirrorVault";
import { useOfWrites } from "@/lib/ofMirrorWrites";

const NEW_POST_SRC = /^\/of-mirror\/pages\/new-post\//;

export function OfMirrorFrame({ src, title }: { src: string; title: string }) {
  const standIn = useStandIn(src);
  return (
    <ScopeOverride accountId={standIn}>
      <Frame src={src} title={title} standIn={standIn} />
    </ScopeOverride>
  );
}

function StandInHint({ accountId }: { accountId: string }) {
  const nickname = useAccountLabel(accountId);
  const name = useQuery(ofMeQuery(accountId)).data?.name || nickname;
  return (
    <div className="shrink-0 px-4 py-1.5 text-xs text-fg-dim border-b border-border" data-testid="of-standin-hint">
      Showing {name}, pick a model to switch
    </div>
  );
}

function Frame({ src, title, standIn }: { src: string; title: string; standIn: string | null }) {
  const ref = useRef<HTMLIFrameElement>(null);
  const router = useRouter();
  const { setScope } = useScope();
  useOfChrome(ref, src);
  useOfIdentity(ref, src);
  useOfSettings(ref, src);
  useOfWrites(ref, src);
  useOfSettingsWrites(ref, src, standIn);
  useOfSubscription(ref, src);
  useOfQr(ref, src);
  useOfLanguage(ref, src);
  useOfStreamBlocked(ref, src);
  useOfStreamCopy(ref, src, standIn);
  useOfScheduleSearch(ref, src);
  useOfGoLiveWindow(ref, src);
  useOfOffers(ref, src);
  useOfPost(ref, src);
  useOfStory(ref, src);
  useOfChat(ref, src);
  useOfChatTools(ref, src);
  useOfMessageMenu(ref, src);
  useOfRow(ref, src);
  // after useOfRow: its load handler runs later, so the real rows win
  useOfData(ref, src);
  useOfChats(ref, src);
  useOfPinHome(ref, src);
  useOfQueue(ref, src);
  useOfNotifications(ref, src);
  useOfReleaseForms(ref, src);
  useOfMoney(ref, src);
  useOfStats(ref, src);
  useOfTooltips(ref, src);
  useOfPostActions(ref, src);
  useOfProfile(ref, src);
  useOfVault(ref, src);
  // after useOfData: the list page's real user cards are there to mark
  useOfCollections(ref, src);
  const dark = useOfTheme(ref, src);
  useOfPhone(ref, src);

  useEffect(() => {
    const frame = ref.current;
    if (!frame) return;
    const onClick = (ev: MouseEvent) => {
      const a = (ev.target as Element | null)?.closest?.("a");
      const href = a?.getAttribute("href");
      if (!href) return;
      if (href === "#") return ev.preventDefault();
      if (ev.button !== 0 || ev.metaKey || ev.ctrlKey || ev.shiftKey || ev.altKey) return;
      if (href.startsWith("/of-manager/")) {
        ev.preventDefault();
        if (standIn && NEW_POST_SRC.test(src) && a?.closest(".b-story-item") && !href.startsWith("/of-manager/new-post")) setScope({ kind: "model", accountId: standIn });
        router.push(href);
      }
    };
    const attach = () => {
      frame.contentDocument?.addEventListener("click", onClick);
      if (frame.contentDocument) scrollToHash(frame.contentDocument, window.location.hash);
    };
    if (frame.contentDocument?.readyState === "complete") attach();
    frame.addEventListener("load", attach);
    return () => {
      frame.removeEventListener("load", attach);
      frame.contentDocument?.removeEventListener("click", onClick);
    };
  }, [src, router, standIn, setScope]);

  return (
    <div className="flex flex-col h-chat">
      {standIn && <StandInHint accountId={standIn} />}
      {/* key: fresh frame per page, so Back stays one step per page; one tree with or without the hint, so the stand-in arriving does not remount it */}
      <iframe key={src} ref={ref} src={src} title={title} className={`block w-full flex-1 min-w-0 min-h-0 border-0 ${dark ? "bg-[#161618]" : "bg-white"}`} />
    </div>
  );
}
