"use client";


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
import { IfButton, IfHelp, IfInput, IfLabel, IfModal } from "@/components/ui/infloww";

import { sanitizePriceInput } from "@/lib/priceInput";

import { MediaTray } from "./MediaTray";
import { useCanOrFallback } from "@/hooks/useCan";
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
import { ifConfirm } from "@/components/ui/ifConfirm";

interface CreatePostResp {
  id?: number;
  [k: string]: unknown;
}

export function PostComposer({
  open,
  onClose,
  onSuccess,
}: {
  open: boolean;
  onClose: () => void;
  onSuccess?: () => void;
}) {
  const qc = useQueryClient();
  const activeAccounts = usePlatformAccounts();
  const { isIncluded } = useAllModelsInclude();
  const [form, rawDispatch] = useReducer(postComposerReducer, null, initPostForm);
  const { touched, dispatch } = useTouched(form, rawDispatch, isAudienceSeed);
  const { allModels, text, attached, price, previewCount, schedule, progress, results, taggedCreators } = form;
  const accountId = sendAccount(form);
  const locked = fanOutLocked(form);
  const set = <K extends PostField>(k: K) => (v: PostForm[K]) => dispatch(postFieldAction(k, v));
  const setAccountId = useCallback((id: string) => dispatch({ type: "setAccount", id }), [dispatch]);
  const [pickerOpen, setPickerOpen] = useState(false);
  const textRef = useRef<ComposeTextBoxHandle | null>(null);
  const allowRich = useCanOrFallback(allModels ? activeAccounts[0]?.id : accountId, "rich_text");
  const { isPaidPage } = usePaidPage(accountId);

  const { targets } = includedTargets(activeAccounts, isIncluded, results);

  const invalid = validatePost(form, { broadcastCount: targets.length, paidPage: isPaidPage });

  function posted() {
    qc.invalidateQueries({ queryKey: ["wall-media"] });
    onSuccess?.();
  }

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
      if (round.some((r) => r.ok)) posted();
      return round.every((r) => r.ok);
    },
    onSuccess: (mayClose) => {
      if (mayClose) onClose();
    },
  });

  function close() {
    if (!create.isPending) onClose();
  }

  function onEmoji(em: string) {
    if (textRef.current) textRef.current.insert(em);
    else dispatch({ type: "appendText", v: em });
  }

  function onPickTemplate(t: PickedTemplate) {
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
        size="editor"
        onClose={close}
        keyboard={!touched}
        footer={<>
          <FanOutStatus
            progress={progress} verb="Posting" invalid={invalid} error={create.error?.message ?? null} results={results}
          />
          <IfButton onClick={close} disabled={create.isPending}>Cancel</IfButton>
          <IfButton
            variant="primary"
            onClick={async () => {
              if (allModels && !(await ifConfirm(
                `Post from ${targets.length} model${targets.length === 1 ? "" : "s"}?`,
              ))) return;
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
            noun="post" accounts={activeAccounts} allModels={allModels} locked={locked}
            onAllModels={(on) => dispatch({ type: "setAllModels", on })}
            accountId={accountId} onAccount={setAccountId}
          />

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
            <div className="flex items-center gap-1.5 flex-wrap">
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
