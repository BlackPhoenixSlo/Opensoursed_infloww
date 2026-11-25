import type { Metadata } from "next";

import ManageEmployees from "@/components/employees/ManageEmployees";
import { InflowwPageHeader } from "@/components/ui/infloww";

export const metadata: Metadata = { title: "Manage employees" };

export default function Page() {
  return (
    <div className="min-w-0">
      <InflowwPageHeader title="Manage employees" />
      <ManageEmployees />
    </div>
  );
}
