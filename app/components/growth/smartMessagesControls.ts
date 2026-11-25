export type CapturedControl = {
  id: `growth-smart-messages#${number}`;
  label: string | null;
  sources: readonly string[];
  inventory: string | null;
  desc?: string;
};

const J = "index.9f50f370.js";

export const SM = {
  title: { id: "growth-smart-messages#3", label: "Smart Messages List", sources: [`${J} @10716029`], inventory: "[CL]" },
  creator: { id: "growth-smart-messages#4", label: null, sources: [`${J} @16322254`], inventory: "[CL]" },
  tabAutomated: { id: "growth-smart-messages#5", label: "Automated Messages", sources: [`${J} @14654444`, `${J} @16247564`], inventory: "C[H262055]" },
  tabMass: { id: "growth-smart-messages#6", label: "Mass Messages", sources: [`${J} @14654487`, `${J} @16247766`], inventory: "[CL]" },
  learn: { id: "growth-smart-messages#11", label: "Learn", sources: [`${J} @16246052`], inventory: "[CL]" },
  newMessage: { id: "growth-smart-messages#15", label: "New Message", sources: [`${J} @16246231`], inventory: "[CL]" },
  childPriority: { id: "growth-smart-messages#56", label: "Priority mass messages", sources: [`${J} @15733662`], inventory: "C[H262055]" },
  childOf: { id: "growth-smart-messages#57", label: "OF mass messages", sources: [`${J} @15733719`], inventory: "C[H262034]" },
  search: { id: "growth-smart-messages#66", label: "Search for message", sources: [`${J} @15751281`, `${J} @15751531`], inventory: null },
  sendingDate: { id: "growth-smart-messages#73", label: "Sending Date:", sources: [`${J} @15753149`], inventory: null },
  reset: { id: "growth-smart-messages#76", label: "Reset", sources: [`${J} @15753442`], inventory: null },
  searchButton: { id: "growth-smart-messages#77", label: "Search", sources: [`${J} @15753553`], inventory: null },
  exportButton: { id: "growth-smart-messages#79", label: "Export", sources: [`${J} @15753704`], inventory: "C[NEWS]" },
  massSent: { id: "growth-smart-messages#70", label: "Sent", sources: [`${J} @15734045`], inventory: null },
  massUnsent: { id: "growth-smart-messages#70", label: "Unsent", sources: [`${J} @15734073`], inventory: null },
  massEmpty: { id: "growth-smart-messages#97", label: "There are no more messages for the selected time period", sources: [`${J} @16171832`], inventory: null },
  popUpTitle: { id: "growth-smart-messages#103", label: "Create message", sources: [`${J} @14716730`, `${J} @14716712`], inventory: null },
  popUpScratch: { id: "growth-smart-messages#104", label: "Start from scratch", sources: [`${J} @14715428`], inventory: null },
  popUpTemplates: { id: "growth-smart-messages#105", label: "or use one of the templates below", sources: [`${J} @14715455`], inventory: null },
  popUpMass: { id: "growth-smart-messages#106", label: "Mass messages", sources: [`${J} @14717209`], inventory: null },
  cardPriority: { id: "growth-smart-messages#107", label: "Priority mass message", desc: "Sent to priority inbox", sources: [`${J} @14707968`, `${J} @14707997`], inventory: "C[H262055]" },
  cardOf: { id: "growth-smart-messages#108", label: "OF mass message", desc: "Sent to general inbox", sources: [`${J} @14708331`, `${J} @14708354`], inventory: "C[H262034]" },
  popUpAutomated: { id: "growth-smart-messages#109", label: "Automated messages", sources: [`${J} @14717265`], inventory: null },
  popUpNext: { id: "growth-smart-messages#110", label: "Next", sources: [`${J} @14716869`], inventory: null },
  popUpCancel: { id: "growth-smart-messages#111", label: "Cancel", sources: [`${J} @14716958`], inventory: null },
  autoSearch: { id: "growth-smart-messages#24", label: "Search message", sources: [`${J} @16287546`, `${J} @16287761`], inventory: null },
  autoStatus: { id: "growth-smart-messages#27", label: "Status:", sources: [`${J} @16287849`, `${J} @16288219`], inventory: null },
  autoTrigger: { id: "growth-smart-messages#29", label: "Trigger:", sources: [`${J} @16288338`, `${J} @16288676`], inventory: null },
  autoSentTo: { id: "growth-smart-messages#30", label: "Sent to:", sources: [`${J} @16288782`, `${J} @16288830`], inventory: null },
  autoStartDate: { id: "growth-smart-messages#31", label: "Start date:", sources: [`${J} @16289060`], inventory: null },
  autoDateCreated: { id: "growth-smart-messages#32", label: "Date created:", sources: [`${J} @16289336`, `${J} @16289312`], inventory: null },
  autoCreatedBy: { id: "growth-smart-messages#33", label: "Created by:", sources: [`${J} @16289614`, `${J} @16289590`, `${J} @16289665`], inventory: null },
  autoReset: { id: "growth-smart-messages#36", label: "Reset", sources: [`${J} @16289890`], inventory: null },
  autoSearchButton: { id: "growth-smart-messages#37", label: "Search", sources: [`${J} @16290000`], inventory: null },
  statusScheduled: { id: "growth-smart-messages#28", label: "Scheduled", sources: [`${J} @16272625`], inventory: null },
  statusActive: { id: "growth-smart-messages#28", label: "Active", sources: [`${J} @16272655`], inventory: null },
  statusCompleted: { id: "growth-smart-messages#28", label: "Completed", sources: [`${J} @16272682`], inventory: null },
  statusCanceled: { id: "growth-smart-messages#28", label: "Canceled", sources: [`${J} @16272712`], inventory: null },
  autoEmpty: { id: "growth-smart-messages#53", label: "No Data", sources: [`${J} @16304021`], inventory: null },
} as const satisfies Record<string, CapturedControl>;

type CapturedEntry = { id: CapturedControl["id"]; label: string; sources: readonly string[] };

export const SM_AUTOMATED_COLUMNS = [
  { id: "growth-smart-messages#39", label: "Messages", width: 390, sources: [`${J} @16296530`] },
  { id: "growth-smart-messages#40", label: "Status", width: 230, sources: [`${J} @16297887`] },
  { id: "growth-smart-messages#41", label: "Trigger", width: 160, sources: [`${J} @16298195`] },
  { id: "growth-smart-messages#42", label: "Sent", width: 160, sources: [`${J} @16298301`] },
  { id: "growth-smart-messages#43", label: "Purchased", width: 140, sources: [`${J} @16298418`] },
  { id: "growth-smart-messages#44", label: "Earnings", width: 140, sources: [`${J} @16298544`] },
  { id: "growth-smart-messages#45", label: "Attachment(s)", width: 240, sources: [`${J} @16299052`] },
  { id: "growth-smart-messages#46", label: "Price", width: 180, sources: [`${J} @16300051`] },
  { id: "growth-smart-messages#47", label: "Sent to", width: 140, sources: [`${J} @16300568`] },
  { id: "growth-smart-messages#48", label: "Created by", width: 140, sources: [`${J} @16300970`] },
  { id: "growth-smart-messages#49", label: "Start date", width: 140, sources: [`${J} @16301218`] },
  { id: "growth-smart-messages#50", label: "End date", width: 140, sources: [`${J} @16301445`] },
  { id: "growth-smart-messages#51", label: "Date created", width: 140, sources: [`${J} @16301606`] },
  { id: "growth-smart-messages#52", label: "Actions", width: 100, sources: [`${J} @16302024`] },
] as const satisfies readonly (CapturedEntry & { width: number })[];

type TriggerCard = { label: string; desc: string; tag?: string; sources: readonly string[] };

export const SM_TRIGGERS = [
  { id: "growth-smart-messages#116", label: "Nudge", sources: [`${J} @16272751`],
    card: { label: "Nudge", desc: "Messages fans when they come online", tag: "Popular", sources: [`${J} @14708639`, `${J} @14708652`, `${J} @14708698`] } },
  { id: "growth-smart-messages#117", label: "Delayed welcome", sources: [`${J} @16272761`],
    card: { label: "Subscriber welcome", desc: "Greet fans when they subscribe", sources: [`${J} @14708892`, `${J} @14708918`] } },
  { id: "growth-smart-messages#118", label: "Purchased", sources: [`${J} @16272781`],
    card: { label: "Purchases", desc: "Follow up with fans who purchased a PPV", sources: [`${J} @14709120`, `${J} @14709137`] } },
  { id: "growth-smart-messages#119", label: "Nearing expiry", sources: [`${J} @16272813`],
    card: { label: "Expiring soon", desc: " Message fans when their subscription is about to expire", sources: [`${J} @14709348`, `${J} @14709369`] } },
  { id: "growth-smart-messages#120", label: "Expired", sources: [`${J} @16272832`],
    card: { label: "Expired", desc: "Messages fans whose subscription has expired", sources: [`${J} @14709603`, `${J} @14709618`] } },
  { id: "growth-smart-messages#121", label: "Resubscribe", sources: [`${J} @16272844`],
    card: { label: "Resubscribe", desc: "Greet fans when they resubscribe", sources: [`${J} @14709845`, `${J} @14709864`] } },
  { id: "growth-smart-messages#122", label: "Birthday", sources: [`${J} @16272860`],
    card: { label: "Birthday greetings", desc: "Wish fans happy birthday", sources: [`${J} @14710064`, `${J} @14710090`] } },
  { id: "growth-smart-messages#123", label: "Not Purchased", sources: [`${J} @16272795`], card: null },
] as const satisfies readonly (CapturedEntry & { card: TriggerCard | null })[];

export const SM_MASS_COLUMNS = [
  { id: "growth-smart-messages#80", label: "Message", width: 250, sources: [`${J} @16207678`] },
  { id: "growth-smart-messages#81", label: "Sent date & time", width: 300, sources: [`${J} @16208370`] },
  { id: "growth-smart-messages#82", label: "Sender", width: 120, sources: [`${J} @16208801`] },
  { id: "growth-smart-messages#83", label: "Attachment", width: 210, sources: [`${J} @16209103`] },
  { id: "growth-smart-messages#84", label: "Status", width: 230, sources: [`${J} @16210077`] },
  { id: "growth-smart-messages#85", label: "Price", width: 110, sources: [`${J} @16210623`] },
  { id: "growth-smart-messages#86", label: "Sent", width: 110, sources: [`${J} @16211153`] },
  { id: "growth-smart-messages#87", label: "Viewed", width: 110, sources: [`${J} @16211442`] },
  { id: "growth-smart-messages#88", label: "Purchased", width: 110, sources: [`${J} @16211541`] },
  { id: "growth-smart-messages#89", label: "Earnings", width: 110, sources: [`${J} @16212228`] },
  { id: "growth-smart-messages#90", label: "Withdrawn by", width: 150, sources: [`${J} @16212514`] },
  { id: "growth-smart-messages#93", label: "Withdrawn date & time", width: 220, sources: [`${J} @16204496`] },
  { id: "growth-smart-messages#94", label: "Actions", width: 80, sources: [`${J} @16204820`] },
] as const satisfies readonly (CapturedEntry & { width: number })[];

export const SM_MASS_ACTIONS = {
  trigger: { label: null, sources: [`${J} @15685010`, `${J} @15685391`, `${J} @15685560`] },
  unsend: { label: "Unsent", sources: [`${J} @16207260`, `${J} @16207438`] },
  unsendTip: { label: "Unsend OF mass message", sources: [`${J} @16206965`] },
  duplicate: { label: "Duplicate", sources: [`${J} @16206736`] },
} as const satisfies Record<string, { label: string | null; sources: readonly string[] }>;

export const SM_EDITOR = {
  scheduling: { label: "Frequency & scheduling", sources: [`${J} @14939513`] },
  frequency: { label: "Frequency", sources: [`${J} @14940382`] },
  once: { label: "Send only once when the fan matches the trigger", sources: [`${J} @14940448`] },
  every: { label: "Send every time the fan matches the trigger", sources: [`${J} @14940514`] },
  effective: { label: "Effective", sources: [`${J} @14941093`] },
  immediately: { label: "Immediately", sources: [`${J} @14941173`] },
  scheduledDate: { label: "Scheduled date", sources: [`${J} @14941250`, `${J} @14942010`] },
  expiry: { label: "Expiry", sources: [`${J} @14941870`] },
  never: { label: "Never", sources: [`${J} @14941939`] },
  sendToFans: { label: "Send message to fans", sources: [`${J} @14901318`] },
  delayNone: { label: "immediately", sources: [`${J} @14901373`] },
  delayOn: { label: "after delay", sources: [`${J} @14901407`] },
  delayRandom: { label: "in random minute intervals", sources: [`${J} @14901614`] },
  delayTilde: { label: "～", sources: [`${J} @14901671`] },
  delayMinutes: { label: "minutes", sources: [`${J} @14901708`] },
  delayTail: { label: "automatically", sources: [`${J} @14901743`] },
  media: { label: "Media", sources: [`${J} @15275429`] },
  price: { label: "Message price", sources: [`${J} @15307295`] },
  priceMin: { label: "Minimum $3 USD", sources: [`${J} @15304458`] },
  autoUnsend: { label: "Auto-unsend", sources: [`${J} @14981346`] },
  unsend: { label: "Unsend messages", sources: [`${J} @14981830`] },
  unsendLead: { label: "Retract free messages and locked PPV content", sources: [`${J} @14981901`] },
  unsendHours: { label: "hour(s), and", sources: [`${J} @14982105`] },
  unsendMinutes: { label: "minute(s) after it has been sent to fans", sources: [`${J} @14982295`] },
} as const satisfies Record<string, { label: string; sources: readonly string[] }>;
