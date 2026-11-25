"use client";


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
import { useCan } from "@/hooks/useCan";
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
import { storedSpendCents } from "./totalSpend";
import { useInsightsBlocks, type InsightsBlockId } from "./useInsightsBlocks";
import { type PickedTemplate } from "./TemplatePicker";
import { effectiveFields, fanDrawerFormReducer, INITIAL_FORM, nickPatch, notesPatch, tagsPatch } from "./fanDrawerForm";
import { fmtSummDollars, pageFigure, unsoldOf, type LightboxMedia } from "./fanDrawerSales";
import { MediaLightbox, PpvSalesSection, PurchasesOverTime, SalesTable, UnsoldPpvsSection } from "./FanDrawerSalesView";
import {
  autoRenewal, Badge, BLOCK_TITLE, BlurEdit, InfoIcon, INLINE_EDIT, INSIGHTS_TABS, InsightsBlock, InsightsRow, LANGUAGE_OPTIONS,
  languageHint, LocalTime,
  InsightsHead, MassExcludeToggle, MM_DD, NickEdit, ProfileCard, RULE, TAB_HINT, TAB_ICON, TAB_LABEL, toneClass, useFocusRequest,
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
  pinned?: boolean;
  onComposeWith?: (t: PickedTemplate) => void;
  focusNotesRequest?: number;
  focusNicknameRequest?: number;
}) {
  const { data: fan, isLoading, update } = useFan(accountId, fanId);
  const accountLabel = useAccountLabel(accountId);
  const ofUserQ = useOFUser(accountId, fanId);
  const lastPurchaseAccountIds = useMemo(() => [accountId], [accountId]);
  const activity = useFanActivity(lastPurchaseAccountIds);
  const lastPurchase = activity.lastPurchase.get(`${accountId}:${fanId}`) ?? null;
  const recentSpend = activity.recentSpend.get(`${accountId}:${fanId}`) ?? 0;
  const [salesLimit, setSalesLimit] = useState(12);
  const ppvHistoryQ = useFanPpvHistory(accountId, fanId, salesLimit);
  const insights = useFanInsights(accountId, fanId, open).data;
  const chatMediaQ = useFanChatMedia(accountId, fanId, {
    purchased: true,
    limit: 20,
    enabled: open && (ppvHistoryQ.data?.items.length ?? 0) > 0,
  });
  const chatMediaFlat = useMemo(
    () => chatMediaQ.data?.pages.flatMap((p) => p.list) ?? [],
    [chatMediaQ.data],
  );

  // from_user=<accountId>: creator-sent items only
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

  const qc = useQueryClient();
  const refreshChatMedia = () => {
    void qc.invalidateQueries({
      queryKey: ["fan-chat-media", accountId, fanId],
      exact: false,
    });
    void qc.invalidateQueries({
      queryKey: ["fan-ppv-history", accountId, fanId],
      exact: false,
    });
    void qc.invalidateQueries({ queryKey: ["last-purchases", accountId] });
    void qc.invalidateQueries({ queryKey: ofUserNameKey(accountId, fanId) });
    void qc.invalidateQueries({ queryKey: ["fan", accountId, fanId] });
  };

  const { effectiveNickname, effectiveNotes } = effectiveFields(ofUserQ, chat.withUser, fan);

  const [form, dispatch] = useReducer(fanDrawerFormReducer, INITIAL_FORM);
  const [lightbox, setLightbox] = useState<LightboxMedia | null>(null);
  const [tab, setTab] = useState<InsightsTab>("insights");
  const { open: addOpen, setOpen: setAddOpen, ref: addRef } = useOutsideClose();
  const canMedia = useCan(accountId, "chat_media");
  const blocks = useInsightsBlocks(canMedia ? null : "unsoldPpvs");
  const drag = useReorder(blocks.shown, blocks.reorder, (id) => id);
  const uid = useId();
  // of-user is cached 5 min and not refetched on open: re-read OF when an edit starts, else a stale prefill gets typed over and a save reverts the other change
  const ofRefetch = ofUserQ.refetch;
  const editRefreshAtRef = useRef(0);
  useEffect(() => { editRefreshAtRef.current = 0; }, [open, accountId, fanId]);
  const refreshBeforeEdit = useCallback(() => {
    if (Date.now() - editRefreshAtRef.current < OF_USER_STALE_MS) return;
    editRefreshAtRef.current = Date.now();
    void ofRefetch();
  }, [ofRefetch]);

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
    dispatch({ type: "adopt", nick: effectiveNickname, notes: effectiveNotes, tags: (fan.tags ?? []).join(", ") });
  }, [fan, effectiveNickname, effectiveNotes]);

  // While the media lightbox is open it owns Esc: no listener here, so one Esc closes one layer
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
  const overlayRef = useRef<HTMLDivElement>(null);
  const panelRef = useRef<HTMLElement>(null);
  const backdropRef = useRef<HTMLDivElement>(null);
  useSwipe(overlayRef, {
    enabled: open && !pinned && !lightbox, dir: "right", onSwipe: onClose, sheet: { panel: panelRef, backdrop: backdropRef },
  });
  useExitGhost(open && !pinned, overlayRef);

  if (!open) return null;

  const displayName =
    effectiveNickname ||
    chat.withUser.name ||
    fan?.of_display_name ||
    chat.withUser.username ||
    `fan ${fanId}`;

  // OF signs CDN URLs for the account's egress IP: go through the relay's /img
  const avatar = proxyImage(chat.withUser.avatar || fan?.avatar_url, accountId) || null;

  const sub = ofUserQ.data?.subscribedOnData;
  const subStatus = interpretSubStatus(
    sub?.status ?? fan?.subscription_status,
    sub?.expiredAt ?? null,
  );
  const fanLists = (ofUserQ.data?.listsStates ?? []).filter((l) => l.hasUser && l.name);
  // Max of three: OF's totalSumm briefly reads 0; the recent and stored fallbacks keep known spend showing.
  const spendCents = Math.max(
    typeof sub?.totalSumm === "number" ? Math.round(sub.totalSumm * 100) : 0,
    recentSpend,
    storedSpendCents(fan),
  );

  const card = (id: InsightsBlockId): BlockCard => {
    const i = blocks.shown.indexOf(id);
    const dragging = drag.draggingIndex;
    return {
      onDragStart: (e) => drag.onDragStart(e, i),
      onDragOver: (e) => { if (dragging !== null) drag.onDragOver(e, i); },
      onDrop: (e) => drag.onDrop(e, i),
      onDragEnd: drag.onDragEnd,
      onMove: (dir) => drag.onKeyboardMove(i, dir),
      dragging: dragging === i,
      over: dragging !== null && dragging !== i && drag.dragOverIndex === i,
      onRemove: () => blocks.remove(id),
    };
  };

  const insightsBlocks = fan ? ({
    spending: (
      <InsightsBlock
        card={card("spending")}
        title={BLOCK_TITLE.spending}
        trail={
          <>
            <hr className={RULE} />
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
                className={cn(INLINE_EDIT, "flex-none max-w-full appearance-none cursor-pointer [text-align-last:right] supports-[appearance:base-select]:[appearance:base-select] [&::picker-icon]:hidden")}
              >
                <option value="">Default (account)</option>
                {LANGUAGE_OPTIONS.map((l) => (
                  <option key={l.code} value={l.code}>{l.label}</option>
                ))}
              </select>
            </NickEdit>
          }
        />
        {/* OF has no birthday field: ours, "MM-DD", read by Smart Messages' Birthday Trigger. */}
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
        {/* FanRecord.source is a relationship class, not how the Fan was acquired. */}
        <InsightsRow term="Source" value="—" />
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
                className={cn(INLINE_EDIT, "flex-none max-w-full appearance-none cursor-pointer [text-align-last:right] supports-[appearance:base-select]:[appearance:base-select] [&::picker-icon]:hidden")}
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
              {blocks.shown.map((id) => <Fragment key={id}>{insightsBlocks[id]}</Fragment>)}
            </div>
          )}

          {fan && tab === "sales" && (
            <>
              <InsightsBlock
                title="Purchases over time"
                trail={<PurchasesOverTime items={ppvHistoryQ.data?.items ?? []} loading={ppvHistoryQ.isLoading} />}
              />
              <InsightsBlock
                title="Sales"
                plainTitle
                trail={<>
                  <SalesTable items={ppvHistoryQ.data?.items ?? []} />
                  {canMedia && <PpvSalesSection
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
                      if (chatMediaQ.hasNextPage && !chatMediaQ.isFetchingNextPage) {
                        void chatMediaQ.fetchNextPage();
                      }
                    }}
                    onRefresh={refreshChatMedia}
                    onOpenMedia={setLightbox}
                    serverFetching={
                      ppvHistoryQ.isFetching || chatMediaQ.isFetchingNextPage
                    }
                  />}
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
              <InsightsBlock title="Creator notes" trail={<p className={MP.insights.metricPlain}>—</p>} />
              <ProfileCard fan={fan} />
              <div title={extraTitle("Persona claims")}>
                <PersonaClaims accountId={accountId} fan={fan}
                               onSave={(patch) => update.mutate(patch)} />
              </div>
            </>
          )}

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
              title={TAB_HINT[t]}
              onClick={() => setTab(t)}
              className={cn(
                MP.insights.tab,
                "flex-1 flex flex-col items-center",
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
  return (
    <div ref={overlayRef} className="absolute inset-0 z-30 flex pointer-events-none lg:hidden">
      <div ref={backdropRef} className="pop-backdrop flex-1 min-w-14 sm:min-w-0 bg-black/40 pointer-events-auto" onClick={onClose} />
      {panel}
    </div>
  );
}

// PUT /subscriptions/{id}: empty string clears the field on OF; X-Account-Id routes it to the right OFClient
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
