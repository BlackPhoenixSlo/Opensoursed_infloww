import type { Metadata } from "next";

import LoginQueueCard from "@/components/setup/LoginQueueCard";
import { IfBody, InflowwPageHeader } from "@/components/ui/infloww";

export const metadata: Metadata = { title: "Paste logins" };

export default async function Page({ searchParams }: { searchParams: Promise<Record<string, string | string[] | undefined>> }) {
  const queue = (await searchParams).queue;
  return (
    <div className="flex flex-col bg-hb-bg">
      <InflowwPageHeader title="Paste logins" />
      <IfBody className="w-full max-w-2xl px-4 md:px-6">
        <LoginQueueCard linkedQueueId={typeof queue === "string" ? queue : null} />
      </IfBody>
    </div>
  );
}
