"use client";


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
import {
  buildFilePayload,
  buildPayload,
  canFileTicked,
  canPress,
  canSubmit,
  focusedId,
  initialPickerState,
  isTicked,
  keyAction,
  pickerReducer,
  possibleOnly,
  rungTally,
  shownRung,
  tickable,
  tickedVerdicts,
  visibleCandidates,
} from "@/components/vault/packPickerState";
import { IfButton, IfModal, IfSegmented } from "@/components/ui/infloww";
import { useIfConfirm } from "@/hooks/useIfConfirm";
import { errText } from "@/lib/errText";
import { cn } from "@/lib/utils";

// Below the relay's VAULT_STILL_CONCURRENCY (12): a cold pane fetching every /image at once exhausts fds and takes the DB and send lane down.
const MAX_INFLIGHT_IMAGES = 4;

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

function useImageSlot(src: string, visible: boolean): { src: string | null; settle: () => void } {
  const [granted, setGranted] = useState(false);
  const tokenRef = useRef<(() => void) | null>(null);

  // settle must run on load, error and unmount, or a held slot starves every tile behind it; the token is nulled so it never double-releases.
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
    return settle;
  }, [visible, src, settle]);

  return { src: granted ? src : null, settle };
}

function Tile({
  accountId,
  item,
  rung,
  suggested,
  focused,
  rungs,
  ticked,
  pressable,
  onRule,
  onFocus,
  onTick,
}: {
  accountId: string;
  item: PackCandidate;
  rung: string | null;
  suggested: boolean;
  focused: boolean;
  rungs: string[];
  ticked: boolean | null;
  pressable: (rung: string) => boolean;
  onRule: (mediaId: number, rung: string | null) => void;
  onFocus: (mediaId: number) => void;
  onTick: (mediaId: number, on: boolean) => void;
}) {
  const ref = useRef<HTMLDivElement | null>(null);
  const [visible, setVisible] = useState(false);
  const [loaded, setLoaded] = useState(false);

  useEffect(() => {
    const el = ref.current;
    if (!el || visible) return;
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
      data-pack-tile={item.media_id}
      tabIndex={focused ? 0 : -1}
      aria-current={focused || undefined}
      aria-label={`media ${item.media_id}${rung ? `, ${suggested ? "suggested " : ""}${rung}` : ""}`}
      onFocus={() => onFocus(item.media_id)}
      className={cn(
        "flex flex-col rounded-md border overflow-hidden bg-bg-subtle outline-none",
        rung ? RUNG_STYLE[rung] ?? "border-fg-dim" : "border-border",
        suggested && "border-dashed",
        focused && "ring-2 ring-accent ring-offset-2 ring-offset-bg",
      )}
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
        <span className="absolute left-1 top-1 flex gap-1 text-[12px] text-white">
          {isVideo && <span className="rounded bg-black/70 px-1">{item.kind}</span>}
          {item.jev && (
            <span className="rounded bg-black/70 px-1" title="Ranked and priced by Jev v8">
              Jev
            </span>
          )}
          {item.possible && (
            <span
              data-pack-possible={item.media_id}
              className="rounded bg-warn/80 px-1"
              title={
                ticked
                  ? "Possible: Jev is less sure feet are the subject. Ticked by you."
                  : "Possible: Jev sees feet but is less sure they are the subject. Not ticked; check it first."
              }
            >
              possible
            </span>
          )}
          {item.unsafe_on_free && (
            <span
              className="flex items-center gap-0.5 rounded bg-err/80 px-1"
              title="On the free rung but Jev says the body may be on show: publish skips it. Unfile it."
            >
              <AlertTriangle className="h-3 w-3" aria-hidden />
              not free-safe
            </span>
          )}
          {!!item.tier && (
            <span className="rounded bg-black/70 px-1" title="Body price tier from Jev">
              ${item.tier}
            </span>
          )}
        </span>
        {rung && (
          <span className="absolute right-1 top-1 rounded bg-black/70 px-1 text-[12px] text-white">
            {suggested ? `${rung}?` : rung}
          </span>
        )}
        {ticked !== null && rung && (
          <label
            className="absolute bottom-1 left-1 flex min-h-11 min-w-11 cursor-pointer items-center justify-center rounded bg-black/70 sm:min-h-0 sm:min-w-0 sm:px-1 sm:py-0.5"
            title={
              !ticked
                ? `Tick to file it on ${rung}`
                : item.possible
                  ? `Ticked by you: "File preselected" puts it on ${rung}`
                  : `Preselected: "File preselected" puts it on ${rung}`
            }
          >
            <input
              type="checkbox"
              data-pack-tick={item.media_id}
              aria-label={item.possible ? `possible: tick to file on ${rung}` : `preselect on ${rung}`}
              className="accent-accent h-4 w-4"
              checked={ticked}
              onChange={(e) => onTick(item.media_id, e.target.checked)}
            />
          </label>
        )}
      </div>

      <p className="line-clamp-3 px-2 py-1 text-[12px] leading-snug text-fg-dim">
        {item.description || "—"}
      </p>

      <div className="mt-auto grid grid-cols-[1fr_1fr_1fr_auto] gap-px bg-border p-px text-[13px] sm:text-[12px]">
        {rungs.map((r, i) => (
          <button
            key={r}
            type="button"
            onClick={() => onRule(item.media_id, rung === r && !suggested ? null : r)}
            disabled={!pressable(r)}
            title={
              pressable(r)
                ? `${i + 1}: ${RUNG_HELP[r] ?? r}`
                : item.kind !== "photo"
                  ? `${i + 1}: photos only: a clip never goes in this pack`
                  : `${i + 1}: Jev says the body may be on show: never the free preview`
            }
            className={cn(
              "min-h-11 whitespace-nowrap px-1 py-1.5 transition-colors sm:min-h-0 disabled:cursor-not-allowed disabled:opacity-40",
              rung === r && !suggested && "bg-accent text-white font-medium",
              rung === r && suggested && "bg-accent/25 text-fg font-medium",
              rung !== r && "bg-bg hover:bg-bg-hover",
            )}
          >
            {r === "nude-body" ? "body" : r}
          </button>
        ))}
        <button
          type="button"
          onClick={() => onRule(item.media_id, null)}
          title="x: not this category. Nothing is stored about a rejection."
          aria-label="Reject"
          className={cn(
            "min-h-11 min-w-11 grid place-items-center whitespace-nowrap px-1 py-1.5 transition-colors sm:min-h-0 sm:min-w-0",
            rung === null ? "bg-bg-hover text-fg-dim" : "bg-bg hover:bg-err/20",
          )}
        >
          <X className="h-4 w-4 sm:h-3 sm:w-3" aria-hidden />
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

  const [pick, dispatch] = useReducer(pickerReducer, initialPickerState);
  const { draft, filter } = pick;
  const [status, dispatchStatus] = useReducer(packStatusReducer, initialPackStatus);
  const { busy } = status;
  const confirm = useIfConfirm();
  const gridRef = useRef<HTMLDivElement | null>(null);
  const scrollToFocus = useRef(false);

  const rungs = useMemo(() => data?.rungs ?? [], [data]);
  const shelf = data?.folders ?? [];

  const shown = useMemo(() => visibleCandidates(data?.candidates ?? [], pick), [data, pick]);
  const order = useMemo(() => shown.map((c) => c.media_id), [shown]);
  const focusId = focusedId(pick, order);
  const tally = useMemo(() => rungTally(data?.candidates ?? [], draft), [data, draft]);

  const dirty = Object.keys(draft).length;
  const candidates = useMemo(() => data?.candidates ?? [], [data]);
  const tickedN = useMemo(() => tickedVerdicts(candidates, pick, rungs).length, [candidates, pick, rungs]);
  const anyPreselect = useMemo(() => candidates.some((c) => c.preselect), [candidates]);
  const anyPossible = useMemo(() => candidates.some((c) => c.possible), [candidates]);
  const onlyPossible = useMemo(() => possibleOnly(candidates), [candidates]);
  const stocked = shelf.filter((f) => f.folder_id && f.count);
  const allPublished = stocked.length > 0 && stocked.every((f) => f.of_list_id);

  function rule(mediaId: number, rung: string | null) {
    dispatch({ type: "rule", mediaId, rung, order });
  }

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.defaultPrevented || e.metaKey || e.ctrlKey || e.altKey) return;
      const grid = gridRef.current;
      const box = grid?.closest('[role="dialog"]');
      const at = e.target instanceof HTMLElement ? e.target : null;
      if (!grid || !box || !at || at.closest('[role="dialog"]') !== box) return;
      if (at.closest('input,textarea,select,[contenteditable="true"],[role="radiogroup"]')) return;
      if ((e.key === "Enter" || e.key === " ") && at.closest("button")) return;
      const cols = getComputedStyle(grid).gridTemplateColumns.split(" ").filter(Boolean).length;
      const focused = shown.find((c) => c.media_id === focusId) ?? null;
      const act = keyAction(e.key, { focused, rungs, order, cols });
      if (!act) return;
      e.preventDefault();
      scrollToFocus.current = true;
      dispatch(act);
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [shown, order, focusId, rungs]);

  useEffect(() => {
    if (pick.focus === null) return;
    const el = gridRef.current?.querySelector<HTMLElement>(`[data-pack-tile="${pick.focus}"]`);
    if (!el) return;
    if (document.activeElement !== el) el.focus({ preventScroll: true });
    if (scrollToFocus.current) el.scrollIntoView?.({ block: "nearest" });
    scrollToFocus.current = false;
  }, [pick.focus, shown]);

  async function save() {
    if (!canSubmit(pick, !!busy)) return;
    dispatchStatus({ type: "start", busy: "saving…" });
    try {
      const verdicts = buildPayload(pick);
      const res = await savePackTriage(accountId, category, verdicts);
      await qc.invalidateQueries({ queryKey: ["vault-pack-candidates", accountId, category] });
      dispatch({ type: "saved", verdicts });
      await qc.invalidateQueries({ queryKey: ["vault-internal-folders", accountId] });
      dispatchStatus({ type: "ok", note: `saved ${res.saved} (${res.rejected} rejected)` });
    } catch (e) {
      dispatchStatus({ type: "fail", note: `save failed: ${errText(e)}` });
    }
  }

  async function fileTicked() {
    if (!canFileTicked(candidates, pick, rungs, !!busy)) return;
    dispatchStatus({ type: "start", busy: "filing…" });
    try {
      const verdicts = buildFilePayload(candidates, pick, rungs);
      const res = await savePackTriage(accountId, category, verdicts);
      await qc.invalidateQueries({ queryKey: ["vault-pack-candidates", accountId, category] });
      dispatch({ type: "saved", verdicts });
      await qc.invalidateQueries({ queryKey: ["vault-internal-folders", accountId] });
      dispatchStatus({ type: "ok", note: `filed ${res.saved - res.rejected} (${res.rejected} rejected)` });
    } catch (e) {
      dispatchStatus({ type: "fail", note: `file failed: ${errText(e)}` });
    }
  }

  function describe(res: Awaited<ReturnType<typeof publishFolderToOf>>): string {
    const skipped = res.skipped_unsafe?.length ?? 0;
    const clips = res.skipped_videos?.length ?? 0;
    return (
      `${res.name} → OF list ${res.of_list_id}: pushed ${res.pushed}` +
      (skipped ? ` · ${skipped} skipped (Jev: not free-safe; unfile them)` : "") +
      (clips ? ` · ${clips} skipped (videos: a pack is photos only; unfile them)` : "") +
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
      width={1280}
      className="h-[calc(100vh-32px)]"
      onClose={onClose}
      keyboard={!dirty}
      footer={
        <>
          <span className="mr-auto min-w-0 flex-1 basis-60 text-[12px] text-muted">
            Nothing is written until Save, and nothing reaches OnlyFans until Publish.
          </span>
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
          {(anyPreselect || anyPossible) && (
            <IfButton
              variant="primary"
              onClick={fileTicked}
              disabled={!canFileTicked(candidates, pick, rungs, !!busy)}
              title="Files every ticked tile on its suggested rung, plus any unsaved verdict"
            >
              {`File ${tickedN} preselected`}
            </IfButton>
          )}
          <IfButton variant="primary" onClick={save} disabled={!canSubmit(pick, !!busy)}>
            {dirty ? `Save ${dirty}` : "Saved"}
          </IfButton>
        </>
      }
    >
      <div className="flex flex-wrap items-center gap-3">
        <span className="text-[12px] text-muted">
          {data ? `${data.candidates.length} candidates · decided` : "…"}
          {rungs.map((r) => ` ${r} ${tally[r] ?? 0}`).join(" ·")}
        </span>
        <IfSegmented
          aria-label="Show"
          className="ml-auto max-w-full overflow-x-auto"
          value={filter}
          onChange={(value) => dispatch({ type: "filter", value })}
          options={["undecided", ...rungs, "all"].map((f) => ({ value: f, label: f }))}
        />
      </div>
      <p className="mt-2 hidden text-[12px] text-muted sm:block">
        Keys: {rungs.map((r, i) => `${i + 1} ${r === "nude-body" ? "body" : r}`).join(" · ")} · x reject · Enter
        confirm the suggestion · ←→ / j k move
        {anyPreselect && " · preselected tiles (Jev sure it is feet) arrive ticked and go on their rung with File preselected"}
        {anyPossible && " · \"possible\" tiles (Jev less sure) come last, never preselected: check each, tick or file it"}
      </p>
      {onlyPossible && filter === "undecided" && (
        <p data-testid="pack-fallback-notice" className="mt-2 text-[12px] text-warn">
          No unfiled confident feet photos — showing Jev&apos;s likelier guesses (score ≥ .3), unticked: check each.
          Rejects are not remembered.
        </p>
      )}

      <div className="mt-3 flex flex-wrap items-center gap-x-4 gap-y-1 rounded-md bg-bg-elev-1 px-3 py-2 text-[12px]">
        {shelf.map((f) => (
          <span key={f.name} className="flex items-center gap-1">
            <b>{f.name}</b> {f.count} saved
            {f.of_list_id ? <span className="text-muted">· on OF</span> : null}
            <IfButton
              variant="link"
              onClick={() => f.folder_id && publish(f.folder_id, f.name)}
              disabled={!f.folder_id || !f.count || !!dirty || !!busy}
              title={dirty ? publishTitle : "Create this as a REAL folder in the OnlyFans vault"}
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
            {data.candidates.length === 0
              ? `No ${category} photos from Jev yet: it checks new photos automatically.`
              : filter === "undecided"
                ? "Nothing left undecided. Switch to a rung to review what you filed."
                : "Nothing here."}
          </p>
        )}
        <div ref={gridRef} className="grid grid-cols-2 gap-2 sm:grid-cols-4 lg:grid-cols-6 xl:grid-cols-8">
          {shown.map((c) => {
            const s = shownRung(c, draft);
            return (
              <Tile
                key={c.media_id}
                accountId={accountId}
                item={c}
                rung={s.rung}
                suggested={s.suggested}
                focused={c.media_id === focusId}
                rungs={rungs}
                ticked={tickable(c, pick, rungs) ? isTicked(c, pick, rungs) : null}
                pressable={(r) => canPress(c, r, rungs, draft)}
                onRule={rule}
                onFocus={(mediaId) => dispatch({ type: "focus", mediaId })}
                onTick={(mediaId, on) => dispatch({ type: "tick", mediaId, on })}
              />
            );
          })}
        </div>
      </div>
      {confirm.modal}
    </IfModal>
  );
}
