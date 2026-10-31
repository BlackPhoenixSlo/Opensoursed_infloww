"use client";

import { usePlatformAccounts } from "@/hooks/useAccounts";
import { useAllModelsInclude } from "@/hooks/useAllModelsInclude";
import { AccountPicker } from "./AccountPicker";

/** The composers' scope block (Mass + Post): the all-models switch with its
 *  "(n/m included)" count, then either the text-only note and the chip strip
 *  over the shared include set (hooks/useAllModelsInclude — click a chip to
 *  drop / re-add a model from this broadcast and the other composers'), or
 *  the one-account AccountPicker. The switch is disabled while the content is
 *  locked (compose/fanOut `fanOutLocked`). */
export function IncludeModelsChips({
  noun, allModels, locked, onAllModels, accountId, onAccount,
}: {
  noun: "broadcast" | "post";
  allModels: boolean;
  locked: boolean;
  onAllModels: (on: boolean) => void;
  accountId: string | null;
  onAccount: (id: string) => void;
}) {
  const accounts = usePlatformAccounts();
  const { isIncluded, toggle } = useAllModelsInclude();
  const includedCount = accounts.filter((a) => isIncluded(a.id)).length;
  return (
    <>
      <label className="flex items-center gap-2 text-xs cursor-pointer select-none">
        <input
          type="checkbox"
          checked={allModels}
          disabled={locked}
          onChange={(e) => onAllModels(e.target.checked)}
        />
        <span className="font-medium">{`${noun === "post" ? "Post" : "Broadcast"} from ALL models`}</span>
        <span className="text-fg-dim">
          ({includedCount}/{accounts.length} included)
        </span>
      </label>

      {allModels ? (
        <>
          <div className="text-[11px] text-fg-dim border border-dashed border-border rounded-md py-2 px-3">
            {`All-models ${noun}s are text-only for now — uploads from computer are temporarily disabled.`}
          </div>
          <div className="flex flex-wrap gap-1.5">
            {accounts.map((a) => {
              const inc = isIncluded(a.id);
              return (
                <button
                  key={a.id}
                  type="button"
                  onClick={() => toggle(a.id)}
                  title={inc ? "Click to exclude from broadcast" : "Click to include"}
                  className={
                    "flex items-center gap-1.5 px-2 py-1 rounded-full text-[11px] border transition-colors " +
                    (inc
                      ? "bg-bg-elev-1 border-border text-fg"
                      : "bg-bg border-border/60 text-fg-dim line-through opacity-60")
                  }
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
              <span className="text-[11px] text-fg-dim">No active sessions.</span>
            )}
          </div>
        </>
      ) : (
        <AccountPicker value={accountId} onChange={onAccount} />
      )}
    </>
  );
}
