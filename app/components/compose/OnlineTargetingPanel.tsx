"use client";

/**
 * OnlineTargetingPanel — the Mass Online live-targeting fields
 * (MassMessageComposer mode "online"). These resolve server-side:
 * online_only + the chosen audience list = fans online now; unread / recent
 * ADD fans; the excludes drop recently-touched fans; auto-unsend schedules a
 * delayed DELETE. Pure view over the form's string fields (blank = not
 * applied; massMessageReducer `buildMassBody` forwards positive numbers only).
 */

import { ExtraTag } from "@/components/ui/primitives";
import { EXTRA_LABEL } from "@/lib/openinflowwwwExtras";

import type { MassField, MassForm } from "./massMessageReducer";

type OnlineField = Extract<
  MassField,
  | "onlineOnly" | "unreadLimit" | "recentChatHours" | "recentChatLimit" | "excludeRepliedHours"
  | "excludeInboundHours" | "unsendAfterHours" | "minTotalSpent" | "minTipped" | "subscribedOverDays"
  | "expiredOverDays"
>;

export function OnlineTargetingPanel({
  form, set, onlineCount, labelExtras, isScheduled,
}: {
  form: Pick<MassForm, OnlineField>;
  set: <K extends OnlineField>(k: K) => (v: MassForm[K]) => void;
  /** OnlyFans' online subscribers count label, null while unknown. */
  onlineCount: string | null;
  /** Tag Auto-unsend as an "Inflowwww extra" (MassMessageComposer `labelExtras`). */
  labelExtras: boolean;
  isScheduled: boolean;
}) {
  const {
    onlineOnly, unreadLimit, recentChatHours, recentChatLimit, excludeRepliedHours, excludeInboundHours,
    unsendAfterHours, minTotalSpent, minTipped, subscribedOverDays, expiredOverDays,
  } = form;
  // Thresholds (Infloww's Total spent / Tipped over / Subscribed over / Expired
  // over). Any one set makes the relay send to the qualifying fans' ids only.
  const hasThresholds = [minTotalSpent, minTipped, subscribedOverDays, expiredOverDays]
    .some((v) => Number(v) > 0);

  return (
    <div className="border border-accent/30 bg-accent/5 rounded-md p-3 space-y-3">
      <div className="text-[11px] uppercase tracking-wide text-accent">
        Online targeting
      </div>

      <label className="flex items-center gap-2 text-xs cursor-pointer select-none">
        <input
          type="checkbox"
          checked={onlineOnly}
          onChange={(e) => set("onlineOnly")(e.target.checked)}
        />
        <span className="font-medium">Only fans online right now</span>
        <span className="text-fg-dim">(OF resolves at send time)</span>
        {onlineCount != null && (
          <span className="ml-auto text-accent" title="OnlyFans' online subscribers list, re-read every minute">
            {onlineCount} online now
          </span>
        )}
      </label>

      <div className="grid grid-cols-2 gap-2">
        <NumField label="Total spent over" suffix="$" value={minTotalSpent}
          onChange={set("minTotalSpent")} placeholder="e.g. 50" />
        <NumField label="Tipped over" suffix="$" value={minTipped}
          onChange={set("minTipped")} placeholder="e.g. 20" />
        <NumField label="Subscribed over" suffix="N days" value={subscribedOverDays}
          onChange={set("subscribedOverDays")} placeholder="e.g. 30" />
        <NumField label="Expired over" suffix="N days" value={expiredOverDays}
          onChange={set("expiredOverDays")} placeholder="online-only off" />
      </div>

      <div className="grid grid-cols-2 gap-2">
        <NumField
          label="Include fans with unread msgs"
          suffix="up to N"
          value={unreadLimit}
          onChange={set("unreadLimit")}
          placeholder="e.g. 100"
        />
        <NumField
          label="Include chatted-with"
          suffix="last N hrs"
          value={recentChatHours}
          onChange={set("recentChatHours")}
          placeholder="e.g. 2"
        />
        <NumField
          label="…cap recent-chat to"
          suffix="N fans"
          value={recentChatLimit}
          onChange={set("recentChatLimit")}
          placeholder="(optional)"
        />
        <div />
        <NumField
          label="Exclude I replied to"
          suffix="last N hrs"
          value={excludeRepliedHours}
          onChange={set("excludeRepliedHours")}
          placeholder="e.g. 2"
        />
        <NumField
          label="Exclude who messaged me"
          suffix="last N hrs"
          value={excludeInboundHours}
          onChange={set("excludeInboundHours")}
          placeholder="e.g. 2"
        />
      </div>

      <div className="pt-2 border-t border-accent/20">
        <NumField
          label="Auto-unsend this broadcast after"
          suffix="N hrs"
          value={unsendAfterHours}
          onChange={set("unsendAfterHours")}
          placeholder="leave blank to keep it"
          extra={labelExtras}
        />
        {isScheduled && unsendAfterHours.trim() !== "" && (
          <div className="text-[10px] text-warn mt-1">
            Auto-unsend applies to immediate sends only — ignored when scheduled.
          </div>
        )}
      </div>

      <div className="text-[10px] text-fg-dim leading-relaxed">
        {hasThresholds
          ? <>Thresholds set: the audience is the fans on the lists above
            {onlineOnly ? " who are online right now and" : " who"} clear every one,
            sent as at most 1,000 fan ids. Expired over reads Fans / Following as
            your expired fans. Online-only sends go now, not scheduled.</>
          : <>Audience = the lists above, filtered to online{onlineOnly ? "" : " (off)"}.</>}
        {" "}Unread / chatted-with ADD fans; the two excludes remove fans you
        touched recently. Counts are resolved by the server at send time.
      </div>
    </div>
  );
}

/** Compact labelled numeric input for the Online-targeting panel. Blank = the
 *  filter isn't applied; the parent only forwards positive numbers. */
function NumField({
  label, suffix, value, onChange, placeholder, extra = false,
}: {
  label: string;
  suffix: string;
  value: string;
  onChange: (v: string) => void;
  placeholder?: string;
  /** Carries the "Inflowwww extra" tag and tooltip. */
  extra?: boolean;
}) {
  return (
    <label className="flex flex-col gap-1 text-[11px] text-fg-dim" title={extra ? EXTRA_LABEL : undefined}>
      <span className="leading-tight">
        {label} <span className="opacity-60">({suffix})</span>
        {extra && <> <ExtraTag /></>}
      </span>
      <input
        type="text"
        inputMode="numeric"
        value={value}
        onChange={(e) => onChange(e.target.value.replace(/[^0-9.]/g, ""))}
        placeholder={placeholder}
        className="bg-bg border border-border rounded-md px-2 py-1.5 text-base md:text-xs text-fg focus:outline-none focus:border-accent"
      />
    </label>
  );
}
