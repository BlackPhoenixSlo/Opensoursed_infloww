"use client";

/**
 * PostComposer — modal for creating a public feed post via
 * POST /api/of/v2/posts. Mirrors OF's own "Create post" surface in the
 * minimum-viable shape:
 *   • text body
 *   • media from vault (reuses the chat VaultPicker — same picker, no
 *     fan-scope so the per-fan badges/MRU just stay neutral)
 *   • price (0 = free; >0 = PPV)
 *
 * Deliberately deferred to v2:
 *   • Polls — no captured curl yet; would be guesswork.
 */

import { useCallback, useReducer, useRef, useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";

import { usePlatformAccounts } from "@/hooks/useAccounts";
import { useAllModelsInclude } from "@/hooks/useAllModelsInclude";
import { usePaidPage, PAID_PAGE_NOTE } from "@/hooks/usePaidPage";
import { relay } from "@/lib/relay";
import { VaultPicker } from "@/components/chat/VaultPicker";
import { EmojiPickerButton, EmojiQuickRow, insertAtCursor } from "@/components/chat/EmojiBar";
import { TemplatePicker, type PickedTemplate } from "@/components/chat/TemplatePicker";
import { TagCreatorsPicker, TaggedCreatorChips } from "@/components/chat/TagCreatorsPicker";
import { recordSchedule } from "@/lib/scheduleHistory";

import { sanitizePriceInput } from "@/lib/priceInput";

import { AccountPicker } from "./AccountPicker";
import { MediaTray } from "./MediaTray";
import { ScheduleField } from "./ScheduleField";
import { FanOutResults, FanOutStatus } from "./FanOutResults";
import { fanOutLocked, includedTargets, runFanOut } from "./fanOut";
import {
  buildPostBody, initPostForm, postComposerReducer, postFieldAction, postPrice, sendAccount, validatePost,
  type PostField, type PostForm,
} from "./postComposerReducer";
import { fmtPrice } from "@/lib/format";

interface CreatePostResp {
  id?: number;
  // OF returns the full post shape; we only need a success signal so the
  // rest stays loose.
  [k: string]: unknown;
}

export function PostComposer({
  open,
  onClose,
  onSuccess,
}: {
  open: boolean;
  onClose: () => void;
  /** Fired whenever a post went live — a single create, a full fan-out (before
   *  the modal closes) or a partial one's posted models (the modal stays open
   *  for the retry) — so a caller surface, e.g. the feed tab, can refetch its
   *  own list. */
  onSuccess?: () => void;
}) {
  const qc = useQueryClient();
  const activeAccounts = usePlatformAccounts();
  // The composers' shared include set (useAllModelsInclude) — a model
  // un-checked in any composer's chip strip is omitted from a broadcast here.
  const { isIncluded, toggle: toggleAllModelsInclude } = useAllModelsInclude();
  // The whole form (postComposerReducer).
  const [form, dispatch] = useReducer(postComposerReducer, null, initPostForm);
  const { allModels, text, attached, price, previewCount, schedule, progress, results, taggedCreators } = form;
  // The account a one-account post goes to; null while all-models is on
  // (postComposerReducer `sendAccount`).
  const accountId = sendAccount(form);
  // A round in flight, or a model took this post: the content is locked (compose/fanOut).
  const locked = fanOutLocked(form);
  const set = <K extends PostField>(k: K) => (v: PostForm[K]) => dispatch(postFieldAction(k, v));
  // Stable: AccountPicker's auto-seed effect depends on it.
  const setAccountId = useCallback((id: string) => dispatch({ type: "setAccount", id }), []);
  const [pickerOpen, setPickerOpen] = useState(false);
  const textareaRef = useRef<HTMLTextAreaElement | null>(null);
  // A subscription page has no paid-post lane on OF, so the price field is not
  // an option there and its price reads as 0 (postComposerReducer `postPrice`)
  // — a typed or template price can't block or ride into the post. The relay
  // refuses a priced post for one anyway (409).
  const { isPaidPage } = usePaidPage(accountId);

  // Honour the shared include set: models the user unchecked in a
  // composer's chip strip are dropped from the broadcast fan-out; a model
  // that already took this post (a partial fan-out's success) is not re-posted.
  const { included: broadcastAccounts, targets } = includedTargets(activeAccounts, isIncluded, results);

  // The one validity check — the Post button, its reason line and the
  // mutation all read it.
  const invalid = validatePost(form, { broadcastCount: targets.length, paidPage: isPaidPage });

  // The created post is visible: the wall-media query backs the vault
  // picker's blue ring (nuking it flips freshly-posted media on next open),
  // and the caller (the feed tab) refetches its list.
  function posted() {
    qc.invalidateQueries({ queryKey: ["wall-media"] });
    onSuccess?.();
  }

  // Resolves to whether the modal may close (every model took it); only a
  // refused form or a one-account failure throws (the footer shows
  // `create.error`).
  const create = useMutation({
    mutationFn: async (): Promise<boolean> => {
      if (invalid) throw new Error(invalid);
      const body = buildPostBody(form, isPaidPage);
      const postTo = async (aid: string) => {
        const resp = await relay.post<CreatePostResp>("/api/of/v2/posts", body, { accountId: aid });
        if (schedule) recordSchedule(aid, schedule);
        return resp;
      };
      if (!allModels) {
        await postTo(accountId!);
        posted();
        return true;
      }
      const round = await runFanOut(targets, postTo, (p) => dispatch({ type: "progress", ...p }));
      dispatch({ type: "results", v: round });
      // A partial round: the models that took it show it now; the composer
      // stays open, locked, so the retry posts the same post to the failed ones.
      if (round.some((r) => r.ok)) posted();
      return round.every((r) => r.ok);
    },
    onSuccess: (mayClose) => {
      if (mayClose) onClose();
    },
  });

  // Mounted only while open (MyFeedTab), so closing drops the form.
  function close() {
    if (!create.isPending) onClose();
  }

  function onEmoji(em: string) {
    const ta = textareaRef.current;
    if (!ta) {
      dispatch({ type: "appendText", v: em });
      return;
    }
    insertAtCursor(ta, text, em, set("text"));
  }

  function onPickTemplate(t: PickedTemplate) {
    // Snapshot semantics (lib/composeDraft applyTemplate): text, media,
    // preview count and price are replaced wholesale.
    dispatch({ type: "pickTemplate", t });
    setTimeout(() => textareaRef.current?.focus(), 0);
  }

  if (!open) return null;

  const priceNum = postPrice(form, isPaidPage);
  const isPPV = priceNum > 0;
  const isScheduled = !!schedule;

  return (
    <div
      className="fixed inset-0 z-50 bg-black/50 grid place-items-center p-0 sm:p-4"
      onClick={close}
    >
      {/* min-h-0 / min-w-0: a grid item's auto minimum is its content, so on a
       *  phone (h-full, no max-h) the panel grew past the screen and the body
       *  never scrolled to the footer. Same fix as MassMessageComposer. */}
      <div
        onClick={(e) => e.stopPropagation()}
        className="min-h-0 min-w-0 w-full h-full sm:h-auto max-w-none sm:max-w-[560px] max-h-none sm:max-h-[90vh] flex flex-col bg-panel border-0 sm:border border-border rounded-none sm:rounded-xl shadow-2xl"
      >
        <header className="px-4 py-3 border-b border-border flex items-center justify-between">
          <h2 className="text-sm font-semibold">New post</h2>
          <button
            type="button"
            onClick={close}
            className="text-fg-dim hover:text-fg text-lg leading-none w-11 h-11 -mr-2 -my-2 grid place-items-center shrink-0 md:w-auto md:h-auto md:mr-0 md:my-0 md:inline"
            title="Close"
          >×</button>
        </header>

        <div className="flex-1 overflow-y-auto p-4 space-y-3">
          <label className="flex items-center gap-2 text-xs cursor-pointer select-none">
            <input
              type="checkbox"
              checked={allModels}
              disabled={locked}
              onChange={(e) => dispatch({ type: "setAllModels", on: e.target.checked })}
            />
            <span className="font-medium">Post from ALL models</span>
            <span className="text-fg-dim">
              ({broadcastAccounts.length}/{activeAccounts.length} included)
            </span>
          </label>

          {allModels ? (
            <>
              <div className="text-[11px] text-fg-dim border border-dashed border-border rounded-md py-2 px-3">
                All-models posts are text-only for now — uploads from
                computer are temporarily disabled.
              </div>
              {/* Creator picker — click a chip to drop / re-add a model
               *  from the broadcast (and from the all-models aggregate
               *  everywhere else). Mirrors MassMessageComposer. */}
              <div className="flex flex-wrap gap-1.5">
                {activeAccounts.map((a) => {
                  const inc = isIncluded(a.id);
                  return (
                    <button
                      key={a.id}
                      type="button"
                      onClick={() => toggleAllModelsInclude(a.id)}
                      title={inc ? "Click to exclude from broadcast" : "Click to include"}
                      className={
                        "flex items-center gap-1.5 px-2 py-1 rounded-full text-[11px] border transition-colors " +
                        (inc
                          ? "bg-bg-elev-1 border-border text-fg"
                          : "bg-bg border-border/60 text-fg-dim line-through opacity-60")
                      }
                    >
                      <span
                        className="w-2 h-2 rounded-full shrink-0"
                        style={{ background: a.color || "#666" }}
                      />
                      <span>{a.nickname || a.id}</span>
                    </button>
                  );
                })}
                {activeAccounts.length === 0 && (
                  <span className="text-[11px] text-fg-dim">No active sessions.</span>
                )}
              </div>
            </>
          ) : (
            <AccountPicker value={accountId} onChange={setAccountId} />
          )}

          {/* The content — locked (disabled) once a model took the post. */}
          <fieldset disabled={locked} className="min-w-0 space-y-3 disabled:opacity-60">
          <div className="space-y-1.5">
            <textarea
              ref={textareaRef}
              value={text}
              onChange={(e) => set("text")(e.target.value)}
              placeholder="What's on your feed today?"
              rows={5}
              className="w-full bg-bg border border-border rounded-md px-3 py-2 text-base md:text-sm placeholder:text-muted focus:outline-none focus:border-accent resize-y"
            />
            <div className="flex items-center gap-1.5 flex-wrap">
              <EmojiQuickRow onInsert={onEmoji} />
              <EmojiPickerButton align="left" onInsert={onEmoji} />
              <TemplatePicker
                accountId={accountId}
                onPick={onPickTemplate}
                hideImageTemplates
              />
              {!allModels && (
                <TagCreatorsPicker
                  accountId={accountId}
                  selected={taggedCreators}
                  onChange={set("taggedCreators")}
                />
              )}
            </div>
            {!allModels && taggedCreators.length > 0 && (
              <TaggedCreatorChips selected={taggedCreators} onChange={set("taggedCreators")} />
            )}
          </div>

          {!allModels && (
            <MediaTray
              accountId={accountId}
              attached={attached}
              onChange={set("attached")}
              onOpenVaultPicker={() => setPickerOpen(true)}
              price={priceNum}
              previewCount={previewCount}
              onPreviewCountChange={set("previewCount")}
            />
          )}

          {/* All-models posts are text-only: no price (postComposerReducer). */}
          {!allModels && (
            <>
              <div className="flex items-center gap-2">
                <label className="text-xs text-fg-dim shrink-0">Price (USD):</label>
                <input
                  type="text"
                  inputMode="decimal"
                  value={isPaidPage ? "" : price}
                  disabled={isPaidPage}
                  onChange={(e) => set("price")(sanitizePriceInput(e.target.value))}
                  placeholder={isPaidPage ? "free only" : "0 (free)"}
                  className="flex-1 bg-bg border border-border rounded-md px-2 py-1.5 text-base md:text-xs focus:outline-none focus:border-accent disabled:opacity-40"
                />
                <span className={isPPV ? "text-warn text-[11px]" : "text-fg-dim text-[11px]"}>
                  {isPPV ? `🔒 PPV ${fmtPrice(Math.round(priceNum * 100))}` : "free"}
                </span>
              </div>
              {isPaidPage && (
                <div className="text-[11px] text-fg-dim">{PAID_PAGE_NOTE}</div>
              )}
            </>
          )}

          <ScheduleField
            scope={allModels ? "all-models" : accountId}
            value={schedule}
            onChange={set("schedule")}
          />
          </fieldset>

          {results && (
            <FanOutResults
              results={results} noun="post" locked={locked} busy={create.isPending}
              onStartOver={() => dispatch({ type: "discardResults" })}
            />
          )}
        </div>

        <footer className="px-4 py-3 pb-[max(0.75rem,env(safe-area-inset-bottom))] sm:pb-3 border-t border-border flex items-center justify-end gap-2">
          <FanOutStatus
            progress={progress} verb="Posting" invalid={invalid} error={create.error?.message ?? null} results={results}
          />
          <button
            type="button"
            onClick={close}
            disabled={create.isPending}
            className="text-xs px-3 py-1.5 rounded border border-border hover:border-border-light text-fg-dim hover:text-fg disabled:opacity-50"
          >
            Cancel
          </button>
          <button
            type="button"
            onClick={() => {
              if (allModels && !confirm(
                `Post from ${targets.length} model${targets.length === 1 ? "" : "s"}?`,
              )) return;
              create.mutate();
            }}
            disabled={create.isPending || invalid !== null}
            title={invalid ?? undefined}
            className="text-xs px-4 py-1.5 rounded bg-accent text-white font-medium hover:bg-accent-hover disabled:opacity-50"
          >
            {create.isPending
              ? (isScheduled ? "Scheduling…" : "Posting…")
              : (isScheduled ? "Schedule post" : "Post")}
          </button>
        </footer>
      </div>

      <VaultPicker
        open={pickerOpen}
        onClose={() => setPickerOpen(false)}
        accountId={accountId}
        fanId={null}
        initialSelectedIds={attached.map((m) => m.id)}
        onConfirm={(picked) => {
          set("attached")(picked);
          setPickerOpen(false);
        }}
      />
    </div>
  );
}
