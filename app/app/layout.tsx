import type { Metadata, Viewport } from "next";
import { cookies, headers } from "next/headers";
import localFont from "next/font/local";

import Providers from "@/components/providers";
import InlineBoot from "@/components/InlineBoot";
import AuthGate from "@/components/auth/AuthGate";
import AppShell from "@/components/shell/AppShell";
import { ImpersonationBanner } from "@/components/ImpersonationBanner";
import { NotificationToaster } from "@/components/NotificationToaster";
import { IdleOverlay } from "@/components/IdleOverlay";
import { ApiKeyToaster } from "@/components/ApiKeyToaster";
import { MoneyRail } from "@/components/MoneyRail";
import { AssistantProvider, AssistantWidget } from "@/components/assistant/AssistantWidget";
import { DeepLinkTarget } from "@/components/DeepLinkTarget";
import { PageCreatorProvider } from "@/contexts/PageCreatorContext";

import { BRAND_ICONS, BRAND_NAME } from "@/lib/brand";
import { BOOT_PATH_HEADER } from "@/lib/inlineBoot";
import { inlinePaths, startInline } from "@/lib/inlineBoot.server";
import { TZ_COOKIE } from "@/lib/screenEntry";

import "./globals.css";

/** Instrument Sans (OFL, app/app/fonts/): the closest free match to Infloww's licensed Suisse Int'l, whose app
 *  ships only Regular 400 and Medium 500 (fe-static-assets.infloww.com/font/SuisseIntl-*-WebS.woff2, declared in
 *  its app.asar). Self-hosted so builds and the demo-shots capture need no Google Fonts. WOFF2 from the upstream
 *  TTF (fontTools; same 501 glyphs and 343 codepoints, wght 400–700 kept) with the wdth axis pinned at its default
 *  100: nothing here sets font-stretch, so the 75–100 width masters were never drawn. 47 KB on the wire against
 *  89 KB with them and 112 KB as TTF; renders pixel-identical at 400–700. To use condensed widths, re-cut from
 *  the TTF without the pin. */
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
  // <meta name="application-name">: the desktop app's notification title fallback (desktop/main.js).
  applicationName: BRAND_NAME,
  // The favicon: public/icon.svg (the OIF mark, SiteLook's IfMark), or a deployment's logo (lib/brand.ts).
  icons: BRAND_ICONS,
};

// Without `width=device-width` mobile browsers render the page at the
// default ~980px viewport and zoom out — fixed widths + dense desktop
// layouts then become unreadable. `viewportFit: cover` lets the chat
// composer slot under iOS Safari's bottom inset; `safe-area-*` padding
// utilities in components handle the offset back.
//
// Zoom is intentionally locked (`maximum=minimum=1`, `userScalable=false`).
// This is an internal agency tool — chatters spend 8h/day in it on
// company-issued phones, and the dense desktop-mirror layout doesn't
// survive a fractional zoom factor (pinch leaves the message list and
// composer at different effective widths). iOS still honors OS-level
// "Display & Text Size" / Android "Display size" even with this lock,
// so accessibility-zoom users aren't shut out — just ad-hoc pinch is.
export const viewport: Viewport = {
  width: "device-width",
  initialScale: 1,
  maximumScale: 1,
  minimumScale: 1,
  userScalable: false,
  viewportFit: "cover",
  // Matches the top bar (`bg-chrome`, globals.css --color-chrome, dark theme)
  // so the mobile browser chrome blends into the shell.
  themeColor: "#000000",
};

// Inline script that runs BEFORE React hydrates so the persisted theme
// is on <html> by the time the first paint happens. Without this you'd
// see a flash of dark mode before the client-side useTheme hook caught
// up. Tiny + safe; the worst-case (localStorage unavailable) falls back
// to the default dark theme defined in globals.css.
const THEME_BOOT_SCRIPT = `
try {
  var t = localStorage.getItem('chatterly:theme');
  if (t === 'light') document.documentElement.setAttribute('data-theme', 'light');
} catch (_e) {}
`;

// The macOS desktop app (desktop/main.js, `titleBarStyle: "hiddenInset"`) draws its traffic lights over
// the page's top-left corner. Its preload sets `window.fasttShell` before any page script, so this marks
// <html data-shell="mac"> before the first paint and the top bar (TopBar) clears them; the web never has it.
const SHELL_BOOT_SCRIPT = `
try {
  var s = window.fasttShell;
  if (s && s.isDesktop === true && s.platform === 'darwin') document.documentElement.setAttribute('data-shell', 'mac');
} catch (_e) {}
`;

// The browser's zone for the server (lib/screenEntry.ts TZ_COOKIE): the next document load's inline Dashboard
// bundle (lib/inlineBoot.server.ts) cuts its days as this browser would.
const TZ_BOOT_SCRIPT = `
try {
  var z = Intl.DateTimeFormat().resolvedOptions().timeZone;
  if (z) document.cookie = '${TZ_COOKIE}=' + encodeURIComponent(z) + '; path=/; max-age=31536000; samesite=lax';
} catch (_e) {}
`;

// Visual-viewport tracker — maintains `--vvh` (px) on <html> so the chat
// surface and composer follow the *visible* area instead of the layout
// viewport. Two reasons to do this in an inline script and not a React
// effect:
//   1. The chat page mounts a 100dvh-tall container; if `--vvh` isn't
//      written before first paint there's a one-frame flash where the
//      composer is below the iOS keyboard.
//   2. iOS Safari fires `visualViewport.resize` *during* keyboard
//      animation. Listening from the layout-level keeps the var in
//      sync across route changes (which would otherwise unmount and
//      re-arm an effect every time).
// `--vvt` is the visual viewport's offsetTop (px): the phone help sheet pins
// its top there (AssistantWidget's VARIANT.sheet).
// Cheap: two DOM property writes per event, no rAF needed.
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

// Pinch-zoom kill switch. The viewport meta already declares
// `maximum-scale=1, user-scalable=no`, which works on Android Chrome —
// but iOS Safari ignores both in some versions / when accessibility
// "page-zoom" is on, leaving pinch-IN still usable. Cancelling the
// `gesturestart` family of events stops the gesture before WebKit
// applies a scale. Same trick used by Slack / Notion / Linear on
// mobile. `passive: false` is required because gesture* events default
// to passive on iOS 14+, which silently no-ops preventDefault().
//
// Also blocks `dblclick` zoom on iOS (double-tap to zoom) via the body
// CSS \`touch-action: manipulation\` that's set in globals.css.
const PINCH_BLOCK_BOOT_SCRIPT = `
(function(){
  function block(e){ e.preventDefault(); }
  document.addEventListener('gesturestart',  block, { passive: false });
  document.addEventListener('gesturechange', block, { passive: false });
  document.addEventListener('gestureend',    block, { passive: false });
})();
`;

// Stale-chunk recovery. Must be an inline script (not a React component)
// because the chunk that most often goes stale after a Turbopack restart
// is the layout chunk itself — if the React tree can't boot, a component-
// based handler never registers its listener and the tab just sits blank
// until the user manually reloads. This script runs while HTML parses,
// before any chunk is requested, so it survives a missing layout chunk.
//
// Same guard semantics as before: ≤3 reloads per session, 60s cooldown,
// bail if sessionStorage is blocked (better a blank tab than a 1000 req/s
// reload loop).
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

// Rendered per request: every page here is an authenticated client surface,
// so there is nothing worth prerendering.
export const dynamic = "force-dynamic";

// The relay's session cookies (service/auth.py COOKIE_NAME, service/chatters.py COOKIE_NAME). Their presence, not
// their validity: AuthGate paints the page's skeleton for a browser that holds one while /auth/me decides.
const SESSION_COOKIES = ["chatterly_session", "chatterly_chatter_session"];

export default async function RootLayout({
  children,
}: Readonly<{ children: React.ReactNode }>) {
  const jar = await cookies();
  const signedIn = SESSION_COOKIES.some((n) => jar.has(n));
  // A document load of the Dashboard or Messages Pro: its first relay answers start now, in this response
  // (lib/inlineBoot.server.ts); not awaited, so the shell streams at once. Never for a browser with no session.
  const h = await headers();
  const inline = signedIn
    ? startInline(
      inlinePaths(h.get(BOOT_PATH_HEADER), (n) => jar.get(n)?.value),
      h.get("cookie"),
      process.env.RELAY_URL || "http://127.0.0.1:8787",
    )
    : null;
  // The font variable lets us reference --font-ui from Tailwind's
  // `font-sans` token (configured in globals.css @theme).
  return (
    <html lang="en" className={ui.variable} suppressHydrationWarning>
      <body className="min-h-dvh bg-bg text-fg antialiased" suppressHydrationWarning>
        {/* This inline script runs synchronously before React hydrates, so
         *  the persisted theme is on <html data-theme=…> by the first paint.
         *  Lives in <body> rather than <head> because Next App Router's
         *  <head> rendering is opinionated and inline scripts there can
         *  end up unreachable in dev mode. */}
        <script dangerouslySetInnerHTML={{ __html: THEME_BOOT_SCRIPT }} />
        <script dangerouslySetInnerHTML={{ __html: SHELL_BOOT_SCRIPT }} />
        <script dangerouslySetInnerHTML={{ __html: TZ_BOOT_SCRIPT }} />
        <script dangerouslySetInnerHTML={{ __html: VVH_BOOT_SCRIPT }} />
        <script dangerouslySetInnerHTML={{ __html: PINCH_BLOCK_BOOT_SCRIPT }} />
        <script dangerouslySetInnerHTML={{ __html: CHUNK_ERROR_BOOT_SCRIPT }} />
        <InlineBoot data={inline} />
        <Providers>
          <AuthGate signedIn={signedIn}>
            {/* The app's model (a page's creator rail, else the switcher). */}
            <PageCreatorProvider>
              {/* One help conversation for the corner dock and /help-center. */}
              <AssistantProvider>
                <ImpersonationBanner />
                <AppShell>{children}</AppShell>
                <NotificationToaster />
                <IdleOverlay />
                <ApiKeyToaster />
                <MoneyRail />
                <AssistantWidget />
                {/* A link's `#go=` steps: opens the inner tab or section it names (lib/deepLink.ts). */}
                <DeepLinkTarget />
              </AssistantProvider>
            </PageCreatorProvider>
          </AuthGate>
        </Providers>
      </body>
    </html>
  );
}
