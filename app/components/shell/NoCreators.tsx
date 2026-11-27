"use client";

import Link from "next/link";

import { useGrantedPages } from "@/components/shell/useGrantedPages";
import { EmptyState } from "@/components/ui/infloww";
import { deniedPage } from "@/lib/nav";
import { cn } from "@/lib/utils";

const NO_PERMISSION = "Unfortunately, you don't have permission for this page. Please contact the administrator.";
const PRIMARY = "h-8 px-[15px] grid place-items-center rounded-md bg-accent text-white text-base hover:opacity-90";

export function CreatorsAction({ label }: { label: string }) {
  if (deniedPage("/creators", useGrantedPages())) return <p className="max-w-[380px] text-err text-sm">{NO_PERMISSION}</p>;
  return <Link href="/creators" className={PRIMARY}>{label}</Link>;
}

export function NoCreators({ className }: { className: string }) {
  return (
    <div className={cn(className, "flex items-center justify-center px-6")}>
      <EmptyState
        kind="data"
        text={<>You have not yet tied a creator, if you need to bind<br />one, you can bind on the “Creators Management” page.</>}
        textClassName="mt-4 mb-1.5 max-w-[400px] text-base leading-6 font-medium text-fg"
        action={<CreatorsAction label="Link account" />}
      />
    </div>
  );
}
