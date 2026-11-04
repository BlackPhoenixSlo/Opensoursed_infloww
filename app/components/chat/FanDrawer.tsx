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

import { Fragment, useCallback, useEffect, useId, useMemo, useReducer, useRef, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";

import { useFan } from "@/hooks/useFan";
import { useExitGhost } from "@/hooks/useExitGhost";
import { useSwipe } from "@/hooks/useSwipe";
import { useAccountLabel } from "@/hooks/useAccounts";
import { OF_USER_STALE_MS, ofUserNameKey, useOFUser } from "@/hooks/useOFUser";
import { useFanActivity } from "@/hooks/useLastPurchases";
import { useFanPpvHistory } from "@/hooks/useFanPpvHistory";
import { useFanChatMedia } from "@/hooks/useFanChatMedia";
import { useFanInsights } from "@/hooks/useFanInsights";
import { fmtCents } from "@/lib/messageFormat";
import { fmtPrice } from "@/lib/format";
import { relay, SALARY_FREQUENCIES, type OFChatItem } from "@/lib/relay";
import { proxyImage } from "@/lib/mediaUrl";
import { type FanId } from "@/lib/fanId";
import { MP } from "@/lib/messagesPro";
import { extraTitle } from "@/lib/openinflowwwwExtras";
import { useReorder } from "@/hooks/useReorder";
import { useOutsideClose } from "@/components/ui/Menu";
import { cn, fmtRelTime, interpretSubStatus } from "@/lib/utils";
import { PersonaClaims } from "./PersonaClaims";
import { useInsightsBlocks, type InsightsBlockId } from "./useInsightsBlocks";
import { type PickedTemplate } from "./TemplatePicker";
import { effectiveFields, fanDrawerFormReducer, INITIAL_FORM, nickPatch, notesPatch, tagsPatch } from "./fanDrawerForm";
import { fmtSummDollars, pageFigure, unsoldOf, type LightboxMedia } from "./fanDrawerSales";
import { MediaLightbox, PpvSalesSection, PurchasesOverTime, SalesTable, UnsoldPpvsSection } from "./FanDrawerSalesView";
import {
  autoRenewal, Badge, BLOCK_TITLE, BlurEdit, InfoIcon, INLINE_EDIT, INSIGHTS_TABS, InsightsBlock, InsightsRow, LANGUAGE_OPTIONS,
  languageHint, LocalTime,
  InsightsHead, MassExcludeToggle, MM_DD, NickEdit, ProfileCard, RULE, TAB_ICON, TAB_LABEL, toneClass, useFocusRequest,
  type BlockCard, type InsightsTab,
} from "./FanDrawerParts";

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
  // to `from_user=<accountId>` so we get creator-sent items only; `unsoldOf`
  // picks the latest 2 and says when to page on. Another Fan's page kept as
  // placeholder while this one loads counts as loading, not as this Fan's.
  const unsoldChatMediaQ = useFanChatMedia(accountId, fanId, {
    purchased: false,
    limit: 20,
    enabled: open,
  });
  const unsoldPages = unsoldChatMediaQ.isPlaceholderData ? undefined : unsoldChatMediaQ.data?.pages;
  const { items: unsoldPpvs, wantMore: unsoldWantMore } = useMemo(() => unsoldOf(unsoldPages), [unsoldPages]);
  const { hasNextPage: unsoldHasMore, isFetching: unsoldFetching, fetchNextPage: unsoldNextPage } = unsoldChatMediaQ;
  useEffect(() => {
    if (!open || !unsoldWantMore || !unsoldHasMore || unsoldFetching) return;
    void unsoldNextPage();
  }, [open, unsoldWantMore, unsoldHasMore, unsoldFetching, unsoldNextPage]);

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

  // The "effective" nickname/note: OF once resolved (even empty), else the
  // chat-list value, then our local mirror (`effectiveFields`).
  const { effectiveNickname, effectiveNotes } = effectiveFields(ofUserQ, chat.withUser, fan);

  // Local form mirrors, their last-applied values and the OF write-through
  // error (`fanDrawerForm`). Adopt whenever the effective value (from OF or local) changes.
  const [form, dispatch] = useReducer(fanDrawerFormReducer, INITIAL_FORM);
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
    // Only untouched fields take it; a fresh OF read (e.g. the pre-edit refresh above) never clobbers typing.
    dispatch({ type: "adopt", nick: effectiveNickname, notes: effectiveNotes, tags: (fan.tags ?? []).join(", ") });
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
  // A swipe right on the slide-over or its backdrop closes it, as Esc does: not
  // the pinned column, and not while the lightbox is up. It slides as an iOS
  // sheet (`useSwipe`: follows the finger, the backdrop fades with it, closes
  // when the release would carry it 75% out); closed any other way it leaves
  // on a non-blocking copy (`useExitGhost`).
  const overlayRef = useRef<HTMLDivElement>(null);
  const panelRef = useRef<HTMLElement>(null);
  const backdropRef = useRef<HTMLDivElement>(null);
  useSwipe(overlayRef, {
    enabled: open && !pinned && !lightbox, dir: "right", onSwipe: onClose, sheet: { panel: panelRef, backdrop: backdropRef },
  });
  useExitGhost(open && !pinned, overlayRef);

  if (!open) return null;

  // `effectiveNickname`: OF name (chat-list name until OF resolves), else the local mirror.
  const displayName =
    effectiveNickname ||
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
                value={form.nick}
                onChange={(e) => dispatch({ type: "edit", field: "nick", value: e.target.value })}
                onFocus={refreshBeforeEdit}
                onBlur={() => {
                  const patch = nickPatch(form.nick, effectiveNickname);
                  if (!patch) return;
                  dispatch({ type: "clearError" });
                  update.mutate(patch);
                  void writeOFCustomName(accountId, fanId, patch.custom_nickname ?? "").catch((err) => {
                    console.warn("[fan-drawer] OF custom-name write failed", err);
                    dispatch({ type: "ofWriteFailed", field: "nick" });
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
                value={form.tags}
                onChange={(e) => dispatch({ type: "edit", field: "tags", value: e.target.value })}
                onBlur={() => {
                  const patch = tagsPatch(form.tags, fan.tags ?? []);
                  if (patch) update.mutate(patch);
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
            value={form.notes}
            onChange={(e) => dispatch({ type: "edit", field: "notes", value: e.target.value })}
            onFocus={refreshBeforeEdit}
            onBlur={() => {
              const patch = notesPatch(form.notes, effectiveNotes);
              if (!patch) return;
              dispatch({ type: "clearError" });
              update.mutate(patch);
              void writeOFNotice(accountId, fanId, form.notes).catch((err) => {
                console.warn("[fan-drawer] OF notice write failed", err);
                dispatch({ type: "ofWriteFailed", field: "notes" });
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
      ref={panelRef}
      role={pinned ? undefined : "dialog"}
      aria-modal={pinned ? undefined : true}
      aria-label="Fan insights"
      data-mp-pane={pinned ? "insights" : undefined}
      className={
        pinned
          ? cn(MP.panes.insights, "hidden lg:flex shrink-0 bg-[var(--inf-insights,var(--color-panel))] border-[var(--inf-rule,var(--color-border))] flex-col h-full")
          : cn(MP.ours.FanDrawer.slideOver, MP.ours.FanDrawer.pullFill, "sheet-right bg-[var(--inf-insights,var(--color-panel))] border-[var(--inf-rule,var(--color-border))] shadow-2xl pointer-events-auto flex flex-col after:bg-[var(--inf-insights,var(--color-panel))]")
      }
    >
        <InsightsHead uid={uid} tab={tab} setTab={setTab} blocks={blocks} onClose={onClose}
                      addOpen={addOpen} setAddOpen={setAddOpen} addRef={addRef} />

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
          {fan && form.ofWriteError && (
            <div className="text-err text-xs">{form.ofWriteError}</div>
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
    <div ref={overlayRef} className="absolute inset-0 z-30 flex pointer-events-none lg:hidden">
      <div ref={backdropRef} className="pop-backdrop flex-1 min-w-14 sm:min-w-0 bg-black/40 pointer-events-auto" onClick={onClose} />
      {panel}
    </div>
  );
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
