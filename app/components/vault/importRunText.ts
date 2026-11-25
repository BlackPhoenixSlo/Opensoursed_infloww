export const ERROR_FRESH_MS = 24 * 60 * 60 * 1000;

type ItemStatus = "pending" | "uploading" | "done" | "failed" | "skipped";
// A union, not string: runSummary branches on literals, so a relay rename must fail typecheck.
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
  still_transcoding?: boolean | null;
  compressed_from?: number | null;
}

export interface RunStatus {
  running: boolean;
  run_id?: string;
  status?: "running" | "done" | "failed" | "interrupted";
  phase?: RunPhase;
  error?: string | null;
  filing_error?: string | null;
  details_saved?: { applied: number; skipped: number; why: string | null } | null;
  details_saved_here?: boolean;
  fan_id?: number | null;
  finished_at?: string | null;
  total?: number;
  done?: number;
  failed?: number;
  skipped?: number;
  carriers_undeletable?: number;
  carriers_unrecorded?: number;
  items?: RunItem[];
  drive_import_configured?: boolean;
  upload_limits?: { max_file_mb: number; max_files: number };
}

const MB = 1024 * 1024;

export function fmtSize(bytes: number | null | undefined): string {
  if (!bytes) return "";
  return bytes >= MB ? `${(bytes / MB).toFixed(1)} MB` : `${Math.max(1, Math.round(bytes / 1024))} KB`;
}

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

export function runSummary(s: RunStatus): string {
  if (!s.run_id) return "No import has run yet.";
  const done = s.done ?? 0;
  const total = s.total ?? 0;
  if (s.running) {
    // mirroring stays `running` on purpose: refreshing the grid before the mirror is written made big imports look empty.
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

export function showsError(s: RunStatus, now: number = Date.now()): boolean {
  if (!s.error) return false;
  if (s.status !== "failed" && s.status !== "interrupted") return false;
  if (!s.finished_at) return true;
  const at = Date.parse(s.finished_at);
  return Number.isNaN(at) || now - at < ERROR_FRESH_MS;
}

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

export function detailsNote(s: Pick<RunStatus, "details_saved">): string | null {
  const d = s.details_saved;
  if (!d?.skipped) return null;
  return `Details for ${d.skipped} file${d.skipped === 1 ? "" : "s"} were not saved${d.why ? `: ${d.why}` : ""}.`;
}
