import { notFound } from "next/navigation";

import { FanslyManagerPage } from "@/components/fansly-manager/FanslyManagerPage";
import { findNavLink } from "@/lib/nav";

export default async function Page({ params }: { params: Promise<{ page: string }> }) {
  const { page } = await params;
  const link = findNavLink(`/fansly-manager/${page}`);
  if (!link) notFound();
  return <FanslyManagerPage link={{ href: link.href, label: link.label, flag: link.flag }} />;
}
