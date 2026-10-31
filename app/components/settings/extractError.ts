import { RelayError } from "@/lib/relay";

/** Pull OF's `error.message` out of the relay's wrapped 4xx/5xx body so
 *  the editor can show a human reason instead of just "HTTP 400". */
export function extractError(err: unknown): string {
  if (err instanceof RelayError) {
    const body = err.body as { detail?: { upstream_body?: string } } | undefined;
    const raw = body?.detail?.upstream_body;
    if (typeof raw === "string") {
      try {
        const parsed = JSON.parse(raw) as { error?: { message?: string } };
        if (parsed?.error?.message) return parsed.error.message;
      } catch { /* fall through */ }
    }
    return `HTTP ${err.status} — ${err.message}`;
  }
  return (err as Error)?.message || "unknown error";
}
