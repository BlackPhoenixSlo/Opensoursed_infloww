import type { Metadata } from "next";

import ProxiesTable from "@/components/setup/ProxiesTable";

export const metadata: Metadata = { title: "Custom proxy" };

/** Creators > Custom proxy. The table draws the capture's own header, "Manage your custom proxies", so the page
 *  adds no frame title (`docs/infloww-layouts/creators-proxy.md`, #3; ticket 17). */
export default function Page() {
  return <ProxiesTable />;
}
