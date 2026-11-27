const CREATOR_HUB = {
  "plans-promos": "/creator/plans",
  "tracking-links": "/creator/trackinglinks",
  subscribers: "/creator/subscribers",
  followers: "/creator/followers",
  streaming: "/creator/streaming",
  management: "/creator/management",
  uploads: "/creator/uploads",
  lists: "/lists",
  vault: "/creator/vault",
  messages: "/messages",
  "profile-statistics": "/creator/stats/overview",
  earnings: "/creator/wallet/payouts",
  "top-supporters": "/creator/topsupporters",
  "tax-documentation": "/creator/payout/documentation",
  back: "/creator",
};

export const MENU = {
  "creator-dashboard": "/creator",
  ...Object.fromEntries(Object.entries(CREATOR_HUB).map(([k, v]) => [`creator-dashboard-${k}`, v])),
  settings: "/settings/account",
  lists: "/lists",
  "vault-back": "/creator",
  "scheduled-back": "/creator",
  "tracking-links": "/creator/trackinglinks",
  coperformers: "/creator/coperformers",
  "coperformers-new": "/creator/coperformers/new",
  profile: "/{username}",
  subscriptions: "/subscriptions",
  "scheduled-posts": "/scheduled",
  notifications: "/notifications",
  message: "/messages",
  bookmarks: "/bookmarks",
  payments: "/settings/payments",
  "balance-payment-methods": "/settings/payments",
  "balance-earnings-payouts": "/creator/wallet/payouts",
  "media-vault": "/creator/vault",
  messages: "/messages",
  "profile-statistics": "/creator/stats/overview",
  "earning-statistics": "/creator/stats/earnings",
  "tax-documentation": "/creator/payout/documentation",
};

export const TABS = [
  ["statistics", (p) => p.section === "statistics", { overview: "/creator/stats/overview", content: "/creator/stats/content", audience: "/creator/stats/audience", earnings: "/creator/stats/earnings", streams: "/creator/stats/streams" }],
  ["co-performers", (p) => p.section === "creator" && /^coperformers(?:\/|$)/.test(p.sub), { "co-performers": "/creator/coperformers", requests: "/creator/coperformers/requests" }],
  ["wallet", (p) => p.section === "creator" && /^wallet(?:\/|$)/.test(p.sub), { payouts: "/creator/wallet/payouts", "wallet history": "/creator/wallet/history" }],
  ["profile", (p) => p.section === "profile", { posts: "/{username}", media: "/{username}/media", followers: "/{username}/followers", following: "/{username}/following" }],
];

const SELECTORS = [[".notifications.dropdown-trigger", "/notifications"]];

const labelOf = (el) => el.textContent.replace(/\s+/g, " ").trim().toLowerCase();

export function menuWires(doc, { page, here, go, taken, missed }) {
  const out = [];
  const overlaps = (el) => taken.some((w) => w.contains(el) || el.contains(w));
  const wire = (el, target, what) => {
    if (!target || el.closest("a") || overlaps(el)) return;
    const href = go(target);
    if (!href) return void missed.add(`${what} -> ${target}`);
    if (href !== here) out.push([el, "oi-state-link", href, "Open"]);
  };
  for (const el of doc.querySelectorAll("[data-menu-item]")) {
    const name = el.getAttribute("data-menu-item");
    if (Object.hasOwn(MENU, name)) wire(el, MENU[name], `menu ${name}`);
  }
  for (const [sel, target] of SELECTORS) for (const el of doc.querySelectorAll(sel)) wire(el, target, `selector ${sel}`);
  const scope = TABS.find(([, match]) => match(page));
  if (scope)
    for (const el of doc.querySelectorAll(".tab-nav-item, .tab-nav-item2")) {
      const label = labelOf(el);
      if (Object.hasOwn(scope[2], label)) wire(el, scope[2][label], `tab ${scope[0]} "${label}"`);
    }
  return out;
}

export function openDropdowns(doc) {
  for (const el of doc.querySelectorAll(".transparent-dropdown > .dropdown-title, div.balance-dropdown, .user-account > .avatar-container")) if (!el.hasAttribute("tabindex")) el.setAttribute("tabindex", "0");
}
