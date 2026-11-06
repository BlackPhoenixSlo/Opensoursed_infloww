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

import { useCallback, useId, useReducer, useRef, useState } from "react";
import { Lock } from "lucide-react";
import { useMutation, useQueryClient } from "@tanstack/react-query";

import { usePlatformAccounts } from "@/hooks/useAccounts";
import { useAllModelsInclude } from "@/hooks/useAllModelsInclude";
import { usePaidPage, PAID_PAGE_NOTE } from "@/hooks/usePaidPage";
import { relay } from "@/lib/relay";
import { VaultPicker } from "@/components/chat/VaultPicker";
import { EmojiPickerButton, EmojiQuickRow } from "@/components/chat/EmojiBar";
import { TemplatePicker, type PickedTemplate } from "@/components/chat/TemplatePicker";
import { TagCreatorsPicker, TaggedCreatorChips } from "@/components/chat/TagCreatorsPicker";
import { recordSchedule } from "@/lib/scheduleHistory";
import { EDITOR_MODAL } from "@/components/automations/automationPage";
import { IfButton, IfHelp, IfInput, IfLabel, IfModal } from "@/components/ui/infloww";

import { sanitizePriceInput } from "@/lib/priceInput";

import { MediaTray } from "./MediaTray";
import { useOfRichAllowed } from "@/hooks/useOfRichAllowed";
import { AaButton, ComposeTextBox, type ComposeTextBoxHandle } from "./ComposeTextBox";
import { ScheduleField } from "./ScheduleField";
import { FanOutResults, FanOutStatus } from "./FanOutResults";
import { IncludeModelsChips } from "./IncludeModelsChips";
import { fanOutLocked, includedTargets, runFanOut } from "./fanOut";
import { isAudienceSeed, useTouched } from "./useTouched";
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
  const { isIncluded } = useAllModelsInclude();
  // The whole form (postComposerReducer).
  const [form, rawDispatch] = useReducer(postComposerReducer, null, initPostForm);
  // The user's dispatch: any action but the picker's first account touches the form (Escape then keeps it).
  const { touched, dispatch } = useTouched(form, rawDispatch, isAudienceSeed);
  const { allModels, text, attached, price, previewCount, schedule, progress, results, taggedCreators } = form;
  // The account a one-account post goes to; null while all-models is on
  // (postComposerReducer `sendAccount`).
  const accountId = sendAccount(form);
  // A round in flight, or a model took this post: the content is locked (compose/fanOut).
  const locked = fanOutLocked(form);
  const set = <K extends PostField>(k: K) => (v: PostForm[K]) => dispatch(postFieldAction(k, v));
  // Stable: AccountPicker's auto-seed effect depends on it.
  const setAccountId = useCallback((id: string) => dispatch({ type: "setAccount", id }), [dispatch]);
  const [pickerOpen, setPickerOpen] = useState(false);
  const textRef = useRef<ComposeTextBoxHandle | null>(null);
  // OF rich text: OnlyFans accounts only (all-models: the platform's, whose accounts these all are).
  const allowRich = useOfRichAllowed(accountId);
  // A subscription page has no paid-post lane on OF, so the price field is not
  // an option there and its price reads as 0 (postComposerReducer `postPrice`)
  // — a typed or template price can't block or ride into the post. The relay
  // refuses a priced post for one anyway (409).
  const { isPaidPage } = usePaidPage(accountId);

  // Honour the shared include set: models the user unchecked in a
  // composer's chip strip are dropped from the broadcast fan-out; a model
  // that already took this post (a partial fan-out's success) is not re-posted.
  const { targets } = includedTargets(activeAccounts, isIncluded, results);

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
      const round = await runFanOut(targets, postTo, (p) => rawDispatch({ type: "progress", ...p }));
      rawDispatch({ type: "results", v: round });
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
    if (textRef.current) textRef.current.insert(em);
    else dispatch({ type: "appendText", v: em });
  }

  function onPickTemplate(t: PickedTemplate) {
    // Snapshot semantics (lib/composeDraft applyTemplate): text, media,
    // preview count and price are replaced wholesale.
    // An OnlyFans account keeps a formatted script's markup; Fansly gets its plain text.
    dispatch({ type: "pickTemplate", t, rich: allowRich });
    setTimeout(() => textRef.current?.focus(), 0);
  }

  const priceId = useId();
  if (!open) return null;

  const priceNum = postPrice(form, isPaidPage);
  const isPPV = priceNum > 0;
  const isScheduled = !!schedule;

  return (
    <>
      <IfModal
        title="New post"
        width={535}
        className={EDITOR_MODAL}
        onClose={close}
        // Escape never drops a draft the user touched; × and Cancel still close.
        keyboard={!touched}
        footer={<>
          <FanOutStatus
            progress={progress} verb="Posting" invalid={invalid} error={create.error?.message ?? null} results={results}
          />
          <IfButton onClick={close} disabled={create.isPending}>Cancel</IfButton>
          <IfButton
            variant="primary"
            onClick={() => {
              if (allModels && !confirm(
                `Post from ${targets.length} model${targets.length === 1 ? "" : "s"}?`,
              )) return;
              create.mutate();
            }}
            disabled={create.isPending || invalid !== null}
            title={invalid ?? undefined}
          >
            {create.isPending
              ? (isScheduled ? "Scheduling…" : "Posting…")
              : (isScheduled ? "Schedule post" : "Post")}
          </IfButton>
        </>}
      >
        <div className="space-y-4">
          <IncludeModelsChips
            noun="post" allModels={allModels} locked={locked}
            onAllModels={(on) => dispatch({ type: "setAllModels", on })}
            accountId={accountId} onAccount={setAccountId}
          />

          {/* The content — locked (disabled) once a model took the post. */}
          <fieldset disabled={locked} className="min-w-0 space-y-4 disabled:opacity-60">
          <div className="space-y-2">
            <ComposeTextBox
              ref={textRef}
              value={text}
              onChange={set("text")}
              placeholder="What's on your feed today?"
              rows={5}
              rich={allowRich && form.mode.rich}
              toolbar={form.mode.toolbar}
              disabled={locked}
            />
            {/* Escape in a picker's search box closes that picker, not the whole composer. */}
            <div className="flex items-center gap-1.5 flex-wrap"
              onKeyDown={(e) => { if (e.key === "Escape" && e.target instanceof HTMLInputElement) e.stopPropagation(); }}>
              <EmojiQuickRow onInsert={onEmoji} />
              <EmojiPickerButton align="left" onInsert={onEmoji} />
              {allowRich && <AaButton on={form.mode.toolbar} onToggle={() => dispatch({ type: "aa" })} />}
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
            <div>
              <IfLabel htmlFor={priceId}>Price (USD)</IfLabel>
              <div className="flex flex-wrap items-center gap-x-4 gap-y-2">
                <IfInput
                  id={priceId}
                  type="text"
                  inputMode="decimal"
                  value={isPaidPage ? "" : price}
                  disabled={isPaidPage}
                  onChange={(e) => set("price")(sanitizePriceInput(e.target.value))}
                  placeholder={isPaidPage ? "free only" : "0 (free)"}
                  className="w-40 has-[:disabled]:opacity-40 max-md:text-base"
                />
                {isPPV ? (
                  <span className="inline-flex items-center gap-1 text-[14px] text-warn">
                    <Lock className="h-3.5 w-3.5" aria-hidden />PPV {fmtPrice(Math.round(priceNum * 100))}
                  </span>
                ) : (
                  <span className="text-[14px] text-muted">Free</span>
                )}
              </div>
              {isPaidPage && <IfHelp>{PAID_PAGE_NOTE}</IfHelp>}
            </div>
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
      </IfModal>

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
    </>
  );
}
