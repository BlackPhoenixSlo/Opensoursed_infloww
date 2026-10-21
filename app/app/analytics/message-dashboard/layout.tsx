import type { Metadata } from "next";

// Analytics > Message dashboard (formerly "Stuff" at /messages, which now
// redirects here).
export const metadata: Metadata = { title: "Message dashboard" };

export default function Layout({ children }: { children: React.ReactNode }) {
  return children;
}
