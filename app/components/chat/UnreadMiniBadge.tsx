import { MP } from "@/lib/messagesPro";
import { cn } from "@/lib/utils";

const PILL = cn(MP.creatorTabs.badge, "inline-flex flex-none items-center justify-center");

export function UnreadMiniBadge({ count }: { count: number | string | null }) {
  return (
    <>
      {" "}
      <span className={cn(PILL, "bg-err text-white")}>
        {count}{count !== null && " "}
        <span className="sr-only">unread</span>
      </span>
    </>
  );
}

export function GreyMiniBadge() {
  return (
    <>
      {" "}
      <span data-red-circle="grey" className={cn(PILL, "bg-fg-dim text-white")}>
        <span className="sr-only">unread count unknown</span>
      </span>
    </>
  );
}

export function OweMiniBadge({ count }: { count: string | null }) {
  return (
    <>
      {" "}
      {count === null ? (
        <span data-badge="owe" data-amber-circle="grey" className={cn(PILL, "bg-fg-dim ring-1 ring-inset ring-warn/60")}>
          <span className="sr-only">awaiting reply unknown</span>
        </span>
      ) : (
        <span data-badge="owe" className={cn(PILL, "bg-warn/20 text-warn ring-1 ring-inset ring-warn/60")}>
          {count}{" "}
          <span className="sr-only">awaiting reply</span>
        </span>
      )}
    </>
  );
}

export function NotifMiniBadge({ count }: { count: number }) {
  return (
    <>
      {" "}
      <span className={cn(PILL, "bg-[var(--inf-online,var(--color-ok))] text-white")}>
        {count > 99 ? "99+" : count}{" "}
        <span className="sr-only">notifications</span>
      </span>
    </>
  );
}
