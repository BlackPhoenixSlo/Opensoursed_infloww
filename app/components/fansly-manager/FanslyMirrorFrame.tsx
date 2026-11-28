"use client";

import { useEffect, useRef } from "react";
import { useRouter } from "next/navigation";

import { withCreator } from "@/lib/fansly-mirror-route";
import { onFanslyFrameReady, useFanslyDoc } from "@/lib/fanslyMirrorDoc";
import { useFanslyPick } from "@/lib/fanslyMirrorPick";

export function FanslyMirrorFrame({ src, title }: { src: string; title: string }) {
  const ref = useRef<HTMLIFrameElement>(null);
  const router = useRouter();
  const { shown } = useFanslyPick();
  const key = `${src}|${shown ?? ""}`;
  useFanslyDoc(ref, src, shown);

  useEffect(() => {
    const frame = ref.current;
    if (!frame) return;
    const onClick = (ev: MouseEvent) => {
      const href = (ev.target as Element | null)?.closest?.("a")?.getAttribute("href");
      if (!href) return;
      if (href === "#") return ev.preventDefault();
      if (ev.button !== 0 || ev.metaKey || ev.ctrlKey || ev.shiftKey || ev.altKey) return;
      if (!href.startsWith("/fansly-manager/")) return;
      ev.preventDefault();
      router.push(withCreator(href, shown));
    };
    return onFanslyFrameReady(frame, (doc) => {
      doc.addEventListener("click", onClick);
      return () => doc.removeEventListener("click", onClick);
    });
  }, [key, shown, router]);

  return (
    <div className="flex flex-col h-chat">
      <iframe key={key} ref={ref} src={src} title={title} className="block w-full flex-1 min-w-0 min-h-0 border-0 bg-bg" />
    </div>
  );
}
