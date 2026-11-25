"use client";


import type { ReactNode } from "react";
import Link from "next/link";

import type { CreatorPick } from "@/components/shell/CreatorRail";
import { EmptyState, IfButton, IfModal, IfSwitch, ifButtonClass, useCreatorParam } from "@/components/ui/infloww";
import { Skeleton } from "@/components/ui/Skeleton";
import { useAccounts, useActiveAccounts } from "@/hooks/useAccounts";
import { useOptionalChatter } from "@/contexts/ChatterContext";
import { useOptionalUser } from "@/contexts/UserContext";
import { isChatterOnly } from "@/lib/session";
import { cn } from "@/lib/utils";

export function useAutomationCreator() {
  const accounts = useActiveAccounts();
  const loading = useAccounts().isLoading;
  const [accountId, setAccountId] = useCreatorParam(accounts);
  const creators: CreatorPick = { accounts, value: accountId, onChange: setAccountId };
  return { accountId, creators, loading };
}

export function NoCreator({ loading = false }: { loading?: boolean }) {
  if (loading) {
    return (
      <div className="space-y-8" role="status" aria-label="Loading">
        {[0, 1].map((i) => (
          <section key={i}>
            <Skeleton className="mb-4 h-5 w-40" />
            <div className="space-y-4 rounded-lg border border-border p-6 max-sm:p-4">
              <Skeleton className="h-4 w-3/4" />
              <Skeleton className="h-9 w-full" />
              <Skeleton className="h-4 w-1/2" />
            </div>
          </section>
        ))}
      </div>
    );
  }
  return (
    <EmptyState kind="creator" text="No creator with a live session" className="min-h-[400px]"
      help={<p className="mt-1 max-w-[360px] text-[12px] text-muted">Automations run on a connected creator&apos;s OnlyFans session.</p>}
      action={<ConnectCreatorLink />} />
  );
}

export function ConnectCreatorLink() {
  const user = useOptionalUser()?.user;
  const chatter = useOptionalChatter()?.chatter;
  if (isChatterOnly(user, chatter)) return null;
  return (
    <Link href="/creators" className={ifButtonClass("primary")}>
      Connect a creator
    </Link>
  );
}

export function FormBlock({ title, children, className }: { title: ReactNode; children: ReactNode; className?: string }) {
  return (
    <section className={className}>
      <h2 className="mb-4 text-[16px] font-semibold text-fg">{title}</h2>
      <div className="space-y-4 rounded-lg border border-border p-6 max-sm:p-4">{children}</div>
    </section>
  );
}

export const ROW = "rounded-lg border border-border px-4";

export function SwitchRow({ label, hint, checked, onChange, disabled, loading, children }: {
  label: string;
  hint?: ReactNode;
  checked: boolean;
  onChange: (checked: boolean) => void;
  disabled?: boolean;
  loading?: boolean;
  children?: ReactNode;
}) {
  return (
    <div className={cn(ROW, disabled && "opacity-50")}>
      <div className="flex min-h-14 items-center justify-between gap-4 py-2">
        <div className="min-w-0">
          <div className="text-[14px] text-fg">{label}</div>
          {hint && <div className="mt-0.5 text-[12px] text-muted">{hint}</div>}
        </div>
        <IfSwitch aria-label={label} checked={checked} onChange={onChange} disabled={disabled} loading={loading} />
      </div>
      {children && <div className="space-y-2 pb-4">{children}</div>}
    </div>
  );
}

export function ConfirmDelete({ title, children, pending, onConfirm, onClose }: {
  title: string;
  children?: ReactNode;
  pending?: boolean;
  onConfirm: () => void;
  onClose: () => void;
}) {
  return (
    <IfModal width={416} title={title} onClose={onClose}
      footer={(
        <>
          <IfButton onClick={onClose}>Cancel</IfButton>
          <IfButton variant="primary" disabled={pending} onClick={onConfirm} className="bg-err hover:bg-err/90">
            Delete
          </IfButton>
        </>
      )}>
      {children && <p className="text-fg-dim">{children}</p>}
    </IfModal>
  );
}

export const TABLE_EMPTY = "min-h-[400px]";
