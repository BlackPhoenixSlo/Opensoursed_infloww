import { NotBuiltYetRoute } from "@/components/NotBuiltYet";
import { FanslyManagerPage } from "@/components/fansly-manager/FanslyManagerPage";
import { findNavLink } from "@/lib/nav";

/** Fansly mode's Fansly Manager pages (lib/nav FANSLY_NAV): Infloww embeds fansly.com there. Ours are the built ones
 *  (Notifications, Lists, Scheduled Posts, Earning Statistics, behind the `fansly_manager` flag); the rest are not
 *  built, and any other page is a 404. */
export default async function Page({ params }: { params: Promise<{ page: string }> }) {
  const { page } = await params;
  const href = `/fansly-manager/${page}`;
  const link = findNavLink(href);
  return link && !link.notBuilt
    ? <FanslyManagerPage link={{ href: link.href, label: link.label, flag: link.flag }} />
    : <NotBuiltYetRoute href={href} />;
}
