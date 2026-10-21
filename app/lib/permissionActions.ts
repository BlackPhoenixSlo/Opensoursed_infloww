/**
 * Function permissions (Infloww's FUN_PERMISSIONS): the destructive, money and export actions a Permission role
 * can deny on a page it grants, stored as `<page href>#<action>` keys in the role's own `permissions` map. A key
 * not stored falls back to its page's grant, so a role saved before these existed keeps every action. The Relay's
 * `permissions.ACTION_KEYS` derives this list from the routes each action calls (one key for every page serving
 * them); service/tests/test_role_enforcement.py pins this copy to it. The Relay cannot tell which page sent a
 * request, so an action is denied everywhere once any of its keys is stored false; the editor sets them alike.
 */

export const PAGE_ACTIONS = {
  "/of-manager/home#delete-post": "Delete posts",
  "/of-manager/new-post#delete-post": "Delete posts",
  "/of-manager/new-post#delete-link": "Delete links and promotions",
  "/of-manager/messages#unsend": "Unsend messages",
  "/of-manager/messages#delete-chat": "Delete chats",
  "/of-manager/messages#mass-message": "Send or unsend mass messages",
  "/of-manager/messages#block-fan": "Block or restrict fans",
  "/of-manager/messages#discount": "Give subscription discounts",
  "/of-manager/queue#mass-message": "Send or unsend mass messages",
  "/of-manager/collections#block-fan": "Block or restrict fans",
  "/of-manager/statements#withdraw": "Request withdrawals",
  "/of-manager/profile#block-fan": "Block or restrict fans",
  "/of-manager/profile#delete-post": "Delete posts",
  "/of-manager/settings#delete-link": "Delete links and promotions",
  "/analytics/creator-reports#export": "Export CSV",
  "/analytics/creator-reports#reassign-sales": "Reassign sales",
  "/analytics/employee-reports#export": "Export CSV",
  "/analytics/employee-reports#reassign-sales": "Reassign sales",
  "/analytics/fan-reports#export": "Export CSV",
  "/analytics/fan-reports#reassign-sales": "Reassign sales",
  "/analytics/message-dashboard#export": "Export CSV",
  "/analytics/message-dashboard#delete-post": "Delete posts",
  "/analytics/sales-records#export": "Export CSV",
  "/analytics/sales-records#reassign-sales": "Reassign sales",
  "/messages-pro#unsend": "Unsend messages",
  "/messages-pro#delete-chat": "Delete chats",
  "/messages-pro#mass-message": "Send or unsend mass messages",
  "/messages-pro#block-fan": "Block or restrict fans",
  "/messages-pro#discount": "Give subscription discounts",
  "/messages-pro#export": "Export CSV",
  "/growth/smart-messages#mass-message": "Send or unsend mass messages",
  "/growth/vault-pro#delete-folder": "Delete vault folders",
  "/growth/scripts#delete-script": "Delete scripts",
  "/growth/profile-promotion#delete-link": "Delete links and promotions",
  "/growth/free-trial-links#delete-link": "Delete links and promotions",
  "/growth/tracking-links#delete-link": "Delete links and promotions",
  "/growth/auto-post#mass-message": "Send or unsend mass messages",
  "/growth/auto-funnel#mass-message": "Send or unsend mass messages",
  "/employees/shifts#edit-shifts": "Create, edit or cancel shifts",
  "/employees/shifts#edit-clock": "Edit or delete clock records",
  "/employees/shifts#reassign-sales": "Reassign sales",
} as const satisfies Record<string, string>;

/** An action's name, the part of its keys after `#`. */
export type ActionName = keyof typeof PAGE_ACTIONS extends `${string}#${infer A}` ? A : never;

/** The Function permissions under page `href`, `[key, label]` in list order. */
export const pageActions = (href: string): [string, string][] =>
  Object.entries(PAGE_ACTIONS).filter(([key]) => key.startsWith(`${href}#`));
