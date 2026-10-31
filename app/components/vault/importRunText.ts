/** The import card's run text (moved out of `VaultImportCard`): the wire types of a run's status and the words
 *  the card shows for it. Pure, no React. */

/** Past this, a finished run's error message is history, not news. */
export const ERROR_FRESH_MS = 24 * 60 * 60 * 1000;

type ItemStatus = "pending" | "uploading" | "done" | "failed" | "skipped";
/** The run's phases — `vault_upload.RUN_PHASES` on the wire. A union rather
 *  than `string`, because `runSummary` branches on two of these literals: with
 *  `phase?: string` a rename on the relay type-checks here and quietly turns
 *  the "caching previews" line back into "uploading", which is the one label
 *  whose entire job is to stop a real wait reading as a stall. */
type RunPhase = "collecting" | "uploading" | "mirroring" | "finished";

interface RunItem {
  name: string;
  source: "local" | "gdrive";
  size: number | null;
  status: ItemStatus;
  error: string | null;
  vault_id: number | null;
  deduped: boolean | null;
  hidden?: boolean | null;
  /** The vault id is real and permanent, but OnlyFans had not finished the
   *  encode when the carrier went away. It finishes on its own. */
  still_transcoding?: boolean | null;
  compressed_from?: number | null;
}

export interface RunStatus {
  running: boolean;
  run_id?: string;
  status?: "running" | "done" | "failed" | "interrupted";
  phase?: RunPhase;
  error?: string | null;
  /** Foldering failed but the media IS in the vault — a warning, not a failure. */
  filing_error?: string | null;
  /** What became of the per-file details once the files landed. */
  details_saved?: { applied: number; skipped: number; why: string | null } | null;
  /** Whether this account's vault is mirrored here, which the details are
   *  saved onto. False: Tag Creators, Hashtags, Notes and price go nowhere. */
  details_saved_here?: boolean;
  /** The run's linked fan, if any: that path costs one write per file. */
  fan_id?: number | null;
  finished_at?: string | null;
  total?: number;
  done?: number;
  failed?: number;
  skipped?: number;
  /** Carriers we know the id of that could NOT be deleted — the relay's own
   *  name for them, so the wire and the module say the same word. */
  carriers_undeletable?: number;
  /** Carriers that may exist but were never recorded — the create call's
   *  response was lost. The sweep hunts these by their marker. */
  carriers_unrecorded?: number;
  items?: RunItem[];
  /** Whether this server's GOOGLE_DRIVE_API_KEY is set (the key's own reader:
   *  Settings → AI keys, then the environment). Only `true` shows the Drive section;
   *  false or absent (an older relay) shows nothing. */
  drive_import_configured?: boolean;
  /** This server's own upload limits, the ones the batch route enforces
   *  (`VAULT_UPLOAD_MAX_MB`, `VAULT_UPLOAD_MAX_FILES`), for the rules row. */
  upload_limits?: { max_file_mb: number; max_files: number };
}

const MB = 1024 * 1024;

export function fmtSize(bytes: number | null | undefined): string {
  if (!bytes) return "";
  return bytes >= MB ? `${(bytes / MB).toFixed(1)} MB` : `${Math.max(1, Math.round(bytes / 1024))} KB`;
}

/** Plain-language state for one row. */
export function itemLabel(it: RunItem): string {
  if (it.status === "done" && it.deduped) return "already in vault";
  if (it.status === "done" && it.still_transcoding)
    return `in vault · ${it.vault_id ?? ""} · still processing`;
  if (it.status === "done") return `in vault · ${it.vault_id ?? ""}`;
  if (it.status === "uploading") return "uploading…";
  if (it.status === "pending") return "waiting";
  if (it.status === "skipped") return it.error || "skipped";
  return it.error || "failed";
}

/** One line summarising a run, in the words an operator would use. */
export function runSummary(s: RunStatus): string {
  if (!s.run_id) return "No import has run yet.";
  const done = s.done ?? 0;
  const total = s.total ?? 0;
  if (s.running) {
    // `mirroring` is the tail of the run: every file is in the vault and the
    // relay is reading them back one by one to fill the local mirror. It is
    // deliberately still `running` — the grid refreshes on the finish edge, and
    // refreshing before the mirror is written is what made a large import look
    // like it uploaded nothing. Naming it stops that wait reading as a stall.
    if (s.phase === "mirroring") return `${done} in vault — caching previews`;
    const phase = s.phase === "collecting" ? "fetching files" : "uploading";
    return `${phase} — ${done} of ${total} done`;
  }
  if (s.status === "interrupted") return "Interrupted — the relay restarted mid-run. Re-run to finish.";
  const bits = [`${done} in vault`];
  if (s.failed) bits.push(`${s.failed} failed`);
  if (s.skipped) bits.push(`${s.skipped} skipped`);
  return bits.join(" · ");
}

/** Is this run's error still worth showing? A failed run's message used to sit
 *  on the panel on every page load until somebody happened to import again. */
export function showsError(s: RunStatus, now: number = Date.now()): boolean {
  if (!s.error) return false;
  if (s.status !== "failed" && s.status !== "interrupted") return false;
  if (!s.finished_at) return true;
  const at = Date.parse(s.finished_at);
  return Number.isNaN(at) || now - at < ERROR_FRESH_MS;
}

/** The Start button's words, most pressing state first. */
export function startLabel(p: {
  sending: { sent: number; total: number } | null;
  running: boolean;
  sessionLost: boolean;
  pending: boolean;
  modelName: string;
}): string {
  if (p.sending) return `Sending ${p.sending.sent} of ${p.sending.total}…`;
  if (p.running) return "Importing…";
  if (p.sessionLost) return "Session dropped";
  if (p.pending) return "Starting…";
  return `Start import → ${p.modelName}`;
}

/** The run's word on the per-file details, when some were not saved. */
export function detailsNote(s: Pick<RunStatus, "details_saved">): string | null {
  const d = s.details_saved;
  if (!d?.skipped) return null;
  return `Details for ${d.skipped} file${d.skipped === 1 ? "" : "s"} were not saved${d.why ? `: ${d.why}` : ""}.`;
}
