import { EmptyState } from "@/components/ui/infloww";

export function NotAvailable({ label }: { label: string }) {
  return (
    <div className="flex h-full min-h-[calc(100dvh-var(--shell-top,56px))] items-center justify-center bg-bg px-6">
      <EmptyState kind="data" text={`${label} is not available.`} />
    </div>
  );
}
