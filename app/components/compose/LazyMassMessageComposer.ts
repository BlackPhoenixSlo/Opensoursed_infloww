import dynamic from "next/dynamic";

/** The mass-message composer, loaded only when opened: render-gated and split
 *  out because it drags in the vault picker cascade. The one entry point for
 *  the pages that open it, Growth > Smart Messages and the Fan List's New
 *  menu. */
export const LazyMassMessageComposer = dynamic(
  () => import("./MassMessageComposer").then((m) => m.MassMessageComposer),
  { ssr: false },
);
