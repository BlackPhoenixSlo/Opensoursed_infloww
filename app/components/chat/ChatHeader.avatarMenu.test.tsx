/**
 * ChatHeader — the Avatar menu and the name, badge and presence line that
 * open it (ticket 95; look-and-feel ticket 141, which drew no avatar and added
 * the verified badge).
 *
 * Moved out of `ChatHeader.test.tsx` unchanged (ticket 141, to keep that file
 * under 1000 lines); the same seam, the `ChatHeader` render test. The relay
 * client is mocked at its module boundary and the session contexts are
 * stubbed, as that file does. Fixture identifiers are invented.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

const { relayGet, relayPost, relayDelete, relayPut } = vi.hoisted(() => ({
  relayGet: vi.fn(), relayPost: vi.fn(), relayDelete: vi.fn(), relayPut: vi.fn(),
}));

vi.mock("@/lib/relay", async (importOriginal) => ({
  describeLoadError: (await importOriginal<typeof import("@/lib/relay")>()).describeLoadError,
  relay: {
    get: (...args: unknown[]) => relayGet(...args),
    post: (...args: unknown[]) => relayPost(...args),
    delete: (...args: unknown[]) => relayDelete(...args),
    put: (...args: unknown[]) => relayPut(...args),
  },
  proxyImage: () => "",
}));

// The Kebab menu reads the role's Function permissions; this suite's role denies none.
vi.mock("@/components/shell/useGrantedPages", () => ({ useActionAllowed: () => true }));

// An owner signed in, no chatter, no employee (as ChatHeader.test.tsx stubs them).
vi.mock("@/contexts/UserContext", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/contexts/UserContext")>();
  const value = { user: { user_id: "u-owner", username: "owner" }, loading: false, logout: vi.fn() };
  return { ...actual, useUser: () => value, useOptionalUser: () => value };
});
vi.mock("@/contexts/ChatterContext", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/contexts/ChatterContext")>();
  const value = { chatter: null, loading: false, logout: vi.fn() };
  return { ...actual, useChatter: () => value, useOptionalChatter: () => value };
});
vi.mock("@/contexts/EmployeeContext", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/contexts/EmployeeContext")>();
  const value = { current: null, hydrated: true, pickedId: null, clear: vi.fn() };
  return { ...actual, useEmployee: () => value };
});

import type { ComponentProps } from "react";
import type { QueryClient } from "@tanstack/react-query";
import type { OFChatItem } from "@/lib/relay";
import { makeTestQueryClient, renderWithProviders } from "@/test-utils";
import { ChatHeader } from "./ChatHeader";

const ACCOUNT_ID = "100000001";
const FAN_ID = 200000001;
const CHAT = {
  withUser: {
    id: FAN_ID, name: "Fixture Fan One", username: "fixturefanone",
    avatar: null, customNickname: null, displayName: null,
  },
  hasUnread: false, unreadMessagesCount: 0, isOnline: false,
  canSendMessage: true, canNotSendReason: null, isMutedNotifications: false,
} as unknown as OFChatItem;

type Props = ComponentProps<typeof ChatHeader>;

function renderHeader(over: Partial<Props> = {}, client?: QueryClient) {
  const props: Props = {
    accountId: ACCOUNT_ID,
    fanId: FAN_ID,
    chat: CHAT,
    name: "Fixture Fan One",
    username: "fixturefanone",
    findOpen: false,
    onToggleFind: vi.fn(),
    refreshing: false,
    onRefresh: vi.fn(),
    onOpenNotes: vi.fn(),
    onEditName: vi.fn(),
    insightsOpen: false,
    onToggleInsights: vi.fn(),
    extras: { focusMode: false, onToggleFocus: vi.fn() },
    ...over,
  };
  renderWithProviders(<ChatHeader {...props} />, client);
  return { props };
}

/** The relay serves `routes` by exact path, `{}` elsewhere. */
const serve = (routes: Record<string, unknown> = {}) =>
  relayGet.mockImplementation(async (path: string) => {
    if (path === "/admin/accounts") return { accounts: [] };
    return path in routes ? routes[path] : {};
  });

beforeEach(() => {
  relayPost.mockReset().mockResolvedValue({});
  relayDelete.mockReset().mockResolvedValue({});
  relayPut.mockReset().mockResolvedValue({});
  relayGet.mockReset();
  serve();
});

afterEach(() => {
  cleanup();
});

describe("ChatHeader", () => {
  describe("Avatar menu (ticket 95)", () => {
    const USER = `/api/of/v2/users/${FAN_ID}`;
    const FOLDERS = "/api/of/v2/chats/folders?limit=50";
    /** The OF user and the lists the relay serves for this Fan. */
    const relayWith = (ofUser: Record<string, unknown>, lists: Record<string, unknown>[] = []) =>
      serve({ [USER]: ofUser, [FOLDERS]: { list: lists, hasMore: false } });
    /** The Avatar menu, a plain box as the Kebab menu is: found through its first row. */
    const avatarMenu = async () => (await screen.findByText("Subscription status")).closest<HTMLElement>("[id]")!;
    const row = (menu: HTMLElement, label: string) => within(menu).getByText(label).parentElement!;
    // Pressed on the Fan's name, which sits in the "Avatar menu" button (no avatar is drawn, ticket 141).
    const openAvatarMenu = async (user: ReturnType<typeof userEvent.setup>) => {
      await user.click(screen.getByText("Fixture Fan One"));
      return avatarMenu();
    };

    it('the verified badge follows the name, inside the Avatar menu button, only when the cached OF user says isVerified (no new request); the header draws no img, even with an avatar URL known', () => {
      const withAvatar = { ...CHAT, withUser: { ...CHAT.withUser, avatar: "https://fixture.invalid/avatar.jpg" } } as unknown as OFChatItem;
      renderHeader({ chat: withAvatar });
      expect(screen.queryByRole("img", { name: "Verified" })).toBeNull();
      expect(document.querySelector("header img")).toBeNull();

      cleanup();
      const client = makeTestQueryClient();
      client.setQueryData(["of-user", ACCOUNT_ID, FAN_ID], { id: FAN_ID, isVerified: true });
      renderHeader({ chat: withAvatar }, client);
      const badge = screen.getByRole("img", { name: "Verified" });
      expect(screen.getByTitle("Avatar menu")).toContainElement(badge);
      expect(screen.getByText("Fixture Fan One").compareDocumentPosition(badge) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
      expect(document.querySelector("header img")).toBeNull();
      expect(relayGet).not.toHaveBeenCalledWith(USER, expect.anything());
    });

    it('the name opens the Avatar menu, not Fan insights: Subscription status, Earnings, Special offers and "Add to lists ▸" in that order; seeded values show as the status and dollars, no status with a past expiry reads "Expired", and missing values read "—"', async () => {
      const user = userEvent.setup();
      relayWith({ id: FAN_ID, subscribedOnData: { status: "Set to Expire", expiredAt: "2099-01-01T00:00:00Z", totalSumm: 42.5 } });
      const { props } = renderHeader();
      const trigger = screen.getByTitle("Avatar menu");
      expect(trigger).toHaveAttribute("aria-expanded", "false");
      let menu = await openAvatarMenu(user);
      expect(trigger).toHaveAttribute("aria-expanded", "true");
      expect(props.onToggleInsights).not.toHaveBeenCalled();
      const labels = ["Subscription status", "Earnings", "Special offers ▸", "Add to lists ▸"];
      const rows = labels.map((label) => within(menu).getByText(label));
      rows.slice(1).forEach((el, i) => {
        expect(rows[i].compareDocumentPosition(el) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
      });
      await waitFor(() => expect(row(menu, "Subscription status")).toHaveTextContent("Subscription statusSet to Expire"));
      expect(row(menu, "Earnings")).toHaveTextContent("Earnings$42.50");

      // Escape closes it, and so does a pointer-down outside it.
      await user.keyboard("{Escape}");
      await waitFor(() => expect(screen.queryByText("Subscription status")).toBeNull());
      menu = await openAvatarMenu(user);
      await user.pointer({ keys: "[MouseLeft>]", target: document.body });
      await waitFor(() => expect(screen.queryByText("Subscription status")).toBeNull());
      await user.pointer({ keys: "[/MouseLeft]", target: document.body });

      cleanup();
      relayWith({ id: FAN_ID, subscribedOnData: { status: null, expiredAt: "2020-01-01T00:00:00Z" } });
      renderHeader();
      menu = await openAvatarMenu(user);
      await waitFor(() => expect(row(menu, "Subscription status")).toHaveTextContent("Subscription statusExpired"));
      expect(row(menu, "Earnings")).toHaveTextContent("Earnings—");

      cleanup();
      relayWith({ id: FAN_ID, subscribedOnData: { status: null, expiredAt: "2099-01-01T00:00:00Z" } });
      renderHeader();
      menu = await openAvatarMenu(user);
      await waitFor(() => expect(relayGet).toHaveBeenCalledWith(USER, { accountId: ACCOUNT_ID }));
      expect(row(menu, "Subscription status")).toHaveTextContent("Subscription status—");
      expect(row(menu, "Earnings")).toHaveTextContent("Earnings—");
    });

    describe('"Special offers ▸" (roadmap 4.5, the discount only)', () => {
      const ME = "/api/of/v2/users/me";
      const DISCOUNT = `/api/of/v2/subscriptions/${FAN_ID}/discount`;
      /** A Creator at `price` dollars a month and this Fan. */
      const offersWith = (ofUser: Record<string, unknown>, price = 10) =>
        serve({ [USER]: { id: FAN_ID, ...ofUser }, [ME]: { subscribePrice: price } });
      const offersRow = (menu: HTMLElement) => within(menu).getByRole("button", { name: "Special offers ▸" });

      it("is disabled, its title saying why, for a Fan OF offers no discount (never subscribed, or a free page); a click opens nothing", async () => {
        const user = userEvent.setup();
        offersWith({ subscribedOn: false });
        renderHeader();
        let menu = await openAvatarMenu(user);
        await waitFor(() => expect(offersRow(menu)).toHaveAttribute("title", expect.stringMatching(/current or past subscriber/)));
        expect(offersRow(menu)).toHaveAttribute("aria-disabled", "true");
        await user.click(offersRow(menu));
        expect(within(menu).getByText("Subscription status")).toBeInTheDocument();

        cleanup();
        offersWith({ subscribedOn: true }, 0);
        renderHeader();
        menu = await openAvatarMenu(user);
        await waitFor(() => expect(relayGet).toHaveBeenCalledWith(ME, expect.anything()));
        await waitFor(() => expect(offersRow(menu)).toHaveAttribute("aria-disabled", "true"));
        expect(relayPut).not.toHaveBeenCalled();
      });

      it("offers OF's percents (5 up to what keeps the price above $4.99, by 5) and 1..12 months, says the price left, and Apply PUTs {discount, period}; Clear is off with no discount set", async () => {
        const user = userEvent.setup();
        offersWith({ subscribedOn: true });
        renderHeader();
        const menu = await openAvatarMenu(user);
        await waitFor(() => expect(offersRow(menu)).toHaveAttribute("aria-disabled", "false"));
        await user.click(offersRow(menu));
        const [percent, period] = within(menu).getAllByRole("combobox");
        expect([...percent.querySelectorAll("option")].map((o) => o.textContent))
          .toEqual(["5% discount", "10% discount", "15% discount", "20% discount", "25% discount",
                    "30% discount", "35% discount", "40% discount", "45% discount", "50% discount"]);
        expect(period.querySelectorAll("option")).toHaveLength(12);
        expect(within(menu).getByRole("button", { name: "Clear" })).toBeDisabled();
        await user.selectOptions(percent, "20");
        await user.selectOptions(period, "3");
        expect(within(menu).getByText("$8.00 per month for 3 months")).toBeInTheDocument();
        await user.click(within(menu).getByRole("button", { name: "Apply" }));
        await waitFor(() => expect(relayPut).toHaveBeenCalledWith(DISCOUNT, { discount: 20, period: 3 }, { accountId: ACCOUNT_ID }));
        expect(await within(menu).findByText(/Discount applied/)).toBeInTheDocument();
        expect(within(menu).getByText("Subscription status")).toBeInTheDocument();
        expect(relayPost).not.toHaveBeenCalled();
      });

      it("opens on the Fan's current discount; Clear PUTs {0, 1}; a rejected write shows the relay's error and stays open", async () => {
        const user = userEvent.setup();
        offersWith({ subscribedOn: true, subscribedOnData: { discountPercent: 15, discountPeriod: 2 } });
        renderHeader();
        const menu = await openAvatarMenu(user);
        await waitFor(() => expect(offersRow(menu)).toHaveAttribute("aria-disabled", "false"));
        await user.click(offersRow(menu));
        const [percent, period] = within(menu).getAllByRole<HTMLSelectElement>("combobox");
        expect([percent.value, period.value]).toEqual(["15", "2"]);

        relayPut.mockRejectedValueOnce(new Error("upstream 400: fixture discount refused"));
        await user.click(within(menu).getByRole("button", { name: "Apply" }));
        expect(await within(menu).findByText(/Could not save the discount: upstream 400: fixture discount refused/)).toBeInTheDocument();
        expect(within(menu).getByRole("button", { name: "Apply" })).toBeEnabled();

        await user.click(within(menu).getByRole("button", { name: "Clear" }));
        await waitFor(() => expect(relayPut).toHaveBeenLastCalledWith(DISCOUNT, { discount: 0, period: 1 }, { accountId: ACCOUNT_ID }));
        expect(await within(menu).findByText(/Discount cleared/)).toBeInTheDocument();
      });
    });

    it('"Add to lists ▸" lists the Creator\'s lists from the chat-folders route with the Fan\'s marked; a click POSTs the Fan onto a list, or DELETEs them from one they are on; the Kebab menu no longer lists it', async () => {
      const user = userEvent.setup();
      relayWith({ id: FAN_ID }, [
        { id: 31, name: "Fixture List A", canAddUsers: true, users: [] },
        { id: 32, name: "Fixture List B", canAddUsers: true, users: [{ id: FAN_ID }] },
      ]);
      renderHeader();
      const menu = await openAvatarMenu(user);
      await user.click(within(menu).getByRole("button", { name: "Add to lists ▸" }));
      const listA = await within(menu).findByRole("button", { name: /Fixture List A/ });
      const listB = within(menu).getByRole("button", { name: /Fixture List B/ });
      expect(relayGet).toHaveBeenCalledWith(FOLDERS, { accountId: ACCOUNT_ID });
      expect(listA).toHaveAttribute("aria-pressed", "false");
      expect(listB).toHaveAttribute("aria-pressed", "true");

      await user.click(listA);
      await waitFor(() => expect(relayPost).toHaveBeenCalledWith(
        `/api/of/v2/lists/31/users/${FAN_ID}`, undefined, { accountId: ACCOUNT_ID }));
      await waitFor(() => expect(listA).toHaveAttribute("aria-pressed", "true"));
      await user.click(listB);
      await waitFor(() => expect(relayDelete).toHaveBeenCalledWith(
        `/api/of/v2/lists/32/users/${FAN_ID}`, { accountId: ACCOUNT_ID }));
      expect(relayPost).toHaveBeenCalledTimes(1);
      expect(relayDelete).toHaveBeenCalledTimes(1);

      await user.click(screen.getByRole("button", { name: "More actions" }));
      expect(await screen.findByRole("button", { name: /Hide chat/ })).toBeInTheDocument();
      expect(screen.queryByRole("button", { name: /Add to list/ })).toBeNull();
    });
  });
});
