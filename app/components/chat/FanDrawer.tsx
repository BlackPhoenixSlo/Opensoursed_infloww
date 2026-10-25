"use client";

/**
 * FanDrawer — slide-over panel on the right edge of the chat surface.
 *
 * Opens when the user clicks the chat header. A title head (reading the
 * active tab, with the "+" that adds a removed block back, and ×) sits over
 * Insights / Sales / Notes tabs chosen from a bottom tab bar. Insights holds
 * the editable fields:
 *   • Custom nickname  — what our team calls them ("the German guy")
 *   • Notes            — free-form per-team memory
 *   • Tags             — comma-separated chips
 *
 * Insights' blocks (Spending behavior first by default, then the rest, and
 * last the Fan's identity, the mass-exclude switches and the unsold PPVs)
 * can each be dragged by the grip to a new place or removed with ×; the
 * layout is saved for this browser (`useInsightsBlocks`).
 *
 * Save: every field saves on blur (notes/nickname) or chip-edit (tags).
 * The mutation patches the cache directly so the panel feels instant.
 *
 * `focusNotesRequest` (Phase 3 ticket 87, spec F23): the Chat header's "Notes"
 * raises it, and each instance answers a higher count by switching to Insights,
 * expanding the Notes block, then scrolling to and focusing Fan notes.
 * `focusNicknameRequest` (messages-pro-look-and-feel ticket 142) is its twin
 * for the Chat header's "Edit name" pencil: the Profile block and Nickname.
 */

import { Fragment, useCallback, useEffect, useId, useMemo, useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { useFan } from "@/hooks/useFan";
import { useAccountLabel } from "@/hooks/useAccounts";
import { OF_USER_STALE_MS, ofUserNameKey, useOFUser } from "@/hooks/useOFUser";
import { useMassExclude } from "@/hooks/useMassExclude";
import { useFanActivity } from "@/hooks/useLastPurchases";
import { useFanPpvHistory, type PpvHistoryItem, type PpvHistoryResp } from "@/hooks/useFanPpvHistory";
import { useFanChatMedia, type FanChatMediaItem } from "@/hooks/useFanChatMedia";
import { useFanInsights } from "@/hooks/useFanInsights";
import { fmtCents } from "@/lib/messageFormat";
import { fmtPrice } from "@/lib/format";
import { stripOFHtml } from "@/lib/ofHtml";
import { relay, SALARY_FREQUENCIES, type FanRecord, type OFChatItem, type VaultMedia } from "@/lib/relay";
import { vaultFilesFromChat } from "@/lib/vaultFiles";
import { proxyImage, proxyScrubFrame } from "@/lib/mediaUrl";
import { type FanId } from "@/lib/fanId";
import { MP } from "@/lib/messagesPro";
import { extraTitle } from "@/lib/openinflowwwwExtras";
import { useReorder } from "@/hooks/useReorder";
import { useOutsideClose } from "@/components/ui/Menu";
import { cn, fmtRelTime, interpretSubStatus, type SubStatusDisplay } from "@/lib/utils";
import { MENU, MENU_ITEM, MENU_ROW } from "./MenuParts";
import { PersonaClaims } from "./PersonaClaims";
import { useInsightsBlocks, type InsightsBlockId } from "./useInsightsBlocks";
import { type PickedTemplate } from "./TemplatePicker";

/** 🚫 Mass-exclude toggle — flags a fan onto MASSdmEXCLUDE so every mass send,
 *  priced or not (mass DM / mass PPV / online blast / nudge), skips them. It
 *  mirrors a server-side List(kind='exclude') to a same-named pinned OF list.
 *  Excluded fans STILL get welcomes / AI replies / manual 1:1s. Shares its query
 *  key with the chat-header ⋯ menu toggle so both stay in sync. Optimistic. */
function MassExcludeToggle({
  accountId, fanId, title, hint,
}: {
  accountId: string; fanId: FanId; title: string; hint: string;
}) {
  const { isOn, isLoading, toggle } = useMassExclude(accountId, fanId);
  return (
    <div title={extraTitle("Mass exclude")} className="flex items-center justify-between gap-3 rounded-md border border-border bg-bg px-2.5 py-2">
      <div className="min-w-0">
        <div className="text-xs font-medium text-fg flex items-center gap-1.5">
          <span>🚫</span> {title}
        </div>
        <div className={cn(MP.ours.FanDrawer.excludeHint, "hidden md:block text-fg-dim")}>{hint}</div>
      </div>
      <button
        type="button"
        role="switch"
        aria-checked={isOn}
        disabled={isLoading || toggle.isPending}
        onClick={() => toggle.mutate(!isOn)}
        title={isOn ? `Remove from ${title}` : `Add to ${title}`}
        className={cn(
          "relative shrink-0 w-12 h-7 md:w-10 md:h-6 rounded-full transition-colors disabled:opacity-50",
          isOn ? "bg-accent" : "bg-bg-elev-1 border border-border",
        )}
      >
        <span
          className={cn(
            "absolute top-0.5 left-0.5 w-6 h-6 md:w-5 md:h-5 rounded-full bg-white shadow transition-transform",
            isOn ? "translate-x-5 md:translate-x-4" : "translate-x-0",
          )}
        />
      </button>
    </div>
  );
}

/**
 * A Chat header focus request (Notes, spec F23; Nickname, ticket 142). A count
 * higher than this instance has answered calls `onAsk` during this render (the
 * switch to Insights) and becomes `asked`, which keys the field's block so it
 * remounts expanded (its one collapse rule); the effect then scrolls to and
 * focuses the field once it exists. It starts at 0, so an instance the click
 * itself mounts answers too. The hidden twin's field is `display: none` and
 * cannot take focus, so only the visible instance does. No field yet (the Fan
 * is still loading): `ready` re-runs the effect when it lands.
 */
function useFocusRequest<T extends HTMLElement>(request: number | undefined, onAsk: () => void, ready: unknown) {
  const ref = useRef<T>(null);
  const focusedRef = useRef(0);
  const [asked, setAsked] = useState(0);
  if ((request ?? 0) > asked) {
    setAsked(request ?? 0);
    onAsk();
  }
  useEffect(() => {
    const field = ref.current;
    if (asked <= focusedRef.current || !field) return;
    focusedRef.current = asked;
    field.scrollIntoView?.({ block: "nearest" });
    field.focus({ preventScroll: true });
  }, [asked, ready]);
  return { ref, asked };
}

export function FanDrawer({
  open, onClose, accountId, fanId, chat,
  pinned = false,
  onComposeWith,
  focusNotesRequest,
  focusNicknameRequest,
}: {
  open: boolean;
  onClose: () => void;
  accountId: string;
  fanId: FanId;
  chat: OFChatItem;
  /** When true, render as the lg+ in-flow Fan insights column (no backdrop,
   *  no click-out close). The slide-over twin below lg is the un-pinned form. */
  pinned?: boolean;
  /** When set, the Unsold-PPVs section's "Send to chat" buttons call
   *  this with a PickedTemplate-shaped payload to populate the parent
   *  Composer's text + attachments + price. Without it, that button
   *  is hidden — the drawer still shows the unsold list as a read-only
   *  preview (useful for the popout window where there's no composer). */
  onComposeWith?: (t: PickedTemplate) => void;
  /** The Chat header's "Notes" ask (spec F23): a count the Thread raises and
   *  passes to every Fan insights it mounts. Not a DOM id, because two mount
   *  at once (the slide-over and the pinned column). */
  focusNotesRequest?: number;
  /** The Chat header's "Edit name" ask, the twin of `focusNotesRequest`: the
   *  Profile block expanded and Nickname focused, so its save is the existing
   *  freshness-guarded one. */
  focusNicknameRequest?: number;
}) {
  const { data: fan, isLoading, update } = useFan(accountId, fanId);
  const accountLabel = useAccountLabel(accountId);
  const ofUserQ = useOFUser(accountId, fanId);
  // Wrapped in a stable single-element array so the underlying useQueries
  // sees the same identity unless accountId actually changes.
  const lastPurchaseAccountIds = useMemo(() => [accountId], [accountId]);
  const activity = useFanActivity(lastPurchaseAccountIds);
  const lastPurchase = activity.lastPurchase.get(`${accountId}:${fanId}`) ?? null;
  const recentSpend = activity.recentSpend.get(`${accountId}:${fanId}`) ?? 0;
  // Ledger page size — DB-side, bumped 20 at a time by Load more.
  const [salesLimit, setSalesLimit] = useState(12);
  const ppvHistoryQ = useFanPpvHistory(accountId, fanId, salesLimit);
  const insights = useFanInsights(accountId, fanId, open).data;
  // OF gallery for thumbnails + message text — gated on the drawer
  // being open AND the local ledger showing at least one PPV. Avoids
  // a wasted upstream call on every drawer mount. Cursor-paginated via
  // `last_id`; Load more calls fetchNextPage() so older pages append
  // rather than refetching the entire list.
  const chatMediaQ = useFanChatMedia(accountId, fanId, {
    purchased: true,
    limit: 20,
    enabled: open && (ppvHistoryQ.data?.items.length ?? 0) > 0,
  });
  // Flatten all loaded pages into one list for the row builder.
  const chatMediaFlat = useMemo(
    () => chatMediaQ.data?.pages.flatMap((p) => p.list) ?? [],
    [chatMediaQ.data],
  );

  // Unsold PPVs — same OF endpoint, drop `purchased=1`. We still pin
  // to `from_user=<accountId>` so we get creator-sent items only.
  // Filter for paid + not-yet-opened items; show the latest 2 in the
  // Unsold PPVs block. A page is every creator-sent media message, free
  // ones and bought PPVs included, so a Fan sent a lot since his last
  // unsold PPV has none on the first page: page on until 2 are found, at
  // most UNSOLD_MAX_PAGES pages. Another Fan's page kept as placeholder
  // while this one loads counts as loading, not as this Fan's.
  const unsoldChatMediaQ = useFanChatMedia(accountId, fanId, {
    purchased: false,
    limit: 20,
    enabled: open,
  });
  const unsoldPages = unsoldChatMediaQ.isPlaceholderData ? undefined : unsoldChatMediaQ.data?.pages;
  const unsoldPpvs = useMemo<FanChatMediaItem[]>(() => {
    const all = unsoldPages?.flatMap((p) => p.list) ?? [];
    return all
      .filter((m) => (m.price ?? 0) > 0 && m.isOpened === false)
      .sort((a, b) => +new Date(b.createdAt) - +new Date(a.createdAt))
      .slice(0, UNSOLD_SHOWN);
  }, [unsoldPages]);
  const { hasNextPage: unsoldHasMore, isFetching: unsoldFetching, fetchNextPage: unsoldNextPage } = unsoldChatMediaQ;
  const unsoldPageCount = unsoldPages?.length ?? 0;
  useEffect(() => {
    if (!open || unsoldPageCount === 0 || unsoldPpvs.length >= UNSOLD_SHOWN) return;
    if (!unsoldHasMore || unsoldFetching || unsoldPageCount >= UNSOLD_MAX_PAGES) return;
    void unsoldNextPage();
  }, [open, unsoldPageCount, unsoldPpvs.length, unsoldHasMore, unsoldFetching, unsoldNextPage]);

  // Force-refresh button: blow away the persisted chat-media cache for
  // this fan + refetch both filter modes. Used when the operator knows
  // the fan just unlocked something and doesn't want to wait the 30 min
  // SWR window for the panel to catch up.
  const qc = useQueryClient();
  const refreshChatMedia = () => {
    void qc.invalidateQueries({
      queryKey: ["fan-chat-media", accountId, fanId],
      exact: false,
    });
    // The ledger spine behind the chart + Sales rows. Previously missing
    // here, which made the ↻ button look broken after a fresh sale: the
    // gallery refetched but the chart/Sales list (and "Last purchase")
    // kept rendering the stale ledger read.
    void qc.invalidateQueries({
      queryKey: ["fan-ppv-history", accountId, fanId],
      exact: false,
    });
    void qc.invalidateQueries({ queryKey: ["last-purchases", accountId] });
    // A manual refresh should also re-pull the authoritative fan profile —
    // the live OF read (nickname/notice/spend) and our local mirror — so a
    // nickname/note changed out-of-band (automation, another device) shows up
    // immediately instead of waiting for a window focus or the next edit.
    void qc.invalidateQueries({ queryKey: ofUserNameKey(accountId, fanId) }); // name + full
    void qc.invalidateQueries({ queryKey: ["fan", accountId, fanId] });
  };

  // The "effective" nickname/note, with OF as the authoritative read (it's what
  // shows on onlyfans.com). ONCE the live OF query has resolved we trust IT — even
  // an empty value — over the chat-list payload, because that payload can be hours
  // stale and would otherwise pin an out-of-date nickname/note after an automation
  // (or another device) changed it. Before the OF query lands we fall back to the
  // chat-list value for an instant first paint, then our local SQLite mirror so the
  // panel never blanks when OF is slow/unreachable. On blur we write through to OF
  // AND our local row so the two stay in sync.
  const ofDisplayName = ofUserQ.isSuccess
    ? (ofUserQ.data?.displayName ?? "")
    : (chat.withUser.displayName ?? "");
  const ofNotice = ofUserQ.isSuccess
    ? (ofUserQ.data?.notice ?? "")
    : (chat.withUser.notice ?? "");
  const effectiveNickname = ofDisplayName || fan?.custom_nickname || "";
  const effectiveNotes = ofNotice || fan?.notes || "";

  // Local form mirrors so blur-save doesn't fight the cache when the user
  // is mid-edit. Reset whenever the effective value (from OF or local) changes.
  const [nickname, setNickname] = useState("");
  const [notes, setNotes] = useState("");
  const [tagsInput, setTagsInput] = useState("");
  // Media lightbox lives at the drawer level (not inside PpvSalesSection)
  // so the drawer's Esc handler can tell when a higher overlay is open and
  // yield to it — Esc should collapse one layer at a time, not nuke both.
  const [lightbox, setLightbox] = useState<LightboxMedia | null>(null);
  // The bottom tab (Insights / Sales / Notes) and the head's "+" menu.
  // Both are local and unsaved: every mount starts on Insights, closed.
  // The form mirrors above stay here, so a tab switch keeps unsaved typing.
  const [tab, setTab] = useState<InsightsTab>("insights");
  const { open: addOpen, setOpen: setAddOpen, ref: addRef } = useOutsideClose();
  // Insights' blocks: their saved order and the removed ones, and the grip's drag.
  const blocks = useInsightsBlocks();
  const drag = useReorder(blocks.shown, blocks.reorder, (id) => id);
  // Two instances mount at once (slide-over + pinned), so ids are per instance.
  const uid = useId();
  // The values we last pushed into the form mirrors. A field is "dirty" (being
  // edited) when its current value no longer equals what we applied — in that
  // case a fresh OF value must NOT overwrite it.
  const appliedRef = useRef({ nick: "", notes: "", tags: "" });
  // Nickname/note are the only fields here that are read back OUT of `of-user`
  // and written over. Opening the drawer no longer refetches that query (see
  // [useOFUser.ts] — the per-open cost on the user lane bought very little), so
  // a value changed elsewhere inside the 5-minute window would prefill stale,
  // get typed over, and save — silently reverting the other change. Focus
  // refetch only covers tab switches, not a same-tab reopen.
  //
  // So we re-read at the moment the operator engages an edit affordance: a
  // deliberate click, orders of magnitude rarer than a drawer open, and the
  // one instant where freshness is load-bearing. It is non-blocking by
  // construction — the field keeps rendering the cached value and the adopt
  // effect below swaps in the fresh one ONLY while nothing has been typed.
  // At most once per staleTime window (per fan): re-reading on every
  // focus/blur cycle would just re-spend the lane we set out to stop
  // spending. Guarded by TIME, not by open — a pinned or popout drawer stays
  // open all day, so a once-per-open boolean would go stale right along with
  // the value it exists to refresh. The window is the query's own
  // OF_USER_STALE_MS because that cache window is precisely what creates
  // the risk this read closes.
  const ofRefetch = ofUserQ.refetch;
  const editRefreshAtRef = useRef(0);
  useEffect(() => { editRefreshAtRef.current = 0; }, [open, accountId, fanId]);
  const refreshBeforeEdit = useCallback(() => {
    if (Date.now() - editRefreshAtRef.current < OF_USER_STALE_MS) return;
    editRefreshAtRef.current = Date.now();
    void ofRefetch();
  }, [ofRefetch]);
  // The OF write-through (custom name / private note) is fire-and-forget and
  // hits a different backend than the local PATCH. When it rejects the local
  // mirror still updates, so without this the panel shows a value OF never
  // accepted and silently reverts the next time of-user is re-read. Surface
  // the failure so the operator knows the OF sync didn't stick.
  const [ofWriteError, setOfWriteError] = useState<string | null>(null);

  // The Chat header's "Notes" (spec F23) and "Edit name" (ticket 142) asks,
  // one mechanism (`useFocusRequest`): Fan notes in the Notes block, Nickname
  // in the Profile block. Nickname's focus is its edit affordance, so its
  // onFocus re-reads OF before the existing blur save.
  // A removed Notes or Profile block comes back for its ask; `ready` then
  // re-runs the focus once the block, and so the field, is there.
  const showInsights = () => setTab("insights");
  const notesShown = blocks.shown.includes("notes");
  const profileShown = blocks.shown.includes("profile");
  const { ref: notesRef, asked: notesAsked } = useFocusRequest<HTMLTextAreaElement>(
    focusNotesRequest, showInsights, notesShown ? fan : null);
  const { ref: nicknameRef, asked: nicknameAsked } = useFocusRequest<HTMLInputElement>(
    focusNicknameRequest, showInsights, profileShown ? fan : null);
  const addBlock = blocks.add;
  useEffect(() => { if (notesAsked) addBlock("notes"); }, [notesAsked, addBlock]);
  useEffect(() => { if (nicknameAsked) addBlock("profile"); }, [nicknameAsked, addBlock]);

  useEffect(() => {
    if (!fan) return;
    const tags = (fan.tags ?? []).join(", ");
    // Adopt the freshest effective value ONLY for fields the user hasn't touched.
    // A fresh OF read can land at any time (focus refetch, an invalidation, or
    // the pre-edit refresh above), and a naive reset would clobber an
    // in-progress edit; comparing against the last-applied value keeps the
    // operator's typing while still picking up out-of-band changes.
    const prev = appliedRef.current;
    setNickname((cur) => (cur === prev.nick ? effectiveNickname : cur));
    setNotes((cur) => (cur === prev.notes ? effectiveNotes : cur));
    setTagsInput((cur) => (cur === prev.tags ? tags : cur));
    appliedRef.current = { nick: effectiveNickname, notes: effectiveNotes, tags };
  }, [fan, effectiveNickname, effectiveNotes]);

  // Esc closes the OVERLAY drawer only; in pinned mode it's a real
  // sibling column, so Esc shouldn't kill it. While the media lightbox is
  // open it owns Esc (collapse one layer at a time) — the drawer registers
  // no listener, so a single Esc only closes the lightbox, not the drawer.
  // From lg (1024px) up the overlay hides itself (`lg:hidden`) beside its
  // pinned twin, which has the lightbox, so the hidden copy ignores Esc too.
  useEffect(() => {
    if (!open || pinned || lightbox) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key !== "Escape") return;
      if (window.matchMedia("(min-width: 1024px)").matches) return;
      onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, onClose, pinned, lightbox]);

  if (!open) return null;

  const displayName =
    ofDisplayName ||
    fan?.custom_nickname ||
    chat.withUser.name ||
    fan?.of_display_name ||
    chat.withUser.username ||
    `fan ${fanId}`;

  // OF signs its CDN URLs for the account's egress IP: through the relay's /img, as the chat list's avatars.
  const avatar = proxyImage(chat.withUser.avatar || fan?.avatar_url, accountId) || null;

  // Live subscription from OF's /users/{id}.subscribedOnData (same path the
  // desktop app uses), falling back to our DB status while OF is in flight.
  const sub = ofUserQ.data?.subscribedOnData;
  const subStatus = interpretSubStatus(
    sub?.status ?? fan?.subscription_status,
    sub?.expiredAt ?? null,
  );
  // The OF lists the Fan is on. `listsStates` carries OF's system lists only.
  const fanLists = (ofUserQ.data?.listsStates ?? []).filter((l) => l.hasUser && l.name);
  // Prefer OF's authoritative totalSumm, fall back to the
  // transactions-derived windowed sum if it briefly reports 0
  // while our DB copy is also empty.
  const spendCents = Math.max(
    typeof sub?.totalSumm === "number" ? Math.round(sub.totalSumm * 100) : 0,
    recentSpend,
    fan?.lifetime_spend_cents || 0,
  );

  // One shown block's place in the drag, its × and its keyboard move.
  const card = (id: InsightsBlockId): BlockCard => {
    const i = blocks.shown.indexOf(id);
    const dragging = drag.draggingIndex;
    return {
      onDragStart: (e) => drag.onDragStart(e, i),
      // Only this pane's own block drag: a file dragged over the pane is no drop here.
      onDragOver: (e) => { if (dragging !== null) drag.onDragOver(e, i); },
      onDrop: (e) => drag.onDrop(e, i),
      onDragEnd: drag.onDragEnd,
      onMove: (dir) => drag.onKeyboardMove(i, dir),
      dragging: dragging === i,
      over: dragging !== null && dragging !== i && drag.dragOverIndex === i,
      onRemove: () => blocks.remove(id),
    };
  };

  // Insights' blocks by id (`INSIGHTS_BLOCKS` holds their default order);
  // the Insights tab shows the saved layout's, each with its grip and ×.
  const insightsBlocks = fan ? ({
    /* The Clone's Spending behavior card (`messages.html:777-795`). */
    spending: (
      <InsightsBlock
        card={card("spending")}
        title={BLOCK_TITLE.spending}
        trail={
          <>
            <hr className={RULE} />
            {/* `insSparkWrap` (`messages.html:790-794`). */}
            <div className={cn(MP.insights.metric, MP.ours.FanDrawer.sparkRow, "flex items-start justify-between")}>
              <span className={cn(MP.insights.metricKey, "text-fg-dim")}>Purchases over time</span>
              <button
                type="button"
                title="Open the full sales history"
                onClick={() => setTab("sales")}
                className={cn(MP.insights.metricPlain, "shrink-0 text-[var(--inf-accent-text,var(--color-accent))] hover:underline")}
              >
                Full history ↗
              </button>
            </div>
            <PurchasesOverTime items={ppvHistoryQ.data?.items ?? []} loading={ppvHistoryQ.isLoading} />
          </>
        }
        lead={
          <>
            {/* `.spend-top`, `.lbl`, `.big`, `.sub` (`messages.html:304-307`). */}
            {/* Two equal columns, Last spend after a 1px rule (2026-10-18 capture). */}
            <dl className={cn(MP.insights.spendTop, "grid grid-cols-2")}>
              <div>
                <dt className={cn(MP.insights.spendLabel, "text-fg-dim")}>Total spend</dt>
                <dd className={MP.insights.spendBig}>{spendCents ? fmtCents(spendCents) : "$0"}</dd>
              </div>
              <div className={cn(MP.insights.spendSplit, "border-border")}>
                <dt className={cn(MP.insights.spendLabel, "text-fg-dim")}>Last spend</dt>
                <dd className={MP.insights.spendSub}>{fmtRelTime(lastPurchase)}</dd>
              </div>
            </dl>
            {/* `.hr` (`messages.html:309`): 1px, 10px above and below. */}
            <hr className={RULE} />
          </>
        }
      >
        <InsightsRow
          term="PPV"
          value={
            <>
              <span className={MP.insights.metricValue}>{fmtSummDollars(sub?.messagesSumm, ppvHistoryQ.data?.summary.messages_cents)}</span> Total
              <br />
              <span className={cn(MP.insights.metricAvg, "text-fg-dim")}>{pageFigure(ppvHistoryQ, salesLimit, "avg_cents")} Avg</span>
            </>
          }
        />
        <InsightsRow
          term="Tip"
          value={
            <>
              <span className={MP.insights.metricValue}>{fmtSummDollars(sub?.tipsSumm, ppvHistoryQ.data?.summary.tips_cents)}</span> Total
              <br />
              <span className={cn(MP.insights.metricAvg, "text-fg-dim")}>— Avg</span>
            </>
          }
        />
        <InsightsRow term="Highest spend" value={pageFigure(ppvHistoryQ, salesLimit, "max_cents")} />
      </InsightsBlock>
    ),
    org: (
      <InsightsBlock title={BLOCK_TITLE.org} card={card("org")}>
        <InsightsRow
          term={<>Spending power<InfoIcon title="This fan's spend over the last 30 days on all your creators, ranked against every fan who spent" /></>}
          value={<Badge>{insights?.spending_power?.label ?? "—"}</Badge>}
        />
        <InsightsRow
          term="Chargeback risk"
          value={
            <span title={insights?.chargeback_risk?.pct != null ? `${insights.chargeback_risk.pct}% of his payments on your creators were charged back or refunded` : undefined}>
              <Badge>{insights?.chargeback_risk?.label ?? "—"}</Badge>
            </span>
          }
        />
      </InsightsBlock>
    ),
    subscription: (
      <InsightsBlock title={BLOCK_TITLE.subscription} card={card("subscription")}>
        <InsightsRow
          term="Status"
          value={<span className={toneClass(subStatus.tone)}>{subStatus.short}</span>}
        />
        <InsightsRow
          term="Cost"
          value={typeof sub?.price === "number" ? fmtPrice(Math.round(sub.price * 100)) : "—"}
        />
        <InsightsRow term="Duration" value={sub?.duration || "—"} />
        <InsightsRow term="Auto-renewal" value={autoRenewal(subStatus)} />
      </InsightsBlock>
    ),
    /* The Clone's Profile card (`messages.html:822-834`) plus Source.
     *  Nickname stays an input that is always rendered (the edit-freshness
     *  suite focuses it), styled as the Clone's `.nick-edit` value. */
    profile: (
      <InsightsBlock
        card={card("profile")}
        key={`nickname-${nicknameAsked}`}
        title={BLOCK_TITLE.profile}
        trail={
          <div
            role="group"
            aria-label="Location"
            className={cn(MP.insights.location, "flex items-center border-border")}
          >
            <svg aria-hidden viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7"
                 className={cn(MP.insights.locationIcon, "shrink-0 text-fg-dim")}>
              <path d="M12 21s7-5.2 7-11a7 7 0 1 0-14 0c0 5.8 7 11 7 11z" /><circle cx="12" cy="10" r="2.4" />
            </svg>
            <span className="min-w-0 truncate">
              {[fan.home_city, fan.home_country].filter(Boolean).join(", ") || "—"}
            </span>
          </div>
        }
      >
        <InsightsRow
          term={
            <>
              <label htmlFor={`${uid}-nickname`}>Nickname</label>
              <InfoIcon title="Synced with OnlyFans. Saving updates OF's per-fan custom name and our local mirror." />
            </>
          }
          value={
            <NickEdit>
              <input
                ref={nicknameRef}
                id={`${uid}-nickname`}
                type="text"
                value={nickname}
                onChange={(e) => setNickname(e.target.value)}
                onFocus={refreshBeforeEdit}
                onBlur={() => {
                  const next = nickname.trim();
                  if (next === effectiveNickname.trim()) return;
                  setOfWriteError(null);
                  update.mutate({ custom_nickname: next || null });
                  void writeOFCustomName(accountId, fanId, next).catch((err) => {
                    console.warn("[fan-drawer] OF custom-name write failed", err);
                    setOfWriteError(
                      "Saved locally, but OnlyFans rejected the nickname change — it may revert on the next sync.",
                    );
                  });
                }}
                placeholder={chat.withUser.name ?? fan.of_display_name ?? ""}
                className={INLINE_EDIT}
              />
            </NickEdit>
          }
        />
        <InsightsRow
          term={<label htmlFor={`${uid}-tags`} title="Comma-separated. Saves on blur.">Tags</label>}
          value={
            <NickEdit>
              <input
                id={`${uid}-tags`}
                type="text"
                value={tagsInput}
                onChange={(e) => setTagsInput(e.target.value)}
                onBlur={() => {
                  const next = tagsInput
                    .split(",")
                    .map((t) => t.trim())
                    .filter(Boolean);
                  const prev = fan.tags ?? [];
                  if (sameList(next, prev)) return;
                  update.mutate({ tags: next });
                }}
                placeholder="whale, EU, kink:feet"
                className={INLINE_EDIT}
              />
            </NickEdit>
          }
        />
        <InsightsRow
          term={
            <label htmlFor={`${uid}-language`} title={languageHint(fan.language, fan.language_source)}>
              Language
            </label>
          }
          value={
            <NickEdit>
              <select
                id={`${uid}-language`}
                value={fan.language ?? ""}
                onChange={(e) => update.mutate({ language: e.target.value })}
                className={cn(INLINE_EDIT, "flex-none max-w-full appearance-none cursor-pointer [text-align-last:right]")}
              >
                <option value="">Default (account)</option>
                {LANGUAGE_OPTIONS.map((l) => (
                  <option key={l.code} value={l.code}>{l.label}</option>
                ))}
              </select>
            </NickEdit>
          }
        />
        {/* OF has no birthday field (Clone: "NO FIELD", `messages.js:3393-3396`): ours,
            "MM-DD", which Smart Messages' Birthday Trigger reads. */}
        <InsightsRow
          term={<label htmlFor={`${uid}-birthday`}>Birthday</label>}
          value={
            <BlurEdit
              key={fan.birthday ?? ""}
              id={`${uid}-birthday`}
              saved={fan.birthday ?? null}
              pattern={MM_DD}
              inputMode="numeric"
              maxLength={5}
              placeholder="MM-DD"
              title="Smart Messages' Birthday Trigger greets the fan on this day"
              onSave={(birthday) => update.mutate({ birthday })}
            />
          }
        />
        {/* `FanRecord.source` is a relationship class, not how the Fan was acquired. */}
        <InsightsRow term="Source" value="—" />
        {/* The zone is resolved from Location server-side; none when Location is ambiguous. */}
        <InsightsRow term="Local time" value={<LocalTime zone={fan.local_timezone ?? null} />} />
        <InsightsRow
          term={<label htmlFor={`${uid}-salary`}>Salary</label>}
          value={
            <BlurEdit
              key={fan.salary ?? ""}
              id={`${uid}-salary`}
              saved={fan.salary ?? null}
              placeholder="$4k / month"
              onSave={(salary) => update.mutate({ salary })}
            />
          }
        />
        <InsightsRow
          term={<label htmlFor={`${uid}-salary-frequency`}>Salary frequency</label>}
          value={
            <NickEdit>
              <select
                id={`${uid}-salary-frequency`}
                value={fan.salary_frequency ?? ""}
                onChange={(e) => update.mutate({
                  salary_frequency:
                    SALARY_FREQUENCIES.find((f) => f.value === e.target.value)?.value ?? null,
                })}
                className={cn(INLINE_EDIT, "flex-none max-w-full appearance-none cursor-pointer [text-align-last:right]")}
              >
                <option value="">—</option>
                {SALARY_FREQUENCIES.map((f) => (
                  <option key={f.value} value={f.value}>{f.label}</option>
                ))}
              </select>
            </NickEdit>
          }
        />
        <InsightsRow
          term={<label htmlFor={`${uid}-last-pay-date`}>Last pay date</label>}
          value={
            <BlurEdit
              key={fan.last_pay_date ?? ""}
              id={`${uid}-last-pay-date`}
              type="date"
              saved={fan.last_pay_date ?? null}
              onSave={(last_pay_date) => update.mutate({ last_pay_date })}
            />
          }
        />
      </InsightsBlock>
    ),
    /* OF's system lists only (`listsStates`), so partial by construction. */
    lists: (
      <InsightsBlock
        card={card("lists")}
        title={BLOCK_TITLE.lists}
        trail={
          fanLists.length ? (
            <ul className="flex flex-wrap gap-1">
              {fanLists.map((l) => (
                <li key={l.id} className={cn(MP.ours.FanDrawer.listChip, "bg-bg-elev-1 border-border")}>
                  {l.name}
                </li>
              ))}
            </ul>
          ) : (
            <p className={MP.insights.metricPlain}>—</p>
          )
        }
      />
    ),
    /* Fan notes, with the Clone's `.note-ta` Geometry (`messages.html:497-498`). */
    notes: (
      <InsightsBlock
        card={card("notes")}
        key={`notes-${notesAsked}`}
        title={BLOCK_TITLE.notes}
        trail={
          <textarea
            ref={notesRef}
            aria-label="Fan notes"
            title="Synced with OnlyFans' private note. Anything the AI should know later goes here."
            value={notes}
            onChange={(e) => setNotes(e.target.value)}
            onFocus={refreshBeforeEdit}
            onBlur={() => {
              if (notes === effectiveNotes) return;
              setOfWriteError(null);
              update.mutate({ notes: notes || null });
              void writeOFNotice(accountId, fanId, notes).catch((err) => {
                console.warn("[fan-drawer] OF notice write failed", err);
                setOfWriteError(
                  "Saved locally, but OnlyFans rejected the note change — it may revert on the next sync.",
                );
              });
            }}
            placeholder="loves bondage, German, paid $500 last week…"
            className={cn(MP.insights.note, "block w-full bg-bg border-border focus:outline-none focus:border-accent resize-y")}
          />
        }
      />
    ),
    // The Fan's identity, the mass-exclude switches and the unsold PPVs:
    // Inflowwww extras (ADR-0003, amended 2026-10-21), each with its
    // catalogue tooltip.
    fan: (
      <InsightsBlock
        card={card("fan")}
        title={BLOCK_TITLE.fan}
        trail={
          <div title={extraTitle("Fan identity")} className="flex items-start gap-3">
            <div className="w-12 h-12 rounded-full bg-bg-elev-1 overflow-hidden shrink-0 grid place-items-center">
              {avatar ? (
                <img
                  src={avatar}
                  alt=""
                  loading="lazy"
                  decoding="async"
                  className="w-full h-full object-cover"
                />
              ) : (
                <span className="text-base">
                  {displayName.slice(0, 1).toUpperCase()}
                </span>
              )}
            </div>
            <div className="min-w-0 flex-1">
              <div className="text-sm font-semibold truncate">{displayName}</div>
              <div className={cn(MP.ours.FanDrawer.extrasHandle, "text-fg-dim truncate")}>
                @{chat.withUser.username || fan.of_username || fanId}
              </div>
              <div className={cn(MP.ours.FanDrawer.extrasMeta, "text-fg-dim")}>
                {accountLabel} · id {fanId}
              </div>
            </div>
          </div>
        }
      />
    ),
    massExclude: (
      <InsightsBlock
        card={card("massExclude")}
        title={BLOCK_TITLE.massExclude}
        trail={
          <MassExcludeToggle accountId={accountId} fanId={fanId}
            title="MASSdmEXCLUDE" hint="Never include in any mass send." />
        }
      />
    ),
    unsoldPpvs: (
      <InsightsBlock
        card={card("unsoldPpvs")}
        title={BLOCK_TITLE.unsoldPpvs}
        trail={
          <UnsoldPpvsSection
            items={unsoldPpvs}
            loading={unsoldChatMediaQ.isLoading || unsoldChatMediaQ.isPlaceholderData}
            failed={unsoldChatMediaQ.isError && !unsoldPages}
            onRetry={() => void unsoldChatMediaQ.refetch()}
            accountId={accountId}
            onComposeWith={onComposeWith}
          />
        }
      />
    ),
  } satisfies Record<InsightsBlockId, React.ReactNode>) : null;

  // Shared panel body. In overlay mode we wrap it in an absolute-positioned
  // backdrop layer; in pinned mode the parent inbox layout slots it next to
  // the chat column as a normal sibling: the Fan insights pane, 280px
  // (`MP.panes.insights`), marked for the harness. The pinned variant is
  // hidden below lg (Messages Pro is one pane at a time there — the overlay
  // branch shows the same content as a slide-over).
  const panel = (
    <aside
      role={pinned ? undefined : "dialog"}
      aria-modal={pinned ? undefined : true}
      aria-label="Fan insights"
      data-mp-pane={pinned ? "insights" : undefined}
      className={
        pinned
          ? cn(MP.panes.insights, "hidden lg:flex shrink-0 bg-[var(--inf-insights,var(--color-panel))] border-[var(--inf-rule,var(--color-border))] flex-col h-full")
          : cn(MP.ours.FanDrawer.slideOver, "bg-[var(--inf-insights,var(--color-panel))] border-[var(--inf-rule,var(--color-border))] shadow-2xl pointer-events-auto flex flex-col")
      }
    >
        {/* The head is the title only (16px/700, padding 16/16/10, no rule),
         *  reading the active tab. The "+" then × sit on its right; "+" lists
         *  the removed Insights blocks, and picking one adds it back. */}
        <header className={cn(MP.insights.head, MP.ours.FanDrawer.head, "flex items-center")}>
          <h2 className="flex-1 min-w-0 truncate leading-6">{TAB_TITLE[tab]}</h2>
          <div ref={addRef} className="relative shrink-0">
            <button
              type="button"
              onClick={() => setAddOpen((o) => !o)}
              aria-expanded={addOpen}
              aria-haspopup="menu"
              aria-controls={addOpen ? `${uid}-add` : undefined}
              aria-label="Add block"
              title="Add a removed block back"
              className={cn(
                "grid place-items-center w-11 h-11 md:w-6 md:h-6 -my-2 md:my-0 rounded-md text-2xl md:text-lg font-normal leading-none hover:text-fg",
                addOpen ? "text-[var(--inf-accent-text,var(--color-accent))]" : "text-fg-dim",
              )}
            >
              +
            </button>
            {addOpen && (
              <div id={`${uid}-add`} role="menu" aria-label="Add block" className={cn(MENU, MP.ours.FanDrawer.addMenu)}>
                {blocks.removed.length === 0 ? (
                  <div className={cn(MENU_ROW, "text-fg-dim")}>Every block is shown</div>
                ) : blocks.removed.map((id) => (
                  <button
                    key={id}
                    type="button"
                    role="menuitem"
                    onClick={() => { blocks.add(id); setTab("insights"); setAddOpen(false); }}
                    className={MENU_ITEM}
                  >
                    {BLOCK_TITLE[id]}
                  </button>
                ))}
              </div>
            )}
          </div>
          <button
            type="button"
            onClick={onClose}
            className="shrink-0 grid place-items-center w-11 h-11 md:w-6 md:h-6 -my-2 md:my-0 -mr-2 md:mr-0 text-2xl md:text-lg font-normal leading-none text-fg-dim hover:text-fg"
            aria-label="Close"
          >
            ×
          </button>
        </header>

        <div
          role="tabpanel"
          aria-labelledby={`${uid}-tab-${tab}`}
          className={cn(MP.insights.body, "flex-1 min-h-0 overflow-y-auto flex flex-col")}
        >
          {fan && tab === "insights" && insightsBlocks && (
            <div className="flex flex-col gap-3">
              {/* One order at every width: page order is screen order, the saved layout's. */}
              {blocks.shown.map((id) => <Fragment key={id}>{insightsBlocks[id]}</Fragment>)}
            </div>
          )}

          {fan && tab === "sales" && (
            <>
              {/* The Sales pane's first card (`messages.js:1532-1536`). */}
              <InsightsBlock
                title="Purchases over time"
                trail={<PurchasesOverTime items={ppvHistoryQ.data?.items ?? []} loading={ppvHistoryQ.isLoading} />}
              />
              {/* The Clone's Sales card (`messages.js:1537-1541`), without its
               *  count (it counts only the loaded page) and without Vault history.
               *  Buy rate, Highest and Lowest price are Infloww's PPV timeline
               *  figures over the last 30 PPVs this creator sent. */}
              <InsightsBlock
                title="Sales"
                plainTitle
                trail={<>
                  <SalesTable items={ppvHistoryQ.data?.items ?? []} />
                  <PpvSalesSection
                    items={ppvHistoryQ.data?.items ?? []}
                    loading={ppvHistoryQ.isLoading}
                    chatMedia={chatMediaFlat}
                    chatMediaLoading={chatMediaQ.isLoading}
                    chatMediaFetching={chatMediaQ.isFetching}
                    chatMediaUpdatedAt={chatMediaQ.dataUpdatedAt}
                    accountId={accountId}
                    salesLimit={salesLimit}
                    onLoadMore={() => {
                      setSalesLimit((n) => Math.min(n + 20, 200));
                      // Fetch the next OF gallery page in parallel so the
                      // enrichment keeps up with the ledger.
                      if (chatMediaQ.hasNextPage && !chatMediaQ.isFetchingNextPage) {
                        void chatMediaQ.fetchNextPage();
                      }
                    }}
                    onRefresh={refreshChatMedia}
                    onOpenMedia={setLightbox}
                    serverFetching={
                      ppvHistoryQ.isFetching || chatMediaQ.isFetchingNextPage
                    }
                  />
                </>}
              >
                <InsightsRow
                  term="Buy rate"
                  value={
                    insights?.ppv_recent?.buy_rate_pct != null ? (
                      <span title={`${insights.ppv_recent.bought} of the last ${insights.ppv_recent.count} PPVs bought`}>
                        {insights.ppv_recent.buy_rate_pct}%
                      </span>
                    ) : "—"
                  }
                />
                <InsightsRow term="Highest price" value={insights?.ppv_recent?.highest_cents != null ? fmtPrice(insights.ppv_recent.highest_cents) : "—"} />
                <InsightsRow term="Lowest price" value={insights?.ppv_recent?.lowest_cents != null ? fmtPrice(insights.ppv_recent.lowest_cents) : "—"} />
              </InsightsBlock>
            </>
          )}

          {fan && tab === "notes" && (
            <>
              {/* We store no Creator notes, so the block reads —. */}
              <InsightsBlock title="Creator notes" trail={<p className={MP.insights.metricPlain}>—</p>} />
              {/* The automation surfaces, after Creator notes, shown by default
                  (ADR-0003's 2026-10-21 amendment; once behind the Legacy flag). */}
              <ProfileCard fan={fan} />
              {/* Persona continuity — the claims ledger the chat engines write and
               *  the pre-send consistency check reads. Sits with the AI profile
               *  because it is the same question ("what does this fan know?"). */}
              <div title={extraTitle("Persona claims")}>
                <PersonaClaims accountId={accountId} fan={fan}
                               onSave={(patch) => update.mutate(patch)} />
              </div>
            </>
          )}

          {/* Status lines sit under the active tab's content on every tab. */}
          {isLoading && (
            <div className="text-xs text-fg-dim">Loading fan profile…</div>
          )}
          {fan && update.error && (
            <div className="text-err text-xs">
              {(update.error as Error).message || "save failed"}
            </div>
          )}
          {fan && ofWriteError && (
            <div className="text-err text-xs">{ofWriteError}</div>
          )}
        </div>

        <div role="tablist" aria-label="Fan insights tabs" className={cn(MP.insights.tabs, "flex shrink-0")}>
          {INSIGHTS_TABS.map((t) => (
            <button
              key={t}
              type="button"
              role="tab"
              id={`${uid}-tab-${t}`}
              aria-selected={tab === t}
              onClick={() => setTab(t)}
              className={cn(
                MP.insights.tab,
                "flex-1 flex flex-col items-center",
                // Infloww's tiles: the active one filled like a card, its glyph and label bright.
                tab === t
                  ? "bg-[var(--inf-card,var(--color-bg-elev-1))] text-[var(--inf-insights-tab-on,var(--color-fg))]"
                  : "text-[var(--inf-insights-tab-off,var(--color-fg-dim))] hover:text-fg",
              )}
            >
              {TAB_ICON[t]}
              {TAB_LABEL[t]}
            </button>
          ))}
        </div>
        {lightbox && (
          <MediaLightbox media={lightbox} onClose={() => setLightbox(null)} />
        )}
      </aside>
  );

  if (pinned) return panel;
  // The overlay is hidden at lg+: there its pinned twin is the in-flow
  // column, and below lg this slide-over is the only branch.
  return (
    <div className="absolute inset-0 z-30 flex pointer-events-none lg:hidden">
      <div className="flex-1 min-w-14 sm:min-w-0 bg-black/40 pointer-events-auto" onClick={onClose} />
      {panel}
    </div>
  );
}

/** The Unsold PPVs block shows the latest 2, read from at most 5 pages of 20. */
const UNSOLD_SHOWN = 2;
const UNSOLD_MAX_PAGES = 5;

/** Each Insights block's title, as its head and the "+" menu read it. */
const BLOCK_TITLE: Record<InsightsBlockId, string> = {
  spending: "Spending behavior", org: "Organization metrics", subscription: "Subscription",
  profile: "Profile", lists: "Lists", notes: "Notes",
  fan: "Fan", massExclude: "Mass exclude", unsoldPpvs: "Unsold PPVs sent",
};

type InsightsTab = "insights" | "sales" | "notes";
const INSIGHTS_TABS: InsightsTab[] = ["insights", "sales", "notes"];
const TAB_LABEL: Record<InsightsTab, string> = { insights: "Insights", sales: "Sales", notes: "Notes" };
/** The head reads the tab (Clone `messages.js:1614`). */
const TAB_TITLE: Record<InsightsTab, string> = { insights: "Fan insights", sales: "Sales", notes: "Notes" };
/** The Clone's 20px tab icons (`messages.html:845-847`): eye, tag, note. */
const TAB_ICON: Record<InsightsTab, React.ReactNode> = {
  insights: (
    <svg aria-hidden viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" className={MP.insights.tabIcon}>
      <path d="M2 12s4-7 10-7 10 7 10 7-4 7-10 7-10-7-10-7z" /><circle cx="12" cy="12" r="2.6" />
    </svg>
  ),
  sales: (
    <svg aria-hidden viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" className={MP.insights.tabIcon}>
      <path d="M20.6 13.4L13 21l-9-9V4h8l8.6 8.6a1.5 1.5 0 0 1 0 .8z" />
      <circle cx="8" cy="8" r="1.3" fill="currentColor" stroke="none" />
    </svg>
  ),
  notes: (
    <svg aria-hidden viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" className={MP.insights.tabIcon}>
      <path d="M6 3h12a2 2 0 0 1 2 2v14a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2z" /><path d="M8 8h8M8 12h8M8 16h5" />
    </svg>
  ),
};

/** An editable Profile value styled as the Clone's `.nick-edit`
 *  (`messages.html:320-321`): the control, then a 13px pencil, gap 8px. */
function NickEdit({ children }: { children: React.ReactNode }) {
  return (
    <span className={cn(MP.insights.nickEdit, "flex items-center justify-end")}>
      {children}
      <svg aria-hidden viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7"
           className={cn(MP.insights.pencil, "shrink-0 text-fg-dim")}>
        <path d="M14 4l6 6L8 22H2v-6z" />
      </svg>
    </span>
  );
}

/** The Clone's `.hr` (`messages.html:309`, FI17): a 1px line drawn as a
 *  fill, so the `<hr>`'s own top border is off. */
const RULE = cn(MP.insights.rule, MP.ours.FanDrawer.rule, "bg-border");

/** An always-rendered input that reads as an inline right-aligned 13.5px value. */
const INLINE_EDIT = cn(
  MP.ours.FanDrawer.inlineEdit,
  "min-w-0 flex-1 bg-transparent text-right focus:outline-none focus:ring-1 focus:ring-accent",
);

const MM_DD = /^(0[1-9]|1[0-2])-(0[1-9]|[12]\d|3[01])$/;

/** A Profile value saved on blur; "" clears it. With `pattern`, anything
 *  else that does not match goes back to the saved value (Birthday's MM-DD). */
function BlurEdit({ id, saved, type = "text", pattern, inputMode, maxLength, placeholder, title, onSave }: {
  id: string; saved: string | null; type?: "text" | "date"; pattern?: RegExp;
  inputMode?: "numeric"; maxLength?: number; placeholder?: string; title?: string;
  onSave: (value: string | null) => void;
}) {
  const [value, setValue] = useState(saved ?? "");
  return (
    <NickEdit>
      <input
        id={id}
        type={type}
        inputMode={inputMode}
        maxLength={maxLength}
        value={value}
        placeholder={placeholder}
        title={title}
        onChange={(e) => setValue(e.target.value)}
        onBlur={() => {
          const v = value.trim();
          if (v === (saved ?? "")) return;
          if (v && pattern && !pattern.test(v)) { setValue(saved ?? ""); return; }
          onSave(v || null);
        }}
        className={INLINE_EDIT}
      />
    </NickEdit>
  );
}

/** The wall clock in `zone`, ticking each minute (a pinned drawer stays open all day). */
function LocalTime({ zone }: { zone: string | null }) {
  const [now, setNow] = useState(() => new Date());
  useEffect(() => {
    setNow(new Date());
    if (!zone) return;
    const t = setInterval(() => setNow(new Date()), 60_000);
    return () => clearInterval(t);
  }, [zone]);
  if (!zone) return <>—</>;
  return (
    <span title={zone}>
      {now.toLocaleTimeString([], { timeZone: zone, hour: "numeric", minute: "2-digit" })}
    </span>
  );
}

type Tone = SubStatusDisplay["tone"];

const TONE_CLASS: Record<Tone, string> = {
  ok: "text-ok", warn: "text-warn", err: "text-err", "fg-dim": "text-fg-dim",
};
function toneClass(tone: Tone): string {
  return TONE_CLASS[tone];
}

/** An Insights tab block's place in its layout (`useInsightsBlocks`): the
 *  grip's drag and arrow-key move, the block as a drop target, and its ×. */
type BlockCard = {
  onDragStart: (e: React.DragEvent) => void;
  onDragOver: (e: React.DragEvent) => void;
  onDrop: (e: React.DragEvent) => void;
  onDragEnd: (e: React.DragEvent) => void;
  onMove: (dir: -1 | 1) => void;
  /** This block is the one being dragged. */
  dragging: boolean;
  /** Another block is being dragged over this one. */
  over: boolean;
  onRemove: () => void;
};

/** An Insights block: the Clone's `.card` (`messages.html:295`) with its
 *  `.card-head` (`:296-301`): a grip, the title, and a chevron that
 *  collapses the rows. Starts expanded; not saved. With `card` (the Insights
 *  tab's blocks) the grip drags the block to a new place (↑/↓ move it from
 *  the keyboard) and a × removes it; without, the grip is not wired. */
function InsightsBlock({
  title, plainTitle, lead, children, trail, card,
}: {
  title: string;
  /** Render the title as the Clone's plain `.ct` span, not an h3: for a block
   *  whose title the pane head already shows as its h2 (Sales on the Sales tab). */
  plainTitle?: boolean;
  /** Content above the rows that is not a row, e.g. Spending behavior's headline pair. */
  lead?: React.ReactNode;
  children?: React.ReactNode;
  /** Content below the rows that is not a row, e.g. the Purchases over time chart. */
  trail?: React.ReactNode;
  card?: BlockCard;
}) {
  const [expanded, setExpanded] = useState(true);
  const id = useId();
  const grip = (
    <svg aria-hidden viewBox="0 0 24 24" fill="currentColor" className={MP.insights.dragIcon}>
      <circle cx="9" cy="6" r="1.4" /><circle cx="15" cy="6" r="1.4" />
      <circle cx="9" cy="12" r="1.4" /><circle cx="15" cy="12" r="1.4" />
      <circle cx="9" cy="18" r="1.4" /><circle cx="15" cy="18" r="1.4" />
    </svg>
  );
  return (
    <section
      aria-labelledby={`${id}-title`}
      onDragOver={card?.onDragOver}
      onDrop={card?.onDrop}
      className={cn(
        MP.insights.block,
        "bg-[var(--inf-card,var(--color-bg-elev-1))] border-[var(--inf-card-border,var(--color-border))]",
        card?.dragging && "opacity-50",
        card?.over && "border-accent",
      )}
    >
      <div className={cn(expanded ? MP.insights.blockHead : MP.ours.FanDrawer.blockHeadCollapsed, "flex items-center")}>
        {card ? (
          <button
            type="button"
            draggable
            onDragStart={(e) => {
              // The whole block follows the pointer, not just the grip.
              const block = e.currentTarget.closest("section");
              if (block) e.dataTransfer.setDragImage?.(block, 0, 0);
              card.onDragStart(e);
            }}
            onDragEnd={card.onDragEnd}
            onKeyDown={(e) => {
              if (e.key !== "ArrowUp" && e.key !== "ArrowDown") return;
              e.preventDefault();
              card.onMove(e.key === "ArrowUp" ? -1 : 1);
            }}
            aria-label={`Move ${title}`}
            title="Drag to move (↑/↓ from the keyboard)"
            className="shrink-0 text-fg-dim hover:text-fg cursor-grab active:cursor-grabbing"
          >
            {grip}
          </button>
        ) : (
          <span title="not wired" className="shrink-0 text-fg-dim">{grip}</span>
        )}
        {plainTitle
          ? <span id={`${id}-title`} className={cn(MP.insights.blockTitle, "flex-1 min-w-0")}>{title}</span>
          : <h3 id={`${id}-title`} className={cn(MP.insights.blockTitle, "flex-1 min-w-0")}>{title}</h3>}
        {card && (
          <button
            type="button"
            onClick={card.onRemove}
            aria-label={`Remove ${title}`}
            title={`Remove ${title} (the head's + adds it back)`}
            className="shrink-0 text-fg-dim hover:text-fg"
          >
            <svg aria-hidden viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.9"
                 className={MP.insights.chevron}>
              <path d="M7 7l10 10M17 7L7 17" />
            </svg>
          </button>
        )}
        <button
          type="button"
          onClick={() => setExpanded((e) => !e)}
          aria-expanded={expanded}
          aria-label={`${expanded ? "Collapse" : "Expand"} ${title}`}
          className="shrink-0 text-fg-dim hover:text-fg"
        >
          <svg aria-hidden viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.9"
               className={cn(MP.insights.chevron, !expanded && "rotate-180")}>
            <path d="M6 15l6-6 6 6" />
          </svg>
        </button>
      </div>
      {expanded && <>{lead}{children && <dl>{children}</dl>}{trail}</>}
    </section>
  );
}

/** A block row, the Clone's `.mrow.plain` (`messages.html:310-316`): the
 *  term left, the value right, both 13.5px, padding 6px 0. */
function InsightsRow({ term, value }: { term: React.ReactNode; value: React.ReactNode }) {
  return (
    <div className={cn(MP.insights.metric, MP.ours.FanDrawer.row, "flex items-start justify-between")}>
      <dt className={cn(MP.insights.metricKey, MP.ours.FanDrawer.term, "flex items-center text-fg-dim")}>{term}</dt>
      <dd className={cn(MP.insights.metricPlain, "min-w-0 flex-1 text-right")}>{value}</dd>
    </div>
  );
}

/** The Clone's `.badge-val` Geometry (`messages.html:315`) in our colours. */
function Badge({ children }: { children: React.ReactNode }) {
  return (
    <span className={cn(MP.insights.badge, "inline-block bg-bg-elev-2")}>
      {children}
    </span>
  );
}

/** The Clone's 14px `.info-i` (`messages.html:302`); `title` is its tooltip. */
function InfoIcon({ title }: { title?: string }) {
  return (
    <span title={title} className="shrink-0">
      <svg role="img" aria-label="info" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7"
           className={cn(MP.insights.info, "shrink-0")}>
        <circle cx="12" cy="12" r="9" /><path d="M12 11v5M12 8h.01" strokeLinecap="round" />
      </svg>
    </span>
  );
}

/** OF's status semantics (`interpretSubStatus`): "active" renews, "Set to
 *  Expire" does not, an expired sub cannot; anything else is unknown. */
function autoRenewal(status: SubStatusDisplay): string {
  if (status.expired || status.short === "Won't renew") return "Off";
  if (status.short === "Active") return "On";
  return "—";
}

/** PPV Avg or Highest spend: the relay's average or maximum over the loaded
 *  purchase-history page (`service/fans.py:1006-1011`). A full page may hide
 *  older purchases, so it reads "—" then, and with no items (B11 option (b)).
 *  A placeholder page (the previous limit's or the previous Fan's, kept by
 *  `placeholderData` while a fetch is in flight) also reads "—". */
function pageFigure(
  q: { data?: PpvHistoryResp; isPlaceholderData: boolean },
  salesLimit: number, key: "avg_cents" | "max_cents",
): string {
  const items = q.data?.items ?? [];
  if (!q.data || q.isPlaceholderData || items.length === 0 || items.length === salesLimit) return "—";
  return fmtPrice(q.data.summary[key]);
}

/** Whole-dollar formatter for ledger summaries. OF returns
 *  these as dollars (`tipsSumm: 87`); our DB returns cents. Prefer the
 *  OF number when it's a real value; fall back to DB cents otherwise.
 *  We treat `0` as "missing" on the OF side because OF reports 0 for
 *  long-tenure / hidden accounts even when activity exists — better to
 *  show our DB total than a misleading $0. */
function fmtSummDollars(ofDollars: number | null | undefined, dbCents: number | null | undefined): string {
  if (typeof ofDollars === "number" && ofDollars > 0) return `$${Math.round(ofDollars).toLocaleString("en-US")}`;
  if (typeof dbCents === "number" && dbCents > 0) return `$${Math.round(dbCents / 100).toLocaleString("en-US")}`;
  return "—";
}

/** The Clone's Sales table (`messages.js:1525-1528`, `.stab` at
 *  `messages.html:488-492`): Date, Gross, Net and Sent by at 12px, one row
 *  per ledger item. Nothing when the ledger is empty; the media rows below
 *  carry the empty text. */
function SalesTable({ items }: { items: PpvHistoryItem[] }) {
  if (items.length === 0) return null;
  const th = cn(MP.insights.salesHead, "border-border text-fg-dim");
  const td = cn(MP.insights.salesCell, "border-border whitespace-nowrap");
  return (
    <table className={cn(MP.insights.salesTable, "w-full border-collapse")}>
      <thead>
        <tr>
          <th className={cn(th, "text-left")}>Date</th>
          <th className={cn(th, "text-right")}>Gross</th>
          <th className={cn(th, "text-right")}>Net</th>
          <th className={cn(th, "text-left")}>Sent by</th>
        </tr>
      </thead>
      <tbody>
        {items.map((i) => {
          const t = parseUtcMs(i.purchased_at);
          return (
            <tr key={i.transaction_id}>
              <td className={td}>
                {t == null ? "—" : new Date(t).toLocaleDateString([], { month: "short", day: "numeric" })}
              </td>
              <td className={cn(td, "text-right")}>{fmtPrice(i.price_cents)}</td>
              <td className={cn(td, "text-right text-fg-dim")}>{i.net_cents == null ? "—" : fmtPrice(i.net_cents)}</td>
              <td className={td}>{i.employee_name ?? "—"}</td>
            </tr>
          );
        })}
      </tbody>
    </table>
  );
}

/** How many sale rows to render before "show more". */
const INITIAL_SALE_ROWS = 3;

/** The Clone's Purchases over time bars (`messages.js:1472-1504`, `.bars`
 *  and `.axis` at `messages.html:493-496`): 12 gross-cent buckets from the
 *  Fan's first purchase to now. Shown on Insights and atop the Sales tab. */
function PurchasesOverTime({ items, loading }: { items: PpvHistoryItem[]; loading: boolean }) {
  if (loading && items.length === 0) {
    return <div className={cn(MP.ours.FanDrawer.status, "text-fg-dim")}>Loading purchase history…</div>;
  }
  if (items.length === 0) {
    return <div className={cn(MP.ours.FanDrawer.status, "text-fg-dim")}>No PPV purchases yet.</div>;
  }
  const { buckets, max, first, step } = salesBars(items);
  const day = (ms: number) => new Date(ms).toLocaleDateString();
  return (
    <>
      <div role="img" aria-label="Purchases over time" className={cn(MP.insights.chart, "flex items-end")}>
        {buckets.map((v, i) => (
          <span
            key={i}
            title={`${day(first + i * step)} – ${day(first + (i + 1) * step)}: ${fmtCents(v)}`}
            style={{ height: `${max > 0 ? Math.max(2, Math.round((v * 100) / max)) : 2}%` }}
            className={cn(MP.insights.bar, "flex-1 block", v ? "bg-accent" : "bg-bg-elev-2")}
          />
        ))}
      </div>
      <div className={cn(MP.insights.axis, "flex justify-between text-fg-dim")}>
        <span>{new Date(first).toLocaleDateString([], { month: "short", day: "numeric", year: "2-digit" })}</span>
        <span>peak {fmtCents(max)}</span>
        <span>now</span>
      </div>
    </>
  );
}

/** `salesBars` (`messages.js:1472-1490`): the window runs from the first
 *  purchase to now, at least 7 days, split into 12 equal steps. Epoch
 *  milliseconds throughout, so the buckets do not depend on the host zone. */
function salesBars(items: PpvHistoryItem[]) {
  const now = Date.now(), N = 12;
  const times = items.map((i) => parseUtcMs(i.purchased_at)).filter((t): t is number => !!t);
  const first = times.length ? Math.min(...times) : now - 7 * 864e5;
  const span = Math.max(now - first, 7 * 864e5);
  const step = span / N;
  const buckets = new Array<number>(N).fill(0);
  for (const i of items) {
    const t = parseUtcMs(i.purchased_at);
    if (t == null) continue;
    const idx = Math.min(N - 1, Math.max(0, Math.floor((t - first) / step)));
    buckets[idx] += i.price_cents || 0;
  }
  return { buckets, max: Math.max(...buckets), first, step };
}

/** The deleted Clone's `InflowwRea.parseUtc` (tag `legacy-ui-final`): relay stamps can be tz-naive
 *  UTC, so a stamp without a zone is read as UTC. Null when unparseable. */
function parseUtcMs(s: string | null): number | null {
  if (!s) return null;
  let str = s;
  if (/^\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}/.test(str) && !/(Z|[+-]\d{2}:?\d{2})$/.test(str)) {
    str = str.replace(" ", "T") + "Z";
  }
  const t = new Date(str).getTime();
  return Number.isNaN(t) ? null : t;
}

/** The purchased-media rows, last in the Sales tab's Sales block (below the
 *  table, under the block's own title). Renders newest-first; first `INITIAL_SALE_ROWS` shown,
 *  remainder revealed via a "Show N more" button at the BOTTOM (so
 *  scrolling down naturally exposes more, the way infinite-scroll
 *  feeds work). */
function PpvSalesSection({
  items, loading,
  chatMedia, chatMediaLoading, chatMediaFetching, chatMediaUpdatedAt,
  accountId,
  salesLimit, onLoadMore, onRefresh, onOpenMedia, serverFetching,
}: {
  items: PpvHistoryItem[];
  loading: boolean;
  chatMedia: FanChatMediaItem[];
  chatMediaLoading: boolean;
  /** True whenever React Query is fetching ANY page (initial OR
   *  background SWR refetch). Spins the refresh button while active. */
  chatMediaFetching: boolean;
  /** ms epoch the cached chat-media was last refreshed. 0 if never. */
  chatMediaUpdatedAt: number;
  accountId: string;
  /** Current page size requested from both ppv-history + chat-media. */
  salesLimit: number;
  /** Bumps the page size in the parent. Hidden once we've hit the
   *  server cap or the ledger has clearly returned fewer rows than
   *  requested (= no more to load). */
  onLoadMore: () => void;
  /** Invalidates the chat-media cache and refetches both purchased +
   *  unsold filter modes. Wired to the ↻ button above the media rows. */
  onRefresh: () => void;
  /** Opens a media tile in the drawer-level lightbox. Lifted to the
   *  drawer so its Esc handler can yield to the open lightbox. */
  onOpenMedia: (m: LightboxMedia) => void;
  /** True while either upstream is mid-refetch — used to disable the
   *  Load-more button so a fast double-click doesn't queue two bumps. */
  serverFetching: boolean;
}) {
  // OF gallery is the spine (thumbnails + text); ledger items get
  // fuzzy-matched on top for accounting/employee. Falls back to a
  // ledger-only render when OF hasn't responded yet so the section
  // never blanks.
  const detailRows = buildSaleRows(chatMedia, items);

  const [showAll, setShowAll] = useState(false);
  const [expandedKeys, setExpandedKeys] = useState<Set<string>>(() => new Set());

  // Delay the "loading media…" text by 300ms so cached data — which resolves
  // almost instantly — renders its timestamp directly instead of flashing the
  // loading state for a frame or two.
  const [showLoading, setShowLoading] = useState(false);
  useEffect(() => {
    if (!(chatMediaLoading && chatMedia.length === 0)) {
      setShowLoading(false);
      return;
    }
    const t = window.setTimeout(() => setShowLoading(true), 300);
    return () => window.clearTimeout(t);
  }, [chatMediaLoading, chatMedia.length]);

  const toggleExpanded = (key: string) => {
    setExpandedKeys((prev) => {
      const next = new Set(prev);
      if (next.has(key)) next.delete(key); else next.add(key);
      return next;
    });
  };

  const visibleRows = showAll ? detailRows : detailRows.slice(0, INITIAL_SALE_ROWS);
  const hiddenCount = detailRows.length - visibleRows.length;

  return (
    <div className="space-y-2 mt-3">
      <div className="flex items-center justify-end gap-2">
        {showLoading && (
          <span className={cn(MP.ours.FanDrawer.mediaStamp, "text-fg-dim")}>loading media…</span>
        )}
        {!chatMediaLoading && chatMediaUpdatedAt > 0 && (
          <span className={cn(MP.ours.FanDrawer.mediaStamp, "text-fg-dim")} title={new Date(chatMediaUpdatedAt).toLocaleString()}>
            {fmtRelTime(new Date(chatMediaUpdatedAt).toISOString())}
          </span>
        )}
        <button
          type="button"
          onClick={onRefresh}
          disabled={chatMediaFetching}
          title="Refresh OnlyFans gallery now (otherwise auto-refreshes after 30 min)"
          aria-label="Refresh gallery"
          className={cn(
            MP.ours.FanDrawer.mediaRefresh,
            "grid md:block place-items-center text-fg-dim hover:text-fg disabled:opacity-50",
            chatMediaFetching && "animate-spin",
          )}
        >
          ↻
        </button>
      </div>
      {loading && items.length === 0 ? (
        <div className={cn(MP.ours.FanDrawer.status, "text-fg-dim")}>Loading purchase history…</div>
      ) : items.length === 0 ? (
        <div className={cn(MP.ours.FanDrawer.status, "text-fg-dim")}>No PPV purchases yet.</div>
      ) : (
        <div className="space-y-2">
          {visibleRows.map((row) => (
            <PpvSaleRow
              key={row.key}
              row={row}
              accountId={accountId}
              expanded={expandedKeys.has(row.key)}
              onToggle={() => toggleExpanded(row.key)}
              onOpenMedia={onOpenMedia}
            />
          ))}
          {/* Show-more lives at the BOTTOM — newest-first feed pattern,
           *  scroll down to load older. */}
          {hiddenCount > 0 && !showAll && (
            <button
              type="button"
              onClick={() => setShowAll(true)}
              className={cn(MP.ours.FanDrawer.showMore, "w-full text-fg-dim hover:text-fg border-dashed border-border")}
            >
              Show {hiddenCount} more
            </button>
          )}
          {showAll && detailRows.length > INITIAL_SALE_ROWS && (
            <button
              type="button"
              onClick={() => setShowAll(false)}
              className={cn(MP.ours.FanDrawer.showMore, "w-full text-fg-dim hover:text-fg border-dashed border-border")}
            >
              Show less
            </button>
          )}
          {/* Server-side pagination. Only meaningful once everything
           *  already fetched is visible (i.e. user has expanded the
           *  client-side hidden rows) — otherwise "Load more" would
           *  confuse with "Show more". Hidden when the ledger came back
           *  with fewer rows than requested (no more to fetch) OR we're
           *  at the server's hard cap. */}
          {showAll
            && items.length >= salesLimit
            && salesLimit < 200 && (
            <button
              type="button"
              onClick={onLoadMore}
              disabled={serverFetching}
              className={cn(MP.ours.FanDrawer.loadMore, "w-full text-[var(--inf-accent-text,var(--color-accent))] border-dashed border-accent/50 disabled:opacity-50 disabled:cursor-progress")}
            >
              {serverFetching ? "Loading…" : "Load more from server"}
            </button>
          )}
        </div>
      )}
    </div>
  );
}

/** Latest 2 unsold PPVs the creator has sent this fan, the Unsold PPVs
 *  block's body. Each row has a "Send to chat" button that populates the
 *  parent Composer with the exact same payload (text + media + price) so the
 *  operator can re-pitch the unlock in one click; without `onComposeWith`
 *  (read-only) the button is hidden. Always renders: a status line while
 *  loading, when the read failed, and when there are none. */
function UnsoldPpvsSection({
  items, loading, failed, onRetry, accountId, onComposeWith,
}: {
  items: FanChatMediaItem[];
  loading: boolean;
  /** The OF read failed and nothing of this Fan's is loaded. */
  failed: boolean;
  onRetry: () => void;
  accountId: string;
  onComposeWith?: (t: PickedTemplate) => void;
}) {
  const status = cn(MP.ours.FanDrawer.status, "text-fg-dim");
  return (
    <div title={extraTitle("Unsold PPVs")} className="space-y-2">
      {items.length > 0 ? items.map((m) => (
        <UnsoldPpvRow
          key={m.id}
          item={m}
          accountId={accountId}
          onComposeWith={onComposeWith}
        />
      )) : loading ? (
        <div className={status}>Loading unsold PPVs…</div>
      ) : failed ? (
        <div className={status}>
          Couldn&apos;t load unsold PPVs.{" "}
          <button type="button" onClick={onRetry} className="underline hover:text-fg">Retry</button>
        </div>
      ) : (
        <div className={status}>No unsold PPVs sent.</div>
      )}
    </div>
  );
}

function UnsoldPpvRow({
  item, accountId, onComposeWith,
}: {
  item: FanChatMediaItem;
  accountId: string;
  onComposeWith?: (t: PickedTemplate) => void;
}) {
  const text = stripOFHtml(item.text);
  const priceCents = Math.round((item.price ?? 0) * 100);
  const thumbs = pickThumbs(item.media);
  const handleSend = () => {
    if (!onComposeWith) return;
    // Synthesize a PickedTemplate so Composer's existing onPickTemplate
    // handler does the full replace (text + attached vault media + price
    // + lock + previewCount). VaultMedia ids ARE the same ids OF returns
    // on chat-media `media[i].id`, so attaching by id Just Works on send.
    // Chat-media files can lack a url; vaultFilesFromChat drops those.
    const media: VaultMedia[] = item.media.map((mm) => ({
      id: mm.id,
      type: (mm.type as VaultMedia["type"]) || "photo",
      duration: mm.duration,
      files: vaultFilesFromChat(mm.files),
    }));
    onComposeWith({
      source: "of",
      text,
      displayText: item.text,
      mediaCount: item.mediaCount ?? media.length,
      price: item.price ?? 0,
      // OF chat-media doesn't expose lockedText separately; we leave it
      // off so the resend defaults to unlocked-text, matching what the
      // operator usually wants for a follow-up pitch.
      lockedText: false,
      isWelcome: false,
      media,
      previews: [],
      taggedUsers: [],
    });
  };
  return (
    <div className="rounded-md bg-[var(--inf-card,var(--color-bg-elev-1))] border border-[var(--inf-card-border,var(--color-border))] overflow-hidden">
      <div className="flex items-center gap-2 px-2 py-1.5">
        <span className={cn(MP.ours.FanDrawer.pricePill, "inline-flex items-center bg-warn text-white")}>
          <span className="opacity-90">$</span>{fmtPrice(priceCents).slice(1)}
        </span>
        <span className={cn(MP.ours.FanDrawer.rowDate, "text-fg-dim flex-1 min-w-0 truncate")}>
          {fmtFullDateTime(item.createdAt)}
        </span>
        {onComposeWith && (
          <button
            type="button"
            onClick={handleSend}
            className={cn(MP.ours.FanDrawer.sendToChat, "bg-accent hover:bg-accent-hover text-white")}
            title="Load this PPV into the composer"
          >
            Send to chat
          </button>
        )}
      </div>
      {thumbs.length > 0 && (
        <div className="flex gap-1.5 overflow-x-auto px-2 pb-2 -mt-0.5">
          {thumbs.map((t, i) => (
            <div
              key={i}
              className="relative shrink-0 w-16 h-16 rounded-md bg-bg-elev-2 border border-border overflow-hidden"
            >
              {t.rawUrl ? (
                <img
                  src={proxyImage(t.rawUrl, accountId)}
                  alt=""
                  loading="lazy"
                  decoding="async"
                  className="w-full h-full object-cover"
                />
              ) : (
                <div className={cn(MP.ours.FanDrawer.thumbEmpty, "w-full h-full grid place-items-center text-fg-dim")}>—</div>
              )}
              {t.isVideo && (
                <span className="absolute inset-0 grid place-items-center bg-black/20 text-white text-base pointer-events-none">
                  ▶
                </span>
              )}
            </div>
          ))}
        </div>
      )}
      {text && (
        <div className={cn(MP.ours.FanDrawer.unsoldText, "text-fg-dim line-clamp-2 whitespace-pre-wrap break-words")}>
          {text}
        </div>
      )}
    </div>
  );
}

interface PpvSaleThumb {
  /** Raw signed OF CDN url — must be wrapped in proxyImage before rendering. */
  rawUrl: string;
  /** Best full-size url for the lightbox (full → preview → thumb). */
  rawFullUrl: string;
  /** Playable signed video URL for videos (used as both the hover-scrub
   *  source and the lightbox <video src>). Empty for photos. */
  rawVideoUrl: string;
  /** Video duration in seconds — lets the relay's storyboard extractor
   *  skip its own ffprobe step. */
  durationSec: number;
  isVideo: boolean;
}

interface PpvSaleRowData {
  key: string;
  /** OF message id when available (OF gallery row), null for ledger-only fallback. */
  ofMessageId: number | null;
  text: string;
  priceCents: number;
  purchasedAt: string | null;
  thumbs: PpvSaleThumb[];
  // DB enrichment — null if no fuzzy match.
  netCents: number | null;
  feeCents: number | null;
  vatCents: number | null;
  employeeName: string | null;
  employeeColor: string | null;
}

interface LightboxMedia {
  proxiedUrl: string;
  isVideo: boolean;
}

function PpvSaleRow({
  row, accountId, expanded, onToggle, onOpenMedia,
}: {
  row: PpvSaleRowData;
  accountId: string;
  expanded: boolean;
  onToggle: () => void;
  onOpenMedia: (m: LightboxMedia) => void;
}) {
  const accounting = formatAccounting(row);
  return (
    <div className="rounded-md bg-[var(--inf-card,var(--color-bg-elev-1))] border border-[var(--inf-card-border,var(--color-border))] overflow-hidden">
      {/* Header row — green price pill + full date + expand chevron.
       *  Clicking anywhere on this strip toggles the body text. */}
      <button
        type="button"
        onClick={onToggle}
        aria-expanded={expanded}
        className="w-full flex items-center gap-2 px-2 py-1.5 text-left hover:bg-bg-elev-2/40"
      >
        <span className={cn(MP.ours.FanDrawer.pricePill, "inline-flex items-center bg-ok text-white")}>
          <span className="opacity-90">$</span>{fmtPrice(row.priceCents).slice(1)}
        </span>
        <span className={cn(MP.ours.FanDrawer.rowDate, "text-fg-dim flex-1 min-w-0 truncate")}>
          {fmtFullDateTime(row.purchasedAt)}
        </span>
        <span className={cn(MP.ours.FanDrawer.rowChevron, "text-fg-dim transition-transform", expanded && "rotate-180")}>
          ▾
        </span>
      </button>

      {/* Media strip — horizontal scroll, vault-style square tiles.
       *  Click a tile to open it in the lightbox. Videos hover-scrub. */}
      {row.thumbs.length > 0 && (
        <div className="flex gap-1.5 overflow-x-auto px-2 pb-2 -mt-0.5 scrollbar-thin">
          {row.thumbs.map((t, i) => {
            const openInLightbox = () => {
              if (!t.rawFullUrl && !t.rawUrl && !t.rawVideoUrl) return;
              onOpenMedia({
                // Videos: prefer the playable mp4 so the lightbox's
                // <video> can stream it. Photos fall through to the
                // best still.
                proxiedUrl: proxyImage(
                  t.isVideo ? (t.rawVideoUrl || t.rawFullUrl || t.rawUrl)
                            : (t.rawFullUrl || t.rawUrl),
                  accountId,
                ),
                isVideo: t.isVideo,
              });
            };
            return t.isVideo && t.rawVideoUrl ? (
              <VideoScrubThumb
                key={i}
                thumb={t}
                accountId={accountId}
                onClick={openInLightbox}
              />
            ) : (
              <button
                key={i}
                type="button"
                onClick={(e) => { e.stopPropagation(); openInLightbox(); }}
                className="relative shrink-0 w-20 h-20 rounded-md bg-bg-elev-2 border border-border overflow-hidden group"
                title="Click to preview"
              >
                {t.rawUrl ? (
                  <img
                    src={proxyImage(t.rawUrl, accountId)}
                    alt=""
                    loading="lazy"
                    decoding="async"
                    className="w-full h-full object-cover transition-transform group-hover:scale-105"
                  />
                ) : (
                  <div className={cn(MP.ours.FanDrawer.thumbEmpty, "w-full h-full grid place-items-center text-fg-dim")}>—</div>
                )}
                {t.isVideo && (
                  <span className="absolute inset-0 grid place-items-center bg-black/20 text-white text-lg pointer-events-none">
                    ▶
                  </span>
                )}
              </button>
            );
          })}
        </div>
      )}

      {/* Expanded body — full text + accounting/employee. The screenshot's
       *  "Read more" is implicit here: header click opens / closes. */}
      {expanded && (
        <div className={MP.ours.FanDrawer.saleBody}>
          {row.text ? (
            <div className="text-fg whitespace-pre-wrap break-words">{row.text}</div>
          ) : row.thumbs.length > 0 ? (
            // OF matched but no caption — just media. Don't say
            // "media only" as a body since the thumbs above already
            // make that obvious.
            null
          ) : (
            // No OF match at all. The accounting line still shows
            // below; the user knows what was paid even without the
            // captioned content cached. Common causes: the OF gallery
            // page that contains this sale hasn't been loaded yet (try
            // Load more), or the message was deleted on OF.
            <div className="text-fg-dim italic">
              No matching OnlyFans gallery item — try Load more, or the
              original message may have been deleted.
            </div>
          )}
          {(accounting || row.employeeName) && (
            <div className={cn(MP.ours.FanDrawer.saleAccounting, "text-fg-dim flex flex-wrap border-border/60")}>
              {accounting && <span>{accounting}</span>}
              {row.employeeName && (
                <span style={row.employeeColor ? { color: row.employeeColor } : undefined}>
                  · {row.employeeName}
                </span>
              )}
            </div>
          )}
        </div>
      )}
    </div>
  );
}

// Scrub-frame slideshow constants — match VaultPicker so the relay's
// /img/scrub disk cache is reused across surfaces (the relay keys cache
// entries by mp4 hash + frame index, not by caller).
const SCRUB_FRAMES = 12;
const SCRUB_INTERVAL_MS = 600;
const HOVER_DELAY_MS = 400;

/** Video thumb with vault-style hover scrub. Hover-intent debounce
 *  (HOVER_DELAY_MS) kills brush-past thrash; once committed we render
 *  all 12 storyboard frames as overlayed <img> with opacity toggled,
 *  cycling every SCRUB_INTERVAL_MS. Frame fetches go through the
 *  relay's /img/scrub endpoint which builds the storyboard once and
 *  serves cached JPGs on subsequent hovers — so a re-hover is free.
 *  On mouseleave we fire-and-forget a /img/scrub/cancel POST so the
 *  relay can abort the build if it's still mid-download. */
function VideoScrubThumb({
  thumb, accountId, onClick,
}: {
  thumb: PpvSaleThumb;
  accountId: string;
  onClick: () => void;
}) {
  const [hovered, setHovered] = useState(false);
  const [scrubFrameIdx, setScrubFrameIdx] = useState(0);
  const [firstFrameReady, setFirstFrameReady] = useState(false);
  // Countdown shown over the shimmer while the relay extracts the
  // storyboard for a cold video — copied formula from VaultPicker
  // (calibrated against real cold-build timings). Estimate ticks
  // down 5×/sec; if the frame arrives before zero, the whole overlay
  // unmounts via `firstFrameReady`; if zero hits first we show "…".
  const [countdownSec, setCountdownSec] = useState<number>(0);
  // Per-hover session id — forwarded to BOTH the /img/scrub frame
  // requests AND the cancel POST so the relay can scope cancellation
  // to this exact hover session. A delayed cancel from a previous
  // hover of the same video can't reach into a freshly-started build.
  const [sessionId, setSessionId] = useState<string>("");
  const hoverTimerRef = useRef<number | null>(null);
  // Touch devices synthesise mouseenter on tap, so every tap on this thumb
  // would commit a 12-frame relay ffmpeg storyboard build (and the cancel
  // POST rides on mouseleave, which may never fire) while the click opens
  // the lightbox on top of it. Real pointers keep the hover-scrub exactly
  // as it is today.
  const [canHover] = useState(
    () =>
      typeof window !== "undefined" &&
      window.matchMedia("(hover: hover) and (pointer: fine)").matches,
  );

  const start = () => {
    if (hoverTimerRef.current != null) window.clearTimeout(hoverTimerRef.current);
    hoverTimerRef.current = window.setTimeout(() => {
      hoverTimerRef.current = null;
      const sid =
        typeof crypto !== "undefined" && typeof crypto.randomUUID === "function"
          ? crypto.randomUUID()
          : `${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 10)}`;
      setSessionId(sid);
      setScrubFrameIdx(0);
      setFirstFrameReady(false);
      setHovered(true);
    }, HOVER_DELAY_MS);
  };
  const stop = () => {
    if (hoverTimerRef.current != null) {
      window.clearTimeout(hoverTimerRef.current);
      hoverTimerRef.current = null;
    }
    setHovered(false);
  };

  // Initialize the countdown estimate the moment hover commits. Same
  // piecewise formula VaultPicker uses (≤60s clips: ~5-7s; >60s clips:
  // 6.5s + 7s per minute past the first). Tick 5×/sec so the number
  // feels live.
  useEffect(() => {
    if (!hovered) {
      setCountdownSec(0);
      return;
    }
    const dur = Math.max(1, thumb.durationSec || 0);
    const estimate = dur <= 60
      ? Math.max(4, Math.round(4.5 + 0.5 * Math.ceil(dur / 15)))
      : Math.max(4, Math.round(6.5 + (7 * (dur - 60)) / 60));
    setCountdownSec(estimate);
    const startedAt = Date.now();
    const tickId = window.setInterval(() => {
      const elapsed = (Date.now() - startedAt) / 1000;
      setCountdownSec(Math.max(0, estimate - elapsed));
    }, 200);
    return () => window.clearInterval(tickId);
  }, [hovered, thumb.durationSec]);

  // Slideshow cursor — only ticks while hovered AND the first frame
  // has actually painted (so we don't show invisible frames over the
  // thumb during the cold-build wait).
  useEffect(() => {
    if (!hovered || !firstFrameReady) return;
    const id = window.setInterval(() => {
      setScrubFrameIdx((n) => (n + 1) % SCRUB_FRAMES);
    }, SCRUB_INTERVAL_MS);
    return () => window.clearInterval(id);
  }, [hovered, firstFrameReady]);

  // Cancel the relay-side build when the user moves on before the
  // first frame is ready. `keepalive: true` lets the request survive
  // an immediate unmount (e.g. clicked away from the drawer).
  useEffect(() => {
    if (hovered || !sessionId || !thumb.rawVideoUrl) return;
    const tok = typeof window !== "undefined"
      ? new URLSearchParams(window.location.search).get("t")
        ?? window.localStorage.getItem("chatterly:share_token")
      : null;
    const qs = new URLSearchParams();
    qs.set("u", thumb.rawVideoUrl);
    qs.set("sid", sessionId);
    if (tok) qs.set("t", tok);
    fetch(`/img/scrub/cancel?${qs.toString()}`, {
      method: "POST",
      keepalive: true,
    }).catch(() => { /* fire-and-forget */ });
  }, [hovered, sessionId, thumb.rawVideoUrl]);

  return (
    <button
      type="button"
      onClick={(e) => { e.stopPropagation(); onClick(); }}
      onMouseEnter={canHover ? start : undefined}
      onMouseLeave={canHover ? stop : undefined}
      className="relative shrink-0 w-20 h-20 rounded-md bg-bg-elev-2 border border-border overflow-hidden group"
      title={canHover ? "Hover to scrub, click to play" : "Tap to play"}
    >
      {/* Static thumb — always rendered as the loading state /
       *  fallback when frames fail. Frames fade in on top. */}
      {thumb.rawUrl ? (
        <img
          src={proxyImage(thumb.rawUrl, accountId)}
          alt=""
          loading="lazy"
          decoding="async"
          className="absolute inset-0 w-full h-full object-cover"
        />
      ) : (
        <div className={cn(MP.ours.FanDrawer.scrubEmpty, "absolute grid place-items-center text-fg-dim")}>—</div>
      )}
      {hovered && sessionId &&
        Array.from({ length: SCRUB_FRAMES }).map((_, idx) => (
          <img
            // Per-frame key bound to the session id so re-hovers force
            // fresh elements — prevents a stale paint from the previous
            // hover bleeding into the new session.
            key={`${sessionId}-${idx}`}
            src={proxyScrubFrame(
              thumb.rawVideoUrl,
              accountId,
              idx,
              thumb.durationSec,
              sessionId,
            )}
            alt=""
            aria-hidden={idx !== scrubFrameIdx}
            decoding="async"
            // Clear the shimmer on the first frame that paints — keying off
            // ANY frame (not just frame 0) means a single failed frame-0
            // fetch can't pin the shimmer forever. The setter is idempotent.
            onLoad={() => setFirstFrameReady(true)}
            // Belt-and-suspenders: if frame 0 itself errors, drop the shimmer
            // so we fall back to the static thumb instead of hanging on it.
            onError={idx === 0 ? () => setFirstFrameReady(true) : undefined}
            style={{
              opacity: idx === scrubFrameIdx && firstFrameReady ? 1 : 0,
            }}
            className="absolute inset-0 w-full h-full object-cover transition-opacity duration-200"
          />
        ))}
      {/* Cold-build shimmer + countdown — covers the thumb while the
       *  relay is extracting the storyboard. Unmounts as soon as the
       *  first frame paints (firstFrameReady → slideshow takes over).
       *  Cached videos go straight to firstFrameReady on the first
       *  frame's onLoad so the shimmer is invisible there. */}
      {hovered && !firstFrameReady && (
        <>
          <div aria-hidden className="scrub-shimmer pointer-events-none" />
          <div
            aria-hidden
            className="absolute inset-0 grid place-items-center pointer-events-none"
          >
            <span className={cn(MP.ours.FanDrawer.countdown, "text-white/85 drop-shadow-black/70")}>
              {countdownSec > 0 ? `${Math.ceil(countdownSec)}s` : "…"}
            </span>
          </div>
        </>
      )}
      {!hovered && (
        <span className="absolute inset-0 grid place-items-center bg-black/20 text-white text-lg pointer-events-none">
          ▶
        </span>
      )}
    </button>
  );
}

function MediaLightbox({ media, onClose }: { media: LightboxMedia; onClose: () => void }) {
  // Close on Esc — mirrors the drawer's own Esc handling so the keyboard
  // story is consistent (Esc collapses one layer at a time).
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") onClose(); };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);
  return (
    <div
      className="fixed inset-0 z-50 bg-black/80 flex items-center justify-center p-4"
      onClick={onClose}
    >
      {media.isVideo ? (
        <video
          src={media.proxiedUrl}
          controls
          autoPlay
          playsInline
          className="max-w-full max-h-full rounded-md"
          onClick={(e) => e.stopPropagation()}
        />
      ) : (
        <img
          src={media.proxiedUrl}
          alt=""
          className="max-w-full max-h-full rounded-md"
          onClick={(e) => e.stopPropagation()}
        />
      )}
      <button
        type="button"
        onClick={onClose}
        className={cn(MP.ours.FanDrawer.lightboxClose, "absolute text-white grid place-items-center bg-black/40 hover:bg-black/60")}
        aria-label="Close preview"
      >
        ×
      </button>
    </div>
  );
}

function fmtFullDateTime(iso: string | null): string {
  if (!iso) return "—";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "—";
  // "May 24, 2026 at 7:04 PM" — matches the OF screenshot phrasing.
  const datePart = d.toLocaleDateString(undefined, {
    month: "short", day: "numeric", year: "numeric",
  });
  const timePart = d.toLocaleTimeString(undefined, {
    hour: "numeric", minute: "2-digit",
  });
  return `${datePart} at ${timePart}`;
}

function formatAccounting(row: PpvSaleRowData): string | null {
  const parts: string[] = [];
  if (row.netCents != null) parts.push(`net ${fmtPrice(row.netCents)}`);
  if (row.feeCents != null) parts.push(`fee ${fmtPrice(row.feeCents)}`);
  if (row.vatCents != null && row.vatCents !== 0) parts.push(`VAT ${fmtPrice(row.vatCents)}`);
  return parts.length ? parts.join(" · ") : null;
}

function pickThumbs(media: FanChatMediaItem["media"]): PpvSaleThumb[] {
  if (!media) return [];
  return media.map((m) => {
    const f = m.files ?? {};
    const thumbUrl =
      f.squarePreview?.url ?? f.thumb?.url ?? f.preview?.url ?? f.full?.url ?? "";
    // Lightbox prefers the full asset; falls back to preview then thumb
    // so a missing `full` (common on locked / no-longer-purchasable media)
    // still gives us something to render in the overlay.
    const fullUrl =
      f.full?.url ?? f.preview?.url ?? f.squarePreview?.url ?? f.thumb?.url ?? "";
    const isVideo = m.type === "video";
    // For videos OF puts the playable mp4 under files.full; preview is a
    // shorter teaser clip on some items, full on others. The relay's
    // /img/scrub builder needs a real mp4, so prefer full → preview.
    const videoUrl = isVideo ? (f.full?.url ?? f.preview?.url ?? "") : "";
    return {
      rawUrl: thumbUrl ?? "",
      rawFullUrl: fullUrl ?? "",
      rawVideoUrl: videoUrl ?? "",
      durationSec: typeof m.duration === "number" ? m.duration : 0,
      isVideo,
    };
  });
}

/** True when OF's list price (in cents) plausibly corresponds to a
 *  ledger row's gross amount. The relationship isn't always 1:1:
 *    • creator sets list price X (e.g. $18.00)
 *    • OF charges fan X + VAT (varies by region, ~12% in EU)
 *    • OF returns `price: 18` on the gallery row regardless
 *    • our ledger row carries amount_cents = gross paid by fan
 *      (sometimes $18, sometimes $18.03 due to FX rounding, $20.16
 *      with VAT, etc.)
 *
 *  We accept a match if the OF price equals any of the following
 *  derivations of the ledger amount, ±2¢ rounding tolerance:
 *    • amount_cents               (no-VAT region; common case)
 *    • amount_cents − vat_cents   (when ledger amount is VAT-inclusive)
 *    • amount_cents + vat_cents   (when ledger amount is ex-VAT)
 *    • net_cents + fee_cents      (some Phase-F rows store these split)
 *  Plus a ±10% loose fallback to catch OF's occasional ad-hoc discount
 *  rounding. The strict candidates win first; loose only fires when no
 *  strict match exists in the whole gallery. */
function priceMatchScore(ofCents: number, it: PpvHistoryItem): "strict" | "loose" | null {
  const lc = it.price_cents;
  const candidates: number[] = [lc];
  if (it.vat_cents) {
    candidates.push(lc - it.vat_cents);
    candidates.push(lc + it.vat_cents);
  }
  if (it.net_cents != null && it.fee_cents != null) {
    candidates.push(it.net_cents + it.fee_cents);
  }
  for (const c of candidates) {
    if (Math.abs(ofCents - c) <= 2) return "strict";
  }
  if (lc > 0 && Math.abs(ofCents - lc) / lc < 0.10) return "loose";
  return null;
}

/** Unified row builder — ledger is the spine (source of truth for what
 *  was paid), OF gallery enriches with thumbnails + text.
 *
 *  Matching pass order:
 *    1. ledger.message_id == OF.id  (definitive, when ledger has the id)
 *    2. price strict-match (any of the candidate derivations ±2¢),
 *       nearest |createdAt − purchased_at| wins
 *    3. price loose-match (±10%), nearest time wins
 *
 *  Each OF item is consumed at most once so two same-priced ledger rows
 *  on the same day can't both claim a single gallery entry. */
function buildSaleRows(
  media: FanChatMediaItem[],
  ledger: PpvHistoryItem[],
): PpvSaleRowData[] {
  const sortedLedger = [...ledger].sort(
    (a, b) =>
      +new Date(b.purchased_at ?? b.sent_at ?? 0) -
      +new Date(a.purchased_at ?? a.sent_at ?? 0),
  );
  const mediaById = new Map(media.map((m) => [m.id, m] as const));
  const usedMediaIds = new Set<number>();

  function chooseMedia(it: PpvHistoryItem): FanChatMediaItem | null {
    // Pass 1: hard message-id match.
    if (it.message_id != null) {
      const direct = mediaById.get(it.message_id);
      if (direct && !usedMediaIds.has(direct.id)) return direct;
    }
    // Pass 2+3: collect strict and loose price candidates, then pick by
    // time-proximity within the tighter bucket.
    const ts = +new Date(it.purchased_at ?? it.sent_at ?? 0);
    let bestStrict: FanChatMediaItem | null = null;
    let bestStrictDelta = Number.POSITIVE_INFINITY;
    let bestLoose: FanChatMediaItem | null = null;
    let bestLooseDelta = Number.POSITIVE_INFINITY;
    for (const m of media) {
      if (usedMediaIds.has(m.id)) continue;
      const ofCents = Math.round((m.price ?? 0) * 100);
      const score = priceMatchScore(ofCents, it);
      if (!score) continue;
      const mTs = +new Date(m.createdAt);
      const delta = ts && mTs ? Math.abs(mTs - ts) : Number.POSITIVE_INFINITY;
      if (score === "strict") {
        if (delta < bestStrictDelta) { bestStrictDelta = delta; bestStrict = m; }
      } else if (delta < bestLooseDelta) {
        bestLooseDelta = delta; bestLoose = m;
      }
    }
    return bestStrict ?? bestLoose;
  }

  return sortedLedger.map((it) => {
    const best = chooseMedia(it);
    if (best) usedMediaIds.add(best.id);
    return {
      key: `tx-${it.transaction_id}`,
      ofMessageId: best?.id ?? it.message_id,
      text: best ? stripOFHtml(best.text) : "",
      priceCents: it.price_cents,
      purchasedAt: it.purchased_at ?? it.sent_at,
      thumbs: best ? pickThumbs(best.media) : [],
      netCents: it.net_cents,
      feeCents: it.fee_cents,
      vatCents: it.vat_cents,
      employeeName: it.employee_name,
      employeeColor: it.employee_color,
    };
  });
}

function sameList(a: string[], b: string[]): boolean {
  if (a.length !== b.length) return false;
  const A = a.slice().sort();
  const B = b.slice().sort();
  return A.every((v, i) => v === B[i]);
}

// Per-fan language override options. "Default (account)" is the empty value — it clears
// the override so the fan follows the account's language. Picking one pins it MANUAL,
// so gen_info's auto-detection can never change it.
const LANGUAGE_OPTIONS: { code: string; label: string }[] = [
  { code: "en", label: "English" },
  { code: "es", label: "Español" },
  { code: "sl", label: "Slovenščina" },
  { code: "pt", label: "Português" },
  { code: "fr", label: "Français" },
  { code: "de", label: "Deutsch" },
  { code: "it", label: "Italiano" },
];

function languageHint(language: string | null, source: string | null): string {
  if (!language) return "Using the account default. Pick one to pin this fan.";
  if (source === "manual") return "Manual override — auto-detection won't change it.";
  return "Auto-detected. Pick one to pin it (stops auto-detection).";
}

const LANG_LABEL: Record<string, string> = {
  en: "English", es: "Español", sl: "Slovenščina", pt: "Português",
  fr: "Français", de: "Deutsch", it: "Italiano",
};

function fmtCommStyle(cs: Record<string, unknown> | undefined): string {
  if (!cs) return "";
  return Object.entries(cs).filter(([, v]) => v === true).map(([k]) => k.replace(/_/g, " ")).join(", ");
}

// Read-only card summarising what gen_info learned: the detected language, the rich
// note, the extracted facts, a dated timeline, and the openers it wrote.
function ProfileCard({ fan }: { fan: FanRecord }) {
  const p = fan.profile;
  const facts: [string, string | null | undefined][] = [
    ["Age", fan.his_age],
    ["Location", [fan.home_city, fan.home_country].filter(Boolean).join(", ") || null],
    ["Job", fan.occupation],
    ["Employer", fan.employer],
    ["Relationship", fan.relationship_status],
    ["Stage", fan.relationship_stage],
    ["Kids", fan.has_kids == null ? null : fan.has_kids ? "yes" : "no"],
    ["Pets", Array.isArray(fan.pets) && fan.pets.length ? fan.pets.map(petLabel).join(", ") : null],
    ["Style", fmtCommStyle(fan.communication_style) || null],
  ];
  const shown = facts.filter(([, v]) => v);
  const timeline = (fan.recent_events_timeline ?? []).filter((t) => t?.event);
  const richNote = p?.rich_note?.trim();
  const langCode = fan.language ?? "";
  const nothing = !richNote && shown.length === 0 && timeline.length === 0 &&
    !(p?.q?.length) && !(p?.tease?.length);

  return (
    <div title={extraTitle("Generated profile note")} className="rounded-lg border border-[var(--inf-card-border,var(--color-border))] bg-[var(--inf-card,var(--color-bg-elev-1))]/40 p-3">
      <div className="flex items-center justify-between mb-2">
        <span className={cn(MP.ours.FanDrawer.sectionHeading, "text-fg-dim uppercase")}>AI profile</span>
        <div className="flex items-center gap-2">
          {langCode ? (
            <span className={cn(MP.ours.FanDrawer.langChip, "border-border text-fg-dim")}
              title={fan.language_source === "manual" ? "Manual override" : "Auto-detected"}>
              🌐 {LANG_LABEL[langCode] ?? langCode}
              {fan.language_source === "manual" ? " · pinned" : ""}
            </span>
          ) : null}
          {p?.last_generated_at ? (
            <span className={cn(MP.ours.FanDrawer.profileMeta, "text-fg-dim")}>{fmtRelTime(p.last_generated_at)}</span>
          ) : null}
        </div>
      </div>

      {nothing ? (
        <div className={cn(MP.ours.FanDrawer.profileText, "text-fg-dim")}>No profile yet — gen_info fills this once he chats a little.</div>
      ) : (
        <div className="flex flex-col gap-3">
          {richNote ? (
            <div className={cn(MP.ours.FanDrawer.profileNote, "text-fg whitespace-pre-line")}>{richNote}</div>
          ) : null}

          {shown.length ? (
            <div className="grid grid-cols-2 gap-x-3 gap-y-1">
              {shown.map(([k, v]) => (
                <div key={k} className={MP.ours.FanDrawer.profileText}>
                  <span className="text-fg-dim">{k}: </span><span className="text-fg">{v}</span>
                </div>
              ))}
            </div>
          ) : null}

          {timeline.length ? (
            <div>
              <div className={cn(MP.ours.FanDrawer.timelineLabel, "text-fg-dim uppercase")}>Timeline</div>
              <ul className="space-y-0.5">
                {timeline.slice(-6).reverse().map((t, i) => (
                  <li key={i} className={cn(MP.ours.FanDrawer.profileText, "text-fg-dim")}>
                    <span className={cn(MP.ours.FanDrawer.profileMeta, "font-mono")}>{t.date}</span> · <span className="text-fg">{t.event}</span>
                  </li>
                ))}
              </ul>
            </div>
          ) : null}

          {p?.q?.length || p?.tease?.length ? (
            <div className={cn(MP.ours.FanDrawer.profileMeta, "text-fg-dim")}>
              {p?.q?.length ? <div>{p.q.length} question{p.q.length > 1 ? "s" : ""} + {p?.tease?.length ?? 0} tease{(p?.tease?.length ?? 0) > 1 ? "s" : ""} ready</div> : null}
            </div>
          ) : null}
        </div>
      )}
    </div>
  );
}

function petLabel(p: unknown): string {
  if (p && typeof p === "object") {
    const o = p as Record<string, unknown>;
    return [o.kind, o.name].filter(Boolean).join(" ") || JSON.stringify(o);
  }
  return String(p);
}

// OF stores both the per-fan rename and the private creator-side note on
// the subscription object. Both use PUT /subscriptions/{id} but the relay
// exposes them as separate endpoints. Empty string clears the field on OF.
// X-Account-Id (via the ctx) is required — without it the relay can't
// route the upstream call to the right account's OFClient.
function writeOFCustomName(accountId: string, fanId: FanId, name: string) {
  return relay.put(
    `/api/of/v2/subscriptions/${fanId}/custom-name`,
    { name },
    { accountId },
  );
}

function writeOFNotice(accountId: string, fanId: FanId, note: string) {
  return relay.put(
    `/api/of/v2/subscriptions/${fanId}/note`,
    { note },
    { accountId },
  );
}

