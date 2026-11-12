"use client";

import { useId, useReducer, useState } from "react";

import { Plus } from "lucide-react";

import { Badge, Button, Input } from "@/components/ui/primitives";
import { HbButton, HbModal } from "@/components/ui/infloww";
import { CopyButton, errMsg } from "@/components/growth/_bits";
import { CreatorFilter, GrowthHbFrame, RowMenu } from "@/components/growth/LinksListFrame";
import { SectionTitle, StatCard } from "@/components/home/ReportsCharts";
import {
  useTrackingLinks, useCreateTrackingLink, useDeleteTrackingLink, useTrackingSummary, useUpdateTrackingLink,
} from "@/hooks/useGrowth";
import { useGrowthCreator } from "@/hooks/useAccounts";
import { DASH } from "@/components/growth/linkMetrics";
import { buildPayload, formError, INITIAL_FORM, redirectFormReducer } from "@/components/growth/customRedirectForm";
import { INITIAL_VIEW, statsRequest, statsViewReducer, summaryCards, verifiedSummary } from "@/components/growth/redirectStats";
import { LinkStats, ClickSparkline } from "@/components/growth/RedirectLinkStats";

const BOT_CHECK_HINT = "Fans pass a Cloudflare bot check (Turnstile) before the redirect; only passed checks count as clicks.";
const BOT_CHECK_OFF = "Unavailable: the server has no Turnstile keys (TURNSTILE_SITE_KEY / TURNSTILE_SECRET_KEY).";

/** The internal link is same-origin (Next rewrites /t/* to the relay). */
function publicUrl(path: string): string {
  if (typeof window === "undefined") return path;
  return `${window.location.origin}${path}`;
}

/** /growth/redirect-links (an Inflowwww extra, its own Growth entry since 11-12; was a Tracking links tab): the panel in
 *  the Growth HB frame, every viewer of the page as before. */
export function RedirectLinksPage() {
  const { accountId, setAccountId } = useGrowthCreator();
  return (
    <GrowthHbFrame title="Redirect links">
      <RedirectLinksPanel accountId={accountId} onAccountChange={setAccountId} />
    </GrowthHbFrame>
  );
}

/** Growth → Redirect links (an Inflowwww extra): the creator filter and
 *  "Create redirect link" (its pop-up, as the other link tabs create), the "Clicks" cards (the Dashboard tab's
 *  SectionTitle and StatCards), then that Creator's internal redirect links, each with its 7-day sparkline and
 *  Analytics. */
export function RedirectLinksPanel({ accountId, onAccountChange }: {
  accountId: string | null;
  onAccountChange: (id: string) => void;
}) {
  const linksQ = useTrackingLinks(accountId);
  const deleteM = useDeleteTrackingLink(accountId);
  const updateM = useUpdateTrackingLink(accountId);
  const summaryQ = useTrackingSummary(accountId);
  const clicksId = useId();

  const [creating, setCreating] = useState(false);
  const [view, viewDispatch] = useReducer(statsViewReducer, INITIAL_VIEW);

  const links = linksQ.data?.links ?? [];
  const botAvailable = !!linksQ.data?.bot_check_available;
  const summary = summaryQ.isError ? undefined : summaryQ.data;
  const open = statsRequest(view, accountId, links.map((l) => l.id));
  const spark = summary?.spark;

  return (
    <div className="px-4 pt-4 mb-4">
      <div className="flex flex-wrap items-center gap-x-4">
        <CreatorFilter accountId={accountId} onAccountChange={onAccountChange} />
        <HbButton size="lg" icon={Plus} onClick={() => setCreating(true)} disabled={!accountId} className="mb-4 ml-auto">
          Create redirect link
        </HbButton>
      </div>
      {links.length > 0 && (
        <section aria-labelledby={clicksId} className="mb-8">
          <SectionTitle id={clicksId} label="Clicks"
            tip="Clicks on the Creator's redirect links, by day in the report time zone; a bot-checked link counts passed checks only" />
          <ul aria-label="Redirect link totals" className="flex flex-col md:flex-row gap-4 md:gap-0">
            {summaryCards(summary, verifiedSummary(summary, links, botAvailable)).map((c) => (
              <StatCard key={c.key} stat={c.key} label={c.title} value={c.value ?? DASH} tip={c.sub}
                valueTitle={c.value ?? undefined} />
            ))}
          </ul>
        </section>
      )}
      <section aria-label="Custom redirect links" className="space-y-4">
        <header>
          <div className="flex flex-wrap items-center gap-2">
            <h2 className="text-lg font-semibold">Custom redirect links</h2>
            <Badge color="muted">/t/&lt;slug&gt;</Badge>
            {links.length > 0 && <span className="text-fg-dim text-xs">· {links.length}</span>}
          </div>
          <p className="text-sm text-fg-dim">
            For a target that isn&rsquo;t your OnlyFans profile — a Linktree, a
            landing page, a link you want to swap later. We count clicks; subscriber
            attribution isn&rsquo;t possible here, since the visitor never lands on OnlyFans.
          </p>
        </header>

        {!linksQ.isLoading && links.length === 0 && (
          <div className="text-sm text-fg-dim">No custom redirect links yet.</div>
        )}

        <ul className="divide-y divide-border">
          {links.map((l) => (
            <li key={l.id} className="py-3 space-y-2">
              <div className="flex flex-wrap items-center gap-3">
                <div className="min-w-0 flex-1">
                  <div className="flex items-center gap-2 min-w-0">
                    <span className="text-sm font-medium text-fg truncate">{l.name}</span>
                    {l.bot_check && (
                      <Badge color="info" title={botAvailable ? BOT_CHECK_HINT : BOT_CHECK_OFF}>
                        bot check{botAvailable ? "" : " (off)"}
                      </Badge>
                    )}
                  </div>
                  <div className="text-[11px] text-fg-dim truncate">
                    <span className="text-accent">{l.path}</span> → {l.target_url}
                  </div>
                </div>
                <div className="flex shrink-0 items-center gap-2 text-sm tabular-nums text-fg">
                  <ClickSparkline values={spark?.[String(l.id)]} message={summaryQ.isError ? "Unavailable" : "Loading…"} />
                  <span>{l.click_count} <span className="text-fg-dim text-[11px]">clicks</span></span>
                </div>
                <div className="flex items-center gap-1.5 shrink-0">
                  <label className={`flex select-none items-center gap-1 text-[11px] ${botAvailable ? "cursor-pointer text-fg" : "text-fg-dim"}`}
                    title={botAvailable ? BOT_CHECK_HINT : BOT_CHECK_OFF}>
                    <input type="checkbox" aria-label={`Bot check for ${l.name}`} checked={l.bot_check}
                      disabled={(!botAvailable && !l.bot_check) || updateM.isPending}
                      onChange={(e) => updateM.mutate({ id: l.id, bot_check: e.target.checked })}
                      className="h-3.5 w-3.5 accent-accent" />
                    Bot check
                  </label>
                  {updateM.isError && updateM.variables?.id === l.id && (
                    <span role="alert" className="text-err text-[11px]">{errMsg(updateM.error, "Bot check not saved")}</span>
                  )}
                  <CopyButton text={publicUrl(l.path)} label="Copy link" />
                  <Button size="sm" variant="ghost" aria-expanded={open?.linkId === l.id}
                    onClick={() => viewDispatch({ type: "toggle", id: l.id })}>
                    {open?.linkId === l.id ? "Hide" : "Analytics"}
                  </Button>
                  <RowMenu
                    name={l.name}
                    action={{
                      label: "Delete",
                      confirmTitle: `Delete redirect link, ${l.name}?`,
                      confirmBody: "The link stops redirecting and its click history is deleted. This action cannot be undone.",
                      failText: "Unable to delete redirect link. Try again later",
                      run: () => deleteM.mutateAsync(l.id),
                    }}
                  />
                </div>
              </div>
              {open?.linkId === l.id && accountId && (
                <LinkStats accountId={accountId} link={l} days={open.days} shareUrl={publicUrl(l.path)} botAvailable={botAvailable}
                  onDays={(days) => viewDispatch({ type: "setDays", days })} />
              )}
            </li>
          ))}
        </ul>
      </section>
      {creating && (
        <CreateRedirectModal accountId={accountId} botAvailable={botAvailable} onClose={() => setCreating(false)} />
      )}
    </div>
  );
}

/** "Create redirect link": Name, Target URL and the bot check (`customRedirectForm`'s reducer), Cancel then Create;
 *  it closes once the relay made the link, and keeps the form with the error otherwise. */
function CreateRedirectModal({ accountId, botAvailable, onClose }: {
  accountId: string | null;
  botAvailable: boolean;
  onClose: () => void;
}) {
  const createM = useCreateTrackingLink(accountId);
  const [form, dispatch] = useReducer(redirectFormReducer, INITIAL_FORM);

  async function create() {
    const why = formError(form);
    if (why) { dispatch({ type: "fail", err: why }); return; }
    try {
      // A target the relay refuses comes back as its 422 detail, shown as the error.
      await createM.mutateAsync(buildPayload(form, botAvailable));
      onClose();
    } catch (e) { dispatch({ type: "fail", err: errMsg(e, "Create failed") }); }
  }

  return (
    <HbModal
      title="Create redirect link"
      width={480}
      onClose={onClose}
      footer={(
        <>
          <HbButton variant="secondary" onClick={onClose}>Cancel</HbButton>
          <HbButton onClick={() => void create()} disabled={createM.isPending || !accountId}>
            {createM.isPending ? "Creating…" : "Create"}
          </HbButton>
        </>
      )}
    >
      <form className="flex flex-col gap-6 text-fg" onSubmit={(e) => { e.preventDefault(); void create(); }}>
        <div className="flex flex-col gap-2">
          <label htmlFor="redirect-new-name" className="text-base">Name</label>
          <Input id="redirect-new-name" className="h-9" autoFocus value={form.name} placeholder="e.g. Linktree"
            onChange={(e) => dispatch({ type: "edit", field: "name", value: e.target.value })} />
        </div>
        <div className="flex flex-col gap-2">
          <label htmlFor="redirect-new-target" className="text-base">Target URL</label>
          <Input id="redirect-new-target" className="h-9" value={form.target} placeholder="linktr.ee/creator"
            onChange={(e) => dispatch({ type: "edit", field: "target", value: e.target.value })} />
        </div>
        <label className={`flex select-none items-center gap-2 text-sm ${botAvailable ? "cursor-pointer text-fg" : "text-fg-dim"}`}
          title={botAvailable ? BOT_CHECK_HINT : BOT_CHECK_OFF}>
          <input type="checkbox" checked={botAvailable && form.botCheck} disabled={!botAvailable}
            onChange={(e) => dispatch({ type: "setBotCheck", on: e.target.checked })} className="h-4 w-4 accent-accent" />
          Bot check before redirect
          <span className="text-fg-dim text-[11px]">{botAvailable ? "· Cloudflare Turnstile" : "· not set up on this server"}</span>
        </label>
        {form.err && <div role="alert" className="text-err text-xs">{form.err}</div>}
        {/* Enter in a field submits. */}
        <button type="submit" hidden aria-hidden tabIndex={-1} />
      </form>
    </HbModal>
  );
}
