"use client";

/**
 * A done report_file step's download (service/report_recipe_api.py GET /admin/reports/files/{id}: the held file for
 * 15 minutes, then 404). Fetched via relayFile + saveBlob, so a dead link never saves the relay's JSON as the
 * "report": a 404 shows the expired line instead of the link, any other refusal shows its words under it. Once the
 * plan's finished_at + 15 minutes has passed, the expired line shows with no request.
 */
import { useEffect, useState } from "react";

import { saveBlob } from "@/lib/csv";
import { errText } from "@/lib/errText";
import { relayFile, RelayError } from "@/lib/relay";

/** service/report_files.TTL_S. */
const FILE_TTL_MS = 15 * 60_000;
export const REPORT_EXPIRED = "This link has expired (links last 15 minutes). Ask Ultra for the report again.";

const deadAt = (finishedAt: string | null) => (finishedAt ? Date.parse(finishedAt) + FILE_TTL_MS : NaN);

export function ReportDownload({ fileId, finishedAt, fallbackName }: {
  fileId: string;
  finishedAt: string | null;
  fallbackName: string;
}) {
  // The one state: what the last click (or the expiry timer) found; expiry by time is also read from props each render.
  const [problem, setProblem] = useState<{ kind: "expired" } | { kind: "error"; text: string } | null>(null);
  useEffect(() => {
    const left = deadAt(finishedAt) - Date.now();
    if (!(left > 0)) return;
    const t = window.setTimeout(() => setProblem({ kind: "expired" }), left);
    return () => window.clearTimeout(t);
  }, [finishedAt]);

  // eslint-disable-next-line react-hooks/purity -- expiry is wall-clock by nature; the timer above re-renders at the boundary
  if (problem?.kind === "expired" || deadAt(finishedAt) <= Date.now()) {
    return <p data-step-download-expired className="mt-2 break-words text-[13px] text-warn">{REPORT_EXPIRED}</p>;
  }
  const path = `/admin/reports/files/${encodeURIComponent(fileId)}`;
  return (
    <div className="mt-2 text-[13px] text-fg-dim">
      <p>
        {/* a relay route, not a page: fetched (never next/link), so a 404 reads as a line, not a saved file */}
        <a data-step-download href={path} download
          onClick={(e) => {
            e.preventDefault();
            setProblem(null);
            relayFile(path)
              .then(({ blob, name }) => saveBlob(name || fallbackName, blob))
              .catch((err: unknown) => setProblem(err instanceof RelayError && err.status === 404
                ? { kind: "expired" } : { kind: "error", text: errText(err) }));
          }}
          className="font-medium text-accent hover:text-accent-hover">Download file</a>
        <span className="ml-2">link lasts 15 minutes</span>
      </p>
      {problem?.kind === "error" && <p role="alert" className="mt-1 break-words text-err">{problem.text}</p>}
    </div>
  );
}
