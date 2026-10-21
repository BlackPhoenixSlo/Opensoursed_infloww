"use client";

/**
 * DiscountSubmenu — the Avatar menu's "Special offers ▸" (04-messages-pro.md
 * M6, roadmap 4.5): OF's "Give user a discount" for this Fan, in the menu box
 * as "Add to lists ▸" is. A percent (5 up to what keeps the price above OF's
 * floor, by 5), 1..12 months, the price it leaves, then Clear (only while a
 * discount is set) and Apply: PUT /subscriptions/{fan}/discount
 * {discount, period}, Clear sending {0, 1}. The rules and the write are the OF
 * mirror's (`lib/fanDiscount`). Infloww's Free trial and Promotional offer are
 * not here: their request bodies are unverified.
 */

import { useState } from "react";
import { useQueryClient } from "@tanstack/react-query";

import { cn } from "@/lib/utils";
import { MP } from "@/lib/messagesPro";
import type { FanId } from "@/lib/fanId";
import { ofUserFullKey } from "@/hooks/useOFUser";
import {
  DISCOUNT_PERIODS, discountPercents, discountSummary, MIN_DISCOUNT, months, offListDiscount, putFanDiscount,
} from "@/lib/fanDiscount";
import { MENU_ROW } from "./MenuParts";

const SELECT = "ml-auto bg-bg border border-border rounded text-fg";

export function DiscountSubmenu({
  accountId, fanId, price, current, currentPeriod, onFlash, onBack,
}: {
  accountId: string;
  fanId: FanId;
  /** The Creator's subscription price in dollars (OF's /users/me). */
  price: number;
  /** The Fan's discount now (`subscribedOnData.discountPercent`), 0 for none. */
  current: number;
  currentPeriod: number;
  onFlash: (ok: boolean, msg: string) => void;
  onBack: () => void;
}) {
  const qc = useQueryClient();
  const percents = discountPercents(price);
  const offList = offListDiscount(current, percents);
  const [percent, setPercent] = useState(current || MIN_DISCOUNT);
  const [period, setPeriod] = useState(Math.max(1, currentPeriod));
  const [busy, setBusy] = useState(false);

  async function send(discount: number, forMonths: number) {
    setBusy(true);
    try {
      await putFanDiscount(accountId, fanId, discount, forMonths);
      qc.invalidateQueries({ queryKey: ofUserFullKey(accountId, fanId), exact: true });
      onFlash(true, discount ? "Discount applied" : "Discount cleared");
      onBack();
    } catch (e) {
      onFlash(false, `Could not save the discount: ${e instanceof Error ? e.message : String(e)}`);
      setBusy(false);
    }
  }

  return (
    <>
      <button
        type="button"
        onClick={onBack}
        className={cn(MENU_ROW, "text-fg-dim hover:text-fg hover:bg-bg-elev-1")}
      >
        ← Back
      </button>
      <div role="separator" className={cn(MP.menu.divider, "bg-border")} />
      <label className={MENU_ROW}>
        <span>Discount</span>
        <select className={SELECT} value={percent} onChange={(e) => setPercent(Number(e.target.value))}>
          {offList && <option value={current} disabled>{current}% discount (current)</option>}
          {percents.map((v) => <option key={v} value={v}>{v}% discount</option>)}
        </select>
      </label>
      <label className={MENU_ROW}>
        <span>For</span>
        <select className={SELECT} value={period} onChange={(e) => setPeriod(Number(e.target.value))}>
          {DISCOUNT_PERIODS.map((n) => <option key={n} value={n}>{months(n)}</option>)}
        </select>
      </label>
      <div className={cn(MENU_ROW, "text-fg-dim")}>{discountSummary(price, percent, period)}</div>
      <div className={cn(MENU_ROW, "justify-end")}>
        <button
          type="button"
          disabled={busy || !current}
          onClick={() => void send(0, 1)}
          className="text-fg-dim hover:text-fg disabled:opacity-50"
        >
          Clear
        </button>
        <button
          type="button"
          disabled={busy || !percents.includes(percent)}
          onClick={() => void send(percent, period)}
          className="ml-3 text-accent disabled:opacity-50"
        >
          Apply
        </button>
      </div>
    </>
  );
}
