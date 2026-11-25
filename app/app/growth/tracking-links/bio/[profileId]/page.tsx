import { redirect } from "next/navigation";

export default async function OldBioEditor({ params }: { params: Promise<{ profileId: string }> }): Promise<never> {
  redirect(`/growth/bio-pages/${encodeURIComponent((await params).profileId)}`);
}
