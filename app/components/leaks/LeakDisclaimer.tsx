"use client";

import { useState } from "react";

import { IfButton, IfModal } from "@/components/ui/infloww";
import { useEmployeeKey } from "@/hooks/useEmployeeKey";

const seenKey = (who: string) => `chatterly:leak_disclaimer_seen:${who}`;

function seen(who: string): boolean {
  try {
    return window.localStorage.getItem(seenKey(who)) === "1";
  } catch {
    return false;
  }
}

export function LeakDisclaimer({ brand }: { brand: string | null }) {
  const who = useEmployeeKey();
  const [closedFor, setClosedFor] = useState<string | null>(null);
  if (who === null || closedFor === who || seen(who)) return null;
  const close = () => {
    try {
      window.localStorage.setItem(seenKey(who), "1");
    } catch {}
    setClosedFor(who);
  };
  return (
    <IfModal title="These results are automated" width={416} onClose={close} maskClosable
      footer={<IfButton variant="primary" onClick={close}>Got it</IfButton>}>
      <p>
        Every link here was found by bots that scrape Google, Mega and pirate sites. Some may be wrong or not about this
        Creator. {brand ?? "The removal team"} personally checks every leak before any removal starts.
      </p>
    </IfModal>
  );
}
