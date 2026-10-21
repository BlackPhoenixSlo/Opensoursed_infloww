import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { useRef, type ReactNode } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, render } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { ScopeOverride, ScopeProvider } from "@/contexts/ScopeContext";
import { loadVaultPick, massDraftKey, useOfChat, vaultPickKey } from "./ofMirrorChat";
import { useStandIn } from "./ofMirrorProfile";
import { MASS_VAULT } from "./ofMirrorRow";
import { relay } from "./relay";

const router = { push: vi.fn(), replace: vi.fn() };
vi.mock("next/navigation", () => ({ useRouter: () => router, useSearchParams: () => new URLSearchParams() }));
vi.mock("@/contexts/UserContext", () => ({ useUser: () => ({ user: { user_id: "owner-1" } }) }));
vi.mock("@/contexts/ChatterContext", () => ({ useChatter: () => ({ chatter: null }) }));
vi.mock("@/lib/events", () => ({ eventBus: { setScope: vi.fn(), on: () => () => {}, onStateChange: () => () => {} } }));

const MODEL = "7";
const VAULT_SRC = "/of-mirror/pages/messages/send/state-vault.html";
const SEND_SRC = "/of-mirror/pages/messages/send.html";
const ACCOUNTS = ["accounts", "owner-1"];
const load = (page: string) => {
  document.documentElement.innerHTML = readFileSync(resolve(__dirname, `../public/of-mirror/pages/messages/${page}.html`), "utf8");
  document.body.className = "";
};
/** The frame as useOfChat reads it: the page in it is loaded (readyState complete), so it binds at once. */
const frame = { contentDocument: document, addEventListener: () => {}, removeEventListener: () => {} } as unknown as HTMLIFrameElement;

function Composer({ src }: { src: string }) {
  useOfChat(useRef(frame), src);
  return null;
}
/** OfMirrorFrame's stand-in over the composer hook, as in All models. */
function Page({ src }: { src: string }) {
  return (
    <ScopeOverride accountId={useStandIn(src)}>
      <Composer src={src} />
    </ScopeOverride>
  );
}

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
  sessionStorage.clear();
});

describe("New message back from its vault while the model list answers nothing (All models)", () => {
  it("still binds as the model the vault was open for: the draft's text and status line back, the vault's ticks dropped", () => {
    vi.spyOn(relay, "get").mockReturnValue(new Promise(() => {}));
    sessionStorage.setItem(massDraftKey(MODEL), JSON.stringify({ text: "typed before the vault", user_lists: [], media_files: [11], thumbs: [""] }));
    const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    qc.setQueryData(ACCOUNTS, { accounts: [{ id: MODEL, has_session: true, is_active: true }], active_account_id: MODEL });
    const wrap = (node: ReactNode) => (
      <QueryClientProvider client={qc}>
        <ScopeProvider>{node}</ScopeProvider>
      </QueryClientProvider>
    );

    // The vault open for the stand-in model: a tile ticked.
    load("send/state-vault");
    const { rerender } = render(wrap(<Page key={VAULT_SRC} src={VAULT_SRC} />));
    sessionStorage.setItem(vaultPickKey(MODEL, MASS_VAULT), JSON.stringify({ ids: [22], thumbs: [""] }));

    // The model list answers nothing for a moment (a refetch's empty answer), then Close: a fresh page, New message.
    qc.setQueryData(ACCOUNTS, { accounts: [], active_account_id: null });
    load("send");
    rerender(wrap(<Page key={SEND_SRC} src={SEND_SRC} />));

    expect(document.querySelector("[contenteditable][aria-label='Textbox field']")?.textContent).toBe("typed before the vault");
    expect(document.getElementById("oi-chat-summary")?.textContent).toContain("1 media");
    expect(loadVaultPick(sessionStorage, vaultPickKey(MODEL, MASS_VAULT)).ids).toEqual([]);
  });

  it("a list that names the model without a session is an answer: no model", () => {
    vi.spyOn(relay, "get").mockReturnValue(new Promise(() => {}));
    sessionStorage.setItem(massDraftKey(MODEL), JSON.stringify({ text: "kept", user_lists: [] }));
    const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    qc.setQueryData(ACCOUNTS, { accounts: [{ id: MODEL, has_session: true, is_active: true }], active_account_id: MODEL });
    const wrap = (node: ReactNode) => (
      <QueryClientProvider client={qc}>
        <ScopeProvider>{node}</ScopeProvider>
      </QueryClientProvider>
    );
    load("send/state-vault");
    const { rerender } = render(wrap(<Page key={VAULT_SRC} src={VAULT_SRC} />));
    qc.setQueryData(ACCOUNTS, { accounts: [{ id: MODEL, has_session: false }], active_account_id: MODEL });
    load("send");
    rerender(wrap(<Page key={SEND_SRC} src={SEND_SRC} />));
    expect(document.querySelector("[contenteditable][aria-label='Textbox field']")?.textContent).toBe("");
  });
});
