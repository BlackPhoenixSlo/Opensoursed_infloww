"use client";

/**
 * VaultAiFoldersModal — preview, then create, the AI-generated vault folders.
 *
 * Two kinds of folder come out of `service/vault_scripts.py`:
 *
 *   SCRIPTS — one shoot. Media grouped by the OUTFIT she is wearing (upload
 *     bursts are kind-pure, so grouping by upload splits a shoot's stills from
 *     its clips), ordered non-explicit → explicit. Sell these as a set.
 *   LANES — cut by heat and by how much is covered: Stories, Mass, Safe
 *     explicit, and the $10 / $50 tease tiers. An item may legitimately appear
 *     in several lanes and holds an INDEPENDENT position in each, which is why
 *     order lives on the folder membership rather than on the media.
 *
 * Ticking SOLO adds a `-solo` cut of each lane — `AI-tease 10-solo` is
 * `AI-tease 10` with everyone but her taken out. It adds rather than filters:
 * the two answer different questions, and an operator who wants both should not
 * have to rebuild the folders to switch between them.
 *
 * Nothing is written until the operator presses Create. The relay re-derives
 * the plan on apply rather than trusting what this preview posted, so a preview
 * left open while the vault changes underneath cannot write a stale grouping.
 * Every folder is prefixed `AI-`, re-running refreshes those folders instead of
 * duplicating them, and a folder the operator made by hand is never touched.
 *
 * TOPIC FOLDERS (Jev) are opt-in: a checklist of topics (`service/vault_topic_folders.py`), none ticked by
 * default. Each ticked topic adds one folder per price (`AI-bikini free`, `AI-bikini $10`, …; explicit topics
 * $50 / $100 / $150, never free) cut from the photos' and clips' Jev answers; a free one never holds anything Jev
 * saw bare, nor a clip Jev wants reviewed. "Split topics by price" off makes one `AI-<topic>` folder each instead.
 * Unticking a topic (or flipping the split) retires the folders it no longer makes on the next build (the preview's
 * retire line names them). Disabled until Jev is on and has read some items. No feet topic: feet live in the vault's
 * Feet pack only (VaultPackPickerModal).
 *
 * Before Confirm the plan's `changes` says what it does to the AI- folders already there (create / keep / retire);
 * retiring one bound to an OnlyFans list unlinks that list, so the button says so. Options live in
 * `vaultAiFoldersForm.ts` (pure reducer); keep runs 0 (lanes only) to 20.
 *
 * No OF writes: these are internal folders. Nothing here sends anything.
 */

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
  type AiFolderPlan,
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
            {/* "12 of 34" is the honest read: a solo cut that happens to be the
                whole lane is a real answer, and so is one that is a third of it. */}
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
  // The topic checklist (+ Jev coverage) does not depend on the options, so it stays drawn while a toggle re-plans.
  const [lastTopics, setLastTopics] = useState<Pick<AiFolderPlan, "topic_catalogue" | "jev"> | null>(null);
  useEffect(() => {
    if (!plan.data) return;
    const next = { topic_catalogue: plan.data.topic_catalogue, jev: plan.data.jev };
    // Same content keeps the same object: no re-render loop when a refetch hands back an equal plan.
    setLastTopics((prev) => (JSON.stringify(prev) === JSON.stringify(next) ? prev : next));
  }, [plan.data]);
  const catalogue = plan.data?.topic_catalogue ?? lastTopics?.topic_catalogue ?? [];
  const jev = plan.data?.jev ?? lastTopics?.jev;
  const topicsOn = topicsUsable(jev);

  // Items that land in more than one folder — the case the per-folder ordering
  // exists for. Flagged in the preview so the overlap is visible up front
  // rather than discovered later in the picker.
  const seen = new Map<number, number>();
  for (const f of plan.data?.folders ?? []) {
    for (const it of f.items) seen.set(it.media_id, (seen.get(it.media_id) ?? 0) + 1);
  }
  const multi = new Set([...seen.entries()].filter(([, n]) => n > 1).map(([m]) => m));

  const applyM = useMutation({
    mutationFn: (opts: ReturnType<typeof buildPayload>) => applyAiFolders(accountId, opts),
    onSuccess: () => {
      // The folder rail and any per-folder grid are now stale.
      qc.invalidateQueries({ queryKey: ["vault-internal-folders", accountId] });
      qc.invalidateQueries({ queryKey: ["vault-of-folders-mirror", accountId] });
      invalidateVaultQueries(qc, { queryKey: ["vault-lists", accountId] });
      qc.invalidateQueries({ queryKey: ["vault-mirror-items"] });
      // The preview's create / keep / retire counts were against the folders before this build.
      qc.invalidateQueries({ queryKey: ["vault-ai-folder-plan", accountId] });
    },
    onError: (e) => console.error("apply AI folders failed", e),
  });
  const busy = applyM.isPending;
  const result: ApplyAiFoldersResult | undefined = applyM.data;

  function onCreate() {
    // The SAME options the preview was built from: the server re-derives the
    // plan and retires generated folders it no longer makes, so applying
    // without `solo` would create the lanes and delete every `-solo` folder
    // in the same call.
    applyM.mutate(buildPayload(form));
  }
  /** An option change makes the last build's result stale (its error stays). */
  const optionChanged = () => { if (applyM.isSuccess) applyM.reset(); };

  const s = plan.data?.summary;
  const changes = plan.data?.changes;
  const flags = plan.data?.flags;
  // Only when the box is ticked AND some described item was never asked who
  // else is in it — the one case where an empty solo cut is correct but reads
  // as breakage.
  const cov = solo ? plan.data?.solo_coverage : null;
  const soloGap = cov?.unknown ? cov : null;
  // Unchecked stills are left out of the flag lanes (safe explicit, $10, $50) server-side (never
  // guessed), so this informs and offers the catch-up; it does not block.
  const flagsMissing = !!flags && flags.missing > 0;
  const submittable = canSubmit(busy, plan.data?.folders.length ?? 0);

  // A whole-vault sweep runs for minutes in the background, so this watches it
  // rather than holding a request open. Polling starts on the click AND on open
  // when a sweep is already going (started from another tab, or before a reload).
  // `since` is when we last asked to watch. Comparing it against the query's
  // own timestamp is what stops the click from reading the PREVIOUS poll's
  // `running: false` and cancelling itself before the first real answer lands.
  const [since, setSince] = useState(() => Date.now());
  const flagsStatus = useVaultFlagsStatus(accountId, since > 0);
  const sweep = flagsStatus.data;
  const sweeping = !!sweep?.running;

  useEffect(() => {
    // Stop polling once it finishes, and re-plan on the fresh flags: the three
    // lanes that need them (safe explicit, $10, $50) were starved until now.
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
      {/* What Confirm does to the AI- folders already there — the same match the apply makes. */}
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
      {/* An empty solo cut on a V1-described vault is CORRECT — `is_solo`
          refuses to call an item solo without the evidence — and reads as
          broken. Say which it is. */}
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
              {result.of_mirrored} mirrored to OnlyFans as real vault folders.
            </span>
          )}
          {!!result.of_failed && (
            <span className="block text-warn">
              {result.of_failed} could not be created on OnlyFans — the folder still
              exists here, press Rebuild to retry.
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
        {plan.isLoading && <p className="text-muted">Reading the vault…</p>}
        {plan.isError && (
          <p className="text-err">Could not build a plan for this account.</p>
        )}
        {plan.data && plan.data.folders.length === 0 && (
          <p className="text-muted">
            Nothing to group yet — the vault needs to be collected and described first.
          </p>
        )}
        {plan.data?.folders.map((f) => (
          <FolderCard key={f.name} accountId={accountId} folder={f} multi={multi} />
        ))}
      </div>
    </IfModal>
  );
}
