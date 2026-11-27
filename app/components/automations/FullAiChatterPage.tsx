"use client";

/**
 * The My Automations sidebar link for Full AI Chat (/full-ai-chatter) is hidden from chatter-only sessions. Roles granted the page can open it.
 * The header's "AI rules" opens the Full AI Turn diagram (`AiRulesDiagram`, also at /ai-rules) in a near full-screen popup. A settings column
 * (`FullAiSettings`: Make draft live / Roll back / JSON over the draft config on top, then Mode, LLM keys, reply speed, Human
 * style, GIFs, Sell); beside it (under it on a phone: the column comes first) one row with the persona editor
 * (`ModelInfoBlock`, saved straight to the account, not into the checkpoint) and, beside that, "Who Full AI answers
 * when Live" (`FullAiAudience`: Fans, Top spend limit; its own write) over "Content" (Content folders, which
 * edits the draft, and Prepare content; `FullAiSellSettings.tsx`), then the owner's Test chat (`FullAiTestChat`: two
 * windows, checkpoint and draft, one composer; nothing reaches a Fan). Below, today's Decision rows (live, a legacy Shadow
 * rule's, and the Test chat's): each Turn's Route, Heat and the Route table row.
 *
 * The Mode control (Off / Live, `FullAiModeControl` over GET / PUT /admin/full-ai/mode, ticket 74): Live asks to
 * confirm, then replies go to the Fans on its Fans list on OnlyFans; Off drops the queued replies. A legacy rule with
 * no Mode reads "Shadow (records only)". Only the owner may write it (permissions.OPT_IN_KINDS).
 * The Test chat and the config share one reducer (`fullAiTestChat.ts`), held here through `useFullAiTestChat` (the
 * turns; its `config` = `useFullAiConfig`, the config reads and writes). Below, today's rows (`useFullAiToday`): counts
 * per Route in the Route table's order plus Jev failures, then the newest rows; Test chat Turns count too and list as
 * "Test chat". Under it the Revenue block (`FullAiRevenue`, live rows only): $ per enrolled Fan and offers per Route,
 * with the honesty line, never a comparison it cannot make.
 */

import { useState } from "react";

import { AiRulesDiagram } from "@/components/automations/AiRulesPage";
import { FormBlock, NoCreator, useAutomationCreator } from "@/components/automations/automationPage";
import { AUDIENCE_TITLE, FullAiAudience } from "@/components/automations/FullAiFans";
import { FullAiRevenue } from "@/components/automations/FullAiRevenue";
import { ContentFoldersRow, PrepareRow } from "@/components/automations/FullAiSellSettings";
import { FullAiSettings } from "@/components/automations/FullAiSettings";
import { canEdit } from "@/components/automations/fullAiTestChat";
import { FullAiTestChat } from "@/components/automations/FullAiTestChatWindows";
import { ModelInfoBlock } from "@/components/automations/ModelInfoBlock";
import type { CreatorPick } from "@/components/shell/CreatorRail";
import { PageFrame } from "@/components/shell/PageFrame";
import { useGrantedPages } from "@/components/shell/useGrantedPages";
import { IF_BTN } from "@/components/settings/ifButton";
import { IF_TABLE, IfModal } from "@/components/ui/infloww";
import { useFullAiTestChat } from "@/hooks/useFullAiTestChat";
import { ROUTE_LABEL, ROUTES, useFullAiToday } from "@/hooks/useFullAiToday";
import { useAppliedSettings } from "@/lib/appliedSettings";
import { deniedPage } from "@/lib/nav";
import { cn } from "@/lib/utils";

const TITLE = "Full AI Chat";
const PERSONA_NOTE = "Saves for every live chat on this Creator now (not part of the Live settings / Draft)";

const CELL = cn(IF_TABLE.td, "whitespace-nowrap py-2");
const HEAD = cn(IF_TABLE.th, IF_TABLE.thDivider);

export default function FullAiChatterPage() {
  const { accountId, creators, loading } = useAutomationCreator();
  if (!accountId) {
    return <PageFrame title={TITLE} creators={creators} actions={<AiRulesButton />}><NoCreator loading={loading} /></PageFrame>;
  }
  // Keyed, so a switch in flight can never land on the next creator, and a new Creator starts a new Test chat.
  return <FullAiChatter key={accountId} accountId={accountId} creators={creators} />;
}

// Its read answers to the /ai-rules grant, not this page's: hidden for a role denied /ai-rules (the Relay refuses it either way).
function AiRulesButton() {
  const [open, setOpen] = useState(false);
  const pending = useAppliedSettings().isPending;
  const denied = deniedPage("/ai-rules", useGrantedPages()) !== null;
  if (pending || denied) return null;
  return (
    <>
      <button type="button" className={IF_BTN} onClick={() => setOpen(true)}>AI rules</button>
      {open && (
        <IfModal title="AI rules" width={1600} className="h-[calc(var(--vvh,100dvh)-32px)]" onClose={() => setOpen(false)}>
          <AiRulesDiagram fill />
        </IfModal>
      )}
    </>
  );
}

function FullAiChatter({ accountId, creators }: { accountId: string; creators: CreatorPick }) {
  const todayQ = useFullAiToday(accountId);
  const chat = useFullAiTestChat(accountId);
  const today = todayQ.data;

  return (
    <PageFrame title={TITLE} creators={creators} actions={<AiRulesButton />}>
      <div className="grid max-w-[1320px] gap-8 lg:grid-cols-[340px_minmax(0,1fr)]">
        <aside className="min-w-0 space-y-8">
          <FormBlock title="Settings">
            <FullAiSettings state={chat.state} cfg={chat.config}
              accountId={accountId} />
          </FormBlock>
        </aside>
        <div className="min-w-0 space-y-8">
          {/* Who the Creator is, who Live answers and what she may sell, above the Test chat. Side by side only when
              each gets 340px (the settings column's width); stacked on a narrower column and on a phone. */}
          <div className="grid gap-8 grid-cols-[repeat(auto-fit,minmax(min(340px,100%),1fr))]">
            <ModelInfoBlock accountId={accountId} draftFromImages saveNote={PERSONA_NOTE} />
            <div className="min-w-0 space-y-8">
              <FormBlock title={AUDIENCE_TITLE}>
                <FullAiAudience accountId={accountId} state={chat.state} cfg={chat.config} />
              </FormBlock>
              <FormBlock title="Content">
                <ContentFoldersRow accountId={accountId} draft={chat.state.draft} off={!canEdit(chat.state)} cfg={chat.config} />
                <PrepareRow accountId={accountId} />
              </FormBlock>
            </div>
          </div>
          <FormBlock title="Test chat">
            <p className="text-[12px] text-muted">
              Type as a fan. Left answers with the Live settings (what fans get), right with your Draft. Nothing is sent on OnlyFans.
            </p>
            <FullAiTestChat chat={chat} accountId={accountId} />
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
              <p className="text-[12px] text-muted">Since {new Date(today.since).toLocaleString()} (includes Test chat)</p>
            )}
          </FormBlock>

          <FormBlock title="Revenue">
            <FullAiRevenue accountId={accountId} />
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
                        <td className={CELL}>{r.test ? "Test chat" : r.fan_name ?? `Fan ${r.fan_id}`}{r.live && " · Live"}</td>
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
