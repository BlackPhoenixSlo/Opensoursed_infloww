"use client";

/**
 * VaultPackPickerModal — one button, every candidate, one Save.
 *
 * The operator opens it, sees every photo in the vault that might be a feet
 * photo, files each one on a rung (or rejects it), and presses Save. That
 * writes the rung folders and their membership. Publishing them to her real
 * OnlyFans vault is a separate, explicit button per rung.
 *
 * WHY A HUMAN IS IN THIS LOOP AT ALL. The vault's own taxonomy cannot find this
 * content. Measured on prod 2026-08-10: `primary_folder='feet'` is set on 265
 * items roster-wide but ZERO on either pilot account, and zero of the 68 items
 * the operator hand-picked on 08-01 carry it. `body_focus` DOES say "feet" — on
 * 278 items on 8000149 — but it says so whenever feet are VISIBLE, not when they
 * are the subject, so a lingerie pose with her feet in frame matches. Hence a
 * 22% hit rate (307 candidates -> 68 keepers) and hence this screen: selling
 * straight off the tag would charge a fan for three photos he did not ask for
 * out of every four.
 *
 * TWO PASSES, and the first one is free. Roughly half the set is rejectable on
 * the DESCRIPTION alone — "walks away from the camera on a paved street" is not
 * a feet picture whatever the tag says — so every tile carries its description
 * and the keyboard works without ever waiting for a pixel.
 *
 * ⚠️ IMAGES ARE RATE-GATED ON PURPOSE. Tiles use /image (full frame), never
 * /thumb: the thumb is a 300x300 centre-crop of a 3:4 portrait and feet sit at
 * exactly the edge it discards — judging from the square means judging from less
 * of the picture than the vision model saw. But /image is a relay-side fetch,
 * the relay refetches at VAULT_STILL_CONCURRENCY=6, and a cold pane asking for
 * 280 at once is the documented route to fd exhaustion, which takes the DB and
 * the send lane down with it. So `useImageSlot` below holds a hard in-flight cap
 * and tiles queue for a turn.
 */

import { useCallback, useEffect, useMemo, useReducer, useRef, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { AlertTriangle, X } from "lucide-react";

import {
  publishFolderToOf,
  savePackTriage,
  usePackCandidates,
  type PackCandidate,
} from "@/hooks/useVaultCache";
import { mirrorFullSrc } from "@/lib/mediaUrl";
import { makeSlotGate } from "@/components/vault/slotGate";
import { initialPackStatus, packStatusReducer } from "@/components/vault/packStatus";
import { IfButton, IfModal, IfSegmented } from "@/components/ui/infloww";
import { useIfConfirm } from "@/hooks/useIfConfirm";
import { errText } from "@/lib/errText";

/** Strictly below the relay's own VAULT_STILL_CONCURRENCY (6) so the pane can
 *  never be the thing that exhausts it, with headroom for the rest of the app. */
const MAX_INFLIGHT_IMAGES = 4;

/** Fan-facing meaning of each rung, so the operator is filing against what the
 *  caption will claim rather than against a folder name. These mirror SPEC 5.2's
 *  authored rung phrases. */
const RUNG_HELP: Record<string, string> = {
  tease: "covered — socks, stockings, heels, boots. Rides free as the preview.",
  nude: "bare feet, body NOT nude. This is the product.",
  "nude-body": "bare feet AND the body nude. Never the first ask.",
};

const RUNG_STYLE: Record<string, string> = {
  tease: "border-info/60 bg-info/15 text-info",
  nude: "border-ok/60 bg-ok/15 text-ok",
  "nude-body": "border-accent/60 bg-accent/15 text-accent",
};

const imageGate = makeSlotGate(MAX_INFLIGHT_IMAGES);

/**
 * A src, once this tile is both on screen and holding a slot — plus the
 * `settle` the <img> MUST call when it loads or errors.
 *
 * ⚠️ Settling is not optional. A tile that renders its image and keeps the slot
 * starves every tile behind it: with a cap of 4 the pane would show four photos
 * and then stop forever. The slot is released on load, on error, and on unmount,
 * and the token is nulled so none of those can double-release and inflate the cap.
 */
function useImageSlot(src: string, visible: boolean): { src: string | null; settle: () => void } {
  const [granted, setGranted] = useState(false);
  const tokenRef = useRef<(() => void) | null>(null);

  const settle = useCallback(() => {
    const token = tokenRef.current;
    if (!token) return;
    tokenRef.current = null;
    imageGate.release(token);
  }, []);

  useEffect(() => {
    if (!visible) return;
    const grant = () => setGranted(true);
    tokenRef.current = grant;
    imageGate.acquire(grant);
    return settle; // unmounting (or re-keying) hands the slot back
  }, [visible, src, settle]);

  return { src: granted ? src : null, settle };
}

function Tile({
  accountId,
  item,
  rung,
  rungs,
  onRule,
}: {
  accountId: string;
  item: PackCandidate;
  rung: string | null;
  rungs: string[];
  onRule: (mediaId: number, rung: string | null) => void;
}) {
  const ref = useRef<HTMLDivElement | null>(null);
  const [visible, setVisible] = useState(false);
  const [loaded, setLoaded] = useState(false);

  useEffect(() => {
    const el = ref.current;
    if (!el || visible) return;
    // rootMargin gives the gate a head start so scrolling doesn't stall on a
    // cold tile, without ever asking for the whole set at once.
    const io = new IntersectionObserver(
      (entries) => entries.forEach((e) => e.isIntersecting && setVisible(true)),
      { rootMargin: "400px" },
    );
    io.observe(el);
    return () => io.disconnect();
  }, [visible]);

  const [failed, setFailed] = useState(false);
  const { src, settle } = useImageSlot(mirrorFullSrc(accountId, item.media_id), visible);
  const isVideo = item.kind !== "photo";

  // Load AND error both settle: either way this tile is done with the network
  // and the next one in the queue must be let through. A still that 404s is
  // ordinary (the cache is built lazily), so it gets a placeholder rather than
  // the browser's broken-image glyph — one cold item should not read as a
  // broken page, and the description is still enough to rule on.
  const onLoad = () => {
    setLoaded(true);
    settle();
  };
  const onError = () => {
    setFailed(true);
    setLoaded(true);
    settle();
  };

  return (
    <div
      ref={ref}
      className={[
        "flex flex-col rounded-md border overflow-hidden bg-bg-subtle",
        rung ? RUNG_STYLE[rung] ?? "border-fg-dim" : "border-border",
      ].join(" ")}
    >
      <div className="relative aspect-[3/4] bg-black/40">
        {src && !failed ? (
          <img
            src={src}
            alt=""
            loading="lazy"
            onLoad={onLoad}
            onError={onError}
            className={[
              "h-full w-full object-contain transition-opacity",
              loaded ? "opacity-100" : "opacity-0",
            ].join(" ")}
          />
        ) : null}
        {(!loaded || failed) && (
          <div className="absolute inset-0 grid place-items-center px-2 text-center text-[12px] text-muted">
            {failed ? "no preview — judge from the text" : visible ? "loading…" : ""}
          </div>
        )}
        {isVideo && (
          <span className="absolute left-1 top-1 rounded bg-black/70 px-1 text-[12px] text-white">
            {item.kind}
          </span>
        )}
        {rung && (
          <span className="absolute right-1 top-1 rounded bg-black/70 px-1 text-[12px] text-white">
            {rung}
          </span>
        )}
      </div>

      {/* Pass A: reject on text alone, no pixels needed. */}
      <p className="line-clamp-3 px-2 py-1 text-[12px] leading-snug text-fg-dim">
        {item.description || "—"}
      </p>

      {/* The reject takes only its glyph's width so the three rung labels get
          the rest — at 8 columns they truncate to nonsense otherwise. */}
      <div className="mt-auto grid grid-cols-[1fr_1fr_1fr_auto] gap-px bg-border p-px text-[12px]">
        {rungs.map((r) => (
          <button
            key={r}
            type="button"
            onClick={() => onRule(item.media_id, rung === r ? null : r)}
            title={RUNG_HELP[r] ?? r}
            className={[
              "whitespace-nowrap px-1 py-1.5 transition-colors",
              rung === r ? "bg-accent text-white font-medium" : "bg-bg hover:bg-bg-hover",
            ].join(" ")}
          >
            {/* "body" not "nude-body": at this width the full name truncates to
                nonsense, and tease / nude / body reads as the ladder it is. The
                title carries the precise meaning. */}
            {r === "nude-body" ? "body" : r}
          </button>
        ))}
        <button
          type="button"
          onClick={() => onRule(item.media_id, null)}
          title="Not this category. Nothing is stored about a rejection."
          aria-label="Reject"
          className={[
            "whitespace-nowrap px-1 py-1.5 transition-colors",
            rung === null ? "bg-bg-hover text-fg-dim" : "bg-bg hover:bg-err/20",
          ].join(" ")}
        >
          <X className="h-3 w-3" aria-hidden />
        </button>
      </div>
    </div>
  );
}

export default function VaultPackPickerModal({
  accountId,
  category = "feet",
  onClose,
}: {
  accountId: string;
  category?: string;
  onClose: () => void;
}) {
  const qc = useQueryClient();
  const { data, isLoading, error } = usePackCandidates(accountId, category);

  /** Unsaved verdicts, media_id -> rung|null. Absent = untouched this session. */
  const [draft, setDraft] = useState<Record<number, string | null>>({});
  const [filter, setFilter] = useState("undecided");
  /** The status bar: `busy` non-empty while any request is in flight, else the last result (packStatus.ts). */
  const [status, dispatchStatus] = useReducer(packStatusReducer, initialPackStatus);
  const { busy } = status;
  const confirm = useIfConfirm();

  const rungs = data?.rungs ?? [];
  // The shelf comes from the QUERY, not from the last save's response, so the
  // rungs and their publish buttons are there the moment the modal opens.
  const shelf = data?.folders ?? [];

  /** The saved rung overlaid with anything unsaved. */
  const effective = useCallback(
    (item: PackCandidate): string | null =>
      item.media_id in draft ? draft[item.media_id] : item.rung,
    [draft],
  );

  const shown = useMemo(() => {
    const all = data?.candidates ?? [];
    if (filter === "all") return all;
    if (filter === "undecided") {
      // Undecided means "never ruled on" — an explicit reject is a decision and
      // drops out, which is what makes the first pass converge.
      return all.filter((c) => effective(c) === null && !(c.media_id in draft));
    }
    return all.filter((c) => effective(c) === filter);
  }, [data, filter, draft, effective]);

  const tally = useMemo(() => {
    const out: Record<string, number> = {};
    for (const c of data?.candidates ?? []) {
      const r = effective(c);
      if (r) out[r] = (out[r] ?? 0) + 1;
    }
    return out;
  }, [data, effective]);

  const dirty = Object.keys(draft).length;
  /** Rungs that exist and have something in them — the only ones publishable. */
  const stocked = shelf.filter((f) => f.folder_id && f.count);
  const allPublished = stocked.length > 0 && stocked.every((f) => f.of_list_id);

  function rule(mediaId: number, rung: string | null) {
    setDraft((d) => ({ ...d, [mediaId]: rung }));
  }

  async function save() {
    if (!dirty) return;
    dispatchStatus({ type: "start", busy: "saving…" });
    try {
      const verdicts = Object.entries(draft).map(([media_id, rung]) => ({
        media_id: Number(media_id),
        rung,
      }));
      const res = await savePackTriage(accountId, category, verdicts);
      setDraft({});
      await qc.invalidateQueries({ queryKey: ["vault-pack-candidates", accountId, category] });
      await qc.invalidateQueries({ queryKey: ["vault-internal-folders", accountId] });
      dispatchStatus({ type: "ok", note: `saved ${res.saved} (${res.rejected} rejected)` });
    } catch (e) {
      // The verdicts stay in the draft: Save again retries them.
      dispatchStatus({ type: "fail", note: `save failed: ${errText(e)}` });
    }
  }

  function describe(res: Awaited<ReturnType<typeof publishFolderToOf>>): string {
    return (
      `${res.name} → OF list ${res.of_list_id}: pushed ${res.pushed}` +
      (res.stale_on_of.length
        ? ` · ${res.stale_on_of.length} still on OF that this rung no longer holds`
        : " · exact copy")
    );
  }

  async function publish(folderId: number, name: string) {
    dispatchStatus({ type: "start", busy: `publishing ${name} to OF…` });
    try {
      const res = await publishFolderToOf(accountId, folderId);
      await qc.invalidateQueries({ queryKey: ["vault-pack-candidates", accountId, category] });
      dispatchStatus({ type: "ok", note: describe(res), stale: res.stale_on_of.length });
    } catch (e) {
      dispatchStatus({ type: "fail", note: `publish failed: ${errText(e)}` });
    }
  }

  /** Every stocked rung, one after another.
   *
   * Sequential on purpose: each rung is 1 create + 1 add + a read-back against
   * her real OnlyFans account, and firing three at once is how you get rate
   * limited mid-way and have to reason about which rungs landed. A rung that
   * fails stops the run and says which one — the ones before it are already
   * real on OF and a re-run tops them up rather than duplicating.
   */
  async function publishAll() {
    if (!stocked.length) return;
    const done: string[] = [];
    let staleN = 0;
    const step = (name: string) => `publishing ${name} to OF… (${done.length + 1}/${stocked.length})`;
    try {
      for (const f of stocked) {
        dispatchStatus({ type: "start", busy: step(f.name) });
        const res = await publishFolderToOf(accountId, f.folder_id!);
        staleN += res.stale_on_of.length;
        done.push(describe(res));
      }
      dispatchStatus({ type: "ok", note: done.join(" · "), stale: staleN });
    } catch (e) {
      dispatchStatus({
        type: "fail",
        stale: staleN,
        note:
          `${done.length} of ${stocked.length} published, then FAILED: ` +
          `${errText(e)}` +
          (done.length ? ` — landed: ${done.join(" · ")}` : ""),
      });
    } finally {
      await qc.invalidateQueries({ queryKey: ["vault-pack-candidates", accountId, category] });
    }
  }

  const publishTitle = dirty
    ? "Save your verdicts first — publish ships the saved shelf"
    : !stocked.length
      ? "Nothing filed yet"
      : `Create ${stocked.length} real folder(s) in the OnlyFans vault`;

  return (
    <IfModal
      title={`Pack picker — ${category}`}
      // A work surface, not a form: an 8-column tile grid wants the screen.
      width={1280}
      className="h-[calc(100vh-32px)]"
      onClose={onClose}
      // Escape and Done would drop unsaved verdicts, so both are off while dirty; the × still closes (a discard).
      keyboard={!dirty}
      footer={
        <>
          <span className="mr-auto min-w-0 flex-1 basis-60 text-[12px] text-muted">
            Nothing is written until Save, and nothing reaches OnlyFans until Publish.
          </span>
          {/* The only control here that leaves the app. Amber, not green:
              Save writes a row, THIS writes to her real OnlyFans vault.
              Disabled while there are unsaved verdicts — publish reads the
              SAVED shelf, so publishing dirty would silently ship the old
              membership and look like it had shipped the new. */}
          <IfButton
            onClick={async () => {
              const yes = await confirm.ask(
                `Create ${stocked.length} REAL folder(s) in the OnlyFans vault?`,
                <>
                  <ul>
                    {stocked.map((f) => <li key={f.name}>{f.name} — {f.count} items</li>)}
                  </ul>
                  <p className="mt-3">This is visible in the OF app. Reversible, but a rebuild gets a new list id.</p>
                </>,
                "Publish",
              );
              if (yes) publishAll();
            }}
            disabled={!stocked.length || !!dirty || !!busy}
            title={publishTitle}
            className="border-warn/60 text-warn hover:border-warn hover:text-warn"
          >
            {allPublished ? "Re-publish to OF" : `Publish to OF${stocked.length ? ` (${stocked.length})` : ""}`}
          </IfButton>
          <IfButton onClick={onClose} disabled={!!dirty} title={dirty ? "Save or discard first" : undefined}>
            Done
          </IfButton>
          <IfButton variant="primary" onClick={save} disabled={!dirty || !!busy}>
            {dirty ? `Save ${dirty}` : "Saved"}
          </IfButton>
        </>
      }
    >
      <div className="flex flex-wrap items-center gap-3">
        {/* Live tally — INCLUDES unsaved draft, which is why it is labelled.
            The shelf below shows the SAVED counts, and the two legitimately
            disagree until Save. */}
        <span className="text-[12px] text-muted">
          {data ? `${data.candidates.length} candidates · decided` : "…"}
          {rungs.map((r) => ` ${r} ${tally[r] ?? 0}`).join(" ·")}
        </span>
        <IfSegmented
          aria-label="Show"
          className="ml-auto max-w-full overflow-x-auto"
          value={filter}
          onChange={setFilter}
          options={["undecided", ...rungs, "all"].map((f) => ({ value: f, label: f }))}
        />
      </div>

      {/* The shelf, always — publishing must not be reachable only in the
          moment after a save. */}
      <div className="mt-3 flex flex-wrap items-center gap-x-4 gap-y-1 rounded-md bg-bg-elev-1 px-3 py-2 text-[12px]">
        {shelf.map((f) => (
          <span key={f.name} className="flex items-center gap-1">
            <b>{f.name}</b> {f.count} saved
            {f.of_list_id ? <span className="text-muted">· on OF</span> : null}
            <IfButton
              variant="link"
              onClick={() => f.folder_id && publish(f.folder_id, f.name)}
              disabled={!f.folder_id || !f.count || !!busy}
              title="Create this as a REAL folder in the OnlyFans vault"
              className="h-auto px-1 text-[12px]"
            >
              {f.of_list_id ? "re-publish" : "publish to OF"}
            </IfButton>
          </span>
        ))}
        <span className={`ml-auto flex items-center gap-1 ${!busy && status.failed ? "text-err" : "text-muted"}`}>
          {!busy && status.stale > 0 && (
            <AlertTriangle className="h-3.5 w-3.5 text-warn" aria-hidden />
          )}
          {busy || status.note}
        </span>
      </div>

      <div className="mt-3">
        {isLoading && <p className="p-6 text-center text-muted">loading candidates…</p>}
        {error && (
          <p className="p-6 text-center text-err">
            {error instanceof Error ? error.message : "failed to load"}
          </p>
        )}
        {data && shown.length === 0 && (
          <p className="p-6 text-center text-muted">
            {filter === "undecided"
              ? "Nothing left undecided. Switch to a rung to review what you filed."
              : "Nothing here."}
          </p>
        )}
        <div className="grid grid-cols-2 gap-2 sm:grid-cols-4 lg:grid-cols-6 xl:grid-cols-8">
          {shown.map((c) => (
            <Tile
              key={c.media_id}
              accountId={accountId}
              item={c}
              rung={effective(c)}
              rungs={rungs}
              onRule={rule}
            />
          ))}
        </div>
      </div>
      {confirm.modal}
    </IfModal>
  );
}
