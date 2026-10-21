"use client";

/**
 * Your Account (docs/spec/settings-tabs/phase-01-account-preferences.md): the
 * signed-in User's Username (from `GET /auth/me` through UserContext, read-only),
 * the owner's Telegram username (Infloww's settings0189), and the Agency Name
 * and picture, saved whole to the `account` Settings blob behind the Load gate.
 * The agency picture is a 96px JPEG data URL in the blob (the 64 KB cap), as a
 * Creator's Display image is (creatorProfiles.ts). The Personal picture and the
 * Username "Edit" have no Relay endpoint, so they are Not wired; the stored
 * values are read by nothing yet (ADR-0008). Nothing here touches a Creator's
 * OnlyFans profile.
 */

import { Camera } from "lucide-react";
import { useRef, useState } from "react";

import { useUser } from "@/contexts/UserContext";
import { avatarDataUrl } from "@/lib/creatorProfiles";
import { useSettingsBlob } from "@/lib/settingsBlob";
import {
  BlobNotes, Field, FieldInput, NotAppliedYet, NotWired, Section, SettingsPanel,
} from "@/components/settings/SettingsPanel";
import { SaveRow } from "@/components/settings/StickySaveBar";

type AccountSettings = { agency_name: string; agency_picture?: string; telegram_username?: string };
const DEFAULTS: AccountSettings = { agency_name: "" };

/** Up to two initials: the first letter of each of the first two words. */
function initials(text: string): string {
  const words = text.trim().split(/\s+/).filter(Boolean);
  if (!words.length) return "?";
  return words.slice(0, 2).map((w) => w[0]).join("").toUpperCase();
}

/** Infloww's 140x140 picture (radius 8, `._personal-avatar_rxwf7_192`): the stored image, else an initials box.
 *  Infloww lays an invisible file input over it and shows a photo icon on hover; ours shows the same veiled 24px
 *  camera on hover, opening the file picker. With no `upload` the upload is Not wired (ADR-0008): a disabled button
 *  titled "not wired" that never fakes an upload. */
function Picture({ label, text, src, upload }: {
  label: string;
  text: string;
  src?: string;
  /** The picked image as a data URL, or why it could not be read; both are required, so no error is dropped. */
  upload?: { onPick: (dataUrl: string) => void; onError: (message: string) => void };
}) {
  const file = useRef<HTMLInputElement>(null);
  return (
    <div className="group relative w-[140px] h-[140px] rounded-[8px] overflow-hidden">
      <div
        role="img"
        aria-label={`${label} picture`}
        className="w-full h-full grid place-items-center bg-[var(--if-accent-bg)] text-[var(--if-accent)] text-[40px] font-[var(--if-fw-title)]"
      >
        {src ? <img src={src} alt="" className="w-full h-full object-cover" /> : initials(text)}
      </div>
      {upload ? (
        <>
          <button
            type="button"
            aria-label={`Upload ${label} picture`}
            onClick={() => file.current?.click()}
            className="absolute inset-0 grid place-items-center bg-black/40 text-white opacity-0 group-hover:opacity-100 focus-visible:opacity-100"
          >
            <Camera aria-hidden size={24} />
          </button>
          <input
            ref={file} type="file" accept="image/*" hidden aria-label={`${label} picture file`}
            onChange={(e) => {
              const f = e.target.files?.[0];
              if (f) void avatarDataUrl(f, 96).then(upload.onPick).catch(() => upload.onError("not an image"));
              e.target.value = "";
            }}
          />
        </>
      ) : (
        <button
          type="button"
          disabled
          title="not wired"
          aria-label="Upload picture (not wired)"
          className="absolute inset-0 grid place-items-center bg-black/40 text-white opacity-0 group-hover:opacity-100 cursor-not-allowed"
        >
          <Camera aria-hidden size={24} />
        </button>
      )}
    </div>
  );
}

export default function YourAccountTab() {
  const username = useUser().user?.username ?? "";
  const blob = useSettingsBlob<AccountSettings>("account", DEFAULTS);
  const agencyName = blob.value.agency_name;
  const [pictureError, setPictureError] = useState<string | null>(null);

  return (
    <SettingsPanel title="Your Account" actions={<SaveRow {...blob.save} gateNote={null} look="settings" />}>
      <Section title="Personal">
        <Field label="Picture">
          <Picture label="Personal" text={username} />
        </Field>
        <Field label="Username" htmlFor="account-username">
          <div className="flex items-center">
            <FieldInput
              id="account-username"
              readOnly
              value={username}
            />
            <div className="ml-[10px]">
              <NotWired label="Edit" />
            </div>
          </div>
        </Field>
        <Field label="Telegram username (recommended)" htmlFor="account-telegram">
          <FieldInput
            id="account-telegram"
            maxLength={32}
            placeholder="@username"
            value={blob.value.telegram_username ?? ""}
            onChange={(e) => blob.set({ telegram_username: e.target.value })}
          />
        </Field>
      </Section>
      <Section title="Agency info">
        <Field label="Picture">
          <Picture
            label="Agency"
            text={agencyName || username}
            src={blob.value.agency_picture}
            upload={{
              onPick: (agency_picture) => { setPictureError(null); blob.set({ agency_picture }); },
              onError: setPictureError,
            }}
          />
          {pictureError && <p role="alert" className="mt-1 text-[length:var(--if-fs-sm)] text-err">{pictureError}</p>}
        </Field>
        <Field label="Agency Name" htmlFor="account-agency-name">
          <FieldInput
            id="account-agency-name"
            value={agencyName}
            onChange={(e) => blob.set({ agency_name: e.target.value })}
          />
        </Field>
      </Section>
      <div className="flex flex-col gap-3">
        <NotAppliedYet />
        <BlobNotes note={blob.save.gateNote} q={blob.query} />
      </div>
    </SettingsPanel>
  );
}
