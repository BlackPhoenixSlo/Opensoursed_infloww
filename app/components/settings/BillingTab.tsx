"use client";

/**
 * Billing: Inflowwww is self-hosted and free, so there is no plan, card or invoice (owner, 2026-11-11). Below
 * that, an optional way to support the maintainer: the direct tip link and three crypto addresses (owner,
 * 2026-11-12; Tron's base58check checksum and Solana's 32-byte length verified on transcription). The Panel
 * reads and writes nothing.
 */

import { CopyButton } from "@/components/growth/_bits";
import { Section, SettingsPanel } from "@/components/settings/SettingsPanel";
import { BRAND_NAME } from "@/lib/brand";

const TIP_URL = "https://jackbase.me/tip";

/** Coin, network, address. A coin sent on another network is lost, so the network is spelled out. */
export const WALLETS = [
  { coin: "USDC", network: "Solana", address: "ictqMeadUmwCmkR4KbEzDPWsnDoQ7xrUgG5uuEDJFFa" },
  { coin: "USDC", network: "BNB Smart Chain (BEP20)", address: "0xe27d43ca9be4045003e2ef5e85392ad99f42b676" },
  { coin: "USDT", network: "Tron (TRC20)", address: "TSJc8Le7sxszWTa3bcQkXT35ScPeK6xdjp" },
] as const;

const NOTE = "text-[length:var(--if-fs)] text-[var(--if-fg-2)]";

export default function BillingTab() {
  return (
    <SettingsPanel title="Billing">
      <p className={`mb-6 ${NOTE}`}>{BRAND_NAME} is self-hosted and free: nothing to pay, no invoices.</p>
      <Section title="Support (optional)">
        <p className={`mb-3 ${NOTE}`}>
          Free gifts keep it going. Tip directly at{" "}
          <a
            href={TIP_URL}
            target="_blank"
            rel="noopener noreferrer"
            className="text-[var(--if-accent)] hover:underline underline-offset-2"
          >
            jackbase.me/tip
          </a>
          , or send crypto to one of these. Use the network shown — a coin sent on another network is lost.
        </p>
        <ul className="space-y-3">
          {WALLETS.map((w) => (
            <li key={w.address} className="rounded border border-[var(--if-line)] p-3">
              <div className="flex items-center justify-between gap-2">
                <p className="text-[length:var(--if-fs)] text-[var(--if-fg)]">
                  {w.coin} <span className="text-[var(--if-fg-3)]">· {w.network}</span>
                </p>
                <CopyButton text={w.address} label="Copy" doneLabel="Copied" />
              </div>
              <p className="mt-1 font-mono text-[12px] break-all text-[var(--if-fg-2)]">{w.address}</p>
            </li>
          ))}
        </ul>
      </Section>
    </SettingsPanel>
  );
}
