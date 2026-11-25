"use client";


import type { AutomationRule } from "@/hooks/useAutomations";
import { boolKnob } from "@/lib/boolKnob";

export function isDryRun(rule: AutomationRule | null | undefined): boolean {
    // inverted default: absent key = dry run, only explicit false is live; re-deriving it per component drifts toward real sends
  return boolKnob(rule?.payload?.dry_run, true);
}


export interface StatChunk {
  text: string;
  tone?: "err" | "warn";
}

function followBackChunks(
  stats: Record<string, unknown>,
  n: (k: string) => number | null,
): StatChunk[] {
    // absent (older relay) is not off: the run can't say, so report nothing
  if (stats.follow_back !== true) return [];
  const out: StatChunk[] = [];
    // dry tick follows nobody: counters are structural zeroes, so state only what would happen
  if (stats.dry_run === true) {
    out.push(stats.follow_back_gate === false
      ? { text: "follow-back gate off — a live run would follow blind", tone: "warn" }
      : { text: "follow-back would run (dry)", tone: "warn" });
    return out;
  }
  const back = n("followed_back") ?? 0;
  const already = n("follow_back_already") ?? 0;
  const paid = n("follow_back_paid_skipped") ?? 0;
  const noPrice = n("follow_back_no_price") ?? 0;
  const failed = n("follow_back_errors") ?? 0;
    // MONEY: nothing read these fans' prices, so follows fired unpriced and may have bought subscriptions
  if (stats.follow_back_gate === false) {
    out.push({
      text: back
        ? `follow-back gate OFF — ${back} follow-backs charged blind`
        : "follow-back gate OFF — paid subscribers WILL be charged",
      tone: "err",
    });
  }
  const sent = n("welcomes_sent");
  if (sent || back || already || paid || noPrice || failed) {
    out.push({ text: `followed back ${back}`, tone: back === 0 ? "warn" : undefined });
  }
  if (already) out.push({ text: `${already} already followed back` });
  if (paid) out.push({ text: `${paid} paid subs not followed back` });
  if (noPrice) out.push({ text: `${noPrice} follow-back prices unreadable` });
  if (failed) out.push({ text: `${failed} follow-backs failed`, tone: "err" });
  return out;
}

// Kinds emit disjoint stats bags: don't add welcome keys here; a formatter answering for every kind answers for none (a welcome tick with 9 errors rendered "ok")
export function runStatsChunks(stats?: Record<string, unknown> | null): StatChunk[] {
  if (!stats) return [];
  const n = (k: string) => (typeof stats[k] === "number" ? (stats[k] as number) : null);
  const len = (k: string) => (Array.isArray(stats[k]) ? (stats[k] as unknown[]).length : null);
  const out: StatChunk[] = [];
  const errors = n("errors");
  if (errors) out.push({ text: `${errors} failed`, tone: "err" });
    // errors first: a follow tick that threw printed "ok" like a quiet healthy day
  const ungated = stats.money_gate === false;
    // only the gate-running preview emits no_price_skipped; an older relay fills would_follow with the un-gated pool, and money_gate-off previews emit examined too
  const gated = n("no_price_skipped") !== null;
  const wouldNotify = gated || ungated ? (len("would_follow") ?? len("would_ping")) : null;
    // MONEY: ungated run reads no profile, so only "will be charged" can be said; ahead of plan chunks
  if (ungated) {
    const charged = n("unpriced_follows") ?? wouldNotify ?? n("followed");
    out.push({
      text: charged !== null
        ? `money gate OFF — ${charged} follows will be charged`
        : "money gate OFF — paid profiles WILL be charged",
      tone: "err",
    });
  }
  if (wouldNotify !== null) {
    out.push({
      text: `${wouldNotify} would notify`,
      tone: wouldNotify === 0 ? "warn" : undefined,
    });
  }
  const liked = n("liked");
  if (liked !== null) out.push({ text: `liked ${liked}` });
  const pinged = n("pinged");
  if (pinged !== null) out.push({ text: `pinged ${pinged}` });
  const stranded = n("stranded");
  if (stranded) out.push({ text: `${stranded} stranded (unfollowed, re-follow failed)`, tone: "err" });
  const followed = n("followed");
  if (followed !== null) out.push({ text: `followed ${followed}` });
  const refollowed = n("refollowed");
  if (refollowed) out.push({ text: `re-followed ${refollowed}` });
  const already = n("already_following");
  if (already) out.push({ text: `${already} already followed`, tone: "warn" });
    // pool_exhausted covers the headroom-truncated slice (cap x 5 fans), so it means "this batch", not the whole pool
  if (stats.pool_exhausted === true) {
    out.push({ text: "nobody new to notify in this batch", tone: "warn" });
  }
  const paid = n("paid_profile_skipped");
  if (paid) out.push({ text: `${paid} paid profiles skipped` });
  const noPrice = n("no_price_skipped");
  if (noPrice) out.push({ text: `${noPrice} price unreadable, skipped` });
  const reactivated = n("reactivated");
  if (reactivated !== null) out.push({ text: `re-created ${reactivated}` });
  const due = n("due");
  if (due !== null) out.push({ text: `${due} due` });
  if (stats.skipped === "of_unreachable") {
    out.push({ text: "OnlyFans unreachable, stood down", tone: "warn" });
  }
  const candidates = n("candidates");
  const examined = n("examined");
  if (candidates !== null) {
    out.push({
      text: examined !== null && examined < candidates
        ? `${examined} of ${candidates} candidates checked`
        : `${candidates} candidates`,
    });
  }
  const dry = stats.dry_run === true;
  const eligible = n("eligible");
  const stacked = typeof stats.source === "string" && stats.source.includes(",");
    // stacked leg only renders STORED last_run rows written before the relay emitted eligible for single-source rules only; delete once none can be on screen
  if (eligible !== null && (stacked || (candidates !== null && eligible > candidates))) {
    const pool = stacked ? `${eligible} eligible in the backfill pool` : `${eligible} eligible`;
    out.push({
      text: dry
        ? `${pool} — a dry run re-checks this same head each tick`
        : `${pool} still to walk`,
      tone: dry ? "warn" : undefined,
    });
  }
  return out;
}

export function welcomeStatsChunks(stats?: Record<string, unknown> | null): StatChunk[] {
  if (!stats) return [];
  const n = (k: string) => (typeof stats[k] === "number" ? (stats[k] as number) : null);
  const out: StatChunk[] = [];
    // errors first: the executor finalises a paced welcome run as ok even when every fan threw, so this is the only place a failed tick shows
  const errors = n("errors");
  if (errors) out.push({ text: `${errors} failed`, tone: "err" });
  const sent = n("welcomes_sent");
  if (sent !== null) {
    out.push({ text: `welcomed ${sent}`, tone: sent === 0 ? "warn" : undefined });
  }
  const fresh = n("new_subscribers");
  if (fresh !== null) out.push({ text: `${fresh} new subs` });
  out.push(...followBackChunks(stats, n));
  const skips: [string, string][] = [
    ["skipped_existing", "already welcomed"],
    ["skipped_cooldown", "on cooldown"],
    ["skipped_guard", "outside the new-sub window"],
    ["skipped_restricted", "restricted from automations"],
    ["skipped_audience", "outside the audience"],
    ["skipped_locked", "locked by another tick"],
  ];
  for (const [key, label] of skips) {
    const v = n(key);
    if (v) out.push({ text: `${v} ${label}` });
  }
  if (stats.batch_capped === true) out.push({ text: "batch cap hit", tone: "warn" });
  const aborted = n("aborted_on_reply");
  if (aborted) out.push({ text: `${aborted} stopped, he replied` });
  const handoff = n("handoff_enqueued");
  if (handoff) out.push({ text: `${handoff} handed to the chat engine` });
  const guardOff = n("reply_guard_off");
  if (guardOff) out.push({ text: `${guardOff} sent without the reply guard`, tone: "warn" });
  return out;
}

export function RunStats(
  { stats, kind }: { stats?: Record<string, unknown> | null; kind?: "send_welcome" },
) {
  const chunks = kind === "send_welcome" ? welcomeStatsChunks(stats) : runStatsChunks(stats);
  return (
    <>
      {chunks.map((c, i) => (
        <span key={i} className={c.tone === "err" ? "text-err" : c.tone === "warn" ? "text-warn" : undefined}>
          {" · "}{c.text}
        </span>
      ))}
      {stats?.dry_run ? <span> · dry run</span> : null}
    </>
  );
}
