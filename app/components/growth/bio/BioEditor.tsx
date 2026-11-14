"use client";

/**
 * One bio page's editor (/growth/bio-pages/<id>): the address and custom domain (read-only), the Profile,
 * Links and Tracking URLs cards, Delete, and the live preview, sticky beside the cards from lg up and behind an
 * "Edit | Preview" switch below it. The Profile and link-dialog reducers live here, so the preview draws both drafts.
 */
import { useEffect, useMemo, useReducer, useRef, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useQueryClient } from "@tanstack/react-query";

import { EmptyState, IfCard, IfHelp, IfSegmented, InflowwPageHeader } from "@/components/ui/infloww";
import { ConfirmDeleteButton, errMsg } from "@/components/growth/_bits";
import { useUser } from "@/contexts/UserContext";
import {
  BIO_KEY, BIO_LIST_HREF, isNotFound, useBioPage, useBioPages, useDeleteBioPage, type BioPage,
} from "@/hooks/useBioPages";
import { initProfileForm, bioProfileReducer } from "@/components/growth/bio/bioProfileForm";
import { INITIAL_LINK, bioLinkReducer } from "@/components/growth/bio/bioLinkForm";
import { draftLinkView, previewModel } from "@/components/growth/bio/bioPreviewModel";
import { PageAddress } from "@/components/growth/bio/bioBits";
import { BioProfileCard } from "@/components/growth/bio/BioProfileCard";
import { BioLinksCard } from "@/components/growth/bio/BioLinksCard";
import { BioLinkDialog } from "@/components/growth/bio/BioLinkDialog";
import { BioTrackingUrls } from "@/components/growth/bio/BioTrackingUrls";
import { BioPreview } from "@/components/growth/bio/BioPreview";
import { cn } from "@/lib/utils";

type View = "edit" | "preview";
const VIEWS = [{ value: "edit" as const, label: "Edit" }, { value: "preview" as const, label: "Preview" }];

export function BioEditor({ profileId }: { profileId: string }) {
  const owner = !!useUser().user;
  const q = useBioPage(profileId, owner);
  const router = useRouter();
  const qc = useQueryClient();
  const [goneId, setGoneId] = useState<string | null>(null);
  const back = () => router.push(BIO_LIST_HREF);

  useEffect(() => {
    if (q.isError && isNotFound(q.error) && goneId !== profileId) {
      let active = true;
      queueMicrotask(() => {
        if (!active) return;
        setGoneId(profileId);
        qc.removeQueries({ queryKey: [BIO_KEY, profileId], exact: true });
      });
      return () => { active = false; };
    }
  }, [q.isError, q.error, qc, profileId, goneId]);

  if (!owner) return <Notice title="Bio page" text="Bio pages are owner-only." onBack={back} />;
  if (goneId === profileId || (q.isError && isNotFound(q.error))) {
    return <Notice title="Bio page" text="This bio page doesn't exist." onBack={back} />;
  }
  if (q.isError && !q.data) {
    return <Notice title="Bio page" text={errMsg(q.error, "Couldn't load this bio page.")} onBack={back} onRetry={() => q.refetch()} />;
  }
  if (!q.data) return <Notice title="Bio page" text="Loading…" onBack={back} plain />;
  return <Editor page={q.data} onBack={back} refreshError={q.isError ? errMsg(q.error, "Couldn't refresh this bio page.") : null} />;
}

function Notice({ title, text, onBack, onRetry, plain }: {
  title: string; text: string; onBack: () => void; onRetry?: () => void; plain?: boolean;
}) {
  return (
    <div>
      <InflowwPageHeader title={title} onBack={onBack} />
      {plain ? (
        <p className="px-6 py-6 text-sm text-fg-dim">{text}</p>
      ) : (
        <EmptyState size="md" className="py-12" kind={onRetry ? "error" : "data"} text={text} onRetry={onRetry}
          action={<Link href={BIO_LIST_HREF} className="text-[14px] text-accent hover:text-accent-hover">Back to Bio pages</Link>} />
      )}
    </div>
  );
}

/** The picked background's object URL for the dialog's thumb and the preview, revoked when it changes. */
function useObjectUrl(file: File | null): string | null {
  const url = useMemo(() => (file ? URL.createObjectURL(file) : null), [file]);
  useEffect(() => () => { if (url) URL.revokeObjectURL(url); }, [url]);
  return url;
}

function Editor({ page, onBack, refreshError }: { page: BioPage; onBack: () => void; refreshError: string | null }) {
  const { profile } = page;
  const [pform, pdispatch] = useReducer(bioProfileReducer, profile, initProfileForm);
  const [lform, ldispatch] = useReducer(bioLinkReducer, INITIAL_LINK);
  const [view, setView] = useState<View>("edit");
  const fileUrl = useObjectUrl(lform.bgFile);
  const bgUrl = fileUrl ?? lform.bgVault?.url ?? null;
  const remove = useDeleteBioPage(profile.id);
  const router = useRouter();
  const qc = useQueryClient();
  const deleted = useRef(false);
  // Whether the bio service answers (the list's health probe, shared with Bio pages); unknown until it loads.
  const serving = useBioPages().data?.serving;

  useEffect(() => () => {
    if (deleted.current) qc.removeQueries({ queryKey: [BIO_KEY, profile.id], exact: true });
  }, [qc, profile.id]);

  useEffect(() => { pdispatch({ type: "hydrate", profile }); }, [profile]);

  const draft = pform.draft;
  const model = previewModel(
    { ...draft, avatarUrl: profile.avatar_url, backgroundUrl: profile.background_url },
    page.links,
    draftLinkView(lform, bgUrl),
  );
  const dom = profile.custom_domain;
  const deleteCopy = `Deletes /${profile.username}, its ${page.links.length} links, its custom domain and all its stats. The address stops working at once.`;

  return (
    <div className="min-w-0">
      <InflowwPageHeader onBack={onBack}
        title={<><Link href={BIO_LIST_HREF} className="text-fg-dim hover:text-accent">Bio pages</Link>
          <span className="px-1.5 text-fg-dim">/</span>{model.displayName || profile.username}</>}
        extra={<span className="hidden truncate text-[13px] text-fg-dim sm:inline">@{profile.username}</span>} />
      <div className="px-4 py-4 lg:px-6">
        {refreshError && <p role="alert" className="mb-4 text-sm text-err">{refreshError}</p>}
        <IfSegmented options={VIEWS} value={view} onChange={setView} aria-label="Edit or preview" className="mb-4 lg:hidden" />
        <div className="lg:grid lg:grid-cols-[minmax(0,1fr)_390px] lg:items-start lg:gap-6">
          <div className={cn("min-w-0 space-y-4", view === "preview" && "max-lg:hidden")}>
            <IfCard title="Address">
              <PageAddress className="mt-2" url={profile.public_url} path={`/${profile.username}`} />
              {(!profile.public_url || serving === false) && (
                <IfHelp role="note">
                  Not public here yet: {profile.public_url ? "the bio page server isn't answering" : "this server has no public bio address"},
                  so visitors can&rsquo;t open this address. You can still edit the page.
                </IfHelp>
              )}
              <div className="mt-3 flex flex-wrap items-baseline gap-x-2 text-[13px]">
                <span className="text-fg-dim">Custom domain:</span>
                <span className="text-fg" data-custom-domain>{dom ? `${dom.domain} · ${dom.status}` : "None"}</span>
              </div>
              <IfHelp>Custom domains are set up outside this editor for now.</IfHelp>
            </IfCard>
            <BioProfileCard page={page} form={pform} dispatch={pdispatch} />
            <BioLinksCard page={page} onAdd={() => ldispatch({ type: "open_new" })}
              onEdit={(link) => ldispatch({ type: "open_edit", link })} />
            <BioTrackingUrls page={page} />
            <IfCard title="Delete bio page">
              <p className="mt-2 text-sm text-fg-dim">
                {deleteCopy}
              </p>
              <div className="mt-3 flex flex-wrap items-center gap-3">
                <ConfirmDeleteButton label="Delete bio page" pending={remove.isPending}
                  confirm={deleteCopy}
                  onConfirm={() => remove.mutate(undefined, { onSuccess: () => {
                    deleted.current = true;
                    router.push(BIO_LIST_HREF);
                  } })} />
                {remove.error && <span role="alert" className="text-[12px] text-err">{errMsg(remove.error, "Delete failed")}</span>}
              </div>
            </IfCard>
          </div>
          <div className={cn("lg:sticky lg:top-4", view === "edit" && "max-lg:hidden")}>
            <BioPreview model={model} />
          </div>
        </div>
      </div>
      {lform.open && (
        <BioLinkDialog page={page} form={lform} dispatch={ldispatch} bgPreviewUrl={bgUrl}
          profileMode={draft.mode} />
      )}
    </div>
  );
}
