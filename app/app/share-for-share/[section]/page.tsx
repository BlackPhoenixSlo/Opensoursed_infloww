import { notFound } from "next/navigation";

import S4SPage, { type S4SSection } from "@/components/s4s/S4SPage";
import { findNavLink } from "@/lib/nav";

export default async function Page({ params }: { params: Promise<{ section: string }> }) {
  const { section } = await params;
  const link = findNavLink(`/share-for-share/${section}`);
  if (!link) notFound();
  return <S4SPage title={link.label} section={section as S4SSection} />;
}
