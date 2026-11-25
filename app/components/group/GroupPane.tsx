"use client";


import { useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import { useQuery } from "@tanstack/react-query";

import { useAccountLabel } from "@/hooks/useAccounts";
import { useChatMessages } from "@/hooks/useChatMessages";
import { ofUserNameQuery } from "@/hooks/useOFUser";
import { useSendMessage } from "@/hooks/useSendMessage";
import { describeLoadError, relay, type OFChatItem, type OFMessage } from "@/lib/relay";
import { stripHtmlPreview } from "@/lib/htmlPreview";
import { proxyImage } from "@/lib/mediaUrl";
import { type FanId } from "@/lib/fanId";
import { cn, decodeHtmlEntities, fmtRelTime } from "@/lib/utils";

const MESSAGE_DISPLAY_CAP = 20;

interface MeResp {
  id: number;
  name?: string;
  username?: string;
}

export function GroupPane({
  accountId,
  fanId,
  onClose,
}: {
  accountId: string;
  fanId: FanId;
  onClose: () => void;
}) {
  const userQ = useQuery({
    ...ofUserNameQuery(accountId, fanId),
    enabled: Number.isFinite(fanId),
    refetchOnWindowFocus: false,
  });

  const meQ = useQuery<MeResp>({
    queryKey: ["of-me", accountId],
    queryFn: () => relay.get<MeResp>("/api/of/v2/users/me", { accountId }),
    staleTime: 60 * 60 * 1000,
    refetchOnWindowFocus: false,
  });

  const handle = useChatMessages({ accountId, fanId, enabled: true });

  const chat: OFChatItem = useMemo(
    () => ({
      withUser: {
        id: fanId,
        name: userQ.data?.name,
        username: userQ.data?.username,
        avatar: userQ.data?.avatar ?? null,
        customNickname: userQ.data?.customNickname ?? null,
      },
      __accountId: accountId,
      hasUnread: false,
    }),
    [accountId, fanId, userQ.data?.name, userQ.data?.username, userQ.data?.avatar, userQ.data?.customNickname],
  );
  void chat;

  const sender = useSendMessage({
    accountId,
    fanId,
    fromUserId: meQ.data?.id,
    fromUserName: meQ.data?.name ?? meQ.data?.username ?? "you",
    hookHandle: handle,
  });

  const markedRef = useRef(false);
  useEffect(() => {
    if (markedRef.current) return;
    markedRef.current = true;
    relay
      .post(`/api/of/v2/chats/${fanId}/mark-as-read`, undefined, { accountId })
      .catch(() => { });
  }, [accountId, fanId]);

  const backfilledRef = useRef(false);
  useEffect(() => {
    if (backfilledRef.current) return;
    if (handle.isLoading) return;
    const len = handle.data?.length ?? 0;
    // SSE seeds the cache with one bubble, which useQuery counts as fresh: one refresh pulls the real backlog.
    if (len === 0) return;
    if (len >= 10) return;
    backfilledRef.current = true;
    void handle.refresh();
  }, [handle.isLoading, handle.data, handle.refresh]);

  const messages = useMemo(() => {
    const all = handle.data ?? [];
    return all.slice(Math.max(0, all.length - MESSAGE_DISPLAY_CAP));
  }, [handle.data]);

  const ownerId = meQ.data?.id ?? null;

  const headerName = decodeHtmlEntities(
    userQ.data?.displayName ||
    userQ.data?.customNickname ||
    userQ.data?.name ||
    userQ.data?.username ||
    `fan ${fanId}`,
  );
  const headerAvatar = proxyImage(userQ.data?.avatar ?? null, accountId);
  const accountLabel = useAccountLabel(accountId);

  const [text, setText] = useState("");
  const [sending, setSending] = useState(false);
  const taRef = useRef<HTMLTextAreaElement | null>(null);

  const scrollRef = useRef<HTMLDivElement | null>(null);
  const last = messages[messages.length - 1];
  const lastKey = last ? `${String(last.id)}:${last._pending ? 1 : 0}` : "";
  // Keyed on the tail id, not length: at the 20-message cap the length stays constant while the tail rolls.
  useLayoutEffect(() => {
    const el = scrollRef.current;
    if (!el) return;
    el.scrollTop = el.scrollHeight;
  }, [lastKey, messages.length]);

  const canSend = text.trim().length > 0 && !sending;

  const onSubmit = async () => {
    if (!canSend) return;
    const value = text.trim();
    setSending(true);
    setText("");
    try {
      await sender.send({ text: value });
    } finally {
      setSending(false);
      taRef.current?.focus();
    }
  };

  return (
    <div className="flex flex-col min-w-0 min-h-0 h-full bg-bg border border-border rounded-lg overflow-hidden">
      <header className="flex items-center gap-2 px-2 py-1.5 border-b border-border bg-panel">
        <a
          href={`/messages-pro/${encodeURIComponent(accountId)}/${fanId}`}
          target="_blank"
          rel="noreferrer"
          className="flex items-center gap-2 flex-1 min-w-0 hover:bg-bg-elev-1/50 -mx-1 px-1 py-0.5 rounded-md transition-colors"
          title="Open full chat in new tab"
        >
          <div className="w-7 h-7 rounded-full bg-bg-elev-1 grid place-items-center text-xs overflow-hidden shrink-0">
            {headerAvatar ? (
              <img
                src={headerAvatar}
                alt=""
                loading="lazy"
                decoding="async"
                className="w-full h-full object-cover"
              />
            ) : (
              <span>{headerName.slice(0, 1).toUpperCase()}</span>
            )}
          </div>
          <div className="flex-1 min-w-0">
            <div className="text-xs font-medium truncate">{headerName}</div>
            <div className="text-[10px] text-fg-dim truncate">{accountLabel}</div>
          </div>
        </a>
        <button
          type="button"
          onClick={onClose}
          className="text-fg-dim hover:text-fg text-sm leading-none px-1.5 py-0.5 rounded hover:bg-bg-elev-1"
          title="Remove from group"
          aria-label="Remove from group"
        >
          ×
        </button>
      </header>

      <div
        ref={scrollRef}
        className="flex-1 min-h-0 overflow-y-auto px-2 py-2 space-y-1 flex flex-col"
      >
        {handle.isLoading && messages.length === 0 && (
          <div className="text-[11px] text-fg-dim text-center py-4">Loading…</div>
        )}
        {handle.isError && (
          <div className="text-[11px] text-err text-center py-4">
            {describeLoadError(handle.error as Error, "This conversation no longer exists on OnlyFans.")}
          </div>
        )}
        {!handle.isLoading && !handle.isError && messages.length === 0 && (
          <div className="text-[11px] text-fg-dim text-center py-4">No messages yet.</div>
        )}
        {messages.map((m) => (
          <GroupMessageRow key={String(m.id)} msg={m} ownerId={ownerId} />
        ))}
      </div>

      <form
        onSubmit={(e) => {
          e.preventDefault();
          void onSubmit();
        }}
        className="border-t border-border bg-panel p-1.5 flex items-end gap-1.5"
      >
        <textarea
          ref={taRef}
          value={text}
          onChange={(e) => setText(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && !e.shiftKey) {
              e.preventDefault();
              void onSubmit();
            }
          }}
          rows={1}
          placeholder={`Message ${headerName}…`}
          className={cn(
            "flex-1 min-w-0 resize-none bg-bg border border-border rounded px-2 py-1.5",
            // text-base (>=16px) on mobile so iOS Safari does not zoom on focus.
            "text-base md:text-xs",
            "placeholder:text-muted focus:outline-none focus:border-accent",
            "max-h-24",
          )}
        />
        <button
          type="submit"
          disabled={!canSend}
          className={cn(
            "shrink-0 px-2.5 py-1.5 rounded text-[11px] font-medium",
            "bg-accent hover:bg-accent-hover text-white",
            "disabled:opacity-40 disabled:cursor-not-allowed",
          )}
        >
          {sender.inflight > 0 ? "…" : "send"}
        </button>
      </form>
      <div className="px-2 py-0.5 text-[9px] text-fg-dim bg-panel border-t border-border/40 flex items-center justify-between">
        <span>fast-chat · last {MESSAGE_DISPLAY_CAP} · no images</span>
        <span>{messages.length}</span>
      </div>
    </div>
  );
}

function GroupMessageRow({
  msg,
  ownerId,
}: {
  msg: OFMessage;
  ownerId: number | null;
}) {
  const outgoing = ownerId != null && msg.fromUser?.id === ownerId;
  const text = stripHtmlPreview(msg.text || "", 600);
  const mediaCount = msg.mediaCount ?? msg.media?.length ?? 0;
  const isLocked = !msg.isFree && (msg.price ?? 0) > 0;
  const failed = !!msg._failed;
  const pending = !!msg._pending && !failed;

  return (
    <div className={cn("flex w-full", outgoing ? "justify-end" : "justify-start")}>
      <div
        className={cn(
          "max-w-[85%] rounded-md px-2 py-1 text-xs break-words",
          outgoing
            ? "bg-accent/90 text-white"
            : "bg-bg-elev-1 text-fg border border-border/40",
          failed && "border border-err text-err bg-err/10",
          pending && "opacity-60",
        )}
        title={msg.createdAt ? fmtRelTime(msg.createdAt) : undefined}
      >
        {text ? <div className="whitespace-pre-wrap">{text}</div> : null}
        {(mediaCount > 0 || isLocked) && (
          <div
            className={cn(
              "mt-0.5 text-[10px] inline-flex items-center gap-1",
              outgoing ? "text-white/80" : "text-fg-dim",
            )}
          >
            {isLocked && <span title={`PPV $${msg.price}`}>🔒</span>}
            {mediaCount > 0 && (
              <span title={`${mediaCount} media attached`}>📎 {mediaCount}</span>
            )}
          </div>
        )}
        {failed && msg._failedReason && (
          <div className="mt-0.5 text-[10px]">{msg._failedReason}</div>
        )}
      </div>
    </div>
  );
}
