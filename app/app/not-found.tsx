import Link from "next/link";

import { EmptyState } from "@/components/ui/infloww";

/** The app's 404, in the theme tokens (Next's default is dark grey on our dark body). */
export default function NotFound() {
  return (
    <div className="grid min-h-full place-items-center bg-bg p-6">
      <EmptyState
        text="This page could not be found."
        textClassName="text-fg-dim"
        action={<Link href="/" className="text-accent-fg hover:underline">Back to Dashboard</Link>}
      />
    </div>
  );
}
