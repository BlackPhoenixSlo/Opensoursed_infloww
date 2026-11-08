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
 * No OF writes: these are internal folders. Nothing here sends anything.
 */

import { useEffect, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { Copy, Send, Shirt, User } from "lucide-react";

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
import { errText } from "@/lib/errText";

const TIER_STYLE: Record<string, string> = {
  sfw: "border-muted/50 bg-muted/10 text-fg-dim",
  suggestive: "border-info/50 bg-info/10 text-info",
  explicit: "border-warn/50 bg-warn/10 text-warn",
  hardcore: "border-err/50 bg-err/10 text-err",
};

/** How many shoots stay their own folder. The rest still feed the lanes. */
const KEEP_CHOICES = [1, 2, 3, 4, 5];

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
            {(() => { const Icon = folder.solo ? User : isScript ? Shirt : Send; return <Icon className="h-3.5 w-3.5 shrink-0 text-muted" aria-hidden />; })()}
            <span className="truncate">{folder.name}</span>
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
              {it.closes ? "closes" : it.clothing_state}
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
  const [keep, setKeep] = useState(2);
  const [mirrorToOf, setMirrorToOf] = useState(true);
  const [solo, setSolo] = useState(false);
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState<ApplyAiFoldersResult | null>(null);
  const [error, setError] = useState<string | null>(null);

  const plan = useAiFolderPlan(accountId, { keep, solo }, true);

  // Items that land in more than one folder — the case the per-folder ordering
  // exists for. Flagged in the preview so the overlap is visible up front
  // rather than discovered later in the picker.
  const seen = new Map<number, number>();
  for (const f of plan.data?.folders ?? []) {
    for (const it of f.items) seen.set(it.media_id, (seen.get(it.media_id) ?? 0) + 1);
  }
  const multi = new Set([...seen.entries()].filter(([, n]) => n > 1).map(([m]) => m));

  async function onCreate() {
    setBusy(true);
    setError(null);
    try {
      // The SAME options the preview was built from: the server re-derives the
      // plan and retires generated folders it no longer makes, so applying
      // without `solo` would create the lanes and delete every `-solo` folder
      // in the same call.
      const res = await applyAiFolders(accountId, { keep, solo, mirrorToOf });
      setResult(res);
      // The folder rail and any per-folder grid are now stale.
      qc.invalidateQueries({ queryKey: ["vault-internal-folders", accountId] });
      qc.invalidateQueries({ queryKey: ["vault-of-folders-mirror", accountId] });
      qc.invalidateQueries({ queryKey: ["vault-lists", accountId] });
      qc.invalidateQueries({ queryKey: ["vault-mirror-items"] });
    } catch (e) {
      setError(errText(e));
      console.error("apply AI folders failed", e);
    } finally {
      setBusy(false);
    }
  }

  const s = plan.data?.summary;
  const flags = plan.data?.flags;
  // Only when the box is ticked AND some described item was never asked who
  // else is in it — the one case where an empty solo cut is correct but reads
  // as breakage.
  const cov = solo ? plan.data?.solo_coverage : null;
  const soloGap = cov?.unknown ? cov : null;
  // Without the flags pass the paid tiers fall back to `clothing_state`, which
  // was measured wrong on ~1 in 3 of the stills the $50 tier is built from. The
  // folders would come out quietly wrong rather than visibly broken, so block
  // the button rather than warn beside it.
  const flagsMissing = !!flags && !flags.ready;

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

  async function onRunFlags() {
    setError(null);
    try {
      await runVaultFlags(accountId);
      setSince(Date.now());
    } catch (e) {
      setError(errText(e));
    }
  }

  return (
    <IfModal
      title="Build AI folders"
      width={820}
      onClose={onClose}
      footer={
        <div className="flex w-full flex-wrap items-center justify-end gap-2">
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
            disabled={busy || flagsMissing || !plan.data?.folders.length}
            title={
              flagsMissing
                ? "Run the flags pass first — the $10/$50 tiers would be built on an unreliable signal"
                : undefined
            }
          >
            {busy
              ? "Creating…"
              : result
                ? "Rebuild"
                : `Create ${s?.folders ?? 0} folders`}
          </IfButton>
        </div>
      }
    >
      <IfHelp className="mt-0">
        Scripts are one shoot, ordered tease to payoff; lanes are cut by heat and cover. Every folder is named AI- so you can tell it from your own.
      </IfHelp>
      {flagsMissing && (
        <div className="mt-4 rounded-md border border-warn/50 bg-warn/10 px-3 py-2 text-warn">
          <p className="flex flex-wrap items-center gap-x-2">
            <b>Run the flags pass first.</b>
            <span>{flags!.missing} of {flags!.stills} stills are unchecked, so the $10 and $50 tiers would be guessed.</span>
            <IfLearn
              tip={
                <>
                  Without the flags pass those tiers fall back to clothing_state — measured wrong on roughly 1 in 3
                  of the stills they are built from. Takes ~3s per still and costs about $0.001 per 100. Anything
                  described from now on is flagged in the same pass; this is a one-off catch-up.
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
              <span className="text-warn/80">
                keeps running if you close this
              </span>
            </p>
          ) : (
            <IfButton className="mt-2 border-warn/60 text-warn hover:border-warn hover:text-warn" onClick={onRunFlags} disabled={busy}>
              Check {flags!.missing} stills
            </IfButton>
          )}
          {!sweeping && !!sweep?.progress?.error && (
            <p className="mt-1 text-[12px] text-err">
              Last run stopped: {sweep.progress.error}
            </p>
          )}
        </div>
      )}

      <div className="mt-4 flex flex-wrap items-end gap-x-6 gap-y-3">
        <div>
          <IfLabel htmlFor="ai-folders-keep">Keep as scripts</IfLabel>
          <IfNativeSelect
            id="ai-folders-keep"
            value={keep}
            onChange={(e) => {
              setKeep(Number(e.target.value));
              setResult(null);
            }}
            disabled={busy}
          >
            {KEEP_CHOICES.map((n) => (
              <option key={n} value={n}>
                top {n} {n === 1 ? "shoot" : "shoots"}
              </option>
            ))}
          </IfNativeSelect>
        </div>
        <span className="flex h-8 items-center" title="Also create these as real folders on OnlyFans, so they show in the OF app and the chat picker">
          <IfSwitch
            checked={mirrorToOf}
            onChange={(on) => {
              setMirrorToOf(on);
              setResult(null);
            }}
            disabled={busy}
            label="Also create on OnlyFans"
          />
        </span>
        <span className="flex h-8 items-center" title="Also cut each lane down to the items nobody else is in — AI-tease 10-solo is AI-tease 10 with every partner clip and photo taken out. The lanes themselves are unchanged.">
          <IfSwitch
            checked={solo}
            onChange={(on) => {
              setSolo(on);
              setResult(null);
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
              {s.solo_cuts > 0 && `, ${s.solo_cuts} solo`}) · {s.unique_media} media ·{" "}
              {s.memberships} placements
              {multi.size > 0 && ` · ${multi.size} in more than one`}
            </>
          )}
        </IfHelp>
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
        <div className="mt-4 rounded-md border border-ok/40 bg-ok/10 px-3 py-2 text-ok">
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
          <span className="block text-ok/80">Nothing was sent.</span>
        </div>
      )}

      {error && (
        <div className="mt-4 rounded-md border border-err/40 bg-err/10 px-3 py-2 text-err">
          {error}
        </div>
      )}

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
