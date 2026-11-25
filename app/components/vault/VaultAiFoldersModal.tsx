"use client";


import { useEffect, useReducer, useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Copy, Send, Shirt, Tag, User } from "lucide-react";
import { invalidateVaultQueries } from "@/lib/vaultInvalidation";

import {
  applyAiFolders,
  runVaultFlags,
  useAiFolderPlan,
  useVaultFlagsStatus,
  type AiFolder,
  type ApplyAiFoldersResult,
} from "@/hooks/useVaultCache";
import { mirrorThumbSrc } from "@/lib/mediaUrl";
import { IfButton, IfHelp, IfLabel, IfLearn, IfModal, IfNativeSelect, IfSwitch } from "@/components/ui/infloww";
import { Notice } from "@/components/vault/Notice";
import { errText } from "@/lib/errText";
import {
  aiFoldersFormReducer,
  buildPayload,
  canSubmit,
  changesLine,
  confirmLabel,
  INITIAL_FORM,
  KEEP_CHOICES,
  keepLabel,
  topicsUsable,
} from "@/components/vault/vaultAiFoldersForm";

const TIER_STYLE: Record<string, string> = {
  sfw: "border-muted/50 bg-muted/10 text-fg-dim",
  suggestive: "border-info/50 bg-info/10 text-info",
  explicit: "border-warn/50 bg-warn/10 text-warn",
  hardcore: "border-err/50 bg-err/10 text-err",
};

function FolderCard({
  accountId,
  folder,
  multi,
}: {
  accountId: string;
  folder: AiFolder;
  multi: Set<number>;
}) {
  const [open, setOpen] = useState(false);
  const shown = open ? folder.items : folder.items.slice(0, 12);
  const isScript = folder.source === "script";

  return (
    <section className="rounded-md border border-border bg-bg-elev-1">
      <header className="px-3 py-2 flex items-start justify-between gap-3 border-b border-border">
        <div className="min-w-0">
          <h3 className="text-[14px] font-semibold flex items-center gap-2">
            {(() => { const Icon = folder.solo ? User : isScript ? Shirt : folder.source === "topic" ? Tag : Send; return <Icon className="h-3.5 w-3.5 shrink-0 text-muted" aria-hidden />; })()}
            <span className="truncate">{folder.name}</span>
            {folder.change && (
              <span className="shrink-0 rounded border border-border px-1 text-[11px] font-normal text-muted">
                {folder.change === "new" ? "new" : "refresh"}
              </span>
            )}
          </h3>
          <p className="text-[12px] text-muted mt-0.5">
            {folder.purpose} · {folder.size} items ·{" "}
            {Object.entries(folder.kinds)
              .map(([k, n]) => `${n} ${k}`)
              .join(", ")}
            {isScript && ` · ${folder.closes_on_own} can close`}
            {folder.solo && ` · ${folder.size} of ${folder.solo_of} in the lane`}
          </p>
          {isScript && !!folder.health?.length && (
            <p data-testid="script-health" className="text-[12px] text-muted mt-0.5">
              {folder.health.join(" · ")}
            </p>
          )}
        </div>
        <div className="flex items-center gap-1 shrink-0">
          {Object.entries(folder.tiers).map(([tier, n]) => (
            <span
              key={tier}
              className={`px-1.5 py-0.5 rounded border text-[12px] ${
                TIER_STYLE[tier] ?? TIER_STYLE.sfw
              }`}
            >
              {tier} {n}
            </span>
          ))}
        </div>
      </header>

      <div className="px-3 py-2.5 flex flex-wrap gap-1.5">
        {shown.map((it) => (
          <figure key={it.media_id} className="m-0 w-[74px]">
            <div className="relative">
              <img
                src={mirrorThumbSrc(accountId, it.media_id)}
                alt=""
                loading="lazy"
                className="w-[74px] h-[74px] object-cover rounded border border-border"
              />
              <span className="absolute top-0 left-0 px-1 rounded-br bg-black/70 text-[12px] text-white tabular-nums">
                {it.manual_order}
              </span>
              {multi.has(it.media_id) && (
                <span
                  title="also in another folder — it keeps a separate position in each"
                  className="absolute bottom-0 right-0 grid place-items-center rounded-tl bg-black/70 p-0.5 text-white"
                >
                  <Copy className="h-3 w-3" aria-hidden />
                </span>
              )}
            </div>
            <figcaption className="mt-0.5 text-[12px] text-muted truncate">
              {it.borrowed ? "borrowed" : it.closes ? "closes" : it.clothing_state}
            </figcaption>
          </figure>
        ))}
      </div>

      {folder.items.length > 12 && (
        <button
          type="button"
          onClick={() => setOpen((v) => !v)}
          className="w-full px-3 py-1.5 border-t border-border text-[12px] text-accent hover:text-accent-hover"
        >
          {open ? "Show fewer" : `Show all ${folder.items.length}`}
        </button>
      )}
    </section>
  );
}

export default function VaultAiFoldersModal({
  accountId,
  onClose,
}: {
  accountId: string;
  onClose: () => void;
}) {
  const qc = useQueryClient();
  const [form, dispatch] = useReducer(aiFoldersFormReducer, INITIAL_FORM);
  const { keep, solo, mirrorToOf, topics, split } = form;

  const plan = useAiFolderPlan(accountId, { keep, solo, topics, split }, true);
  const catalogue = plan.data?.topic_catalogue ?? [];
  const jev = plan.data?.jev;
  const fresh = plan.isPlaceholderData ? undefined : plan.data;
  const topicsOn = topicsUsable(jev);

  const seen = new Map<number, number>();
  for (const f of fresh?.folders ?? []) {
    for (const it of f.items) seen.set(it.media_id, (seen.get(it.media_id) ?? 0) + 1);
  }
  const multi = new Set([...seen.entries()].filter(([, n]) => n > 1).map(([m]) => m));

  const applyM = useMutation({
    mutationFn: (opts: ReturnType<typeof buildPayload>) => applyAiFolders(accountId, opts),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["vault-internal-folders", accountId] });
      qc.invalidateQueries({ queryKey: ["vault-of-folders-mirror", accountId] });
      invalidateVaultQueries(qc, { queryKey: ["vault-lists", accountId] });
      qc.invalidateQueries({ queryKey: ["vault-mirror-items"] });
      qc.invalidateQueries({ queryKey: ["vault-ai-folder-plan", accountId] });
    },
    onError: (e) => console.error("apply AI folders failed", e),
  });
  const busy = applyM.isPending;
  const result: ApplyAiFoldersResult | undefined = applyM.data;

  // Same options as the preview: the server re-derives the plan and retires folders it no longer makes, so dropping `solo` would delete every -solo folder.
  function onCreate() {
    applyM.mutate(buildPayload(form, changes));
  }
  const optionChanged = () => { if (applyM.isSuccess) applyM.reset(); };

  const s = fresh?.summary;
  const changes = fresh?.changes;
  const flags = fresh?.flags;
  const cov = solo ? fresh?.solo_coverage : null;
  const soloGap = cov?.unknown ? cov : null;
  const flagsMissing = !!flags && flags.missing > 0;
  const submittable = canSubmit(busy, fresh?.folders.length ?? 0);

  // `since` stops the click reading the previous poll's `running: false` and cancelling itself before the first real answer.
  const [since, setSince] = useState(() => Date.now());
  const flagsStatus = useVaultFlagsStatus(accountId, since > 0);
  const sweep = flagsStatus.data;
  const sweeping = !!sweep?.running;

  useEffect(() => {
    if (since > 0 && flagsStatus.dataUpdatedAt > since && !sweep?.running) {
      setSince(0);
      plan.refetch();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [sweep?.running, flagsStatus.dataUpdatedAt, since]);

  const topicRow = (t: (typeof catalogue)[number]) => (
      <label
        key={t.slug}
        className={`flex items-baseline gap-2 text-[13px] ${topicsOn ? "cursor-pointer" : "opacity-60"}`}
      >
        <input
          type="checkbox"
          className="accent-accent translate-y-[1px]"
          checked={topics.includes(t.slug)}
          disabled={busy || !topicsOn}
          onChange={(e) => { dispatch({ type: "topic", slug: t.slug, on: e.target.checked }); optionChanged(); }}
        />
        <span className="min-w-0 flex-1">
          <span className="text-fg">{t.name}</span>{" "}
          <span className="text-[12px] text-muted">{t.description}</span>
        </span>
        <span className="text-[12px] text-muted tabular-nums">{t.count}</span>
      </label>
  );

  const flagsM = useMutation({
    mutationFn: () => runVaultFlags(accountId),
    onSuccess: () => setSince(Date.now()),
  });

  return (
    <IfModal
      title="Build AI folders"
      width={820}
      onClose={onClose}
      footer={
        <>
          <span className="min-w-0 flex-1 basis-60 text-[12px] text-muted">
            {result
              ? "Re-running refreshes these folders rather than making duplicates."
              : mirrorToOf
                ? "Creates real folders on this OnlyFans account. Nothing is sent."
                : "Nothing has been created yet. Your own folders are never touched."}
          </span>
          <IfButton onClick={onClose}>{result ? "Done" : "Cancel"}</IfButton>
          <IfButton
            variant="primary"
            onClick={onCreate}
            disabled={!submittable}
          >
            {confirmLabel({ busy, built: !!result, folders: s?.folders ?? 0, changes })}
          </IfButton>
        </>
      }
    >
      <IfHelp className="mt-0">
        Scripts are one shoot, ordered tease to payoff; lanes are cut by heat and cover. Every folder is named AI- so you can tell it from your own.
      </IfHelp>
      {flagsMissing && (
        <div className="mt-4 rounded-md border border-accent/40 bg-accent/10 px-3 py-2 text-accent">
          <p className="flex flex-wrap items-center gap-x-2">
            <span>
              <b>{flags!.missing} of {flags!.stills} stills not checked yet</b> — they&apos;re left out of the
              safe-explicit, $10 and $50 folders until checked.
            </span>
            <IfLearn
              tip={
                <>
                  Guessing those from clothing_state was wrong on roughly 1 in 3 stills, so unchecked ones wait
                  in explicit 1:1 instead. Check them, then Rebuild. ~3s per still, about $0.001 per 100.
                </>
              }
            >
              Why
            </IfLearn>
          </p>
          {sweeping ? (
            <p className="mt-2 text-[12px] tabular-nums">
              Checking… {sweep?.progress?.done ?? 0} of{" "}
              {sweep?.progress?.total ?? flags!.missing} done
              {!!sweep?.progress?.failed && ` · ${sweep.progress.failed} failed`}
              {" · "}
              <span className="text-accent/80">
                keeps running if you close this
              </span>
            </p>
          ) : (
            <IfButton className="mt-2 border-accent/60 text-accent hover:border-accent hover:text-accent" onClick={() => flagsM.mutate()} disabled={busy || flagsM.isPending}>
              Check {flags!.missing} stills
            </IfButton>
          )}
          {flagsM.error && <p className="mt-1 text-[12px] text-err">{errText(flagsM.error)}</p>}
          {!sweeping && !!sweep?.progress?.error && (
            <p className="mt-1 text-[12px] text-err">
              Last run stopped: {sweep.progress.error}
            </p>
          )}
        </div>
      )}

      <section className="mt-4 rounded-md border border-border px-3 py-2.5" data-testid="ai-folders-topics">
        <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
          <span className="text-[14px] font-semibold">Topic folders (Jev)</span>
          {jev && (
            <span className="text-[12px] text-muted tabular-nums">
              {jev.with_jev} of {jev.items} items have Jev data
            </span>
          )}
          <span className="ml-auto flex flex-wrap items-center gap-2">
            <span title="Off: one AI-<topic> folder per ticked topic, free and paid together, instead of one per price.">
              <IfSwitch
                checked={split}
                onChange={(on) => { dispatch({ type: "split", on }); optionChanged(); }}
                disabled={busy}
                label="Split topics by price"
              />
            </span>
            <IfButton
              onClick={() => { dispatch({ type: "topicsAll", slugs: catalogue.map((t) => t.slug) }); optionChanged(); }}
              disabled={busy || !topicsOn || catalogue.length === 0}
            >
              Select all
            </IfButton>
            <IfButton
              onClick={() => { dispatch({ type: "topicsNone" }); optionChanged(); }}
              disabled={busy || topics.length === 0}
            >
              None
            </IfButton>
          </span>
        </div>
        <IfHelp>
          {topicsOn
            ? `${split ? "One folder per ticked topic and price" : "One folder per ticked topic (price split off)"} (free / $10 / $50 / $100; explicit topics $50 / $100 / $150, never free), from Jev's answers on photos and clips. Free never holds anything Jev saw bare; photos Jev is unsure about go nowhere, clips it wants reviewed only to their paid price.`
            : "Needs Jev classification: check the stills, then come back."}
        </IfHelp>
        <div className="mt-2 grid grid-cols-1 gap-x-4 gap-y-1 sm:grid-cols-2">
          {catalogue.map(topicRow)}
        </div>
      </section>
      <div className="mt-4 flex flex-wrap items-end gap-x-6 gap-y-3">
        <div>
          <IfLabel htmlFor="ai-folders-keep">Keep as scripts</IfLabel>
          <IfNativeSelect
            id="ai-folders-keep"
            value={keep}
            onChange={(e) => {
              dispatch({ type: "keep", keep: Number(e.target.value) });
              optionChanged();
            }}
            disabled={busy}
          >
            {KEEP_CHOICES.map((n) => (
              <option key={n} value={n}>
                {keepLabel(n)}
              </option>
            ))}
          </IfNativeSelect>
        </div>
        <span className="flex h-8 items-center" title="Also create these as real folders on OnlyFans, so they show in the OF app and the chat picker">
          <IfSwitch
            checked={mirrorToOf}
            onChange={(on) => {
              dispatch({ type: "mirror", on });
              optionChanged();
            }}
            disabled={busy}
            label="Also create on OnlyFans"
          />
        </span>
        <span className="flex h-8 items-center" title="Also cut each lane down to the items nobody else is in — AI-tease 10-solo is AI-tease 10 with every partner clip and photo taken out. The lanes themselves are unchanged.">
          <IfSwitch
            checked={solo}
            onChange={(on) => {
              dispatch({ type: "solo", on });
              optionChanged();
            }}
            disabled={busy}
            label="Solo cut of each lane"
          />
        </span>
      </div>
      {(plan.isFetching || s) && (
        <IfHelp className="mt-3">
          {plan.isFetching && "planning… "}
          {s && (
            <>
              {s.folders} folders ({s.scripts} scripts, {s.lanes} lanes
              {s.solo_cuts > 0 && `, ${s.solo_cuts} solo`}
              {s.topics > 0 && `, ${s.topics} topic`}) · {s.unique_media} media ·{" "}
              {s.memberships} placements
              {multi.size > 0 && ` · ${multi.size} in more than one`}
              {s.dupes_collapsed > 0 && ` · ${s.dupes_collapsed} duplicate copies left out`}
            </>
          )}
        </IfHelp>
      )}
      {changes && (
        <div className="mt-2 text-[13px]">
          <p className="tabular-nums">Confirm {changesLine(changes)}</p>
          {changes.retire > 0 && (
            <p className="mt-0.5 text-[12px] text-muted">
              Retiring {changes.retired.slice(0, 6).map((r) => r.name).join(", ")}
              {changes.retire > 6 && ` and ${changes.retire - 6} more`}
            </p>
          )}
          {changes.retire_on_of > 0 && (
            <p className="mt-0.5 text-[12px] text-warn">
              {changes.retire_on_of} of them {changes.retire_on_of === 1 ? "is" : "are"} linked to an OnlyFans list. The list stays on
              OnlyFans; it is just no longer linked here.
            </p>
          )}
        </div>
      )}
      {/* An empty solo cut on a V1-described vault is correct (`is_solo` needs the evidence) but reads as broken. */}
      {soloGap && (
        <div className="mt-4 flex flex-wrap items-center gap-x-2 rounded-md border border-accent/40 bg-accent/10 px-3 py-2 text-accent">
          <b>{soloGap.unknown} of {soloGap.described} described items were never asked who else is in them,</b>
          <span>so they stay out of the solo folders.</span>
          <IfLearn
            tip="Only the rich (B) describe prompt records that, so those items stay out rather than being guessed in — a partner clip in a solo folder is the wrong thing sold under the wrong promise. Re-scan them with prompt B to include them."
          >
            Why
          </IfLearn>
        </div>
      )}

      {result && (
        <Notice tone="ok">
          Created {result.new} new{" "}
          {result.reused > 0 && `and refreshed ${result.reused} existing `}
          {result.folders === 1 ? "folder" : "folders"} with {result.items} placements.
          {result.of_mirrored != null && (
            <span className="block text-ok/80">
              {result.of_mirrored} mirrored to OnlyFans as real vault folders (adds only: nothing is removed from
              an OnlyFans list).
            </span>
          )}
          {!!result.of_stale && (
            <span className="block text-warn">
              {result.of_stale} {result.of_stale === 1 ? "item stays" : "items stay"} in an OnlyFans list this
              build no longer puts {result.of_stale === 1 ? "it" : "them"} in — remove on OnlyFans if needed.
            </span>
          )}
          {!!result.of_failed && (
            <span className="block text-warn">
              {result.of_failed} could not be created on OnlyFans — the folder still
              exists here, press Rebuild to retry.
            </span>
          )}
          {!!result.skipped_retire?.length && (
            <span className="block text-warn">
              {result.skipped_retire.length} more {result.skipped_retire.length === 1 ? "folder" : "folders"} went
              out of date after this preview and {result.skipped_retire.length === 1 ? "was" : "were"} left in
              place — press Rebuild to review.
            </span>
          )}
          {!!result.skipped_adopted?.length && (
            <span className="block text-warn">
              {result.skipped_adopted.length} {result.skipped_adopted.length === 1 ? "folder was" : "folders were"}{" "}
              edited by hand during this build and left as edited.
            </span>
          )}
          {result.of_mirrored == null && (
            <span className="block text-ok/80">
              Internal folders only — nothing was written to OnlyFans.
            </span>
          )}
        </Notice>
      )}

      {applyM.error && <Notice tone="err">{errText(applyM.error)}</Notice>}

      <div className="mt-4 flex flex-col gap-3">
        {(plan.isLoading || plan.isPlaceholderData) && <p className="text-muted">Reading the vault…</p>}
        {plan.isError && (
          <p className="text-err">Could not build a plan for this account.</p>
        )}
        {fresh && fresh.folders.length === 0 && (
          <p className="text-muted">
            Nothing to group yet — the vault needs to be collected and described first.
          </p>
        )}
        {fresh?.folders.map((f) => (
          <FolderCard key={f.name} accountId={accountId} folder={f} multi={multi} />
        ))}
      </div>
    </IfModal>
  );
}
