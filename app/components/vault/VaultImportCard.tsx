"use client";


import { useEffect, useReducer, useRef, useState, type DragEvent, type ReactNode } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Plus, SquarePen, Trash2, X } from "lucide-react";

import { useVaultAccount, useVaultAccountId } from "@/components/vault/VaultAccount";
import { invalidateVaultGrid } from "@/hooks/useVaultCache";
import { fetchAllVaultLists, vaultListsKey } from "@/hooks/useVaultMedia";
import { relay, type VaultList } from "@/lib/relay";
import { EXTRA_LABEL } from "@/lib/openinflowwwwExtras";
import { sendVaultBatch, type ResolvedFan } from "@/lib/vaultImport";
import { VaultTour, markVaultTourSeen, vaultTourSeen, type VaultTourStep } from "@/components/vault/VaultTour";
import { BatchEditModal, MetaField, STEP3_FIELDS, metaToWire } from "@/components/vault/VaultImportDetails";
import VaultImportDrive from "@/components/vault/VaultImportDrive";
import { chosenOf, importPickReducer, initialPickState } from "@/components/vault/importPickReducer";
import {
  detailsNote,
  fmtSize,
  itemLabel,
  runSummary,
  showsError,
  startLabel,
  type RunStatus,
} from "@/components/vault/importRunText";
import { cn } from "@/lib/utils";
import { InfoTip } from "@/components/ui/InfoTip";

const POLL_MS = 2500;
// Keep polling after a start even before the server says `running`: the worker begins on a thread and the first poll can beat it.
const FORCE_POLL_MS = 20_000;

// A drop bypasses the picker's `accept`, so dropped files are held to the same kinds.
const MEDIA_TYPE = /^(image|video|audio)\//;

const BAR_TOUR: VaultTourStep[] = [
  { target: "[data-tour='vault-batch-edit']", content: "With your media selected, click here to batch-edit their details" },
  {
    target: "[data-tour='vault-bulk-upload']",
    content: "Once you’re ready, click here to upload your selected media file(s)",
  },
];
const BAR_TOUR_KEYS = ["batchEdit", "uploadBtn"] as const;

const FAN_TIP =
  "Infloww will automatically send media to this account so that it appears in your Creator’s vault.\n" +
  "NOTE: You must be subscribed to this fan account, or the account must be subscribed to you.\n" +
  "Leave it empty and each file is attached to a scheduled post that is deleted again at once — nothing reaches a fan.";

function Step({
  title,
  titleId,
  last = false,
  children,
}: {
  title: ReactNode;
  titleId?: string;
  last?: boolean;
  children?: ReactNode;
}) {
  return (
    <li className="relative flex">
      {!last && (
        <span aria-hidden className="absolute left-[6px] top-[15px] h-[calc(100%-15px)] w-[3px] bg-accent/15" />
      )}
      <span aria-hidden className="flex h-[15px] w-[15px] shrink-0 items-center justify-center rounded-full bg-accent/30">
        <span className="h-[9px] w-[9px] rounded-full bg-accent" />
      </span>
      <div className="relative min-w-0 flex-1 pb-[65px] pl-4">
        <h3 id={titleId} className="mb-[18px] flex items-center text-base font-medium">
          {title}
        </h3>
        {children}
        {!last && <span aria-hidden className="absolute bottom-8 left-4 right-0 h-px bg-border" />}
      </div>
    </li>
  );
}

const MIRROR_ONLY: ReadonlySet<string> = new Set(["tag", "hashtags", "notes", "price"]);

export default function VaultImportCard() {
  const qc = useQueryClient();
  // The PAGE's model; the card is remounted on change (an effect clearing staged files binned them on null -> id).
  const accountId = useVaultAccountId();
  const { account, sessionLost } = useVaultAccount();
  const ctx = { accountId };
  const fileRef = useRef<HTMLInputElement>(null);
  const [pickState, dispatch] = useReducer(importPickReducer, initialPickState);
  const { picked, selected, details } = pickState;
  const [batchOpen, setBatchOpen] = useState(false);
  const [fan, setFan] = useState("");
  const [fanFound, setFanFound] = useState<(ResolvedFan & { typed: string }) | null>(null);
  const [sending, setSending] = useState<{ sent: number; total: number } | null>(null);
  const [links, setLinks] = useState("");
  const [startError, setStartError] = useState<string | null>(null);
  const [runId, setRunId] = useState<string | null>(null);
  const [folder, setFolder] = useState<string>("");
  const settledRef = useRef(false);
  const forceUntilRef = useRef(0);

  const folders = useQuery({
    // Same paginated fetcher as every reader of this key: a single-page queryFn would poison the cache.
    queryKey: vaultListsKey(accountId),
    queryFn: () => fetchAllVaultLists(ctx),
    staleTime: 5 * 60 * 1000,
    select: (d: { list?: VaultList[] }) =>
      (d.list ?? []).filter((l) => l.type === "custom"),
  });

  const status = useQuery<RunStatus>({
    // Per model too: with no run_id the route answers with the latest run of whatever account the header names.
    queryKey: ["vault-import-status", accountId, runId],
    queryFn: () =>
      relay.get<RunStatus>(
        runId
          ? `/api/of/v2/vault/upload/status?run_id=${encodeURIComponent(runId)}`
          : "/api/of/v2/vault/upload/status",
        ctx,
      ),
    // eslint-disable-next-line local/no-fixed-polling -- stops when the job ends
    refetchInterval: (q) =>
      q.state.data?.running || Date.now() < forceUntilRef.current ? POLL_MS : false,
    staleTime: 0,
    refetchOnWindowFocus: true,
  });

  const s = status.data ?? { running: false };
  const running = !!s.running;
  // Fail-closed: only an answer of `true` shows the Drive slot.
  const driveOn = status.data?.drive_import_configured === true;
  const driveLinks = driveOn ? links.trim() : "";

  useEffect(() => {
    if (running) {
      settledRef.current = true;
      return;
    }
    if (settledRef.current) {
      settledRef.current = false;
      // One call built from the hooks' key factories: hand-listed keys missed (TanStack compares elements, ["vault"] is no prefix of ["vault-media", ...]).
      invalidateVaultGrid(qc, accountId);
    }
  }, [running, qc, accountId]);

  const remove = (files: readonly File[]) => {
    dispatch({ type: "remove", files });
    if (fileRef.current) fileRef.current.value = "";
  };
  const chosen = chosenOf(pickState);

  const barShown = chosen.length > 0;
  const [barTour, setBarTour] = useState<number | null>(null);
  useEffect(() => {
    if (!barShown) return;
    const first = BAR_TOUR_KEYS.findIndex((k) => !vaultTourSeen(k));
    if (first < 0) return;
    markVaultTourSeen(BAR_TOUR_KEYS[first]);
    // eslint-disable-next-line react-hooks/set-state-in-effect -- the store is read only after mount (no SSR access)
    setBarTour(first);
  }, [barShown]);
  const endBarTour = (key: (typeof BAR_TOUR_KEYS)[number]) => {
    setBarTour(null);
    markVaultTourSeen(key);
  };

  const start = useMutation({
    mutationFn: (files: File[]) => {
      setSending(files.length > 1 ? { sent: 0, total: files.length } : null);
      let taken = 0;
      return sendVaultBatch(
        files,
        { metaOf: (f) => metaToWire(details.get(f)), driveLinks, folder, fan: fanReady },
        ctx,
        (f, id) => {
          taken += 1;
          if (taken === 1) {
            setStartError(null);
            setLinks("");
            forceUntilRef.current = Date.now() + FORCE_POLL_MS;
            // Watch the run just started, by id, not whatever the latest run is.
            if (id) setRunId(id);
            else void status.refetch();
          }
          if (f) remove([f]);
          if (files.length > 1) setSending({ sent: taken, total: files.length });
        },
      );
    },
    onSettled: () => setSending(null),
    onError: (e: unknown) => setStartError(e instanceof Error ? e.message : "Could not start the import"),
  });

  const fanTyped = fan.trim();
  const fanReady = fanFound && fanFound.typed === fanTyped ? fanFound : null;
  const checkFan = useMutation({
    mutationFn: async (typed: string) => ({
      ...(await relay.get<ResolvedFan>(`/api/of/v2/vault/upload/fan?username=${encodeURIComponent(typed)}`, ctx)),
      typed,
    }),
    onSuccess: setFanFound,
  });
  const fanError =
    checkFan.isError && checkFan.variables === fanTyped
      ? checkFan.error instanceof Error
        ? checkFan.error.message
        : "Could not check that account"
      : null;

  const locked = running || start.isPending;

  // Always claim a file drag so a locked drop is refused here, not opened in the tab.
  const onDragOver = (e: DragEvent) => {
    if (!Array.from(e.dataTransfer?.types ?? []).includes("Files")) return;
    e.preventDefault();
    e.dataTransfer.dropEffect = locked ? "none" : "copy";
  };
  const onDrop = (e: DragEvent) => {
    const files = Array.from(e.dataTransfer?.files ?? []);
    if (files.length === 0) return;
    e.preventDefault();
    if (locked) return;
    const media = files.filter((f) => MEDIA_TYPE.test(f.type));
    if (media.length === 0) return;
    dispatch({ type: "pick", files: media });
    if (fileRef.current) fileRef.current.value = "";
  };

  const nothingToDo = chosen.length === 0 && !driveLinks;
  // A typed fan name not yet checked blocks Start: it is a real DM. sessionLost is a hard stop.
  const canStart = !(running || nothingToDo || start.isPending || sessionLost || (fanTyped && !fanReady));
  const lim = s.upload_limits;
  const rules = [
    ...(lim ? [`File size limit: ${lim.max_file_mb}MB`, `Files per import: ${lim.max_files}`] : []),
    "Images, GIF, video and audio",
  ];
  const items = s.items ?? [];
  const notSaved = s.details_saved_here === false;
  const note = detailsNote(s);
  const fanRun = running ? !!s.fan_id : !!fanReady;
  // Upload into the wrong creator's vault cannot be undone (OF delete is a one-way hide), so the target is named before the form.
  const modelName = account?.nickname || account?.id || accountId;

  return (
    <section className="rounded-lg border border-border bg-panel p-4 flex flex-col gap-3">
      <header className="space-y-1">
        <h2 title={EXTRA_LABEL} className="text-sm font-semibold">
          Import to{" "}
          <span className="text-accent">{modelName}</span>
          &apos;s vault
        </h2>
        <p title={EXTRA_LABEL} className="text-xs text-fg-dim">
          Large video is re-encoded before upload — OnlyFans refuses very large
          files.{" "}
          {fanReady
            ? `Each new file is sent to @${fanReady.username} in chat, so it lands in the vault. Nothing is posted.`
            : fanTyped
              ? "Check the fan account below before starting."
              : "Nothing is posted or sent to fans."}
        </p>
      </header>

      <div className="space-y-2">
        <ol aria-label="Upload steps">
          <Step
            title={
              <>
                <span className="mr-[6px]">Link a fan account (optional)</span>
                <InfoTip text={FAN_TIP} label="About linking a fan account" iconClassName="h-4 w-4" className="text-fg-dim" />
              </>
            }
          >
            <label htmlFor="vault-import-fan" className="mb-2 block text-sm font-medium leading-5">
              OnlyFans account
            </label>
            <div className="flex items-center gap-2">
              <input
                id="vault-import-fan"
                value={fan}
                disabled={locked}
                onChange={(e) => setFan(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === "Enter" && fanTyped && !fanReady) checkFan.mutate(fanTyped);
                }}
                placeholder="Enter OnlyFans username"
                autoComplete="off"
                spellCheck={false}
                className="h-10 w-[240px] max-w-full rounded border border-border bg-bg px-3 text-sm disabled:cursor-not-allowed disabled:opacity-60"
              />
              {fanTyped && !fanReady && (
                <button
                  type="button"
                  title={EXTRA_LABEL}
                  disabled={locked || checkFan.isPending}
                  onClick={() => checkFan.mutate(fanTyped)}
                  className="h-10 rounded border border-border px-3 text-xs disabled:opacity-40"
                >
                  {checkFan.isPending ? "Checking…" : "Check"}
                </button>
              )}
            </div>
            {fanError && <p className="mt-2 text-xs text-err">{fanError}</p>}
            <p title={EXTRA_LABEL} className="mt-2 text-xs text-fg-dim">
              {fanReady
                ? `Will send to ${fanReady.name || fanReady.username} (@${fanReady.username}): each new file goes to them as a free message, so it appears in the vault. You must be subscribed to this account, or it to you.`
                : fanTyped
                  ? "Check who this is before starting: each new file is sent to this account as a free message."
                  : "Empty: each new file rides a scheduled post that is deleted straight away — nothing is posted or sent to fans."}
            </p>
          </Step>

          <Step title="Select media" titleId="vault-import-select-media">
            <div
              role="group"
              aria-labelledby="vault-import-select-media"
              aria-disabled={locked || undefined}
              onDragOver={onDragOver}
              onDrop={onDrop}
              className={cn("flex h-[344px] w-full flex-col items-center justify-center bg-bg-elev-1", locked && "opacity-50")}
            >
              <label
                className={cn(
                  "flex flex-col items-center justify-center bg-bg-elev-2 focus-within:ring-2 focus-within:ring-accent",
                  picked.length > 0 ? "h-[106px] w-[106px]" : "h-[120px] w-[120px]",
                  locked ? "cursor-not-allowed" : "cursor-pointer",
                )}
              >
                <input
                  ref={fileRef}
                  type="file"
                  multiple
                  accept="image/*,video/*,audio/*"
                  disabled={locked}
                  onChange={(e) => dispatch({ type: "pick", files: Array.from(e.target.files ?? []) })}
                  className="sr-only"
                />
                <Plus size={picked.length > 0 ? 16 : 24} aria-hidden className="text-accent" />
                <span className="mt-2 text-sm font-normal text-accent">Add media</span>
              </label>
              <p className="mt-4 text-sm font-normal leading-5 text-fg">
                Drag and drop media file(s) here or select them from your computer
              </p>
              <ul
                aria-label="Upload rules"
                title={EXTRA_LABEL}
                className="mt-4 flex flex-wrap items-center justify-center gap-y-1 px-2 text-xs font-normal leading-5 text-fg-dim"
              >
                {rules.map((r, i) => (
                  <li key={r} className={cn("flex items-center", i === 1 && "mx-6")}>
                    <span className="mr-1 flex h-4 w-4 items-center justify-center rounded-full bg-bg-elev-2">{i + 1}</span>
                    {r}
                  </li>
                ))}
              </ul>
            </div>
            {picked.length > 0 && (
              <p title={EXTRA_LABEL} className="mt-2 text-xs text-fg-dim">
                {picked.length} file{picked.length === 1 ? "" : "s"} ·{" "}
                {fmtSize(picked.reduce((n, f) => n + f.size, 0))}
              </p>
            )}
          </Step>

          <Step title="Edit media" last>
            {picked.length > 0 && (
              <div className="overflow-x-auto">
                <table className="w-full text-left text-xs">
                  <thead className="text-fg-dim">
                    <tr className="border-b border-border">
                      <th className="w-8 py-2 pr-2 font-medium">
                        <input
                          type="checkbox"
                          aria-label="Select all media"
                          checked={chosen.length === picked.length}
                          disabled={locked}
                          onChange={(e) => dispatch({ type: "selectAll", on: e.target.checked })}
                        />
                      </th>
                      <th className="py-2 pr-3 font-medium">Media</th>
                      {STEP3_FIELDS.map(([h, key]) => (
                        <th
                          key={h}
                          title={
                            notSaved && MIRROR_ONLY.has(key)
                              ? "This model's vault is not synced here yet, so this is not saved. Collect the vault first."
                              : undefined
                          }
                          className={cn(
                            "py-2 pr-3 font-medium",
                            h === "Tag Creators" && "w-[170px]",
                            h === "Hashtags" && "w-[134px]",
                          )}
                        >
                          {h}
                          {notSaved && MIRROR_ONLY.has(key) && <span className="ml-1 text-warn">· not saved</span>}
                        </th>
                      ))}
                      <th className="py-2 font-medium">Action</th>
                    </tr>
                  </thead>
                  <tbody>
                    {picked.map((f, i) => (
                      <tr key={`${f.name}-${i}`} className="border-b border-border">
                        <td className="py-2 pr-2">
                          <input
                            type="checkbox"
                            aria-label={`Select ${f.name}`}
                            checked={selected.has(f)}
                            disabled={locked}
                            onChange={() => dispatch({ type: "toggle", file: f })}
                          />
                        </td>
                        <td className="max-w-[220px] py-2 pr-3">
                          <div className="truncate" title={f.name}>{f.name}</div>
                          <div className="text-fg-dim">{fmtSize(f.size)}</div>
                        </td>
                        {STEP3_FIELDS.map(([h, key]) => (
                          <td key={h} className="py-2 pr-3">
                            <MetaField
                              field={key}
                              label={`${h} for ${f.name}`}
                              value={details.get(f)?.[key] ?? ""}
                              onChange={(v) => dispatch({ type: "edit", files: [f], values: { [key]: v } })}
                              folders={folders.data ?? []}
                              disabled={locked}
                              className={cn(
                                "w-full px-2 py-1 disabled:cursor-not-allowed disabled:opacity-60",
                                key === "category" ? "min-w-[96px]" : "min-w-[80px]",
                              )}
                            />
                          </td>
                        ))}
                        <td className="py-2">
                          <button
                            type="button"
                            aria-label={`Delete ${f.name}`}
                            disabled={locked}
                            onClick={() => remove([f])}
                            className="text-fg-dim hover:text-err disabled:opacity-50"
                          >
                            <Trash2 size={16} aria-hidden />
                          </button>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
            {chosen.length > 0 && (
              <div
                role="region"
                aria-label="Selected media"
                className="sticky bottom-4 mt-4 flex h-[38px] items-center justify-between gap-3 rounded-lg border border-border bg-bg-elev-1 px-3 text-sm sm:px-6"
              >
                <div className="flex items-center gap-2">
                  <span>Selected</span>
                  <span className="font-semibold text-accent">{chosen.length}</span>
                  <button
                    type="button"
                    aria-label="Clear selection"
                    onClick={() => dispatch({ type: "selectAll", on: false })}
                    className="text-fg-dim hover:text-fg"
                  >
                    <X size={16} aria-hidden />
                  </button>
                </div>
                <div className="flex items-center gap-4 sm:gap-6">
                  <button
                    type="button"
                    aria-label="Batch edit"
                    title="Batch edit"
                    data-tour="vault-batch-edit"
                    disabled={locked}
                    onClick={() => {
                      endBarTour("batchEdit");
                      setBatchOpen(true);
                    }}
                    className="text-fg-dim hover:text-fg disabled:opacity-50"
                  >
                    <SquarePen size={20} aria-hidden />
                  </button>
                  <button
                    type="button"
                    aria-label="Delete selected"
                    title="Delete"
                    disabled={locked}
                    onClick={() => remove(chosen)}
                    className="text-fg-dim hover:text-err disabled:opacity-50"
                  >
                    <Trash2 size={20} aria-hidden />
                  </button>
                  <button
                    type="button"
                    disabled={!canStart}
                    data-tour="vault-bulk-upload"
                    onClick={() => {
                      endBarTour("uploadBtn");
                      start.mutate(chosen);
                    }}
                    className="whitespace-nowrap rounded bg-accent px-3 py-1 text-xs font-semibold text-white disabled:opacity-40"
                  >
                    Bulk upload
                  </button>
                </div>
                {barTour !== null && (
                  <VaultTour
                    key={barTour}
                    steps={BAR_TOUR}
                    start={barTour}
                    variant="coach"
                    placement="top"
                    overlayClose
                    onClose={() => setBarTour(null)}
                  />
                )}
              </div>
            )}
          </Step>
        </ol>

        <label title={EXTRA_LABEL} className="flex items-center gap-2 text-xs text-fg-dim">
          <span className="shrink-0">Put into folder</span>
          <select
            value={folder}
            disabled={locked}
            onChange={(e) => setFolder(e.target.value)}
            className="min-w-0 flex-1 rounded border border-border bg-bg px-2 py-1 text-xs disabled:opacity-50"
          >
            <option value="">No folder — just the vault</option>
            {(folders.data ?? []).map((l) => (
              <option key={String(l.id)} value={String(l.id)}>
                {l.name}
              </option>
            ))}
          </select>
        </label>

        <VaultImportDrive
          configured={driveOn}

          links={links}
          onLinks={setLinks}
          disabled={locked}
        />
      </div>


      <div title={EXTRA_LABEL} className="flex items-center gap-3">
        <button
          type="button"
          disabled={!canStart}
          onClick={() => start.mutate(chosen)}
          className="rounded bg-accent px-3 py-1.5 text-xs font-semibold text-white disabled:opacity-40"
        >
          {startLabel({ sending, running, sessionLost, pending: start.isPending, modelName })}
        </button>
        <span className="text-xs text-fg-dim">{runSummary(s)}</span>
      </div>

      <div title={EXTRA_LABEL} className="space-y-3 empty:hidden">
        {running && (
          <p className="text-xs text-fg-dim">
            {fanRun
              ? "Each new file costs one paced write — the chat message to the fan — and OnlyFans allows about one write every 10 seconds, so new files land at roughly 6 a minute;"
              : "Each new file costs two paced writes — the scheduled post that carries it, and the deletion of that post — and OnlyFans allows about one write every 10 seconds, so new files land at roughly 3 a minute;"}{" "}
            anything already in the vault is recognised and skipped straight away. You can
            leave this page — the import keeps going and this panel picks it back
            up.
          </p>
        )}

        {(startError || showsError(s)) && (
          <p className="text-xs text-err">{startError || s.error}</p>
        )}

        {note && <p className="text-xs text-warn">{note}</p>}

        {s.filing_error && (
          <p className="text-xs text-warn">
            {s.filing_error} — the media is in the vault, just not in that folder.
          </p>
        )}

        {!!s.carriers_undeletable && (
          <p className="text-xs text-err">
            {s.carriers_undeletable} scheduled post{s.carriers_undeletable === 1 ? "" : "s"} could not be
            removed. Check Scheduled posts on OnlyFans — they publish on their date.
          </p>
        )}

        {!!s.carriers_unrecorded && (
          <p className="text-xs text-warn">
            {s.carriers_unrecorded} scheduled post
            {s.carriers_unrecorded === 1 ? " may have been" : "s may have been"} created
            without being recorded — the relay is searching OnlyFans for
            {s.carriers_unrecorded === 1 ? " it" : " them"} and will delete
            {s.carriers_unrecorded === 1 ? " it" : " them"}. If this is still here
            tomorrow, check Scheduled posts on OnlyFans yourself.
          </p>
        )}

        {items.length > 0 && (
          <ul className="max-h-56 overflow-y-auto divide-y divide-border text-xs">
            {items.map((it, i) => (
              <li key={`${it.name}-${i}`} className="flex items-baseline justify-between gap-3 py-1">
                <span className="truncate" title={it.name}>{it.name}</span>
                <span
                  className={
                    it.status === "failed"
                      ? "shrink-0 text-err"
                      : it.status === "done"
                        ? "shrink-0 text-ok"
                        : "shrink-0 text-fg-dim"
                  }
                >
                  {it.compressed_from
                    ? `${fmtSize(it.compressed_from)} → ${fmtSize(it.size)} · `
                    : ""}
                  {itemLabel(it)}
                </span>
              </li>
            ))}
          </ul>
        )}
      </div>
      {batchOpen && (
        <BatchEditModal
          folders={folders.data ?? []}
          onClose={() => setBatchOpen(false)}
          onSave={(values) => {
            dispatch({ type: "edit", files: chosen, values });
            setBatchOpen(false);
          }}
        />
      )}
    </section>
  );
}
