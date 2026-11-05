"use client";

/**
 * VaultDuplicatesModal — review + confirm removal of re-uploaded vault media.
 *
 * A mature vault is ~30% re-uploads (measured on one account: 706 of 2,309). Each copy
 * costs a describe call, clutters the picker, and splits folder ordering.
 *
 * The relay groups them into sets where `original` is the EARLIEST-uploaded copy
 * and is always kept; everything else is a removal candidate, pre-selected. The
 * operator sees both sides as real thumbnails before anything happens.
 *
 * Removing calls OF's own "Remove selected items from vault"
 * (PUT /vault/media/hidden — the exact call OF's web app makes). The copies
 * leave her real vault but are NOT destroyed, so anything already attached to a
 * sent PPV or a live post keeps working. OF exposes no unhide, so this is
 * one-way — hence the explicit confirm step.
 *
 * The relay re-clusters server-side on submit and refuses any id that is an
 * original, is not currently a duplicate, or has been sent (unless allowed), so
 * a stale selection in this UI can never remove the keeper.
 */

import { useMemo, useReducer } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { Check } from "lucide-react";

import {
  hideDuplicates,
  mirrorThumbSrc,
  useDuplicates,
  type DupeCluster,
  type DupeMember,
} from "@/hooks/useVaultCache";
import { IfButton, IfHelp, IfLabel, IfModal, IfNativeSelect } from "@/components/ui/infloww";
import { errText } from "@/lib/errText";

import {
  allOff,
  doneText,
  duplicatesReducer,
  hidePayload,
  initialDupesState,
  selectedIdsOf,
} from "./duplicatesReducer";

const BAND_STYLE: Record<string, string> = {
  identical: "border-ok/50 bg-ok/10 text-ok",
  near: "border-info/50 bg-info/10 text-info",
  similar: "border-warn/50 bg-warn/10 text-warn",
  loose: "border-err/50 bg-err/10 text-err",
};

const THRESHOLDS = [
  { v: 0, label: "0 · pixel-identical only" },
  { v: 2, label: "2 · recommended" },
  { v: 4, label: "4 · looser" },
  { v: 6, label: "6 · review every set" },
];

function fmtDate(iso: string | null): string {
  if (!iso) return "—";
  return iso.slice(0, 10);
}

function Tile({
  accountId,
  m,
  isOriginal,
  checked,
  onToggle,
}: {
  accountId: string;
  m: DupeMember;
  isOriginal: boolean;
  checked?: boolean;
  onToggle?: () => void;
}) {
  const band = m.band ?? "identical";
  return (
    <figure className="m-0 w-[126px] shrink-0">
      <button
        type="button"
        disabled={isOriginal}
        aria-pressed={isOriginal ? undefined : !!checked}
        onClick={onToggle}
        className={[
          "relative block w-[126px] h-[126px] rounded-lg overflow-hidden border-2 transition-all",
          isOriginal
            ? "border-ok cursor-default"
            : checked
              ? "border-err opacity-100"
              : "border-border opacity-45 hover:opacity-75",
        ].join(" ")}
      >
        {/* eslint-disable-next-line @next/next/no-img-element */}
        <img
          src={mirrorThumbSrc(accountId, m.media_id)}
          alt={`media ${m.media_id}`}
          loading="lazy"
          className="w-full h-full object-cover"
        />
        {!isOriginal && (
          <span
            className={[
              "absolute top-1 right-1 w-5 h-5 rounded-md grid place-items-center text-[11px] font-bold",
              checked ? "bg-err text-white" : "bg-black/60 text-fg-dim",
            ].join(" ")}
          >
            {checked && <Check className="h-3.5 w-3.5" aria-hidden />}
          </span>
        )}
      </button>
      <figcaption className="mt-1 text-[12px] leading-tight text-muted">
        <span className="block text-fg-dim/90">#{m.media_id}</span>
        {fmtDate(m.created_at)}
        {m.send_count > 0 && (
          <span className="block text-warn">sent {m.send_count}×</span>
        )}
        {isOriginal ? (
          <span className="mt-0.5 inline-block px-1.5 py-px rounded-full border border-ok/50 bg-ok/10 text-ok text-[12px] font-semibold">
            ORIGINAL · keep
          </span>
        ) : (
          <span
            className={`mt-0.5 inline-block px-1.5 py-px rounded-full border text-[12px] font-semibold ${
              BAND_STYLE[band] ?? BAND_STYLE.identical
            }`}
          >
            {m.exact ? "exact bytes" : `${band} d${m.dhash_dist}/a${m.ahash_dist}`}
          </span>
        )}
      </figcaption>
    </figure>
  );
}

export default function VaultDuplicatesModal({
  accountId,
  onClose,
}: {
  accountId: string;
  onClose: () => void;
}) {
  const qc = useQueryClient();
  const [state, dispatch] = useReducer(duplicatesReducer, undefined, initialDupesState);
  const { threshold, deselected, phase } = state;
  const busy = phase.kind === "hiding";
  const done = phase.kind === "done" ? phase : null;
  const error = phase.kind === "error" ? phase.msg : "";

  const scan = useDuplicates(accountId, threshold, true);
  const clusters: DupeCluster[] = useMemo(
    () => scan.data?.clusters ?? [],
    [scan.data],
  );

  // Everything is a candidate unless the operator explicitly unticked it, so
  // the default action is the safe-by-measurement one and un-checking is the
  // deliberate act.
  const selectedIds = useMemo(
    () => selectedIdsOf(clusters, deselected),
    [clusters, deselected],
  );

  // Sends the ids + threshold frozen at confirm — never the live selection.
  async function doHide() {
    const payload = hidePayload(state);
    if (!payload) return;
    dispatch({ type: "hideStart" });
    try {
      const res = await hideDuplicates(accountId, payload.ids, {
        threshold: payload.threshold,
        onProgress: (done) => dispatch({ type: "progress", done }),
      });
      dispatch({ type: "hideOk", result: res });
    } catch (e) {
      dispatch({ type: "hideFail", msg: errText(e) });
      // eslint-disable-next-line no-console
      console.error("hide duplicates failed", e);
    } finally {
      // Refresh the grid, the counts and the scan — also after a failed later
      // batch, since the earlier batches ARE gone from OF.
      qc.invalidateQueries({ queryKey: ["vault-duplicates"] });
      qc.invalidateQueries({ queryKey: ["vault-mirror-items"] });
      qc.invalidateQueries({ queryKey: ["vault-cache-summary"] });
      qc.invalidateQueries({ queryKey: ["vault-of-folders-mirror"] });
    }
  }

  const confirming = phase.kind === "confirming" || phase.kind === "hiding";
  return (
    <IfModal
      title="Duplicate media"
      width={820}
      // No ×, no Escape while the removal is out (it cannot be stopped half way).
      closable={!busy}
      onClose={onClose}
      footer={
        <div className="flex w-full flex-wrap items-center justify-end gap-2">
          {!confirming ? (
            <>
              {/* "Done", not "Close": the kit's × already owns that name. */}
              <IfButton onClick={onClose}>Done</IfButton>
              <IfButton
                variant="primary"
                className="bg-err hover:bg-err/90"
                disabled={selectedIds.length === 0}
                onClick={() => dispatch({ type: "confirm", ids: selectedIds })}
              >
                Remove {selectedIds.length} {selectedIds.length === 1 ? "copy" : "copies"} from
                OnlyFans…
              </IfButton>
            </>
          ) : (
            <>
              <span className="min-w-0 flex-1 basis-60 text-[12px] text-err">
                Removes {phase.frozenIds.length} from your real vault. Originals are kept
                and sent PPVs keep working — but OnlyFans has no undo.
              </span>
              <IfButton disabled={busy} onClick={() => dispatch({ type: "cancel" })}>
                Cancel
              </IfButton>
              <IfButton variant="primary" className="bg-err hover:bg-err/90" disabled={busy} onClick={doHide}>
                {phase.kind === "hiding"
                  ? `Removing ${phase.done}/${phase.frozenIds.length}…`
                  : "Yes, remove them"}
              </IfButton>
            </>
          )}
        </div>
      }
    >
      <IfHelp className="mt-0">
        Green is the original (first upload, always kept); ticked red copies are hidden from your OnlyFans vault, not deleted.
      </IfHelp>

      <div className="mt-4 flex flex-wrap items-end gap-3">
        <div>
          <IfLabel htmlFor="dupes-threshold">Match strictness</IfLabel>
          <IfNativeSelect
            id="dupes-threshold"
            value={threshold}
            disabled={busy}
            onChange={(e) => dispatch({ type: "threshold", v: Number(e.target.value) })}
          >
            {THRESHOLDS.map((t) => (
              <option key={t.v} value={t.v}>
                {t.label}
              </option>
            ))}
          </IfNativeSelect>
        </div>
        {scan.isFetching && <span className="flex h-8 items-center text-muted">scanning…</span>}
        {scan.data && (
          <>
            <span className="flex h-8 items-center text-muted">
              {scan.data.sets} sets · {scan.data.removable} copies ·{" "}
              {scan.data.scanned} items scanned
            </span>
            <span className="flex h-8 items-center font-medium text-fg">
              {selectedIds.length} selected for removal
            </span>
          </>
        )}
      </div>

      {done && (
        <div className={`mt-4 rounded-md border px-3 py-2 ${done.result.of_error ? "border-warn/40 bg-warn/10 text-warn" : "border-ok/40 bg-ok/10 text-ok"}`}>
          <span>{doneText(done.result, done.total)}</span>
          {Object.entries(done.result.refused).map(([why, ids]) => (
            <span key={why} className="block text-warn">
              refused ({why}): {ids.length}
            </span>
          ))}
          {!!done.result.not_hidden?.length && (
            <span className="block text-warn">
              {done.result.not_hidden.length} not removed — re-scan and try again.
            </span>
          )}
        </div>
      )}

      {error && (
        <div className="mt-4 rounded-md border border-err/40 bg-err/10 px-3 py-2 text-err">
          {error}
        </div>
      )}

      <div className="mt-4 flex flex-col gap-3">
        {scan.isLoading && (
          <p className="text-muted">Hashing thumbnails…</p>
        )}
        {scan.data && clusters.length === 0 && (
          <p className="text-muted">No duplicates at this strictness.</p>
        )}
        {clusters.map((c) => {
          const ids = c.dupes.map((d) => d.media_id);
          return (
            <section
              key={c.original.media_id}
              className="rounded-md border border-border bg-bg-elev-1/40"
            >
              <div className="flex flex-wrap items-center gap-2 border-b border-border px-3 py-1.5 text-[12px]">
                <b className="text-fg">
                  {c.dupes.length} duplicate{c.dupes.length === 1 ? "" : "s"}
                </b>
                <span
                  className={`rounded-full border px-1.5 py-px text-[12px] font-semibold ${
                    BAND_STYLE[c.band] ?? BAND_STYLE.identical
                  }`}
                >
                  {c.band}
                </span>
                <span className="text-muted">
                  {c.original.kind} · original uploaded{" "}
                  {fmtDate(c.original.created_at)}
                </span>
                {c.sent_dupes > 0 && (
                  <span className="text-warn">
                    {c.sent_dupes} already sent
                  </span>
                )}
                <IfButton variant="link" className="ml-auto h-6 text-[12px]" onClick={() => dispatch({ type: "toggleSet", ids })}>
                  {allOff(ids, deselected) ? "Select set" : "Keep all"}
                </IfButton>
              </div>
              <div className="flex gap-2 overflow-x-auto px-3 py-3">
                <Tile accountId={accountId} m={c.original} isOriginal />
                <div className="my-1 w-px shrink-0 bg-border" />
                {c.dupes.map((d) => (
                  <Tile
                    key={d.media_id}
                    accountId={accountId}
                    m={d}
                    isOriginal={false}
                    checked={!deselected.has(d.media_id)}
                    onToggle={() => dispatch({ type: "toggle", id: d.media_id })}
                  />
                ))}
              </div>
            </section>
          );
        })}
      </div>
    </IfModal>
  );
}
