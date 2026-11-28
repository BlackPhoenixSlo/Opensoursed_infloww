"use client";

import { useState } from "react";

import { IfButton, IfModal } from "@/components/ui/infloww";
import { useEmployeeKey } from "@/hooks/useEmployeeKey";

export const PREVIEW_LINE = "Google previews are automated search matches. They can be explicit or show someone else. "
  + "They stay blurred until you click one, and this app keeps no copy.";

const seenKey = (who: string, previews: boolean) => `chatterly:leak_disclaimer_seen:${previews ? "v2:" : ""}${who}`;

function seen(key: string): boolean {
  try {
    return window.localStorage.getItem(key) === "1";
  } catch {
    return false;
  }
}

export function LeakDisclaimer({ brand, previews }: { brand: string | null; previews: boolean }) {
  const who = useEmployeeKey();
  const [closedFor, setClosedFor] = useState<string | null>(null);
  if (who === null) return null;
  const key = seenKey(who, previews);
  if (closedFor === key || seen(key) || (!previews && seen(seenKey(who, true)))) return null;
  const close = () => {
    try {
      window.localStorage.setItem(key, "1");
    } catch {}
    setClosedFor(key);
  };
  return (
    <IfModal title="These results are automated" width={416} onClose={close} maskClosable
      footer={<IfButton variant="primary" onClick={close}>Got it</IfButton>}>
      <p>
        Every link here was found by bots that scrape Google, Mega and pirate sites. Some may be wrong or not about this
        Creator. {brand ?? "The removal team"} personally checks every leak before any removal starts.
      </p>
      {previews && <p className="mt-2">{PREVIEW_LINE}</p>}
    </IfModal>
  );
}
