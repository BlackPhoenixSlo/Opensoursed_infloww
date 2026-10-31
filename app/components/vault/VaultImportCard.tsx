"use client";

/**
 * Vault import — drop files in, or paste public Google Drive links, and the
 * relay pushes them into the OnlyFans vault.
 *
 * Each picked file carries its own details (Category = vault folder, tagged
 * creators, hashtags, notes, suggested price), which the relay writes onto the
 * file's vault row once it lands. None of it is required: pick, Bulk upload.
 * The first file opens the run and the rest follow one request each, so the
 * first is already on its way to OnlyFans while the others are still uploading
 * to the relay. A Drive folder skips the edit step: its files are tagged with
 * the folder they sit in.
 *
 * WHAT THE UI HAS TO BE HONEST ABOUT, because the underlying operation is slow
 * and strange:
 *
 *  - OnlyFans has no "save to vault" API. With a linked fan account each NEW
 *    file is sent to that fan in chat (Infloww's way); with none it is attached
 *    to a far-future scheduled post, its vault id read off that post, and the
 *    post deleted — nothing published, no fan sees anything. Either way the
 *    import IS creating real objects, so the panel says so rather than
 *    pretending it is a plain upload.
 *  - OnlyFans throttles WRITES to ~1 per 10s and each new file costs two on
 *    the carrier path (the post and its deletion) or one with a linked fan
 *    (the chat message), so a batch of NEW files runs at roughly 3 or 6 a
 *    minute no matter how small they are or how fast the connection. Files
 *    already in the vault cost no write and go straight through, which is why
 *    a re-import finishes in seconds.
 *  - Big video is re-encoded first (OnlyFans rejects large objects outright),
 *    which can take minutes per file before a single byte is uploaded.
 *
 * So the panel reports phase and per-item state from the server's own run
 * record, and polls THAT RUN by id — the id comes back from the start call, so
 * the panel can never end up watching the previous import. State lives on the
 * relay, not here: a reload, a second tab, or a closed laptop does not lose the
 * run.
 */

import { useEffect, useReducer, useRef, useState, type DragEvent, type ReactNode } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Info, Plus, SquarePen, Trash2, X } from "lucide-react";

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

const POLL_MS = 2500;
/** How long to keep polling after a start even if the server has not yet said
 *  `running` — the worker begins on a thread and the first poll can beat it. */
const FORCE_POLL_MS = 20_000;

/** The picker's `accept` (images, video, audio). A drop bypasses `accept`, so
 *  dropped files are held to the same three kinds. */
const MEDIA_TYPE = /^(image|video|audio)\//;

/** The selection bar's tour: the bundle's `multipleSelectionOperationJoyrideSteps` and their text
 *  (index.9f50f370.js @12947586), and the `VaultProOnboardingKeyMap` key each step is stored under. */
const BAR_TOUR: VaultTourStep[] = [
  { target: "[data-tour='vault-batch-edit']", content: "With your media selected, click here to batch-edit their details" },
  {
    target: "[data-tour='vault-bulk-upload']",
    content: "Once you’re ready, click here to upload your selected media file(s)",
  },
];
const BAR_TOUR_KEYS = ["batchEdit", "uploadBtn"] as const;

/** Step 1's info tip: the capture's two lines (#86), then what empty means here. */
const FAN_TIP =
  "Infloww will automatically send media to this account so that it appears in your Creator’s vault.\n" +
  "NOTE: You must be subscribed to this fan account, or the account must be subscribed to you.\n" +
  "Leave it empty and each file is attached to a scheduled post that is deleted again at once — nothing reaches a fan.";

/** One upload step, as growth-vault-pro.md draws it: a 15px marker with a 9px
 *  dot, a 3px line down to the next step (#81), a body padded 0 0 65px 16px
 *  with a 1px rule 32px above its bottom (#83), and a 16px weight-500 title
 *  18px above the body (#84). Colours are tokens (ADR-0001 / ADR-0010). */
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

/** The details columns that are written onto the mirror row, not to OnlyFans. */
const MIRROR_ONLY: ReadonlySet<string> = new Set(["tag", "hashtags", "notes", "price"]);

export default function VaultImportCard() {
  const qc = useQueryClient();
  // The account every call on this card is scoped to — the PAGE's model, from
  // the header picker. It used to be `accounts[0]`, unconditionally: switching
  // model moved the grid and left the importer behind, so files uploaded into
  // the first account's vault (and were offered the first account's folder ids,
  // which go to OnlyFans verbatim) while the operator watched a different
  // model's vault above the form.
  //
  // A plain string, and the card is REMOUNTED when it changes — the same
  // mechanism the grid and the review tab use. It used to clear itself with an
  // effect instead, which fired once on the null → id transition every mount
  // and silently binned files an operator had staged while `/admin/accounts`
  // was still answering.
  const accountId = useVaultAccountId();
  const { account, sessionLost } = useVaultAccount();
  const ctx = { accountId };
  const fileRef = useRef<HTMLInputElement>(null);
  // The picked files, step 3's row selection and each file's details, as one
  // state (importPickReducer). Only the selected files are sent.
  const [pickState, dispatch] = useReducer(importPickReducer, initialPickState);
  const { picked, selected, details } = pickState;
  const [batchOpen, setBatchOpen] = useState(false);
  // Step 1: the fan account each new file is sent to. Empty is the carrier path.
  // A typed name sends nothing until the relay has said who it is (`fanFound`,
  // for exactly the text it was checked for).
  const [fan, setFan] = useState("");
  const [fanFound, setFanFound] = useState<(ResolvedFan & { typed: string }) | null>(null);
  // The pipelined send: how many of this batch's files the relay has taken.
  const [sending, setSending] = useState<{ sent: number; total: number } | null>(null);
  const [links, setLinks] = useState("");
  const [startError, setStartError] = useState<string | null>(null);
  const [runId, setRunId] = useState<string | null>(null);
  const [folder, setFolder] = useState<string>("");
  const settledRef = useRef(false);
  const forceUntilRef = useRef(0);

  // Vault folders, so "file everything into a folder" is reachable from the UI
  // the feature was built for. Same paginated fetcher every other reader of
  // this cache uses — a single-page queryFn under this key would poison it.
  const folders = useQuery({
    queryKey: vaultListsKey(accountId),
    queryFn: () => fetchAllVaultLists(ctx),
    staleTime: 5 * 60 * 1000,
    select: (d: { list?: VaultList[] }) =>
      (d.list ?? []).filter((l) => l.type === "custom"),
  });

  const status = useQuery<RunStatus>({
    // Per MODEL as well as per run: with no `run_id` this route answers with the
    // latest run for whatever account the header names, so a key without the
    // account served one model's import progress under another's name.
    queryKey: ["vault-import-status", accountId, runId],
    queryFn: () =>
      relay.get<RunStatus>(
        runId
          ? `/api/of/v2/vault/upload/status?run_id=${encodeURIComponent(runId)}`
          : "/api/of/v2/vault/upload/status",
        ctx,
      ),
    // Self-arming: poll while the run is live, and unconditionally for a short
    // window after a start — the route creates the record before it answers,
    // but the worker reaches its first item on a thread a moment later.
    refetchInterval: (q) =>
      q.state.data?.running || Date.now() < forceUntilRef.current ? POLL_MS : false,
    staleTime: 0,
    refetchOnWindowFocus: true,
  });

  const s = status.data ?? { running: false };
  const running = !!s.running;
  // Fail-closed: no answer yet, a failed read, false or absent all render no
  // Drive slot; only an answer saying `true` shows the section.
  const driveOn = status.data?.drive_import_configured === true;
  // A keyless card never sends links, even ones typed before the key went.
  const driveLinks = driveOn ? links.trim() : "";

  // When a run finishes, the vault grid is stale — it has new media in it.
  useEffect(() => {
    if (running) {
      settledRef.current = true;
      return;
    }
    if (settledRef.current) {
      settledRef.current = false;
      // Every key the grid, the folder rail and the counter read — as ONE
      // call, built from the hooks' own key factories. Hand-listing them is how
      // this went wrong twice: `["vault"]` looks like a prefix of
      // `["vault-media", …]` but TanStack compares elements, so it matched
      // nothing at all and an import stayed invisible behind a three-day
      // `vault-media` cache; and the panel's own copy of the list was missing a
      // key from the day it was written.
      invalidateVaultGrid(qc, accountId);
    }
  }, [running, qc, accountId]);

  /** Take files off the list; nothing has been sent, so nothing is lost. */
  const remove = (files: readonly File[]) => {
    dispatch({ type: "remove", files });
    if (fileRef.current) fileRef.current.value = "";
  };
  const chosen = chosenOf(pickState);

  // The selection bar's tour (index.9f50f370.js @12947586, `useMultipleSelectionOperationOnboarding`): each time the
  // bar appears, its first unseen step shows and is marked seen; "Got it" moves on, and Batch edit or Bulk upload
  // closes it and marks its own step.
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

  // The protocol is `sendVaultBatch`'s; this keeps the card's state in step
  // with it. Each file leaves the list the moment the relay has it. The rows
  // are locked while it runs (`locked`), so the details read here are the ones
  // on screen.
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
            // Watch the run we just started, by id — not "whatever the latest run is".
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

  // Step 1's check: who the typed name is on OnlyFans, before anything is sent
  // to them. The batch route resolves it again and refuses a different id.
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

  // While a run is live or a batch is still going up, the form is fixed: an
  // edit then would reach no file, or replace the list being sent.
  const locked = running || start.isPending;

  // Always claim a file drag, so a drop while the form is locked is refused
  // here rather than opening the file in the tab.
  const onDragOver = (e: DragEvent) => {
    if (!Array.from(e.dataTransfer?.types ?? []).includes("Files")) return;
    e.preventDefault();
    e.dataTransfer.dropEffect = locked ? "none" : "copy";
  };
  // A drop fills the same picked list the picker does, and replaces it as the
  // picker does.
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
  // A typed fan name that has not been checked blocks Start: it is a real DM.
  const canStart = !(running || nothingToDo || start.isPending || sessionLost || (fanTyped && !fanReady));
  // The rules row: this server's own limits when the status read gives them,
  // and the kinds the drop takes (narrower than the capture's, which adds PDF).
  const lim = s.upload_limits;
  const rules = [
    ...(lim ? [`File size limit: ${lim.max_file_mb}MB`, `Files per import: ${lim.max_files}`] : []),
    "Images, GIF, video and audio",
  ];
  const items = s.items ?? [];
  const notSaved = s.details_saved_here === false;
  const note = detailsNote(s);
  // The run on screen, which may be another tab's: does it send to a fan?
  const fanRun = running ? !!s.fan_id : !!fanReady;
  // The model this card writes to, named. Never a placeholder: this card does
  // not exist until the page knows which vault it is writing into.
  const modelName = account?.nickname || account?.id || accountId;

  return (
    <section className="rounded-lg border border-border bg-panel p-4 flex flex-col gap-3">
      <header className="space-y-1">
        {/* WHOSE vault, said out loud. This card used to name no model at all
            while uploading into a different one than the page displayed, and
            the operator's only clue was recognising the media afterwards. An
            upload into the wrong creator's vault cannot be undone — OnlyFans'
            delete is a one-way hide — so the target is stated before the form,
            not inferred from a chip somewhere else on the page. The title and
            the sentence under it are the card's own safety rules, which the
            capture's upload card has no item for, so both carry the extra
            label (ADR-0003). */}
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
        {/* The capture's three steps (growth-vault-pro.md #81 to #119), joined
            by their markers. Step 1 is optional here, where Infloww requires
            it: with a username each new file is sent to that fan, as Infloww
            does (#86's text); left empty, the relay's own carrier path files
            it without anything reaching a fan. */}
        <ol aria-label="Upload steps">
          <Step
            title={
              <>
                <span className="mr-[6px]">Link a fan account (optional)</span>
                <span role="img" aria-label="About linking a fan account" title={FAN_TIP} className="text-fg-dim">
                  <Info size={16} aria-hidden />
                </span>
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

          {/* The file drop, as growth-vault-pro.md records step 2: the title
              "Select media" (#90), a full-width 344px centred column (#91), a
              120px drop target (#93, #94; 106px with a 16px plus once files are
              picked, #107) holding a 24px plus over "Add media" (#95, #96), the
              tip (#97, #98), then the rules row (#99, #104): this server's own
              limits and the kinds the drop takes, never Infloww's, so the row
              carries the extra label. Colours are tokens (ADR-0001 /
              ADR-0010); the capture records no border. */}
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

          {/* Step 3, "Edit media" (#108 to #110): the picked files under the
              capture's columns. Every field is optional and goes up with its
              file; the relay writes it onto the file's vault row once it lands
              (Category is the vault folder). The row checkbox and Delete act
              on this list only, before anything is sent. */}
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
                                "w-full rounded border border-border bg-bg px-2 py-1 disabled:cursor-not-allowed disabled:opacity-60",
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
            {/* The selection bar (#112): "Selected" and the count, Batch edit,
                delete, and "Bulk upload", which starts the same batch as Start
                import with the selected files. */}
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

        {/* The capture sets a folder per file (step 3's "Category", #111) and
            has no single folder control, so this one is an extra. */}
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

        {/* The Drive import, an extra Infloww's card lacks (#106: step 2's
            next control is step 3), so it sits after the three steps, right
            above Start. Shown only on a server with the key; nothing at all
            until the status read answers, or when the key is unset (Settings
            → AI keys says what the key is for). */}
        <VaultImportDrive
          configured={driveOn}

          links={links}
          onLinks={setLinks}
          disabled={locked}
        />
      </div>


      {/* The capture starts uploads only from the selection bar's "Bulk
          upload" (#112); this row starts the same batch (the selected files
          and any Drive links) and names its target Creator, so it carries
          the extra label. */}
      <div title={EXTRA_LABEL} className="flex items-center gap-3">
        <button
          type="button"
          // `sessionLost` is a hard stop, not a nicety. The relay builds this
          // account's OFClient before it claims the run, so a dead session is
          // now a clean 503 that strands nothing — but a start that cannot
          // possibly work, offered under a banner saying nothing on this page
          // can load, is an error message dressed as a button.
          disabled={!canStart}
          onClick={() => start.mutate(chosen)}
          className="rounded bg-accent px-3 py-1.5 text-xs font-semibold text-white disabled:opacity-40"
        >
          {startLabel({ sending, running, sessionLost, pending: start.isPending, modelName })}
        </button>
        <span className="text-xs text-fg-dim">{runSummary(s)}</span>
      </div>

      {/* The run's progress and warnings: the card's own, with no item in
          the capture, so the block carries the extra label. Hidden when
          empty, so an idle card gains no gap. */}
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
