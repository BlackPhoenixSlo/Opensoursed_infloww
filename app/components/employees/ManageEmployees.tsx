"use client";


import EmployeesTab from "@/components/settings/EmployeesTab";
import { useUser } from "@/contexts/UserContext";
import { useChatter } from "@/contexts/ChatterContext";

export default function ManageEmployees() {
  const { user } = useUser();
  const { chatter } = useChatter();

  if (!user) return chatter ? <p className="p-4 text-sm text-fg-dim">Only the agency owner can manage employees.</p> : null;
  return <EmployeesTab />;
}
