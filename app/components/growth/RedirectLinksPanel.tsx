"use client";

import { useReducer, useState } from "react";

import { Badge, Button, Card, Input } from "@/components/ui/primitives";
import { ConfirmDeleteButton, CopyButton, Field, errMsg } from "@/components/growth/_bits";
import { CreatorFilter } from "@/components/growth/LinksListFrame";
import {
  useTrackingLinks, useCreateTrackingLink, useDeleteTrackingLink, useTrackingAnalytics, useUpdateTrackingLink,
} from "@/hooks/useGrowth";
import { buildPayload, formError, INITIAL_FORM, redirectFormReducer } from "@/components/growth/customRedirectForm";

const BOT_CHECK_HINT = "Fans pass a Cloudflare bot check (Turnstile) before the redirect; only passed checks count as clicks.";
const BOT_CHECK_OFF = "Unavailable: the server has no Turnstile keys (TURNSTILE_SITE_KEY / TURNSTILE_SECRET_KEY).";

/** The internal link is same-origin (Next rewrites /t/* to the relay). */
function publicUrl(path: string): string {
  if (typeof window === "undefined") return path;
  return `${window.location.origin}${path}`;
}

/** Tracking links' "Redirect links" tab (an Inflowwww extra, after the bundle's tabs): the creator filter, as on the
 *  other tabs, over that Creator's internal redirect links. */
export function RedirectLinksPanel({ accountId, onAccountChange }: {
  accountId: string | null;
  onAccountChange: (id: string) => void;
}) {
  const linksQ = useTrackingLinks(accountId);
  const createM = useCreateTrackingLink(accountId);
  const deleteM = useDeleteTrackingLink(accountId);
  const updateM = useUpdateTrackingLink(accountId);

  const [form, dispatch] = useReducer(redirectFormReducer, INITIAL_FORM);
  const [openId, setOpenId] = useState<number | null>(null);

  const links = linksQ.data?.links ?? [];
  const botAvailable = !!linksQ.data?.bot_check_available;
  const err = form.err;

  async function create() {
    const why = formError(form);
    if (why) { dispatch({ type: "fail", err: why }); return; }
    try {
      // A target the relay refuses comes back as its 422 detail, shown as the error.
      await createM.mutateAsync(buildPayload(form, botAvailable));
      dispatch({ type: "reset" });
    } catch (e) { dispatch({ type: "fail", err: errMsg(e, "Create failed") }); }
  }

  return (
    <div className="px-4 pt-4 mb-4">
      <CreatorFilter accountId={accountId} onAccountChange={onAccountChange} />
      <section aria-label="Custom redirect links" className="space-y-4">
        <header>
          <div className="flex flex-wrap items-center gap-2">
            <h2 className="text-lg font-semibold">Custom redirect links</h2>
            <Badge color="muted">/t/&lt;slug&gt;</Badge>
            {links.length > 0 && <span className="text-fg-dim text-xs">· {links.length}</span>}
          </div>
          <p className="text-sm text-fg-dim">
            For a target that <i>isn&rsquo;t</i> your OnlyFans profile — a Linktree, a
            landing page, a link you want to swap later. We count clicks; subscriber
            attribution isn&rsquo;t possible here, since the visitor never lands on OnlyFans.
          </p>
        </header>

        <Card className="p-4 space-y-3">
          <div className="grid gap-3 sm:grid-cols-2">
            <Field label="Name">
              <Input value={form.name} onChange={(e) => dispatch({ type: "edit", field: "name", value: e.target.value })}
                placeholder="e.g. Linktree" />
            </Field>
            <Field label="Target URL">
              <Input value={form.target} onChange={(e) => dispatch({ type: "edit", field: "target", value: e.target.value })}
                placeholder="linktr.ee/creator" />
            </Field>
          </div>
          <label className={`flex select-none items-center gap-2 text-sm ${botAvailable ? "cursor-pointer text-fg" : "text-fg-dim"}`}
            title={botAvailable ? BOT_CHECK_HINT : BOT_CHECK_OFF}>
            <input type="checkbox" checked={botAvailable && form.botCheck} disabled={!botAvailable}
              onChange={(e) => dispatch({ type: "setBotCheck", on: e.target.checked })} className="h-4 w-4 accent-accent" />
            Bot check before redirect
            <span className="text-fg-dim text-[11px]">{botAvailable ? "· Cloudflare Turnstile" : "· not set up on this server"}</span>
          </label>
          <div className="flex items-center gap-2">
            {err && <span className="text-err text-xs mr-auto">{err}</span>}
            <Button size="sm" onClick={create} disabled={createM.isPending || !accountId}
              className={err ? "" : "ml-auto"}>
              {createM.isPending ? "Creating…" : "Create link"}
            </Button>
          </div>
        </Card>

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
                <div className="text-sm tabular-nums text-fg shrink-0">
                  {l.click_count} <span className="text-fg-dim text-[11px]">clicks</span>
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
                  <Button size="sm" variant="ghost" onClick={() => setOpenId(openId === l.id ? null : l.id)}>
                    {openId === l.id ? "Hide" : "Analytics"}
                  </Button>
                  <ConfirmDeleteButton
                    confirm={`Delete redirect link "${l.name}"?`}
                    onConfirm={() => deleteM.mutate(l.id)}
                    pending={deleteM.isPending}
                  />
                </div>
              </div>
              {openId === l.id && accountId && <Analytics accountId={accountId} linkId={l.id} />}
            </li>
          ))}
        </ul>
      </section>
    </div>
  );
}

/** A redirect link's clicks by day (its "Analytics" toggle). */
function Analytics({ accountId, linkId }: { accountId: string; linkId: number }) {
  const q = useTrackingAnalytics(accountId, linkId);
  if (q.isLoading) return <div className="text-[11px] text-fg-dim ml-1">Loading analytics…</div>;
  if (q.isError || !q.data) return <div className="text-[11px] text-err ml-1">Failed to load analytics.</div>;
  const a = q.data;
  const max = Math.max(1, ...a.by_day.map((d) => d.clicks));
  return (
    <div className="ml-1 rounded-lg border border-border bg-bg/40 p-3 space-y-2">
      <div className="text-sm text-fg">
        <b>{a.total_clicks}</b> total clicks
        <span className="text-fg-dim text-[11px]"> · subscribers not tracked for off-profile links</span>
      </div>
      {a.by_day.length > 0 ? (
        <div className="flex items-end gap-1 h-16">
          {a.by_day.map((d) => (
            <div key={d.day} className="flex-1 min-w-2 flex flex-col items-center justify-end" title={`${d.day}: ${d.clicks}`}>
              <div className="w-full bg-accent/70 rounded-t" style={{ height: `${(d.clicks / max) * 100}%` }} />
              <span className="text-[8px] text-fg-dim mt-0.5 truncate w-full text-center">{d.day.slice(5)}</span>
            </div>
          ))}
        </div>
      ) : (
        <div className="text-[11px] text-fg-dim">No clicks yet.</div>
      )}
    </div>
  );
}
