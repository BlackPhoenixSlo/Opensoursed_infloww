import { redirect } from "next/navigation";

/** The old editor address: bookmarks land on /growth/bio-pages/<id> (Bio pages left Tracking links 11-12). */
export default async function OldBioEditor({ params }: { params: Promise<{ profileId: string }> }): Promise<never> {
  redirect(`/growth/bio-pages/${encodeURIComponent((await params).profileId)}`);
}
