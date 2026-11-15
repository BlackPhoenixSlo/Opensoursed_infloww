import type { Metadata } from "next";
import AiRulesPage from "@/components/automations/AiRulesPage";

export const metadata: Metadata = { title: "AI rules" };

export default function Page() {
  return <AiRulesPage />;
}
