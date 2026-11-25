import { keyUrl } from "@/components/setup/providerFields";

export default function KeyLink({ name }: { name: string }) {
  const url = keyUrl(name);
  if (!url) return null;
  return (
    <a
      href={url}
      target="_blank"
      rel="noopener noreferrer"
      className="inline-block text-[11px] text-accent hover:underline"
    >
      Get your key at {new URL(url).host} ↗
    </a>
  );
}
