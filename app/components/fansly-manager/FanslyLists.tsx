"use client";

/**
 * Fansly Manager > Lists: the creator's own Fansly lists and "Create list", over the Relay's `GET`/`POST
 * /api/of/v2/lists`, which the Fansly shim answers from Fansly's `GET /lists/account` and `POST /lists`
 * (fansly_shim.get_lists / create_list). Fansly's built-in lists (Blocked, Muted, VIP, DM allow) are not returned.
 * Rename, members and delete are not built: their Fansly requests are not captured.
 */

import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Plus } from "lucide-react";

import { EmptyState, IF_TABLE, IfBody, IfButton, IfInput, IfModal } from "@/components/ui/infloww";
import { relay } from "@/lib/relay";
import { cn } from "@/lib/utils";

interface FanslyList { id: string; name: string }

export function FanslyLists({ accountId }: { accountId: string }) {
  const qc = useQueryClient();
  const queryKey = ["fansly-manager", "lists", accountId];
  const listQ = useQuery<{ list: FanslyList[] }>({
    queryKey,
    queryFn: () => relay.get("/api/of/v2/lists?limit=50", { accountId }),
    staleTime: 30_000,
  });
  const [creating, setCreating] = useState(false);
  const [name, setName] = useState("");
  const create = useMutation({
    mutationFn: (n: string) => relay.post("/api/of/v2/lists", { name: n }, { accountId }),
    onSuccess: () => {
      setCreating(false);
      setName("");
      void qc.invalidateQueries({ queryKey });
    },
  });
  const close = () => { setCreating(false); setName(""); create.reset(); };
  const rows = listQ.data?.list ?? [];

  return (
    <IfBody>
      <div className="mb-4 flex items-center justify-between gap-3">
        <p className="text-[12px] text-muted">
          Your own lists. Fansly&apos;s built-in lists are not shown; rename, members and delete are not available here.
        </p>
        <IfButton variant="primary" icon={Plus} onClick={() => setCreating(true)}>Create list</IfButton>
      </div>
      {listQ.isError ? (
        <EmptyState kind="error" text="Could not load lists." onRetry={() => void listQ.refetch()} className="mt-16" />
      ) : listQ.isPending ? (
        <p className="mt-16 text-center text-[14px] text-muted">Loading…</p>
      ) : rows.length === 0 ? (
        <EmptyState text="No lists" className="mt-16" />
      ) : (
        <table className={IF_TABLE.table}>
          <thead>
            <tr><th className={cn(IF_TABLE.th, IF_TABLE.thDivider)}>List name</th></tr>
          </thead>
          <tbody>
            {rows.map((l) => (
              <tr key={l.id} className={IF_TABLE.row}><td className={IF_TABLE.td}>{l.name}</td></tr>
            ))}
          </tbody>
        </table>
      )}
      {creating && (
        <IfModal
          title="Create list"
          onClose={close}
          footer={
            <>
              <IfButton onClick={close}>Cancel</IfButton>
              <IfButton
                variant="primary"
                disabled={!name.trim() || create.isPending}
                onClick={() => create.mutate(name.trim())}
              >
                {create.isPending ? "Creating…" : "Create"}
              </IfButton>
            </>
          }
        >
          <IfInput
            autoFocus
            aria-label="List name"
            placeholder="List name"
            maxLength={100}
            value={name}
            onChange={(e) => setName(e.target.value)}
            onKeyDown={(e) => { if (e.key === "Enter" && name.trim() && !create.isPending) create.mutate(name.trim()); }}
            className="w-full"
          />
          {create.isError && <p role="alert" className="mt-2 text-[12px] text-err">Could not create the list.</p>}
        </IfModal>
      )}
    </IfBody>
  );
}
