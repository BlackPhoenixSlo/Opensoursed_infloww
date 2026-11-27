import { FanslyMirrorChrome } from "@/components/fansly-manager/FanslyMirrorChrome";

export default function FanslyManagerLayout({ children }: { children: React.ReactNode }) {
  return <FanslyMirrorChrome>{children}</FanslyMirrorChrome>;
}
