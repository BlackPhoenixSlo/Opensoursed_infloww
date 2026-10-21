"use client";

/**
 * SubscriptionBundles — OF's "Subscription bundles" section (Settings > Subscription > promotion campaign), on Growth's
 * Profile promotion page. One implementation with OF Manager's mirror: the same reads (users/me's subscriptionBundles
 * and price, users/me settings' canAddSubscriberByBundle, under the mirror's own query keys), the same writes (POST
 * /subscriptions/bundles {discount, duration}, DELETE /{id}) and the same rules (ofMirrorOffers' bundleOptions,
 * bundleAmount, bundleBlock; ofMirrorSubscription's bundleLabel and OF's delete confirm). Edit is OF's own
 * bundles/saveBundle with an id (PUT /{id} {discount, duration}), which OF's settings page does not offer.
 */

import { useState } from "react";

import { Badge, Button, ExtraTag } from "@/components/ui/primitives";
import { ConfirmDeleteButton, SelectInput, errMsg } from "@/components/growth/_bits";
import { useBundleSettings, useDeleteBundle, useOfMe, useSaveBundle } from "@/hooks/useGrowth";
import { bundleAmount, bundleBlock, bundleHelp, bundleOptions, type BundleForm } from "@/lib/ofMirrorOffers";
import { ASKS, bundleLabel, type Bundle } from "@/lib/ofMirrorSubscription";
import { ofErrorMessage } from "@/lib/ofMirrorWrites";
import { cn } from "@/lib/utils";

/** The open editor: a new bundle, or the bundle being edited. */
type Editing = { id?: Bundle["id"] } & BundleForm;

export default function SubscriptionBundles({ accountId }: { accountId: string | null }) {
  const meQ = useOfMe(accountId);
  const settingsQ = useBundleSettings(accountId);
  const saveM = useSaveBundle(accountId);
  const deleteM = useDeleteBundle(accountId);
  const [editing, setEditing] = useState<Editing | null>(null);
  const [err, setErr] = useState<string | null>(null);

  const me = meQ.data;
  const bundles = (me?.subscriptionBundles ?? []) as Bundle[];
  const price = Number(me?.subscribePrice ?? 0);
  // OF grays the section and disables Add bundle while the subscription is free.
  const free = !!me && !(price > 0);
  const durationsOf = (except?: Bundle["id"]) => bundles.filter((b) => b.id !== except).map((b) => Number(b.duration));
  const addLeft = bundleOptions(settingsQ.data, durationsOf()).durations;
  const addWhy = free
    ? "OnlyFans offers bundles only on a paid subscription"
    : settingsQ.data && !addLeft.length ? "Every bundle length already has a bundle" : "";

  function open(b?: Bundle) {
    setErr(null);
    const { discounts, durations } = bundleOptions(settingsQ.data, durationsOf(b?.id));
    setEditing(b
      ? { id: b.id, discount: Number(b.discount ?? 0), duration: Number(b.duration ?? 0) }
      : { discount: Number(discounts[0]?.value ?? 0), duration: Number(durations[0]?.value ?? 0) });
  }

  async function save() {
    if (!editing) return;
    setErr(null);
    try {
      await saveM.mutateAsync(editing);
      setEditing(null);
    } catch (e) { setErr(ofErrorMessage(e) ?? errMsg(e, editing.id != null ? "Could not save the bundle" : "Could not add the bundle")); }
  }

  async function remove(id: Bundle["id"]) {
    setErr(null);
    try { await deleteM.mutateAsync(id); }
    catch (e) { setErr(ofErrorMessage(e) ?? errMsg(e, "Could not delete the bundle")); }
  }

  const opts = editing ? bundleOptions(settingsQ.data, durationsOf(editing.id)) : null;
  const amount = editing ? bundleAmount(editing, price) : 0;
  const block = editing && opts ? bundleBlock({ settings: settingsQ.data, ...opts, amount }) : "";
  const durationLabel = opts?.durations.find((d) => Number(d.value) === editing?.duration)?.label ?? "";

  return (
    <section aria-label="Subscription bundles" className="space-y-3">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className={cn(free && "opacity-50")}>
          <h3 className="flex items-center gap-2 text-base font-semibold">Subscription bundles <ExtraTag /></h3>
          <p className="text-sm text-fg-dim">Offer several months of subscription as a discounted bundle.</p>
        </div>
        <Button size="sm" variant="ghost" onClick={() => open()} title={addWhy || undefined}
          disabled={!accountId || !me || !!addWhy || !!editing}>
          Add bundle
        </Button>
      </div>

      {meQ.isLoading && <div className="text-sm text-fg-dim">Loading…</div>}
      {meQ.isError && <div className="text-sm text-warn">OnlyFans not reachable — bundles can&apos;t be read.</div>}
      {me && !bundles.length && !editing && <div className="text-sm text-fg-dim">No subscription bundles yet.</div>}

      {editing && opts && (
        <div className="rounded-xl border border-border p-3 space-y-2" aria-label={editing.id != null ? "Edit bundle" : "Add bundle"}>
          <div className="grid gap-3 sm:grid-cols-2">
            <label className="block space-y-1">
              <span className="text-[11px] uppercase tracking-wide text-fg-dim">Discount percent</span>
              <SelectInput ariaLabel="Discount percent" value={editing.discount} options={opts.discounts}
                onChange={(discount) => setEditing({ ...editing, discount })} />
            </label>
            <label className="block space-y-1">
              <span className="text-[11px] uppercase tracking-wide text-fg-dim">Discount duration</span>
              <SelectInput ariaLabel="Discount duration" value={editing.duration} options={opts.durations}
                onChange={(duration) => setEditing({ ...editing, duration })} />
            </label>
          </div>
          <p className={cn("text-xs", block ? "text-err" : "text-fg-dim")}>{block || bundleHelp(amount, durationLabel)}</p>
          <div className="flex justify-end gap-2">
            <Button size="sm" variant="ghost" onClick={() => setEditing(null)}>Cancel</Button>
            <Button size="sm" onClick={save} disabled={!!block || saveM.isPending}>
              {saveM.isPending ? "Saving…" : "Save"}
            </Button>
          </div>
        </div>
      )}

      {bundles.length > 0 && (
        <ul className={cn("divide-y divide-border", free && "opacity-50")}>
          {bundles.map((b) => {
            const label = bundleLabel(b);
            return (
              <li key={String(b.id)} className="py-2.5 flex flex-wrap items-center gap-3" data-bundle-row>
                <div className="min-w-0 flex-1 text-sm">
                  <b className="text-fg">{label.price}</b> <span className="text-fg-dim">{label.time}</span>
                  {label.discount && <Badge color="ok" className="ml-2">{label.discount}</Badge>}
                </div>
                {b.id != null && (
                  <div className="flex items-center gap-1.5 shrink-0">
                    <Button size="sm" variant="ghost" onClick={() => open(b)} disabled={free}>Edit</Button>
                    <ConfirmDeleteButton confirm={ASKS.bundle.text} pending={deleteM.isPending}
                      onConfirm={() => void remove(b.id)} />
                  </div>
                )}
              </li>
            );
          })}
        </ul>
      )}
      {err && <div className="text-err text-xs" role="alert">{err}</div>}
    </section>
  );
}
