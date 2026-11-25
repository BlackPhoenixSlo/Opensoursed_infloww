"use client";

import { useEffect, useState } from "react";

import { saveBlob } from "@/lib/csv";
import { errText } from "@/lib/errText";
import { relayFile, RelayError } from "@/lib/relay";

// service/report_files.TTL_S
const FILE_TTL_MS = 15 * 60_000;
export const REPORT_EXPIRED = "This link has expired (links last 15 minutes). Ask Ultra for the report again.";

const deadAt = (endedAt: string | null) => (endedAt ? Date.parse(endedAt) + FILE_TTL_MS : NaN);

export function ReportDownload({ fileId, endedAt, fallbackName }: {
  fileId: string;
  endedAt: string | null;
  fallbackName: string;
}) {
  const [problem, setProblem] = useState<{ kind: "expired" } | { kind: "error"; text: string } | null>(null);
  useEffect(() => {
    const left = deadAt(endedAt) - Date.now();
    if (!(left > 0)) return;
    const t = window.setTimeout(() => setProblem({ kind: "expired" }), left);
    return () => window.clearTimeout(t);
  }, [endedAt]);

  // eslint-disable-next-line react-hooks/purity -- expiry is wall-clock by nature; the timer above re-renders at the boundary
  if (problem?.kind === "expired" || deadAt(endedAt) <= Date.now()) {
    return <p data-step-download-expired className="mt-2 break-words text-[13px] text-warn">{REPORT_EXPIRED}</p>;
  }
  const path = `/admin/reports/files/${encodeURIComponent(fileId)}`;
  return (
    <div className="mt-2 text-[13px] text-fg-dim">
      <p>
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
