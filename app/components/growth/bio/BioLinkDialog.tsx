"use client";

/**
 * The bio editor's link dialog ("Add link" / "Edit link"), almost full screen on a phone: title, destination, icon,
 * background image, the 18+ gate, Mode, and "Tracking and Geo Rule" (OnlyFans tracking, the default code with a picker
 * of the Creator's OnlyFans tracking links, the Geo Rule). Copy after v2 `links.js`. State: `bioLinkForm.ts`, held by
 * BioEditor (the preview draws the draft); this dialog dispatches and runs the save: the link write, then the
 * background upload or removal. A background that fails after the link saved leaves the dialog on the saved link.
 */
import { useId, type Dispatch } from "react";
import { ChevronDown } from "lucide-react";

import {
  IfButton, IfHelp, IfInput, IfLabel, IfModal, IfNativeSelect, IfSwitch, IfTextArea,
} from "@/components/ui/infloww";
import { useOfTrackingLinks } from "@/hooks/useGrowth";
import {
  BIO_MODES, bioFailure, useBioLinkBackground, useCreateBioLink, usePatchBioLink,
  type BioLink, type BioMode, type BioPage, type StockIcon,
} from "@/hooks/useBioPages";
import {
  buildLinkPayload, canSubmit, isDirty, type Action, type BioLinkForm, type IconChoice, type LinkMode,
} from "@/components/growth/bio/bioLinkForm";
import { MODE_NAMES } from "@/components/growth/bio/bioBits";
import { trackingRows, draftLinkView } from "@/components/growth/bio/bioPreviewModel";
import { IMAGE_ACCEPT, MAX_TITLE } from "@/components/growth/bio/bioRules";
import { cn } from "@/lib/utils";

const ICONS: Array<[StockIcon, string]> = [
  ["onlyicon", "OnlyFans"], ["linkicon", "Link"], ["twitchicon", "Twitch"], ["igicon", "Instagram"],
];

export function BioLinkDialog({ page, form, dispatch, profileMode, bgPreviewUrl }: {
  page: BioPage;
  form: BioLinkForm;
  dispatch: Dispatch<Action>;
  /** The profile's Mode as edited: what "Profile default" means right now. */
  profileMode: BioMode;
  /** The picked background's object URL (BioEditor owns it; the preview draws it too). */
  bgPreviewUrl: string | null;
}) {
  const pid = page.profile.id;
  const id = useId();
  const create = useCreateBioLink(pid);
  const patch = usePatchBioLink(pid);
  const background = useBioLinkBackground(pid);
  const accountId = page.profile.account_id;
  const ofLinks = useOfTrackingLinks(accountId);
  const codes = trackingRows(ofLinks.data?.links ?? [], page.profile.public_url ?? `/${page.profile.username}`);
  const d = form.draft;
  const base = form.open ? form.base : null;
  const bad = (field: string) => form.error?.fields.includes(field) || undefined;
  const set = (patch: Partial<BioLinkForm["draft"]>) => dispatch({ type: "set", patch });
  const close = () => dispatch({ type: "close" });

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    dispatch({ type: "submit" });
    if (!canSubmit(form)) return;
    const body = buildLinkPayload(base, d);
    let link: BioLink | null = base;
    try {
      if (!base) {
        const before = new Set(page.links.map((l) => l.id));
        const P = await create.mutateAsync(body!);
        // service/bio_pages/admin.py:433-443 assigns max(sort_order)+1 under _lock_own;
        // _page at :182-183 returns the links sorted in that transaction.
        link = P.links.filter((l) => !before.has(l.id)).at(-1) ?? null;
        if (!link) throw new Error("The link was saved; reload the page to see it.");
        dispatch({ type: "saved", link });
      } else if (body) {
        const P = await patch.mutateAsync({ lid: base.id, body });
        link = P.links.find((l) => l.id === base.id) ?? base;
        dispatch({ type: "saved", link });
      }
    } catch (err) {
      const f = bioFailure(err, "Save failed");
      dispatch({ type: "failed", msg: f.msg, fields: f.fields });
      return;
    }
    if (!link) return;
    try {
      if (form.bgFile) await background.mutateAsync({ lid: link.id, file: form.bgFile });
      else if (form.bgRemove && link.background_image) await background.mutateAsync({ lid: link.id, file: null });
    } catch (err) {
      dispatch({ type: "failed", msg: `Link saved; the background failed: ${bioFailure(err, "upload failed").msg}` });
      return;
    }
    close();
  }

  const linkView = draftLinkView(form, bgPreviewUrl);
  const iconSrc = linkView?.iconUrl ?? "";
  const bgSrc = linkView?.backgroundUrl ?? "";
  const touched = isDirty(form);
  return (
    <IfModal title={base ? "Edit link" : "Add link"} width={600} size="editor" onClose={close}
      keyboard={!touched && !form.busy} closable={!form.busy}
      footer={<>
        {form.error && <p role="alert" className="mr-auto min-w-0 basis-full text-[12px] text-err sm:basis-auto">{form.error.msg}</p>}
        <IfButton onClick={close} disabled={form.busy}>Cancel</IfButton>
        <IfButton type="submit" form={id} variant="primary" disabled={form.busy}>
          {form.busy ? "Saving…" : "Save link"}
        </IfButton>
      </>}>
      <form id={id} onSubmit={submit} noValidate>
        <fieldset disabled={form.busy} className="space-y-4">
          <p className="text-[13px] text-fg-dim">Where the card on your page leads.</p>
          <div>
            <IfLabel htmlFor={`${id}-title`} required>Title</IfLabel>
            <IfInput id={`${id}-title`} className="w-full" value={d.title} maxLength={MAX_TITLE} autoComplete="off"
              aria-invalid={bad("title")} onChange={(e) => set({ title: e.target.value })} />
            <IfHelp>What Visitors read on the card.</IfHelp>
          </div>
          <div>
            <IfLabel htmlFor={`${id}-dest`} required>Destination</IfLabel>
            <IfInput id={`${id}-dest`} className="w-full" value={d.destination} inputMode="url" autoComplete="off"
              autoCapitalize="none" spellCheck={false} placeholder="https://" aria-invalid={bad("destination")}
              onChange={(e) => set({ destination: e.target.value })} />
            <IfHelp>Where the Link leads. Starts with https://, http:// or /.</IfHelp>
          </div>
          <div>
            <IfLabel htmlFor={`${id}-icon`}>Icon</IfLabel>
            <div className="flex items-center gap-3">
              <IfNativeSelect id={`${id}-icon`} className="min-w-0 flex-1" value={d.icon}
                onChange={(e) => set({ icon: e.target.value as IconChoice })}>
                {base?.icon && !base.icon_stock && <option value="current">Current icon</option>}
                <option value="none">None</option>
                {ICONS.map(([stem, label]) => <option key={stem} value={stem}>{label}</option>)}
              </IfNativeSelect>
              <span aria-hidden className="h-11 w-11 shrink-0 rounded-md bg-bg-elev-2 bg-contain bg-center bg-no-repeat"
                style={iconSrc ? { backgroundImage: `url("${iconSrc}")` } : undefined} />
            </div>
            <IfHelp>Shows on the link&rsquo;s background image only.</IfHelp>
          </div>
          <div>
            <IfLabel htmlFor={`${id}-bg`}>Background image</IfLabel>
            <div className="flex flex-wrap items-center gap-3">
              {bgSrc && (
                <span aria-hidden className="h-11 w-[110px] shrink-0 rounded-md bg-cover bg-center"
                  style={{ backgroundImage: `url("${bgSrc}")` }} />
              )}
              <input key={String(form.bgRemove)} id={`${id}-bg`} type="file" accept={IMAGE_ACCEPT}
                className="min-w-0 max-w-full text-[13px] text-fg-dim file:mr-3 file:h-8 file:rounded-md file:border file:border-border file:bg-transparent file:px-3 file:text-fg"
                onChange={(e) => dispatch({ type: "pick_bg", file: e.target.files?.[0] ?? null })} />
            </div>
            <IfHelp>Any photo: jpg, png, gif or webp. Shown behind the title.</IfHelp>
            {base?.background_image && (
              <div className="mt-2">
                <IfSwitch checked={form.bgRemove} label="Remove background"
                  onChange={(on) => dispatch({ type: "remove_bg", on })} />
                <IfHelp>Picking a new image replaces it instead.</IfHelp>
              </div>
            )}
          </div>
          <div>
            <IfSwitch checked={d.isAdult} label="18+ Age Gate" onChange={(isAdult) => set({ isAdult })} />
            <IfHelp>Visitors who tap it on your page confirm they are 18 or older first. Works with any Mode.</IfHelp>
          </div>
          <div>
            <IfLabel htmlFor={`${id}-mode`}>Mode</IfLabel>
            <IfNativeSelect id={`${id}-mode`} className="w-full" value={d.mode}
              onChange={(e) => set({ mode: e.target.value as LinkMode })}>
              <option value="">Profile default (currently {MODE_NAMES[profileMode]})</option>
              {BIO_MODES.map((m) => <option key={m} value={m}>{MODE_NAMES[m]}</option>)}
            </IfNativeSelect>
            <IfHelp>How a tap leaves Instagram or TikTok. Not sure? Keep Profile default.</IfHelp>
          </div>

          <div className="rounded-md border border-border">
            <button type="button" aria-expanded={form.advanced} onClick={() => dispatch({ type: "toggle_advanced" })}
              className="flex w-full items-center gap-2 px-3 py-2 text-left">
              <ChevronDown aria-hidden className={cn("h-4 w-4 shrink-0 transition-transform", !form.advanced && "-rotate-90")} />
              {/* One line for the heading; the hint goes under it on a phone, beside it from sm */}
              <span className="flex min-w-0 flex-1 flex-col sm:flex-row sm:items-baseline sm:gap-2">
                <span className="whitespace-nowrap text-[14px] text-fg">Tracking and Geo Rule</span>
                <span aria-hidden className="truncate text-[12px] text-muted">Only for OnlyFans Links.</span>
              </span>
            </button>
            {form.advanced && (
              <div className="space-y-4 border-t border-border px-3 py-3">
                <div>
                  <IfSwitch checked={d.tracking} label="OnlyFans tracking" onChange={(tracking) => set({ tracking })} />
                  <IfHelp>Adds a Tracking Code to the address so OnlyFans credits each subscriber to its source.</IfHelp>
                </div>
                <div>
                  <IfLabel htmlFor={`${id}-code`}>Default Tracking Code</IfLabel>
                  <div className="flex flex-wrap gap-2">
                    <IfInput id={`${id}-code`} className="w-40" value={d.code} inputMode="numeric" autoComplete="off"
                      maxLength={20} aria-invalid={bad("default_tracking_code")}
                      onChange={(e) => set({ code: e.target.value })} />
                    {codes.length > 0 && (
                      <IfNativeSelect aria-label="Pick a tracking link" className="min-w-0 flex-1" value=""
                        onChange={(e) => e.target.value && set({ code: e.target.value })}>
                        <option value="">Pick a tracking link…</option>
                        {codes.map((l) => <option key={l.key} value={l.code}>{l.name} ({l.code})</option>)}
                      </IfNativeSelect>
                    )}
                  </div>
                  <IfHelp>Digits only. Used when no other code applies.</IfHelp>
                </div>
                <div>
                  <IfLabel htmlFor={`${id}-geo`}>Geo Rule</IfLabel>
                  <IfTextArea id={`${id}-geo`} rows={4} spellCheck={false} autoCapitalize="none" value={d.geoText}
                    className="font-mono text-[13px]" aria-invalid={bad("geo")}
                    onChange={(e) => set({ geoText: e.target.value })} />
                  <IfHelp>
                    Advanced: Tracking Codes per country as JSON, e.g. {'{"US": "5"}'}. Leave it empty for none. Used for
                    visitors who arrive at /{page.profile.username}/geo.
                  </IfHelp>
                </div>
              </div>
            )}
          </div>
        </fieldset>
      </form>
    </IfModal>
  );
}
