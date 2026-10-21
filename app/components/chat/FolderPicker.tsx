"use client";

import { useEffect } from "react";

import { useAllChatFolders, usePinChatFolder } from "@/hooks/useChatFolders";
import { MP } from "@/lib/messagesPro";
import { describeLoadError } from "@/lib/relay";
import { cn } from "@/lib/utils";

/** Modal-ish popover listing every pinnable list (pinned + unpinned)
 *  with a checkbox toggle. Mirrors /ui/'s folder picker. Closes on outside
 *  click or Esc. */
export function FolderPicker({
  accountId, onClose,
}: { accountId: string; onClose: () => void }) {
  const all = useAllChatFolders(accountId);
  const pin = usePinChatFolder(accountId);
  const rows = all.data ?? [];

  // Close on Esc
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") onClose(); };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [onClose]);

  return (
    <div className="fixed inset-0 z-50 bg-black/40" onClick={onClose}>
      <div
        onClick={(e) => e.stopPropagation()}
        className={cn(MP.ours.FolderPicker.panel, "absolute flex flex-col bg-panel border-border shadow-xl")}
      >
        <div className="px-3 py-2 border-b border-border text-sm font-semibold">
          Pin folders to chat sidebar
        </div>
        <div className="flex-1 overflow-y-auto">
          {all.isFetching && rows.length === 0 && (
            <div className="p-4 text-xs text-fg-dim">Loading…</div>
          )}
          {all.isError && (
            <div className="p-4 text-xs text-err">
              {describeLoadError(all.error as Error)}
            </div>
          )}
          {!all.isFetching && rows.length === 0 && !all.isError && (
            <div className="p-4 text-xs text-fg-dim">
              No pinnable lists yet — create one in OF first.
            </div>
          )}
          {rows.map((f) => {
            const id = String(f.id);
            const checked = !!f.isPinnedToChat;
            return (
              <label
                key={id}
                className="flex items-center gap-2 px-3 py-3 md:py-2 text-sm md:text-xs hover:bg-bg-elev-1 cursor-pointer"
              >
                <input
                  type="checkbox"
                  checked={checked}
                  disabled={pin.isPending}
                  onChange={(e) =>
                    pin.mutate({ listId: f.id, pinned: e.target.checked })
                  }
                />
                <span className="flex-1 truncate">
                  {f.name || `List #${id}`}
                </span>
                <span className="text-fg-dim shrink-0">
                  {f.usersCount ?? f.subscribersCount ?? 0}
                </span>
              </label>
            );
          })}
        </div>
        <div className="px-3 py-2 border-t border-border flex justify-end">
          <button
            type="button"
            onClick={onClose}
            className="text-xs px-3 py-1 rounded border border-border hover:border-border-light"
          >
            Done
          </button>
        </div>
      </div>
    </div>
  );
}
