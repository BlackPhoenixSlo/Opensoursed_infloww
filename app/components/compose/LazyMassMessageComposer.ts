import dynamic from "next/dynamic";

export const LazyMassMessageComposer = dynamic(
  () => import("./MassMessageComposer").then((m) => m.MassMessageComposer),
  { ssr: false },
);
