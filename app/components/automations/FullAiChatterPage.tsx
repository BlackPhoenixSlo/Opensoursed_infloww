"use client";

/**
 * My AI Chatter > Full AI Chat (ours; owner only in the sidebar, same /full-ai-chatter address). A settings column
 * (`FullAiSettings`: on/off, LLM keys, reply speed, text like a girl, GIFs; Save / Roll back / JSON over the draft
 * config) with the persona editor (`ModelInfoBlock`, saved straight to the account, not into the checkpoint) under it;
 * beside it (above it on a phone: the column comes first) the owner's Test chat (`FullAiTestChat`: two windows,
 * checkpoint and draft, one composer; nothing reaches a Fan). Below, Full AI Chat in Shadow
 * (service/automations/full_ai_chat.py): each inbound DM on a Creator with the switch on gets one Decision row, what
 * the AI would do (its Route, Heat and the Route table row), and nothing is sent.
 *
 * The on/off switch (Shadow / Off) is `useSwitchKind` over kind `full_ai_chat`, saving the moment it flips (the
 * server creates the rule from its catalog the first time). Only the owner may write it (permissions.OPT_IN_KINDS).
 * The Test chat and the config share one reducer (`fullAiTestChat.ts`), held here through `useFullAiTestChat` (the
 * turns; its `config` = `useFullAiConfig`, the config reads and writes). Below, today's rows (`useFullAiToday`): counts
 * per Route in the Route table's order plus Jev failures, then the newest rows.
 */

import { FormBlock, NoCreator, useAutomationCreator } from "@/components/automations/automationPage";
import { FullAiSettings } from "@/components/automations/FullAiSettings";
import { FullAiTestChat } from "@/components/automations/FullAiTestChatWindows";
import { ModelInfoBlock } from "@/components/automations/ModelInfoBlock";
import type { CreatorPick } from "@/components/shell/CreatorRail";
import { PageFrame } from "@/components/shell/PageFrame";
import { IF_TABLE } from "@/components/ui/infloww";
import { useAutomationRules, useSwitchKind } from "@/hooks/useAutomations";
import { useFullAiTestChat } from "@/hooks/useFullAiTestChat";
import { ROUTES, useFullAiToday, type Route } from "@/hooks/useFullAiToday";
import { cn } from "@/lib/utils";

const TITLE = "Full AI Chat";
const PERSONA_NOTE = "Saves for every live chat on this Creator now (not part of the checkpoint)";
const KIND = "full_ai_chat";

const ROUTE_LABEL: Record<Route, string> = {
  chat: "Chat", sext: "Sext", sell_now: "Sell now", tease: "Tease",
  make_right: "Make right", ai_dare: "AI dare", no_send: "No send",
};

const CELL = cn(IF_TABLE.td, "whitespace-nowrap py-2");
const HEAD = cn(IF_TABLE.th, IF_TABLE.thDivider);

export default function FullAiChatterPage() {
  const { accountId, creators, loading } = useAutomationCreator();
  if (!accountId) {
    return <PageFrame title={TITLE} creators={creators}><NoCreator loading={loading} /></PageFrame>;
  }
  // Keyed, so a switch in flight can never land on the next creator, and a new Creator starts a new Test chat.
  return <FullAiChatter key={accountId} accountId={accountId} creators={creators} />;
}

function FullAiChatter({ accountId, creators }: { accountId: string; creators: CreatorPick }) {
  const rulesQ = useAutomationRules(accountId);
  const switchKind = useSwitchKind(accountId);
  const todayQ = useFullAiToday(accountId);
  const chat = useFullAiTestChat(accountId);
  // Shadow = a running full_ai_chat row. No rows read yet → the switch is disabled rather than claiming "Off".
  const on = (rulesQ.data ?? []).some((r) => r.kind === KIND && r.is_enabled);
  const today = todayQ.data;

  const power = {
    on, disabled: !rulesQ.isSuccess, loading: switchKind.isPending,
    onChange: (enable: boolean) => switchKind.mutate({ kind: KIND, enable }),
  };

  return (
    <PageFrame title={TITLE} creators={creators}>
      <div className="grid max-w-[1320px] gap-8 lg:grid-cols-[340px_minmax(0,1fr)]">
        <aside className="min-w-0 space-y-8">
          <FormBlock title="Settings">
            <div className="space-y-2">
              <p className="text-[14px] text-fg">
                Shadow: for every DM a fan sends, records what the AI would do. Nothing is sent.
              </p>
              {rulesQ.isLoadingError && (
                <p className="text-[12px] text-err">
                  Couldn&apos;t read this creator&apos;s automations, so this can&apos;t say whether Full AI Chat is on.
                </p>
              )}
              {switchKind.isError && (
                <p className="text-[12px] text-err">
                  {switchKind.error?.message || "Couldn't switch Full AI Chat."} Try again.
                </p>
              )}
            </div>
            <FullAiSettings state={chat.state} cfg={chat.config} power={power} />
          </FormBlock>
          <ModelInfoBlock accountId={accountId} draftFromImages saveNote={PERSONA_NOTE} />
        </aside>
        <div className="min-w-0 space-y-8">
          <FormBlock title="Test chat">
            <p className="text-[12px] text-muted">
              Type as a fan. Checkpoint answers with the saved config, Draft with your draft. Nothing is sent on OnlyFans.
            </p>
            <FullAiTestChat chat={chat} />
          </FormBlock>

          <FormBlock title="Today">
            {todayQ.isError && <p className="text-[12px] text-err">Couldn&apos;t read today&apos;s decisions.</p>}
            <ul aria-label="Decisions per route" className="flex flex-wrap gap-2">
              {ROUTES.map((route) => (
                <li key={route} className="min-w-[96px] rounded-lg border border-border px-3 py-2">
                  <div className="text-[12px] text-muted">{ROUTE_LABEL[route]}</div>
                  <div className="text-[18px] font-semibold text-fg tabular-nums">{today?.counts[route] ?? "–"}</div>
                </li>
              ))}
              <li className="min-w-[96px] rounded-lg border border-err/40 px-3 py-2">
                <div className="text-[12px] text-muted">Jev failed</div>
                <div className="text-[18px] font-semibold text-fg tabular-nums">{today?.jev_failed ?? "–"}</div>
              </li>
            </ul>
            {today && (
              <p className="text-[12px] text-muted">Since {new Date(today.since).toLocaleString()}</p>
            )}
          </FormBlock>

          <FormBlock title="Newest">
            {today && today.rows.length === 0 && (
              <p className="text-[14px] text-fg-dim">No decisions yet today.</p>
            )}
            {today && today.rows.length > 0 && (
              <div className="overflow-x-auto">
                <table className={IF_TABLE.table}>
                  <thead>
                    <tr>
                      {["Time", "Fan", "Route", "Heat", "Row", "Jev"].map((h) => <th key={h} className={HEAD}>{h}</th>)}
                    </tr>
                  </thead>
                  <tbody>
                    {today.rows.map((r) => (
                      <tr key={r.id} className={IF_TABLE.row} data-testid="full-ai-row">
                        <td className={CELL}>{new Date(r.created_at).toLocaleTimeString()}</td>
                        <td className={CELL}>{r.fan_name ?? `Fan ${r.fan_id}`}</td>
                        <td className={CELL}>{ROUTE_LABEL[r.route]}</td>
                        <td className={cn(CELL, "tabular-nums")}>{r.heat}</td>
                        <td className={cn(CELL, "text-fg-dim")}>{r.row}</td>
                        <td className={cn(CELL, "tabular-nums", r.jev_failed && "text-err")}>
                          {r.jev_failed ? "Jev failed" : r.jev_ms == null ? "–" : `${r.jev_ms} ms`}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </FormBlock>
        </div>
      </div>
    </PageFrame>
  );
}
