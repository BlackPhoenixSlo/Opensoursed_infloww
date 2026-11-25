import type { Metadata, Viewport } from "next";
import { cookies, headers } from "next/headers";
import localFont from "next/font/local";

import Providers from "@/components/providers";
import InlineBoot from "@/components/InlineBoot";
import AuthGate from "@/components/auth/AuthGate";
import AppShell from "@/components/shell/AppShell";
import { ImpersonationBanner } from "@/components/ImpersonationBanner";
import { NotificationToaster } from "@/components/NotificationToaster";
import { IfConfirmHost } from "@/components/ui/ifConfirm";
import { IdleOverlay } from "@/components/IdleOverlay";
import { ViewLeaseHeartbeat } from "@/components/ViewLeaseHeartbeat";
import { ApiKeyToaster } from "@/components/ApiKeyToaster";
import { MoneyRail } from "@/components/MoneyRail";
import { AssistantProvider, AssistantWidget } from "@/components/assistant/AssistantWidget";
import { DeepLinkTarget } from "@/components/DeepLinkTarget";
import { PageCreatorProvider } from "@/contexts/PageCreatorContext";
import { VaultDownloadProvider } from "@/components/vault/VaultDownloadPanel";

import { BRAND_ICONS, BRAND_NAME } from "@/lib/brand";
import { BOOT_PATH_HEADER } from "@/lib/inlineBoot";
import { inlinePaths, startInline } from "@/lib/inlineBoot.server";

import "./globals.css";

const ui = localFont({
  src: "./fonts/InstrumentSans-Variable.woff2",
  weight: "400 700",
  display: "swap",
  variable: "--font-ui",
});

export const metadata: Metadata = {
  title: {
    default: BRAND_NAME,
    template: `%s · ${BRAND_NAME}`,
  },
  description: "OnlyFans agency dashboard — unified inbox + automations.",
  applicationName: BRAND_NAME,
  icons: BRAND_ICONS,
};

// Zoom locked on purpose: the dense desktop-mirror layout breaks at fractional zoom; OS-level text size still applies.
export const viewport: Viewport = {
  width: "device-width",
  initialScale: 1,
  maximumScale: 1,
  minimumScale: 1,
  userScalable: false,
  viewportFit: "cover",
  themeColor: "#000000",
};

const THEME_BOOT_SCRIPT = `
try {
  var t = localStorage.getItem('chatterly:theme');
  if (t === 'light') document.documentElement.setAttribute('data-theme', 'light');
} catch (_e) {}
`;

const SHELL_BOOT_SCRIPT = `
try {
  var s = window.fasttShell;
  if (s && s.isDesktop === true && s.platform === 'darwin') document.documentElement.setAttribute('data-shell', 'mac');
} catch (_e) {}
`;

// --vvh must exist before first paint, else the composer flashes below the iOS keyboard.
const VVH_BOOT_SCRIPT = `
(function(){
  var vv = window.visualViewport;
  if (!vv) return;
  function update(){
    var st = document.documentElement.style;
    st.setProperty('--vvh', vv.height + 'px');
    st.setProperty('--vvt', vv.offsetTop + 'px');
  }
  update();
  vv.addEventListener('resize', update);
  vv.addEventListener('scroll', update);
})();
`;

// passive:false is required: gesture* events are passive on iOS 14+, which silently no-ops preventDefault().
const PINCH_BLOCK_BOOT_SCRIPT = `
(function(){
  function block(e){ e.preventDefault(); }
  document.addEventListener('gesturestart',  block, { passive: false });
  document.addEventListener('gesturechange', block, { passive: false });
  document.addEventListener('gestureend',    block, { passive: false });
})();
`;

// Inline, not a component: the stale chunk is often the layout chunk itself. Max 3 reloads/session, 60s cooldown, bail if sessionStorage is blocked (no reload loop).
const CHUNK_ERROR_BOOT_SCRIPT = `
(function(){
  var GUARD='chatterly:chunk-reload-attempted',COUNT='chatterly:chunk-reload-count',MAX=3,COOL=60000;
  function stale(e){if(!e)return false;if(e.name==='ChunkLoadError')return true;var m=e.message||'';
    return m.indexOf('Loading chunk')>=0||m.indexOf('Failed to fetch dynamically imported module')>=0||m.indexOf('error loading dynamically imported module')>=0;}
  function reload(){try{var s=sessionStorage.getItem(GUARD);if(s&&Date.now()-Number(s)<COOL)return;
    var c=Number(sessionStorage.getItem(COUNT)||'0');if(c>=MAX){console.warn('[chunk-reloader] reload cap reached');return;}
    sessionStorage.setItem(GUARD,String(Date.now()));sessionStorage.setItem(COUNT,String(c+1));}catch(_){return;}
    location.reload();}
  addEventListener('error',function(ev){if(stale(ev.error)||stale({message:ev.message}))reload();});
  addEventListener('unhandledrejection',function(ev){if(stale(ev.reason))reload();});
})();
`;

export const dynamic = "force-dynamic";

const SESSION_COOKIES = ["chatterly_session", "chatterly_chatter_session"];

export default async function RootLayout({
  children,
}: Readonly<{ children: React.ReactNode }>) {
  const jar = await cookies();
  const signedIn = SESSION_COOKIES.some((n) => jar.has(n));
  const h = await headers();
  const inline = signedIn
    ? startInline(
      inlinePaths(h.get(BOOT_PATH_HEADER), (n) => jar.get(n)?.value),
      h.get("cookie"),
      process.env.RELAY_URL || "http://127.0.0.1:8787",
    )
    : null;
  return (
    <html lang="en" className={ui.variable} suppressHydrationWarning>
      <body className="min-h-dvh bg-bg text-fg antialiased" suppressHydrationWarning>
        <script dangerouslySetInnerHTML={{ __html: THEME_BOOT_SCRIPT }} />
        <script dangerouslySetInnerHTML={{ __html: SHELL_BOOT_SCRIPT }} />
        <script dangerouslySetInnerHTML={{ __html: VVH_BOOT_SCRIPT }} />
        <script dangerouslySetInnerHTML={{ __html: PINCH_BLOCK_BOOT_SCRIPT }} />
        <script dangerouslySetInnerHTML={{ __html: CHUNK_ERROR_BOOT_SCRIPT }} />
        <InlineBoot data={inline} />
        <Providers>
          <AuthGate signedIn={signedIn}>
            <PageCreatorProvider>
              <AssistantProvider>
                <VaultDownloadProvider>
                  <ImpersonationBanner />
                  <AppShell>{children}</AppShell>
                  <NotificationToaster />
                  <IfConfirmHost />
                  <IdleOverlay />
                  <ViewLeaseHeartbeat />
                  <ApiKeyToaster />
                  <MoneyRail />
                  <AssistantWidget />
                  <DeepLinkTarget />
                </VaultDownloadProvider>
              </AssistantProvider>
            </PageCreatorProvider>
          </AuthGate>
        </Providers>
      </body>
    </html>
  );
}
