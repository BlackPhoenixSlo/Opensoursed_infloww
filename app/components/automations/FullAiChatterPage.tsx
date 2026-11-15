"use client";

/**
 * Full AI Chat (ours; owner only, a top-level sidebar link, same /full-ai-chatter address). The header's "AI rules"
 * opens the Full AI Turn diagram (`AiRulesDiagram`, also at /ai-rules) in a near full-screen popup. A settings column
 * (`FullAiSettings`: Mode, LLM keys, reply speed, Human style, GIFs, Sell, Content folders, Prepare content; Save /
 * Roll back / JSON over the draft
 * config) with the persona editor (`ModelInfoBlock`, saved straight to the account, not into the checkpoint) under it;
 * beside it (above it on a phone: the column comes first) the owner's Test chat (`FullAiTestChat`: two windows,
 * checkpoint and draft, one composer; nothing reaches a Fan). Below, today's Decision rows (live, a legacy Shadow
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
import { FullAiRevenue } from "@/components/automations/FullAiRevenue";
import { FullAiSettings } from "@/components/automations/FullAiSettings";
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
const PERSONA_NOTE = "Saves for every live chat on this Creator now (not part of the checkpoint)";

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

/** The header's "AI rules": the diagram in a popup over this page (X, Escape), near full-screen on a phone too.
 *  Its read answers to the /ai-rules page grant, not this page's: hidden while the Applied settings read is pending
 *  and for a role that is denied /ai-rules (the Relay refuses it either way). */
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
            <p className="text-[14px] text-fg">
              Live: replies to the fans on its Fans list on OnlyFans. Off: sends nothing.
            </p>
            <FullAiSettings state={chat.state} cfg={chat.config}
              accountId={accountId} />
          </FormBlock>
          <ModelInfoBlock accountId={accountId} draftFromImages saveNote={PERSONA_NOTE} />
        </aside>
        <div className="min-w-0 space-y-8">
          <FormBlock title="Test chat">
            <p className="text-[12px] text-muted">
              Type as a fan. Checkpoint answers with the saved config, Draft with your draft. Nothing is sent on OnlyFans.
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
