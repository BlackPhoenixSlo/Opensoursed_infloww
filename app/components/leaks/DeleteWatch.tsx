"use client";

import { type InfiniteData, useMutation, useQueryClient } from "@tanstack/react-query";

import { ifConfirm } from "@/components/ui/ifConfirm";
import { IfButton } from "@/components/ui/infloww";
import { relay } from "@/lib/relay";

import { untrack, withoutCreator, type LeakPage, type LeakRoster } from "./leakView";

export function DeleteWatch({ creatorId, scopeAccountId, name, brand, onDeleted }: {
  creatorId: string;
  scopeAccountId: string | null;
  name: string;
  brand: string | null;
  onDeleted: () => void;
}) {
  const qc = useQueryClient();
  const drop = useMutation({
    mutationFn: () => relay.delete(`/admin/leaks/watches/${creatorId}`, { accountId: scopeAccountId }),
    onSuccess: () => {
      qc.setQueriesData<LeakRoster>({ queryKey: ["leak-tracker", "roster", scopeAccountId] }, (r) => r && untrack(r, creatorId));
      qc.setQueriesData<InfiniteData<LeakPage>>({ queryKey: ["leak-tracker", "all", scopeAccountId] },
        (d) => d && { ...d, pages: d.pages.map((p) => withoutCreator(p, creatorId)) });
      qc.removeQueries({ queryKey: ["leak-tracker", "watch", creatorId, scopeAccountId] });
      onDeleted();
      void qc.invalidateQueries({ queryKey: ["leak-tracker", "setup", scopeAccountId] });
      void qc.invalidateQueries({ queryKey: ["leak-tracker", "roster", scopeAccountId] });
      void qc.invalidateQueries({ queryKey: ["leak-tracker", "all", scopeAccountId] });
    },
  });
  const ask = async () => {
    const ok = await ifConfirm(
      `Delete Leak tracking for ${name}?\n\nTracking stops now, and ${brand || "the removal service"} removes the data within 30 days.`,
      { confirmLabel: "Delete", danger: true },
    );
    if (ok) drop.mutate();
  };
  return (
    <>
      <IfButton variant="link" className="mt-2 ml-4 text-err hover:text-err/80" disabled={drop.isPending} onClick={() => void ask()}>
        Delete
      </IfButton>
      {drop.error && <p role="alert" className="mt-1 text-[14px] text-err">{drop.error.message}</p>}
    </>
  );
}
