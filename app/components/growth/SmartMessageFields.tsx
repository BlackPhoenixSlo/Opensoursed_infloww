"use client";

/**
 * The Smart Message settings our Trigger editors share (Purchased, the four
 * lifecycle Triggers, Delayed welcome), as Infloww's editor lays them out:
 * media with an optional price, "Frequency & scheduling" (Frequency, Effective,
 * Expiry), the Purchased / welcome "after delay" row and Auto-unsend. Labels
 * from `SM_EDITOR`; the Relay keeps the values as `service/smart_message_extras`
 * describes. Dates are entered in the Agency's report time zone (the browser's
 * when none is saved) and stored in UTC.
 *
 * Only the house differs where it says so: a paid message is never auto-unsent
 * (its late buyers are real money, and OnlyFans' per-chat unsend window is
 * about a day, so Auto-unsend stops at 23 hours), a price needs media and
 * stops at OnlyFans' $200 PPV ceiling.
 */

import { useState } from "react";

import { VaultPicker } from "@/components/chat/VaultPicker";
import { MediaTray } from "@/components/compose/MediaTray";
import { Input } from "@/components/ui/primitives";
import { useReportTimeZone } from "@/lib/appliedSettings";
import { VAULT_PICK_MAX, readPrice } from "@/lib/ofMirrorChat";
import { MIN_PRICE } from "@/lib/sendGuards";
import { type VaultMedia } from "@/lib/relay";
import { fromZonedInput, toZonedInput } from "@/lib/shifts";

import { SM_EDITOR as E } from "./smartMessagesControls";

export type Frequency = "once" | "every";

/** The settings as the config routes read and write them. */
export interface SmartExtras {
  media_ids: number[];
  price_cents: number;
  starts_at: string | null;
  ends_at: string | null;
  unsend_minutes: number;
  frequency?: Frequency;
  /** Purchased / welcome only: [a, b] minutes, null = "immediately". */
  delay_range?: [number, number] | null;
}

/** The settings as a rule's stored payload holds them (the welcome rule, and
 *  every rule the Automated Messages list reads), read without trusting it.
 *  `delay_range` is left out when the payload has none. */
export function extrasOfPayload(p: Record<string, unknown> | null | undefined): Partial<SmartExtras> {
  const int = (v: unknown) => (typeof v === "number" && Number.isInteger(v) && v > 0 ? v : 0);
  const stamp = (v: unknown) => (typeof v === "string" && !Number.isNaN(Date.parse(v)) ? v : null);
  const ids = Array.isArray(p?.media_ids) ? p.media_ids.filter((x): x is number => int(x) > 0) : [];
  const out: Partial<SmartExtras> = {
    media_ids: ids,
    price_cents: ids.length ? int(p?.price_cents) : 0,
    starts_at: stamp(p?.starts_at),
    ends_at: stamp(p?.ends_at),
    unsend_minutes: int(p?.unsend_minutes),
  };
  const r = p?.delay_range;
  if (p && "delay_range" in p) {
    out.delay_range = Array.isArray(r) && r.length === 2 && r.every((x) => Number.isInteger(x))
      ? clampDelay(r[0], r[1]) : null;
  }
  return out;
}

/** The form's state: media as tiles, dates as ISO (UTC), numbers as typed. */
export type ExtrasDraft = {
  media: VaultMedia[];
  price: string;
  frequency: Frequency;
  startsOn: boolean;
  startsAt: string | null;
  endsOn: boolean;
  endsAt: string | null;
  unsendOn: boolean;
  unsendH: string;
  unsendM: string;
  delayOn: boolean;
  delayA: string;
  delayB: string;
};

const DELAY_MIN = 1;
const DELAY_MAX = 60;
// Inside OnlyFans' ~24h per-chat delete window (smart_message_extras.UNSEND_MAX_MINUTES).
const UNSEND_MAX_H = 23;
/** OnlyFans' PPV ceiling, the Relay's `PRICE_MAX_CENTS`. */
export const MAX_PRICE = 200;
export const MAX_PRICE_NOTE = "Maximum $200 USD";

/** Infloww's `handleRuleDelayValues` (index.9f50f370.js @14775733): each end
 *  inside 1..60, in order, never equal (an equal pair widens by a minute; 60
 *  becomes 59～60). The Relay clamps the same way. */
export function clampDelay(a: number, b: number): [number, number] {
  let lo = Math.max(DELAY_MIN, Math.min(a, DELAY_MAX));
  let hi = Math.max(DELAY_MIN, Math.min(b, DELAY_MAX));
  if (lo > hi) [lo, hi] = [hi, lo];
  if (lo === hi) [lo, hi] = lo === DELAY_MAX ? [59, 60] : [lo, lo + 1];
  return [lo, hi];
}

/** The draft for a saved config. `delayDefault`: the range "after delay"
 *  offers when the config is on "immediately". */
export function extrasDraft(c: Partial<SmartExtras>, delayDefault: [number, number] = [1, 3]): ExtrasDraft {
  const unsend = c.unsend_minutes ?? 0;
  const delay = c.delay_range ?? null;
  return {
    media: (c.media_ids ?? []).map((id) => ({ id, type: "photo" }) as VaultMedia),
    price: c.price_cents ? String(c.price_cents / 100) : "",
    frequency: c.frequency ?? "once",
    startsOn: !!c.starts_at,
    startsAt: c.starts_at ?? null,
    endsOn: !!c.ends_at,
    endsAt: c.ends_at ?? null,
    unsendOn: unsend > 0,
    unsendH: String(Math.floor(unsend / 60)),
    unsendM: String(unsend % 60),
    delayOn: !!delay,
    delayA: String((delay ?? delayDefault)[0]),
    delayB: String((delay ?? delayDefault)[1]),
  };
}

const whole = (s: string) => (/^\d+$/.test(s.trim()) ? Number(s.trim()) : null);

/** The settings to save, or the line that says why they cannot be. `delay`:
 *  the Trigger has the "after delay" row; `frequency`: it has Frequency.
 *  `initial`: the draft the form opened on — an "after delay" row left as it
 *  was is not sent, so the Relay keeps what it stored (a Purchased rule's old
 *  fixed delay stays exactly as it was until a new range is picked). */
export function collectExtras(
  d: ExtrasDraft, opts: { delay?: boolean; frequency?: boolean; initial?: ExtrasDraft } = {},
): SmartExtras | string {
  const price = readPrice(d.price);
  if (price === null) return E.priceMin.label;
  if (price > MAX_PRICE) return MAX_PRICE_NOTE;
  if (price > 0 && !d.media.length) return "Add media to set a price";
  if (d.startsOn && !d.startsAt) return `Pick the ${E.effective.label} date`;
  if (d.endsOn && !d.endsAt) return `Pick the ${E.expiry.label} date`;
  const starts_at = d.startsOn ? d.startsAt : null;
  const ends_at = d.endsOn ? d.endsAt : null;
  if (starts_at && ends_at && Date.parse(ends_at) <= Date.parse(starts_at)) {
    return `The ${E.expiry.label} must come after the ${E.effective.label} date`;
  }
  let unsend_minutes = 0;
  if (d.unsendOn) {
    const h = whole(d.unsendH || "0");
    const m = whole(d.unsendM || "0");
    if (h === null || m === null || h > UNSEND_MAX_H || m > 59 || (h === UNSEND_MAX_H && m > 0) || h * 60 + m === 0) {
      return `Unsend after 1 minute to ${UNSEND_MAX_H} hours`;
    }
    unsend_minutes = h * 60 + m;
  }
  const out: SmartExtras = {
    media_ids: d.media.map((m) => m.id),
    price_cents: Math.round(price * 100),
    starts_at,
    ends_at,
    unsend_minutes,
  };
  if (opts.frequency) out.frequency = d.frequency;
  const i = opts.initial;
  const delayUntouched = !!i && i.delayOn === d.delayOn
    && (!d.delayOn || (i.delayA === d.delayA && i.delayB === d.delayB));
  if (opts.delay && !delayUntouched) {
    if (!d.delayOn) out.delay_range = null;
    else {
      const a = whole(d.delayA);
      const b = whole(d.delayB);
      if (a === null || b === null) return `The delay is whole minutes from ${DELAY_MIN} to ${DELAY_MAX}`;
      out.delay_range = clampDelay(a, b);
    }
  }
  return out;
}

const browserTz = () => Intl.DateTimeFormat().resolvedOptions().timeZone;

export function SmartMessageFields({
  accountId, id, draft, onChange, delay = false, frequency = false,
}: {
  accountId: string;
  /** The editor's id prefix, for the fields' labels. */
  id: string;
  draft: ExtrasDraft;
  onChange: (patch: Partial<ExtrasDraft>) => void;
  delay?: boolean;
  frequency?: boolean;
}) {
  const tz = useReportTimeZone(accountId) ?? browserTz();
  const [picking, setPicking] = useState(false);
  const price = readPrice(draft.price);
  const paid = !!price && price >= MIN_PRICE;

  return (
    <div className="space-y-4 text-sm">
      <div className="space-y-1">
        <span className="block">{E.media.label}</span>
        <MediaTray
          accountId={accountId}
          attached={draft.media}
          onChange={(media) => onChange({ media: media.slice(0, VAULT_PICK_MAX) })}
          onOpenVaultPicker={() => setPicking(true)}
        />
        {picking && (
          <VaultPicker
            open
            onClose={() => setPicking(false)}
            accountId={accountId}
            initialSelectedIds={draft.media.map((m) => m.id)}
            onConfirm={(picked) => { onChange({ media: picked.slice(0, VAULT_PICK_MAX) }); setPicking(false); }}
          />
        )}
        <div className="flex items-center gap-2">
          <label htmlFor={`${id}-price`}>{E.price.label}</label>
          <Input
            id={`${id}-price`}
            inputMode="decimal"
            placeholder="0"
            value={draft.price}
            onChange={(e) => onChange({ price: e.target.value })}
            className="!w-[110px]"
          />
          <span className="text-fg-dim">{E.priceMin.label}</span>
        </div>
      </div>

      {delay && (
        <div className="flex flex-wrap items-center gap-2">
          <label htmlFor={`${id}-delay`}>{E.sendToFans.label}</label>
          <select
            id={`${id}-delay`}
            value={draft.delayOn ? "on" : "off"}
            onChange={(e) => onChange({ delayOn: e.target.value === "on" })}
            className="bg-bg border border-border rounded-lg px-2 py-1"
          >
            <option value="off">{E.delayNone.label}</option>
            <option value="on">{E.delayOn.label}</option>
          </select>
          {draft.delayOn && (
            <>
              <span>{E.delayRandom.label}</span>
              <Input aria-label="Delay from (minutes)" type="number" min={DELAY_MIN} max={DELAY_MAX} value={draft.delayA}
                onChange={(e) => onChange({ delayA: e.target.value })} className="!w-[70px]" />
              <span>{E.delayTilde.label}</span>
              <Input aria-label="Delay to (minutes)" type="number" min={DELAY_MIN} max={DELAY_MAX} value={draft.delayB}
                onChange={(e) => onChange({ delayB: e.target.value })} className="!w-[70px]" />
              <span>{E.delayMinutes.label}</span>
            </>
          )}
          <span>{E.delayTail.label}</span>
        </div>
      )}

      <fieldset className="space-y-2">
        <legend className="font-medium">{E.scheduling.label}</legend>
        {frequency && (
          <div role="radiogroup" aria-label={E.frequency.label} className="space-y-1">
            <span className="block text-fg-dim">{E.frequency.label}</span>
            {(["once", "every"] as const).map((f) => (
              <label key={f} className="flex items-center gap-2">
                <input type="radio" name={`${id}-frequency`} checked={draft.frequency === f}
                  onChange={() => onChange({ frequency: f })} />
                {f === "once" ? E.once.label : E.every.label}
              </label>
            ))}
          </div>
        )}
        <DateChoice id={`${id}-starts`} title={E.effective.label} offLabel={E.immediately.label} tz={tz}
          on={draft.startsOn} iso={draft.startsAt}
          onChange={(on, iso) => onChange({ startsOn: on, startsAt: iso })} />
        <DateChoice id={`${id}-ends`} title={E.expiry.label} offLabel={E.never.label} tz={tz}
          on={draft.endsOn} iso={draft.endsAt}
          onChange={(on, iso) => onChange({ endsOn: on, endsAt: iso })} />
        <p className="text-[11px] text-fg-dim">Times in {tz}.</p>
      </fieldset>

      <fieldset className="space-y-1">
        <legend className="font-medium">{E.autoUnsend.label}</legend>
        <label className="flex items-center gap-2">
          <input type="checkbox" checked={draft.unsendOn} onChange={(e) => onChange({ unsendOn: e.target.checked })} />
          {E.unsend.label}
        </label>
        {draft.unsendOn && (
          <div className="flex flex-wrap items-center gap-2">
            <span>{E.unsendLead.label}</span>
            <Input aria-label="Unsend after (hours)" type="number" min={0} max={UNSEND_MAX_H} value={draft.unsendH}
              onChange={(e) => onChange({ unsendH: e.target.value })} className="!w-[70px]" />
            <span>{E.unsendHours.label}</span>
            <Input aria-label="Unsend after (minutes)" type="number" min={0} max={59} value={draft.unsendM}
              disabled={whole(draft.unsendH) === UNSEND_MAX_H}
              onChange={(e) => onChange({ unsendM: e.target.value })} className="!w-[70px]" />
            <span>{E.unsendMinutes.label}</span>
          </div>
        )}
        {draft.unsendOn && paid && (
          <p className="text-[11px] text-warn">A paid message is never unsent: only a free one is.</p>
        )}
      </fieldset>
    </div>
  );
}

/** Effective / Expiry: the bundle's two radios, "Immediately" / "Never" or
 *  "Scheduled date" with its date and time. */
function DateChoice({ id, title, offLabel, tz, on, iso, onChange }: {
  id: string; title: string; offLabel: string; tz: string;
  on: boolean; iso: string | null; onChange: (on: boolean, iso: string | null) => void;
}) {
  return (
    <div role="radiogroup" aria-label={title} className="flex flex-wrap items-center gap-3">
      <span className="w-[70px] text-fg-dim">{title}</span>
      <label className="flex items-center gap-1.5">
        <input type="radio" name={id} checked={!on} onChange={() => onChange(false, iso)} />
        {offLabel}
      </label>
      <label className="flex items-center gap-1.5">
        <input type="radio" name={id} checked={on} onChange={() => onChange(true, iso)} />
        {E.scheduledDate.label}
      </label>
      {on && (
        <input
          type="datetime-local"
          aria-label={`${title} date`}
          value={iso ? toZonedInput(iso, tz) : ""}
          onChange={(e) => onChange(true, fromZonedInput(e.target.value, tz))}
          className="bg-bg border border-border rounded-lg px-2 py-1"
        />
      )}
    </div>
  );
}
