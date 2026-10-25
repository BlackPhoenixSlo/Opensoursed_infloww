import { CreatorRail, type CreatorPick } from "@/components/shell/CreatorRail";
import { InflowwPageHeader } from "@/components/ui/infloww";

/** Infloww's 48px page header, then the page body (`padding:16px`, full width like Infloww's pages), for routes that
 *  wrap one existing panel. `actions` (Learn, the primary) pass to the header; `creators` puts Smart lists' creator
 *  column left of the body (`CreatorRail`). */
export function PageFrame({ title, extra, actions, creators, children }: {
  title: string;
  extra?: React.ReactNode;
  actions?: React.ReactNode;
  creators?: CreatorPick;
  children: React.ReactNode;
}) {
  if (creators) {
    return (
      <div className="flex min-h-full min-w-0 flex-col">
        <InflowwPageHeader title={title} extra={extra} actions={actions} />
        <CreatorRail creators={creators} className="p-4">{children}</CreatorRail>
      </div>
    );
  }
  return (
    <div className="min-w-0">
      <InflowwPageHeader title={title} extra={extra} actions={actions} />
      <div className="p-4">{children}</div>
    </div>
  );
}
