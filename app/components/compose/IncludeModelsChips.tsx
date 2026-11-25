"use client";

import { useAllModelsInclude } from "@/hooks/useAllModelsInclude";
import { IfHelp } from "@/components/ui/infloww";
import type { AccountMeta } from "@/lib/relay";
import { cn } from "@/lib/utils";
import { AccountPicker } from "./AccountPicker";

export function IncludeModelsChips({
  noun, accounts, allModels, locked, onAllModels, accountId, onAccount,
}: {
  noun: "broadcast" | "post";
  accounts: readonly AccountMeta[];
  allModels: boolean;
  locked: boolean;
  onAllModels: (on: boolean) => void;
  accountId: string | null;
  onAccount: (id: string) => void;
}) {
  const { isIncluded, toggle } = useAllModelsInclude();
  const includedCount = accounts.filter((a) => isIncluded(a.id)).length;
  return (
    <>
      <label className="flex cursor-pointer select-none items-center gap-2 text-[14px] text-fg">
        <input
          type="checkbox"
          checked={allModels}
          disabled={locked}
          onChange={(e) => onAllModels(e.target.checked)}
          className="h-4 w-4 accent-accent"
        />
        <span>
          {`${noun === "post" ? "Post" : "Broadcast"} from ALL models`}{" "}
          <span className="text-muted">({includedCount}/{accounts.length} included)</span>
        </span>
      </label>

      {allModels ? (
        <div>
          <div className="flex flex-wrap gap-2">
            {accounts.map((a) => {
              const inc = isIncluded(a.id);
              return (
                <button
                  key={a.id}
                  type="button"
                  onClick={() => toggle(a.id)}
                  title={inc ? "Click to exclude from broadcast" : "Click to include"}
                  className={cn(
                    "flex h-7 items-center gap-1.5 rounded-full border px-3 text-[12px] transition-colors",
                    inc ? "border-border bg-bg-elev-1 text-fg hover:border-accent" : "border-border/60 bg-bg text-fg-dim line-through opacity-60",
                  )}
                >
                  <span
                    className="w-2 h-2 rounded-full shrink-0"
                    style={{ background: a.color || "#666" }}
                  />
                  <span>{a.nickname || a.id}</span>
                </button>
              );
            })}
            {accounts.length === 0 && (
              <span className="text-[12px] text-muted">No active sessions.</span>
            )}
          </div>
          <IfHelp>{`All-models ${noun}s are text-only for now — uploads from computer are temporarily disabled.`}</IfHelp>
        </div>
      ) : (
        <AccountPicker accounts={accounts} value={accountId} onChange={onAccount} />
      )}
    </>
  );
}
