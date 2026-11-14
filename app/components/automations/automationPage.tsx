"use client";

/**
 * The pieces the My Automations pages (Auto Post, Auto Mass, Auto Story, Auto-reply, Auto Funnel, Get to know fans)
 * share on Infloww's look (page-parity ticket 16): one creator column bound to `?creator=`, the no-creator
 * empty state, the S4S-settings form block and its 56px switch row, the Save row, and the 416px delete confirm.
 */

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

/** The page's creator and its pick for the creator column (`PageFrame`'s `creators`); `loading` while the account
 *  list is still in flight, so the no-creator state does not flash on load. */
export function useAutomationCreator() {
  const accounts = useActiveAccounts();
  const loading = useAccounts().isLoading;
  const [accountId, setAccountId] = useCreatorParam(accounts);
  const creators: CreatorPick = { accounts, value: accountId, onChange: setAccountId };
  return { accountId, creators, loading };
}

/** No Creator has a live session: ticket 04's creator art in the list body's 400px. While the account list is still
 *  `loading` it is the page's form instead, as placeholder bars (a FormBlock's heading and box), so the page is not
 *  blank before the creator resolves. */
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

/** "Connect a creator" to Creators Management (32px primary); none for a chatter session (it cannot connect one). */
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

/** A settings block: a 16 / 600 T1 heading, 16px below it a bordered box; blocks sit 32px apart (`space-y-8`). */
export function FormBlock({ title, children, className }: { title: ReactNode; children: ReactNode; className?: string }) {
  return (
    <section className={className}>
      <h2 className="mb-4 text-[16px] font-semibold text-fg">{title}</h2>
      <div className="space-y-4 rounded-lg border border-border p-6 max-sm:p-4">{children}</div>
    </section>
  );
}

/** A settings row's box (SwitchRow, and rows built beside it). */
export const ROW = "rounded-lg border border-border px-4";

/** A 56px row: the label (and a 12px hint under it) left, the switch right; the switch is named by `label`.
 *  `children` show under the row (a switch's own fields). */
export function SwitchRow({ label, hint, checked, onChange, disabled, loading, children }: {
  label: string;
  hint?: ReactNode;
  checked: boolean;
  onChange: (checked: boolean) => void;
  disabled?: boolean;
  /** A switch write in flight: the knob spins, clicks wait. */
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

/** antd's 416px confirm for a delete: "Cancel" and a red "Delete". */
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

/** A rule table's empty state height (EmptyState itself stays in view when the table scrolls sideways). */
export const TABLE_EMPTY = "min-h-[400px]";
