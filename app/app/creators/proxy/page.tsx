import type { Metadata } from "next";

import ProxiesTable from "@/components/setup/ProxiesTable";

export const metadata: Metadata = { title: "Custom proxy" };

export default function Page() {
  return <ProxiesTable />;
}
