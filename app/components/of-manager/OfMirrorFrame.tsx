"use client";

/**
 * One mirrored OnlyFans page (public/of-mirror/pages, built by
 * scripts/of-mirror.mjs) in a same-origin iframe, so OF's global CSS
 * never touches our shell. Links the mirror points at /of-manager/*
 * carry target="_top" (a full navigation if this script is not attached yet);
 * once the frame loads they become client-side router pushes. Every other OF
 * link is "#" and inert. Settings writes: see useOfWrites; New post: see useOfPost; Add to story: see useOfStory; OF's dark mode follows
 * our theme: see useOfTheme; with a single model the list pages show its real rows
 * (chats, a chat's thread, vault folders, user lists): see useOfData, and their post rows' like, comments and
 * own-post menu work: see useOfPostActions; My profile's own controls: see useOfProfile; the Vault page's
 * filters and folder and media writes: see useOfVault; otherwise a
 * chat or list row's page shows that example row: see useOfRow. My profile, the avatar menu, Messages, the Queue,
 * Statements' Earnings, New post, Statistics, the Vault and Release forms in All models show the first model (ScopeOverride), with a
 * "Showing <model>" line over the frame: see standInModel and useStandIn. OF's --vh and its phone bar (main.js setVHVariable,
 * WebsiteHeader's isXSMQ) are set from the frame's own size: see ofMirrorPhone. A chat has Messages Pro's Fan insights
 * and Scripts beside it: see OfChatSidePanel.
 */

import { useEffect, useRef } from "react";
import { useRouter } from "next/navigation";
import { useQuery } from "@tanstack/react-query";
import { ScopeOverride, useScope } from "@/contexts/ScopeContext";
import { OfChatSidePanel } from "@/components/of-manager/OfChatSidePanel";
import { useAccountLabel } from "@/hooks/useAccounts";
import { useOfChat } from "@/lib/ofMirrorChat";
import { useOfCollections } from "@/lib/ofMirrorCollections";
import { useOfData } from "@/lib/ofMirrorData";
import { useOfChats } from "@/lib/ofMirrorChats";
import { useOfLanguage } from "@/lib/ofMirrorLanguage";
import { useOfQr } from "@/lib/ofMirrorQr";
import { useOfPhone } from "@/lib/ofMirrorPhone";
import { useOfStreamBlocked } from "@/lib/ofMirrorStreamBlocked";
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
import { useOfTheme } from "@/lib/ofMirrorTheme";
import { useOfTooltips } from "@/lib/ofMirrorTooltip";
import { useOfVault } from "@/lib/ofMirrorVault";
import { useOfWrites } from "@/lib/ofMirrorWrites";

/** New post's pages (new-post/index, new-post/state-*). */
const NEW_POST_SRC = /^\/of-mirror\/pages\/new-post\//;

export function OfMirrorFrame({ src, title }: { src: string; title: string }) {
  const standIn = useStandIn(src);
  return (
    <ScopeOverride accountId={standIn}>
      <Frame src={src} title={title} standIn={standIn} />
    </ScopeOverride>
  );
}

/** "Showing <model>, pick a model to switch": its OF name, else its nickname. */
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
  useOfChrome(ref, src); // OF's own left nav hidden, as Infloww: our sidebar navigates
  useOfIdentity(ref, src);
  useOfSettings(ref, src);
  useOfWrites(ref, src);
  useOfSettingsWrites(ref, src);
  useOfSubscription(ref, src); // Subscription settings: promotion, bundle, tracking and free trial link rows
  useOfQr(ref, src); // Settings > QR code: OF's code, its two switches and Download
  useOfLanguage(ref, src); // Settings > Display > Language: OF's client-only pick, and Display's row
  useOfStreamBlocked(ref, src); // Settings > Streaming > Blocked users: OF's list, read-only
  useOfOffers(ref, src); // the promotion, bundle and free trial link dialogs, the trial links' sort and share, Stop promotion
  useOfPost(ref, src);
  useOfStory(ref, src);
  useOfChat(ref, src); // a chat's composer and New message
  useOfChatTools(ref, src); // a chat's header tools (rename, lists, notes) and its ⋮ menu
  useOfMessageMenu(ref, src); // a message's ⋮ menu and the pinned page's Unpin all
  useOfRow(ref, src);
  useOfData(ref, src); // after useOfRow: its load handler runs later, so the real rows win
  useOfChats(ref, src); // the chat list's tabs, sort menu, search, folders, Clear messages and Mark all as read
  useOfQueue(ref, src);
  useOfReleaseForms(ref, src); // Release forms: the Tag user and Release form lists, their search, Sort, row More and Invite
  useOfMoney(ref, src); // Statements and Statistics balances, earning statistics, referral earnings, chargeback ratio
  useOfStats(ref, src); // Statistics: the period menu, figures, tables, charts and chargeback ratio for the period picked
  useOfTooltips(ref, src); // Statistics and Statements: OF's hover text on its "i" icons and status tips
  useOfPostActions(ref, src);
  useOfProfile(ref, src); // My profile's Story archive, Copy link, More info, Spotify and Media tabs, in place
  useOfVault(ref, src);
  useOfCollections(ref, src); // after useOfData: the list page's real user cards are there to mark
  const dark = useOfTheme(ref, src);
  useOfPhone(ref, src); // OF's --vh, its phone bar below XS and a state page's open menu below SM

  useEffect(() => {
    const frame = ref.current;
    if (!frame) return;
    const onClick = (ev: MouseEvent) => {
      const a = (ev.target as Element | null)?.closest?.("a");
      const href = a?.getAttribute("href");
      if (!href) return;
      if (href === "#") return ev.preventDefault();
      // Let modified clicks open a real tab via target="_top".
      if (ev.button !== 0 || ev.metaKey || ev.ctrlKey || ev.shiftKey || ev.altKey) return;
      if (href.startsWith("/of-manager/")) {
        ev.preventDefault();
        // New post's tiles that leave it (Go live, Send message) in All models: their page opens for the model the
        // composer shows, which becomes the selected model. Its promotion and trial link dialogs open over New post, in
        // the scope it has.
        if (standIn && NEW_POST_SRC.test(src) && a?.closest(".b-story-item") && !href.startsWith("/of-manager/new-post")) setScope({ kind: "model", accountId: standIn });
        router.push(href);
      }
    };
    const attach = () => {
      frame.contentDocument?.addEventListener("click", onClick);
      // The app URL's hash (AFTER_NEW_POST_PROMOTION's #promotion) is for the page in the frame, as OF's.
      if (frame.contentDocument) scrollToHash(frame.contentDocument, window.location.hash);
    };
    if (frame.contentDocument?.readyState === "complete") attach();
    frame.addEventListener("load", attach);
    return () => {
      frame.removeEventListener("load", attach);
      frame.contentDocument?.removeEventListener("click", onClick);
    };
  }, [src, router, standIn, setScope]);

  // key: a fresh frame per page, so moving between pages adds no extra
  // entries to the joint session history (Back stays one step per page).
  // #161618: OF's dark --bg-color, so the frame never flashes white.
  // One tree with or without the hint: the stand-in arriving (the model list loads) must not remount the frame.
  return (
    <div className="flex flex-col h-chat">
      {standIn && <StandInHint accountId={standIn} />}
      <div className="flex flex-1 min-h-0">
        <iframe key={src} ref={ref} src={src} title={title} className={`block w-full flex-1 min-w-0 min-h-0 border-0 ${dark ? "bg-[#161618]" : "bg-white"}`} />
        <OfChatSidePanel frameRef={ref} src={src} />
      </div>
    </div>
  );
}
