import { OfManagerChrome } from "@/components/of-manager/OfManagerChrome";

/** Every OF Manager page: Infloww's page header and creator column around the mirrored OF view. */
export default function OfManagerLayout({ children }: { children: React.ReactNode }) {
  return <OfManagerChrome>{children}</OfManagerChrome>;
}
