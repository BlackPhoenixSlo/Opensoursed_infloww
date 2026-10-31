"use client";

import { useState } from "react";

import { Badge, Button, Card, ExtraTag, Input } from "@/components/ui/primitives";
import { ConfirmDeleteButton, CopyButton, Field, errMsg } from "@/components/growth/_bits";
import { useTrackingLinks, useCreateTrackingLink, useDeleteTrackingLink, useTrackingAnalytics } from "@/hooks/useGrowth";

/** The internal link is same-origin (Next rewrites /t/* to the relay). */
function publicUrl(path: string): string {
  if (typeof window === "undefined") return path;
  return `${window.location.origin}${path}`;
}

/** Internal redirect links: an Inflowwww extra, after the capture's elements. */
export function CustomRedirects({ accountId }: { accountId: string | null }) {
  const linksQ = useTrackingLinks(accountId);
  const createM = useCreateTrackingLink(accountId);
  const deleteM = useDeleteTrackingLink(accountId);

  const [name, setName] = useState("");
  const [target, setTarget] = useState("");
  const [err, setErr] = useState<string | null>(null);
  const [openId, setOpenId] = useState<number | null>(null);
  const [open, setOpen] = useState(false);

  const links = linksQ.data ?? [];

  async function create() {
    setErr(null);
    if (!name.trim()) { setErr("Name is required."); return; }
    if (!/^https?:\/\//.test(target.trim())) { setErr("Target must be an http(s) URL."); return; }
    try {
      await createM.mutateAsync({ name: name.trim(), target_url: target.trim() });
      setName(""); setTarget("");
    } catch (e) { setErr(errMsg(e, "Create failed")); }
  }

  return (
    <section aria-label="Custom redirect links" className="space-y-4 border-t border-border pt-6">
      <header>
        <div className="flex flex-wrap items-center gap-2">
          <button type="button" onClick={() => setOpen((v) => !v)}
            className="flex items-center gap-2 text-left">
            <h2 className="text-lg font-semibold">Custom redirect links</h2>
            <Badge color="muted">/t/&lt;slug&gt;</Badge>
            <span className="text-fg-dim text-xs">{open ? "▲" : "▼"}</span>
            {links.length > 0 && <span className="text-fg-dim text-xs">· {links.length}</span>}
          </button>
          <ExtraTag />
        </div>
        <p className="text-sm text-fg-dim">
          For a target that <i>isn&rsquo;t</i> your OnlyFans profile — a Linktree, a
          landing page, a link you want to swap later. We count clicks; subscriber
          attribution isn&rsquo;t possible here, since the visitor never lands on OnlyFans.
        </p>
      </header>

      {open && (
        <>
          <Card className="p-4 space-y-3">
            <div className="grid gap-3 sm:grid-cols-2">
              <Field label="Name">
                <Input value={name} onChange={(e) => setName(e.target.value)} placeholder="e.g. Linktree" />
              </Field>
              <Field label="Target URL">
                <Input value={target} onChange={(e) => setTarget(e.target.value)}
                  placeholder="https://linktr.ee/creator" />
              </Field>
            </div>
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
                    <div className="text-sm font-medium text-fg truncate">{l.name}</div>
                    <div className="text-[11px] text-fg-dim truncate">
                      <span className="text-accent">{l.path}</span> → {l.target_url}
                    </div>
                  </div>
                  <div className="text-sm tabular-nums text-fg shrink-0">
                    {l.click_count} <span className="text-fg-dim text-[11px]">clicks</span>
                  </div>
                  <div className="flex items-center gap-1.5 shrink-0">
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
        </>
      )}
    </section>
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
