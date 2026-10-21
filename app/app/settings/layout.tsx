import type { Metadata } from "next";

import SettingsShell from "@/components/settings/SettingsShell";

export const metadata: Metadata = { title: "Settings" };

export default function Layout({ children }: { children: React.ReactNode }) {
  return <SettingsShell>{children}</SettingsShell>;
}
