/**
 * A PPV's status line ("$X.XX · paid" / "$X.XX · not paid", spec gap row L6).
 * Split out of `MessageList` (ticket 99). Prices are dollars (`OFMessage.price`).
 */
import { fmtCents } from "@/lib/format";
import { MP } from "@/lib/messagesPro";
import { cn } from "@/lib/utils";

function dollars(price: number): string {
  return fmtCents(Math.round(price * 100));
}

/** The last line inside the PPV card, after its title and media, as the old
 *  Infloww overlay's `.ppv-mini .paid-tag` (the deleted Clone's
 *  `messages.js:885-890`, tag `legacy-ui-final`). Paid is
 *  `isOpened || isPaid` (the caller's rule): `ok` when paid, Infloww's muted
 *  grey otherwise. The Creator's side shows this, never the Fan's unlock bar. */
export function PpvStatusLine({ price, paid }: {
  price: number;
  paid: boolean;
}) {
  return (
    <div className={cn(MP.messageList.paidTag,
                       paid ? "text-ok" : "text-[var(--inf-unpaid,var(--color-fg-dim))]")}>
      <span>{dollars(price)}</span>{paid ? " · paid" : " · not paid"}
    </div>
  );
}

/** A PPV price as a short label: whole dollars bare, cents otherwise
 *  ("$15", "$29.99"), for MediaStrip's tile pill. */
export function ppvPriceLabel(price: number): string {
  return `$${price % 1 === 0 ? price : price.toFixed(2)}`;
}
