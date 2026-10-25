"use client";

/**
 * My Automations > Auto Funnel — the mass-message funnels (a broadcast opener,
 * then reply-checked steps ending in a PPV) as their own My Automations page.
 *
 * Nothing new underneath: it is the legacy /automations "Mass funnels" tab
 * (`MassFunnelsTab` — list, editor, per-model Media, Start and the Reply
 * walking switch) on Infloww's legacy list page (page-parity ticket 16): the
 * creator column (`?creator=`) scopes it to one model, Learn and
 * "New funnel" sit in the header. The relay pre-adds the default "strokes"
 * funnel (seeds/funnels.py), so it is listed here and in the mass composer's
 * "Funnel follow-up" picker from the first boot. Funnel TEXT is shared by every
 * model; the PPV media is bound per model via Media.
 */

import { AiKeyNotice } from "@/components/AiKeyNotice";
import { NoCreator, useAutomationCreator } from "@/components/automations/automationPage";
import { MassFunnelsTab } from "@/components/automations/FunnelEditor";
import { PageFrame } from "@/components/shell/PageFrame";

const TITLE = "Auto Funnel";

export default function AutoFunnelPage() {
  const { accountId, creators, loading } = useAutomationCreator();

  if (!accountId) {
    return <PageFrame title={TITLE} creators={creators}>{!loading && <NoCreator />}</PageFrame>;
  }
  return (
    <MassFunnelsTab
      accountId={accountId}
      frame={(actions, body) => (
        <PageFrame title={TITLE} creators={creators} actions={actions}>
          <div className="space-y-4">
            <AiKeyNotice accountId={accountId} kinds={["reply_mass_funnel"]} />
            {body}
          </div>
        </PageFrame>
      )}
    />
  );
}
