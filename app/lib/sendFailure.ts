export interface SendFailure {
  reason?: string;
  refusedMediaIds?: number[];
}

// A refused item is not a duration ceiling near 5:00: videos over 300s were delivered (measured); OF's vault API exposes no cause.
export function parseSendFailure(body: unknown): SendFailure {
  const detail = (body as {
    detail?: { message?: unknown; owned_media?: unknown; upstream_body?: unknown };
  })?.detail;
  // `_proxy` truncates upstream_body at 2000 chars, so a very long OF error parses to nothing.
  const own = detail?.message;
  if (typeof own === "string" && own) {
    return { reason: own, refusedMediaIds: numericIds(detail?.owned_media) };
  }

  const raw = detail?.upstream_body;
  if (typeof raw !== "string") return {};
  let parsed: unknown;
  try {
    parsed = JSON.parse(raw);
  } catch {
    return {};
  }
  const error = (parsed as {
    error?: { message?: unknown; payload?: { removeFromInputMediaIds?: unknown } };
  })?.error;
  return {
    reason: typeof error?.message === "string" ? error.message : undefined,
    refusedMediaIds: numericIds(error?.payload?.removeFromInputMediaIds),
  };
}

function numericIds(raw: unknown): number[] | undefined {
  if (!Array.isArray(raw)) return undefined;
  const ids = raw.map(Number).filter((n) => Number.isFinite(n) && n > 0);
  return ids.length ? ids : undefined;
}

