"use client";


import { use, useMemo } from "react";

import { MessagesPro } from "@/components/chat/MessagesPro";
import { fanIdFromParam } from "@/lib/fanId";

export default function DeepLinkPage({
  params,
}: { params: Promise<{ accountId: string; fanId: string }> }) {
  const { accountId, fanId: fanIdStr } = use(params);
  // Keep the id as the URL spelled it: Number() corrupts Fansly snowflakes (> 2^53) into a ghost fan.
  const fanId = useMemo(() => fanIdFromParam(fanIdStr), [fanIdStr]);
  const deepLink = useMemo(
    () => (fanId == null ? null : { accountId, fanId }),
    [accountId, fanId],
  );

  // Guard after every hook: an early return above a hook changes the hook count (React #310).
  if (deepLink == null) {
    return (
      <div className="grid place-items-center h-chat text-sm text-err">
        Invalid fan id: {fanIdStr}
      </div>
    );
  }

  return <MessagesPro key={`${accountId}:${fanIdStr}`} deepLink={deepLink} />;
}
