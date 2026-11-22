/** Under a provider key field (the owner's card and the founder's form): the wrong-field
 *  warning while the typed value looks like another vendor's key, else the provider's help,
 *  then the vendor's key-page link. */

import { HELP, wrongFieldWarning } from "@/components/setup/providerFields";
import KeyLink from "@/components/setup/KeyLink";

export default function KeyFieldHint({ name, value }: { name: string; value: string }) {
  const warning = wrongFieldWarning(name, value);
  return (
    <>
      {warning ? (
        <p className="text-[11px] text-warn" role="alert">{warning}</p>
      ) : (
        HELP[name] && <p className="text-[11px] text-fg-dim">{HELP[name]}</p>
      )}
      <KeyLink name={name} />
    </>
  );
}
