"use client";


import { useCallback, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";

import { relay, RelayError, type OFMedia, type OFMessage, type SendMessageBody, type VaultMedia } from "@/lib/relay";
import { type FanId } from "@/lib/fanId";
import { relayNow } from "@/lib/ageClock";
import { bumpAfterSend, patchChatCaches, type SentMessage } from "@/lib/chatsCache";
import { parseSendFailure, type SendFailure } from "@/lib/sendFailure";
import { useEmployee } from "@/contexts/EmployeeContext";
import { uploadErrorText, uploadToVault, type PendingUpload } from "@/hooks/useComposerUploads";
import { sendStash, type SendInput, type StashEntry } from "@/lib/sendStash";

import { useChatMessages } from "./useChatMessages";
import { scheduledSendsKey } from "./useServerScheduledSends";

// OF's native queue lags/rejects too-near times, so near ones ride our executor.
export const EXECUTOR_MAX_MINUTES = 15;

export type SendSettled = { sent: true } | { sent: false; failure?: SendFailure };

export type SendStatus = "sent" | "scheduled" | "failed";

export interface SendOutcome {
  tempId: number;
  failure: SendFailure | null;
  settled: Promise<SendSettled>;
}

// Shared by every hook instance: two can write one Fan's cache, and per-instance counters would reuse an id and overwrite a message. Negative never collides with OF.
let nextTempId = -1;

let nextPlaceholderId = -1_000_000_000;

function placeholderMedia(file: File, previewUrl: string | null): VaultMedia {
  return {
    id: nextPlaceholderId--,
    type: file.type.startsWith("video") ? "video" : "photo",
    files: null,
    _localPreview: previewUrl ?? undefined,
  };
}

function buildBody(input: SendInput, attached: VaultMedia[]): SendMessageBody {
  const body: SendMessageBody = {
    text: input.text,
    locked_text: input.lockedText ?? false,
    price: input.price ?? 0,
    media_files: attached.map((m) => m._claim ?? m.id),
  };
  if (input.previews && input.previews.length > 0 && (input.price ?? 0) > 0) {
    body.previews = input.previews;
  }
  if (input.replyToMessageId) body.reply_to_message_id = input.replyToMessageId;
  if (input.taggedUsers && input.taggedUsers.length > 0) {
    body.tagged_users = input.taggedUsers;
  }
  if (input.giphyId) body.giphy_id = input.giphyId;
  return body;
}

export interface UseSendMessageOpts {
  accountId: string | null;
  fanId: FanId | null;
  fromUserId?: number | string;
  fromUserName?: string;
  hookHandle: ReturnType<typeof useChatMessages>;
  onStart?: () => void;
  onSettled?: (status: SendStatus) => void;
}

interface SendOpts extends SendInput {
  uploads?: PendingUpload[];
}

function vaultToOFMedia(v: VaultMedia): OFMedia {
  // Local preview wins: the CDN hasn't seen a just-uploaded file yet, and fresh claims have no `files`.
  const thumbUrl =
    v._localPreview || v.files?.thumb?.url || null;
  const sourceUrl =
    v._localPreview ||
    v.files?.full?.url ||
    v.files?.preview?.url ||
    null;
  return {
    id: v.id,
    type: v.type,
    files: {
      thumb: thumbUrl ? { url: thumbUrl } : null,
      source: sourceUrl ? { url: sourceUrl } : null,
    },
  };
}

export function useSendMessage(opts: UseSendMessageOpts) {
  const { accountId, fanId, fromUserId, fromUserName, hookHandle, onStart, onSettled } = opts;
  const { appendLocal, reconcileLocal, failLocal, dropLocal } = hookHandle;
  const qc = useQueryClient();
  const { current: currentEmployee } = useEmployee();
  const employeeId = currentEmployee?.id ?? null;

  const [inflight, setInflight] = useState(0);

  const report = useCallback((ending: Promise<SendSettled | undefined>) => {
    void ending.then(
      (ended) => onSettled?.(ended?.sent ? "sent" : "failed"),
      () => onSettled?.("failed"),
    );
  }, [onSettled]);

  const doSend = useCallback(
    async (
      tempId: number, body: SendMessageBody, capturedAccountId: string, capturedFanId: FanId,
    ): Promise<SendFailure | null> => {
      setInflight((n) => n + 1);
      try {
        const server = await relay.post<OFMessage>(
          `/api/of/v2/chats/${capturedFanId}/messages`,
          body,
          { accountId: capturedAccountId, employeeId },
        );
        reconcileLocal(tempId, server);
        recordVaultSends(qc, capturedAccountId, capturedFanId, server, body.price ?? 0);
        qc.invalidateQueries({ queryKey: ["msg-attribution", capturedAccountId, capturedFanId] });
        sendStash.sent(tempId);
        return null;
      } catch (err) {
        let failure: SendFailure;
        if (err instanceof RelayError) {
          console.warn("[send] failed", { status: err.status, body: err.body, message: err.message });
          const parsed = parseSendFailure(err.body);
          failure = { ...parsed, reason: parsed.reason ?? `HTTP ${err.status}` };
        } else {
          console.warn("[send] failed", err);
          failure = { reason: (err as Error)?.message };
        }
        failLocal(tempId, failure);
        return failure;
      } finally {
        setInflight((n) => n - 1);
      }
    },
    [failLocal, reconcileLocal, qc, employeeId],
  );

  const optimisticMessage = useCallback(
    (tempId: number, input: SendInput, media: OFMedia[], uploading: boolean): OFMessage => ({
      id: tempId,
      _tempId: tempId,
      _pending: true,
      _uploading: uploading || undefined,
      text: input.text,
      fromUser: { id: fromUserId ?? -1, name: fromUserName ?? "you" },
      createdAt: new Date().toISOString(),
      media,
      mediaCount: media.length,
      price: input.price ?? 0,
      replyToMessageId: input.replyToMessageId,
      replyToMessage: input.replyToMessage ?? null,
      giphyId: input.giphyId,
    }),
    [fromUserId, fromUserName],
  );

  const sendAfterUploads = useCallback(
    async (
      tempId: number, entry: StashEntry, done: Array<Promise<VaultMedia[]>>,
      capturedAccountId: string, capturedFanId: FanId,
    ): Promise<SendSettled> => {
      const waited = entry.files.some((f) => !f.media);
      const settled = await Promise.allSettled(done);
      if (sendStash.get(tempId) !== entry) return { sent: false };
      settled.forEach((r, i) => {
        if (r.status === "fulfilled") entry.files[i].media = r.value;
        entry.files[i].cancel = undefined;
      });
      const lost = settled.find((r): r is PromiseRejectedResult => r.status === "rejected");
      if (lost) {
        console.warn("[send] upload failed", lost.reason);
        const raw = lost.reason instanceof Error ? lost.reason.message : "";
        const failure: SendFailure = { reason: uploadErrorText(raw) };
        failLocal(tempId, failure);
        return { sent: false, failure };
      }
      const attached = [...(entry.input.attached ?? []), ...entry.files.flatMap((f) => f.media ?? [])];
      if (waited) {
        dropLocal(tempId);
        appendLocal(optimisticMessage(tempId, entry.input, attached.map(vaultToOFMedia), false));
      }
      const failure = await doSend(tempId, buildBody(entry.input, attached), capturedAccountId, capturedFanId);
      return failure ? { sent: false, failure } : { sent: true };
    },
    [appendLocal, dropLocal, failLocal, doSend, optimisticMessage],
  );

  const sendNow = useCallback(
    async (input: SendOpts, capturedAccountId: string, capturedFanId: FanId): Promise<SendOutcome> => {
      const { uploads = [], ...rest } = input;
      const attached = rest.attached ?? [];
      const tempId = nextTempId--;
      const entry: StashEntry = {
        input: rest,
        files: uploads.map((u) => ({ file: u.file, previewUrl: u.previewUrl, cancel: u.cancel })),
      };
      sendStash.set(tempId, entry);
      const optimisticMedia: OFMedia[] = [
        ...attached,
        ...uploads.map((u) => placeholderMedia(u.file, u.previewUrl)),
      ].map(vaultToOFMedia);
      appendLocal(optimisticMessage(tempId, rest, optimisticMedia, uploads.length > 0));
      patchChatListAfterSend(qc, capturedAccountId, capturedFanId, {
        // Raw account id, not Number(): a Fansly snowflake is past 2^53 and the yellow unanswered dot would return.
        fromUserId: fromUserId ?? capturedAccountId,
        fromUserName: fromUserName ?? "you",
        text: input.text,
        mediaCount: optimisticMedia.length,
        price: input.price ?? 0,
      });
      const sending = sendAfterUploads(tempId, entry, uploads.map((u) => u.done), capturedAccountId, capturedFanId);
      if (uploads.length > 0) return { tempId, failure: null, settled: sending };
      const ended = await sending;
      return { tempId, failure: ended.sent ? null : ended.failure ?? null, settled: sending };
    },
    [fromUserId, fromUserName, appendLocal, sendAfterUploads, optimisticMessage, qc],
  );

  const schedule = useCallback(
    async (input: SendOpts, scheduledAt: string, accountId: string, fanId: FanId): Promise<void> => {
      if (input.uploads?.length) throw new Error("Wait for the upload to finish before scheduling");
      const fireAt = new Date(scheduledAt).getTime();
      const delay = fireAt - Date.now();
      if (delay > 0 && delay <= EXECUTOR_MAX_MINUTES * 60_000) {
        const attached = input.attached ?? [];
        try {
          await relay.post(
            `/api/of/v2/scheduled-sends`,
            {
              fan_id: fanId,
              run_at: scheduledAt,
              text: input.text,
              price: input.price ?? 0,
              locked_text: input.lockedText ?? false,
              media_files: attached.map((m) => m._claim ?? m.id),
              previews:
                input.previews && (input.price ?? 0) > 0 ? input.previews : [],
              tagged_users: input.taggedUsers ?? [],
              giphy_id: input.giphyId,
            },
            { accountId, employeeId },
          );
          qc.invalidateQueries({ queryKey: scheduledSendsKey(accountId, fanId) });
        } catch (err) {
          // Rethrow: a scheduled send has no bubble to turn red, so swallowing showed "Scheduled" for a message the relay refused.
          console.warn("[schedule] near-term enqueue failed", err);
          throw err;
        }
        return;
      }
      const attached = input.attached ?? [];
      try {
        const scheduledBody: Record<string, unknown> = {
          text: input.text,
          locked_text: input.lockedText ?? false,
          price: input.price ?? 0,
          media_files: attached.map((m) => m._claim ?? m.id),
          scheduled_date: scheduledAt,
        };
        if (input.previews && input.previews.length > 0 && (input.price ?? 0) > 0) {
          scheduledBody.previews = input.previews;
        }
        if (input.taggedUsers && input.taggedUsers.length > 0) {
          scheduledBody.tagged_users = input.taggedUsers;
        }
        if (input.giphyId) scheduledBody.giphy_id = input.giphyId;
        await relay.post(
          `/api/of/v2/chats/${fanId}/messages/scheduled`,
          scheduledBody,
          { accountId, employeeId },
        );
      } catch (err) {
        console.warn("[schedule] failed", err);
        throw err;
      }
    },
    [qc, employeeId],
  );

  const send = useCallback(
    async (input: SendOpts): Promise<SendOutcome | undefined> => {
      onStart?.();
      if (!accountId || fanId == null) {
        console.warn("[send] missing accountId or fanId — refusing to send");
        onSettled?.("failed");
        return;
      }
      if (input.scheduledAt) {
        try {
          await schedule(input, input.scheduledAt, accountId, fanId);
        } catch (err) {
          onSettled?.("failed");
          throw err;
        }
        onSettled?.("scheduled");
        return;
      }
      const sending = sendNow(input, accountId, fanId);
      report(sending.then((outcome) => outcome.settled));
      return sending;
    },
    [accountId, fanId, sendNow, schedule, onStart, onSettled, report],
  );

  const retry = useCallback(
    async (tempId: number): Promise<SendSettled> => {
      onStart?.();
      const entry = sendStash.get(tempId);
      if (!accountId || fanId == null || !entry) {
        onSettled?.("failed");
        return { sent: false };
      }
      const done = entry.files.map((f) => {
        if (f.media) return Promise.resolve(f.media);
        const ctl = new AbortController();
        f.cancel = () => ctl.abort();
        return uploadToVault(accountId, f.file, f.previewUrl, ctl.signal);
      });
      const media = [
        ...(entry.input.attached ?? []),
        ...entry.files.flatMap((f) => f.media ?? [placeholderMedia(f.file, f.previewUrl)]),
      ].map(vaultToOFMedia);
      dropLocal(tempId);
      appendLocal(optimisticMessage(tempId, entry.input, media, entry.files.some((f) => !f.media)));
      const sending = sendAfterUploads(tempId, entry, done, accountId, fanId);
      report(sending);
      return await sending;
    },
    [accountId, fanId, appendLocal, dropLocal, optimisticMessage, sendAfterUploads, onStart, onSettled, report],
  );

  const cancelOptimistic = useCallback(
    (tempId: number) => {
      dropLocal(tempId);
      sendStash.discard(tempId);
    },
    [dropLocal],
  );

  return { send, retry, cancelOptimistic, inflight };
}

function recordVaultSends(
  qc: ReturnType<typeof useQueryClient>,
  accountId: string,
  fanId: FanId,
  server: OFMessage,
  priceDollars: number,
): void {
  const mediaIds = (server.media ?? [])
    .map((m) => (typeof m.id === "number" ? m.id : Number(m.id)))
    .filter((n) => Number.isFinite(n) && n > 0);
  if (mediaIds.length === 0) return;
  const msgId = typeof server.id === "number" ? server.id : Number(server.id);
  relay
    .post("/admin/vault/sends", {
      account_id: accountId,
      fan_id: fanId,
      media_ids: mediaIds,
      message_id: Number.isFinite(msgId) && msgId > 0 ? msgId : null,
      price_cents: Math.max(0, Math.round((priceDollars || 0) * 100)),
    })
    .then(() => {
      qc.invalidateQueries({ queryKey: ["vault-history", accountId, fanId] });
    })
    .catch((err) => console.warn("[vault-sends] record failed", err));
}

export function patchChatListAfterSend(
  qc: ReturnType<typeof useQueryClient>,
  accountId: string,
  fanId: FanId,
  msg: SentMessage,
): void {
  const nowIso = new Date(relayNow()).toISOString();
  patchChatCaches(qc, accountId, (data, { key }) => bumpAfterSend(key, data, accountId, fanId, msg, nowIso));
}
