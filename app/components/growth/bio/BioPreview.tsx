"use client";

/**
 * The bio editor's live preview: the public page drawn in React from `previewModel` (the draft, not the saved page),
 * its markup and look after `public/script.js` renderProfile/renderLinks and `style.css` (black page, 100px avatar, the verified badge,
 * #1C1C1E cards; a background card at 2.5:1 until its image loads, then the image's natural ratio, with its text at the
 * foot and the icon top-left). Never an iframe: the real
 * page counts a view on load and shows only what is saved. The look is approximated; "Open" shows the real page.
 */
import { Lock } from "lucide-react";
import { useEffect, useState } from "react";

import { bgAspectRatio, type ImageSize, type PreviewModel } from "@/components/growth/bio/bioPreviewModel";
import { cn } from "@/lib/utils";

/** Matches service/bio_pages/public/images/verified.svg. */
function VerifiedBadge() {
  return <svg aria-label="Verified" viewBox="0 0 24 24" className="h-5 w-5">
    <circle cx="12" cy="12" r="11" fill="#1d9bf0" />
    <path d="M7 12.4l3.3 3.3L17.2 8.8" fill="none" stroke="#fff" strokeWidth="2.4"
      strokeLinecap="round" strokeLinejoin="round" />
  </svg>;
}

/** Natural sizes of the cards' background images, measured as each loads, like the public page's img.onload. */
function useImageRatios(urls: readonly string[]): (url: string) => string {
  const [sizes, setSizes] = useState<Record<string, ImageSize>>({});
  const key = urls.join("\n");
  useEffect(() => {
    const imgs = key.split("\n").filter(Boolean).map((url) => {
      const img = new Image();
      img.onload = () => setSizes((prev) => prev[url] ? prev
        : { ...prev, [url]: { width: img.naturalWidth, height: img.naturalHeight } });
      img.src = url;
      return img;
    });
    return () => imgs.forEach((img) => { img.onload = null; });
  }, [key]);
  return (url) => bgAspectRatio(sizes[url] ?? null);
}

export function BioPreview({ model, className }: { model: PreviewModel; className?: string }) {
  const ratios = useImageRatios(model.links.map((l) => l.backgroundUrl));
  return (
    <div aria-label="Preview" role="region" data-bio-preview
      className={cn(
        "mx-auto w-full max-w-[390px] overflow-hidden rounded-[28px] border border-[#333] bg-black text-white",
        "lg:h-[760px]",
        className,
      )}>
      <div className="h-full overflow-y-auto overscroll-contain"
        style={{ fontFamily: '-apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif' }}>
        <div className="flex flex-col items-center p-5">
          <header className="mb-[30px] mt-10 text-center">
            <div className="mx-auto mb-[15px] h-[100px] w-[100px] overflow-hidden rounded-full border-2 border-[#333] bg-[#1C1C1E] bg-cover bg-center"
              style={model.avatarUrl ? { backgroundImage: `url("${model.avatarUrl}")` } : undefined} />
            <div className="flex items-center justify-center gap-[5px]">
              <h3 className="m-0 text-[1.2rem] font-bold">{model.displayName || " "}</h3>
              {model.verified && <VerifiedBadge />}
            </div>
            {model.bio && <p className="mt-2.5 whitespace-pre-line text-[0.9rem] text-[#888]">{model.bio}</p>}
          </header>
          <ul className="flex w-full flex-col gap-[15px]">
            {model.links.map((l) => (
              <li key={l.key} data-preview-link={l.title}
                className={cn(
                  "relative flex overflow-hidden rounded-2xl text-white",
                  l.backgroundUrl
                    ? "flex-col justify-end border border-white/20 bg-cover bg-center [text-shadow:0_2px_4px_rgba(0,0,0,0.9)]"
                    : "items-center border border-[#333] bg-[#1C1C1E] p-[15px]",
                )}
                style={l.backgroundUrl ? { backgroundImage: `url("${l.backgroundUrl}")`, aspectRatio: ratios(l.backgroundUrl) }
                  : undefined}>
                {l.iconUrl && (
                  <span aria-hidden className="absolute left-2.5 top-2.5 z-10 h-8 w-8 bg-contain bg-center bg-no-repeat"
                    style={{ backgroundImage: `url("${l.iconUrl}")` }} />
                )}
                <div className={cn("min-w-0", l.backgroundUrl ? "relative z-[2] w-full p-[15px] text-center" : "flex-1")}>
                  <span className="mb-[3px] block break-words text-base font-semibold">
                    {l.title || " "}
                    {l.isAdult && <Lock aria-label="18+" className="ml-2.5 inline h-3.5 w-3.5 align-[-2px] text-[#888]" />}
                  </span>
                  <span className="text-[0.8rem] text-[#888]">{l.subtitle}</span>
                </div>
              </li>
            ))}
          </ul>
        </div>
      </div>
    </div>
  );
}
