"use client";


import { cn } from "@/lib/utils";
import { useActiveAccounts } from "@/hooks/useAccounts";

export function AccountChips({
  accountId,
  onChange,
  className,
}: {
  accountId: string | null;
  onChange: (id: string) => void;
  className?: string;
}) {
  const accounts = useActiveAccounts();
  // Keep the picker when the selected model dropped out of the list (session lost): a lone remaining option must stay pickable.
  const stranded = accountId !== null && !accounts.some((a) => a.id === accountId);
  if (accounts.length === 0 || (accounts.length <= 1 && !stranded)) return null;
  return (
    <div className={cn("flex items-center gap-1.5 flex-wrap", className)}>
      <span className="text-[10px] uppercase tracking-wide text-fg-dim mr-1">Account</span>
      {accounts.map((a) => {
        const active = accountId === a.id;
        return (
          <button
            key={a.id}
            type="button"
            onClick={() => onChange(a.id)}
            className={cn(
              "px-2.5 py-1 rounded-full text-xs border transition-colors",
              active
                ? "bg-accent text-white border-accent"
                : "bg-bg-elev-1 text-fg-dim border-border hover:text-fg hover:border-fg-dim",
            )}
          >
            {a.nickname || a.id}
          </button>
        );
      })}
    </div>
  );
}
