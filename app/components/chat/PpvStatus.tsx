import { fmtPrice } from "@/lib/format";
import { MP } from "@/lib/messagesPro";
import { cn } from "@/lib/utils";

export const PPV_BORDER = "border-[var(--inf-ppv-border,var(--color-border))]";
export const PPV_FILL = "bg-[var(--inf-ppv,var(--color-accent))]";

function dollars(price: number): string {
  return fmtPrice(Math.round(price * 100));
}

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

export function ppvPriceLabel(price: number): string {
  return `$${price % 1 === 0 ? price : price.toFixed(2)}`;
}
