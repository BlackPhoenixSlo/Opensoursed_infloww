import { InflowwPageHeader } from "@/components/ui/infloww";

/** Infloww's 48px page header, then the page body (`padding:16px`, full width like Infloww's pages), for routes that
 *  wrap one existing panel. `extra` (a creator select) and `actions` (Learn, the primary) pass to the header. */
export function PageFrame({ title, extra, actions, children }: {
  title: string;
  extra?: React.ReactNode;
  actions?: React.ReactNode;
  children: React.ReactNode;
}) {
  return (
    <div className="min-w-0">
      <InflowwPageHeader title={title} extra={extra} actions={actions} />
      <div className="p-4">{children}</div>
    </div>
  );
}
