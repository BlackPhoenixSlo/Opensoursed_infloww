/**
 * The OS notice an SSE frame becomes — one shape, three parsers (design.md
 * B3): this page (toastStore's lanes → `noticeOf`), the desktop app's stream
 * (desktop/lib/relay-notices.js) and the relay's Web Push
 * (service/push_notice.py). The table is `service/tests/fixtures/
 * notice_cases.json`, the expectations taken from THIS side's output; each
 * other parser's test reads the same file, so whichever drifts goes red.
 */
import { readFileSync, writeFileSync } from "node:fs";
import { join } from "node:path";

import { describe, expect, it } from "vitest";

import { dmArrival, noticeOf, purchaseArrival, toastArrival, type Arrival } from "@/components/toastStore";
import { resolveChatTarget, type ChatMessageEvent } from "@/hooks/useInboxRealtime";
import { isValidFanId } from "@/lib/fanId";
import { DEFAULT_NOTIF_SETTINGS, type NotifSettings } from "@/lib/notifSettings";
import { pushTypes } from "@/lib/pushPrefs";

interface Notice { id: string; typeKey: string | null; title: string; body: string; href: string | null }
interface Case { name: string; frame: Record<string, unknown>; settings?: Partial<NotifSettings>; expect: Notice[] | null }

const FIXTURE = join(__dirname, "..", "..", "service", "tests", "fixtures", "notice_cases.json");
const fixture = JSON.parse(readFileSync(FIXTURE, "utf8")) as { note: string; cases: Case[] };

/** The arrivals each lane of useNotificationDelta delivers for a frame. */
function arrivals(frame: Record<string, unknown>): Arrival[] {
  const aid = typeof frame.__account_id === "string" ? frame.__account_id : null;
  if ("api2_chat_message" in frame) {
    const t = resolveChatTarget(frame as ChatMessageEvent);
    return t && !t.isOutbound ? [dmArrival(t)] : [];
  }
  if ("purchase_notified" in frame) {
    const p = frame.purchase_notified as { notif_id?: string; fan_id?: unknown };
    return aid && p?.notif_id && isValidFanId(p.fan_id)
      ? [purchaseArrival(aid, { ...p, notif_id: p.notif_id, fan_id: p.fan_id }, null)]
      : [];
  }
  if (aid && Array.isArray(frame.toasts)) {
    return frame.toasts.map((raw) => toastArrival(aid, raw)).filter((a): a is Arrival => a !== null);
  }
  return [];
}

/** The OS notices that pass the per-type gate (push and the desktop app skip a type with no key). */
function notices(c: Case): Notice[] {
  const s: NotifSettings = {
    ...DEFAULT_NOTIF_SETTINGS, ...c.settings, toast: { ...DEFAULT_NOTIF_SETTINGS.toast, ...c.settings?.toast },
  };
  const types: string[] = pushTypes(s);
  return arrivals(c.frame)
    .filter((a) => a.typeKey !== null && types.includes(a.typeKey))
    .map((a) => {
      const n = noticeOf(a);
      return { id: n.id, typeKey: a.typeKey, title: n.title, body: n.body, href: n.href ?? null };
    });
}

// UPDATE_NOTICE_FIXTURE=1: rewrite every `expect` from this side's output (review the diff).
if (process.env.UPDATE_NOTICE_FIXTURE) {
  for (const c of fixture.cases) c.expect = notices(c);
  writeFileSync(FIXTURE, JSON.stringify(fixture, null, 2) + "\n");
}

describe("notice_cases.json — the page's notices", () => {
  it("covers every case kind", () => {
    expect(fixture.cases.length).toBeGreaterThanOrEqual(15);
  });

  for (const c of fixture.cases) {
    it(c.name, () => {
      expect(notices(c)).toEqual(c.expect);
    });
  }
});
