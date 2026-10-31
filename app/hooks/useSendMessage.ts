"use client";

/**
 * useSendMessage — optimistic send for a single chat.
 *
 * Flow:
 *   1. Caller invokes send(text, opts). We:
 *      a. Allocate a fresh negative tempId.
 *      b. Build an optimistic OFMessage and append via appendLocal.
 *      c. POST /api/of/v2/chats/{fanId}/messages.
 *      d. On success → reconcileLocal(tempId, server) (merges media files).
 *      e. On failure → failLocal(tempId) (shows Retry button).
 *
 * Cross-chat guard: we capture `accountId` + `fanId` at send time. If the
 * user switches chats while a send is in flight, the response still
 * reconciles into the original chat's query — there's no `selectedChatIdRef`
 * issue because TanStack Query's query key is the source of truth (we
 * write straight to the (accountId, fanId) cache, regardless of what's
 * visible).
 *
 * Uploads still running at Send (`uploads`, from the Composer): the bubble
 * shows at once with the files' previews ("uploading…"), `send` returns, and
 * the POST goes out when every file has landed, re-seating the bubble at the
 * tail as it goes. A failed upload fails the bubble instead — nothing is sent
 * without its file — and Retry uploads the failed files again, then sends.
 * Every send and Retry runs through `sendAfterUploads` (a file already landed
 * is a resolved promise); its state is the send stash (lib/sendStash), not the
 * mount, so it finishes after a chat switch and Retry works from the reopened
 * chat. Discarding the bubble (or an identity switch) stops it before the POST.
 *
 * Inflight counter exposed for the spinner.
 */

import { useCallback, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";

import { relay, RelayError, type OFMedia, type OFMessage, type SendMessageBody, type VaultMedia } from "@/lib/relay";
import { type FanId } from "@/lib/fanId";
import { bumpAfterSend, type ChatPages, type SentMessage } from "@/lib/chatsCache";
import { parseSendFailure, type SendFailure } from "@/lib/sendFailure";
import { useEmployee } from "@/contexts/EmployeeContext";
import {
  useRosterCountActions,
  rosterDelta,
  applyRosterDelta,
  rosterPriorFromRow,
} from "@/hooks/useRosterCounts";
import { findFanChatRow } from "@/hooks/useInboxRealtime";
import { uploadErrorText, uploadToVault, type PendingUpload } from "@/hooks/useComposerUploads";
import { sendStash, type SendInput, type StashEntry } from "@/lib/sendStash";

import { useChatMessages } from "./useChatMessages";
import { scheduledSendsKey } from "./useServerScheduledSends";

/** A scheduled send this many minutes out or fewer rides OUR executor queue;
 *  later ones go to OF's native queue (see `send` below). */
export const EXECUTOR_MAX_MINUTES = 15;

/** How a send ended: sent, or not (failed, with why; or discarded, the
 *  bubble dropped or the identity switched, without). */
export type SendSettled = { sent: true } | { sent: false; failure?: SendFailure };

/** How a send (or a Retry) ended, as `onSettled` reports it: it went out, it
 *  was scheduled, or it failed (refused, discarded, or OF said no). */
export type SendStatus = "sent" | "scheduled" | "failed";

/** What an immediate send came to: the optimistic bubble's temp id, why the
 *  send failed (null when it landed, or when it still waits on its uploads:
 *  that bubble carries its own outcome), and `settled`, which resolves once
 *  the send is over. */
export interface SendOutcome {
  tempId: number;
  failure: SendFailure | null;
  settled: Promise<SendSettled>;
}

// Temp ids are shared by every instance of the hook. Two instances can write
// one Fan's message cache (the Thread's Composer and a notification's quick
// reply), and a reconciled message keeps its `_tempId`, so per-instance
// counters would hand out the same id twice and one send's reconcile would
// overwrite the other's message. Decrementing: negative ids never collide
// with OF.
let nextTempId = -1;

// Placeholder ids for a file still uploading, far below the claim ids
// (`toAttachments`) so a bubble's media keys never collide.
let nextPlaceholderId = -1_000_000_000;

/** A file still uploading, as the pending bubble's media: its blob preview. */
function placeholderMedia(file: File, previewUrl: string | null): VaultMedia {
  return {
    id: nextPlaceholderId--,
    type: file.type.startsWith("video") ? "video" : "photo",
    files: null,
    _localPreview: previewUrl ?? undefined,
  };
}

/** The wire body of an immediate send. */
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
  /** Our own creator id — numeric on OF, a string snowflake on Fansly. */
  fromUserId?: number | string;
  fromUserName?: string;
  hookHandle: ReturnType<typeof useChatMessages>;
  /** A send or a Retry began (called before any await). */
  onStart?: () => void;
  /** How each send or Retry ended; exactly one call per `onStart`. */
  onSettled?: (status: SendStatus) => void;
}

interface SendOpts extends SendInput {
  /** Files still uploading. The optimistic bubble shows at once; the send
   *  goes out when they land, their media after `attached`. Immediate sends
   *  only. */
  uploads?: PendingUpload[];
}

function vaultToOFMedia(v: VaultMedia): OFMedia {
  // Local preview (just-uploaded file) wins over server URLs because the
  // CDN hasn't seen the file yet — and for fresh claims there's no `files`
  // at all, so without the blob URL the bubble would be blank.
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
  const { patchLocal: patchRosterLocal, refreshOne: refreshRoster } = useRosterCountActions();

  const [inflight, setInflight] = useState(0);

  /** Reports how a send ended: nothing sent (undefined) or a rejection is a failure. */
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
        // Record vault sends so the picker can mark "you sent this" /
        // "she bought this" next time. Pull ids straight from OF's response
        // because (a) fresh-claims didn't have a real vault id pre-send,
        // and (b) some uploads collapse onto an existing vault item.
        recordVaultSends(qc, capturedAccountId, capturedFanId, server, body.price ?? 0);
        // Invalidate the outbound-attribution map so the new real
        // message_id picks up its "Sent by …" label. Without this,
        // the optimistic fallback (`_tempId<0`) carries the label
        // until the next chat refetch replaces the merged row with
        // pure server data (no `_tempId`) — at which point the label
        // disappears for the 5-min attribution staleTime window.
        qc.invalidateQueries({ queryKey: ["msg-attribution", capturedAccountId, capturedFanId] });
        sendStash.sent(tempId);
        return null;
      } catch (err) {
        // Leave the optimistic in place but flag it failed so Retry can
        // recover, carrying what OF (or our own pre-flight guard) said and
        // which attachments it blamed — one parse of one envelope, see
        // lib/sendFailure. The console line spreads the upstream details so
        // logs read as status + body, not "[object Object]".
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
        // The optimistic roster decrement in the send path assumed this would
        // land; it didn't → reconcile the badge to OF truth (force past the 8s
        // cooldown — this only fires on the rare failure path).
        void refreshRoster(capturedAccountId, { force: true });
        return failure;
      } finally {
        setInflight((n) => n - 1);
      }
    },
    [failLocal, reconcileLocal, qc, employeeId, refreshRoster],
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

  // Wait for a send's files, then send it. Runs to the end after the chat
  // closes (every write goes to the (account, Fan) message cache), unless the
  // bubble is discarded meanwhile.
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
        void refreshRoster(capturedAccountId, { force: true });
        return { sent: false, failure };
      }
      const attached = [...(entry.input.attached ?? []), ...entry.files.flatMap((f) => f.media ?? [])];
      if (waited) {
        // Re-seat the bubble at the tail: it goes out now, after anything
        // sent while its files uploaded, and OF will order it so.
        dropLocal(tempId);
        appendLocal(optimisticMessage(tempId, entry.input, attached.map(vaultToOFMedia), false));
      }
      const failure = await doSend(tempId, buildBody(entry.input, attached), capturedAccountId, capturedFanId);
      return failure ? { sent: false, failure } : { sent: true };
    },
    [appendLocal, dropLocal, failLocal, doSend, optimisticMessage, refreshRoster],
  );

  // Immediate-send path, extracted so the no-schedule case can call it
  // without recursion gymnastics.
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
      // Optimistically flip the chat-list row's `lastMessage.fromUser` to
      // us so the yellow "read but unanswered" dot disappears immediately.
      // Without this the dot lingers for up to 60s (the chat-list poll).
      // Read the fan's PRE-flip roster state from the FRESHEST cached row
      // (findFanChatRow picks newest lastMessage, not a stale first-match) BEFORE
      // patchChatListAfterSend flips the row to us.
      const prior = rosterPriorFromRow(findFanChatRow(qc, capturedAccountId, capturedFanId));
      patchChatListAfterSend(qc, capturedAccountId, capturedFanId, {
        // The raw account id, NOT Number(accountId): a Fansly snowflake is past
        // 2^53, so parsing it yields a DIFFERENT id — the row would read as "the
        // fan spoke last" and the yellow dot would come straight back on the
        // thread we just answered.
        fromUserId: fromUserId ?? capturedAccountId,
        fromUserName: fromUserName ?? "you",
        text: input.text,
        mediaCount: optimisticMedia.length,
        price: input.price ?? 0,
      });
      // Clear this conversation's roster badge (orange owe-reply, or blue if it
      // was still unread) the SAME tick we send. The outbound SSE echo can't do
      // this — by the time it lands, the row above is already flipped to us, so
      // the realtime handler would compute a no-op. Must happen here, from the
      // prior state, or the manual-send badge waits out the 60s poll.
      if (prior) {
        const d = rosterDelta(true, prior);
        if (d.dUnread !== 0 || d.dOwe !== 0) {
          patchRosterLocal(capturedAccountId, (cur) => applyRosterDelta(cur, d));
        }
      }
      const sending = sendAfterUploads(tempId, entry, uploads.map((u) => u.done), capturedAccountId, capturedFanId);
      // Waiting on files: Send is done once the bubble shows, so the Composer
      // is free for the next message.
      if (uploads.length > 0) return { tempId, failure: null, settled: sending };
      const ended = await sending;
      return { tempId, failure: ended.sent ? null : ended.failure ?? null, settled: sending };
    },
    [fromUserId, fromUserName, appendLocal, sendAfterUploads, optimisticMessage, qc, patchRosterLocal],
  );

  // Scheduled path; resolves once enqueued, throws when refused. Two
  // branches, BOTH server-side (survive reload + are shared across every
  // chatter on the account):
  //   • Short delay (≤ 15 min from now): hand to OUR executor — enqueue a
  //     `scheduled_jobs` row (kind="scheduled_send") that the supervisor
  //     fires at run_at. We fire it ourselves (not OF's queue) because OF's
  //     queue lags/rejects too-near times; this also lets us attribute the
  //     eventual bubble to the chatter who scheduled it.
  //   • Long delay: hand off to OF's native queue so it survives even if our
  //     VPS is down, can be edited from OF web, etc.
  const schedule = useCallback(
    async (input: SendOpts, scheduledAt: string, accountId: string, fanId: FanId): Promise<void> => {
      // A schedule carries media ids; the Composer holds it while a file
      // uploads. Never schedule a message without its file.
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
          // Surface the ghost bubble immediately (and for any other chatter
          // on next poll). Server is the source of truth from here on.
          qc.invalidateQueries({ queryKey: scheduledSendsKey(accountId, fanId) });
        } catch (err) {
          // RETHROW. A scheduled send has no optimistic bubble to turn red —
          // the only evidence it exists is the server-side ghost row. Swallowing
          // here left the composer showing its "Scheduled ✓" toast over an empty
          // textarea for a message the relay had REFUSED (a Fansly PPV/media
          // schedule 400s), which is indistinguishable from success. The caller
          // restores the composer and shows the real reason.
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
        // Same contract as the near-term branch above: no bubble exists to
        // carry the failure, so it must reach the composer.
        console.warn("[schedule] failed", err);
        throw err;
      }
    },
    [qc, employeeId],
  );

  /** Resolves to the outcome of an immediate send; to undefined when it
   *  refuses (no chat) or schedules (a scheduled failure throws instead). */
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
    async (tempId: number) => {
      onStart?.();
      const entry = sendStash.get(tempId);
      if (!accountId || fanId == null || !entry) {
        onSettled?.("failed");
        return;
      }
      // Upload the files that failed again (the landed ones keep their
      // media; discarding the bubble cancels the rest), then send as the
      // first attempt would have.
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
      // appendLocal is a no-op when the id already exists, so to flip the
      // bubble back to pending we drop and re-append it.
      dropLocal(tempId);
      appendLocal(optimisticMessage(tempId, entry.input, media, entry.files.some((f) => !f.media)));
      // A successful RETRY (the first attempt failed → D4's catch restored the
      // badge) lands the send but took no send-time decrement — reconcile the
      // badge to OF truth so the answered fan's orange/blue clears without waiting
      // out the 60s poll.
      const sending = sendAfterUploads(tempId, entry, done, accountId, fanId);
      report(sending);
      const ended = await sending;
      if (ended.sent) void refreshRoster(accountId, { force: true });
    },
    [accountId, fanId, appendLocal, dropLocal, refreshRoster, optimisticMessage, sendAfterUploads, onStart, onSettled, report],
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

/** Record vault sends in the local DB so the picker shows "sent / paid"
 *  badges on this fan's next vault open. Fire-and-forget: the request is
 *  pure-local, but failing to log a send shouldn't surface as an error
 *  toast (the message went out OK from OF's perspective). We pull media
 *  ids from the SERVER response, not the optimistic body, because:
 *    • Fresh-claim uploads only get a real id after OF assigns one.
 *    • Some uploads collapse onto an existing vault item, in which case
 *      OF echoes the canonical id we want to track. */
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

/** Patch the chat-list cache so the row we just sent into reflects the
 *  new lastMessage AND pops to the top of the inbox the same frame the
 *  user hits Send. Without the reorder, the row's createdAt is "now" but
 *  it stays where it was until the 60s poll re-sorts — which feels like
 *  a janky bounce. We lift it out wherever it was and prepend to page 0.
 *
 *  Drives:
 *    • Yellow "read · awaiting your reply" dot → gone (lastFromFan now us).
 *    • Row jumps to the top of the inbox instantly.
 *  Walks every chats cache (Unified Inbox vs per-model keys); the per-cache
 *  rule (lift vs patch in place, never a new row) is lib/chatsCache
 *  `bumpAfterSend`. */
function patchChatListAfterSend(
  qc: ReturnType<typeof useQueryClient>,
  accountId: string,
  fanId: FanId,
  msg: SentMessage,
): void {
  const nowIso = new Date().toISOString();
  qc.getQueryCache().findAll({ queryKey: ["chats"] }).forEach((q) => {
    const data = q.state.data as ChatPages | undefined;
    if (!data?.pages?.length) return;
    const next = bumpAfterSend(q.queryKey, data, accountId, fanId, msg, nowIso);
    if (next !== data) qc.setQueryData(q.queryKey, next);
  });
}
