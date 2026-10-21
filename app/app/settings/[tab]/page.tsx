import type { ComponentType } from "react";
import { notFound } from "next/navigation";

import AboutTab from "@/components/settings/AboutTab";
import AiKeysTab from "@/components/settings/AiKeysTab";
import AuditTab from "@/components/settings/AuditTab";
import BalanceTab from "@/components/settings/BalanceTab";
import BillingTab from "@/components/settings/BillingTab";
import CotagTab from "@/components/settings/CotagTab";
import MessagingSettingsTab from "@/components/settings/MessagingSettingsTab";
import PreferencesTab from "@/components/settings/PreferencesTab";
import RoleSettingsTab from "@/components/settings/RoleSettingsTab";
import SalesSettingsTab from "@/components/settings/SalesSettingsTab";
import SecurityOrgTab from "@/components/settings/SecurityOrgTab";
import SecurityPersonalTab from "@/components/settings/SecurityPersonalTab";
import SystemTab from "@/components/settings/SystemTab";
import TimeTrackingTab from "@/components/settings/TimeTrackingTab";
import YourAccountTab from "@/components/settings/YourAccountTab";
import { SETTINGS_TABS } from "@/lib/nav";

/** Each Settings tab's Panel, keyed by its full href ("/settings/<tab>"); a
 *  Panel renders its own SettingsPanel. An href with no Panel is a 404
 *  (docs/spec/settings-tabs/phase-05-billing-balance-about.md). */
const SETTINGS_PANELS: Partial<Record<string, ComponentType>> = {
  "/settings/account": YourAccountTab,
  "/settings/preferences": PreferencesTab,
  "/settings/security-org": SecurityOrgTab,
  "/settings/security-personal": SecurityPersonalTab,
  "/settings/billing": BillingTab,
  "/settings/balance": BalanceTab,
  "/settings/roles": RoleSettingsTab,
  "/settings/sales": SalesSettingsTab,
  "/settings/time-tracking": TimeTrackingTab,
  "/settings/messaging": MessagingSettingsTab,
  "/settings/cotag": CotagTab,
  "/settings/ai-keys": AiKeysTab,
  "/settings/audit": AuditTab,
  "/settings/about": AboutTab,
  // Master only: SystemTab itself 404s anyone whose session is not users.is_admin.
  "/settings/system": SystemTab,
};

export default async function Page({ params }: { params: Promise<{ tab: string }> }) {
  const { tab } = await params;
  const link = SETTINGS_TABS.find((t) => t.href === `/settings/${tab}`);
  if (!link) notFound();
  const Panel = SETTINGS_PANELS[link.href];
  if (!Panel) notFound();
  return <Panel />;
}
