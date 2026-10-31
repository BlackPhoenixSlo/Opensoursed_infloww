import { describe, expect, it } from "vitest";
import { collectPost, type CreatePostBody, type PostDraft } from "./ofMirrorPostDraft";

/** The fixed "now" every row is collected at (passed as collectPost's `now`). */
const NOW = new Date("2026-10-13T12:00:00.000Z");
const at = (ms: number) => new Date(NOW.getTime() + ms).toISOString();
const draft = (patch: Partial<PostDraft> = {}): PostDraft => ({ text: "", tagged_users: [], media_files: [], thumbs: [], ...patch });
const body = (patch: Partial<CreatePostBody> = {}): CreatePostBody => ({ text: "Synthetic post", media_files: [], price: 0, ...patch });

const EMPTY_TEXT = "Write something or add media to post";
const TOO_SOON = "Pick a time at least a minute from now";
const FEW_OPTIONS = "Add at least two options";
const NO_ANSWER = "Pick the correct answer";

describe("collectPost table (fixed now)", () => {
  it.each<[string, string, Partial<PostDraft>, CreatePostBody | string]>([
    // text / media
    ["empty text, no media", "", {}, EMPTY_TEXT],
    ["blank text, no media", " \n\t ", {}, EMPTY_TEXT],
    ["empty text with media", "", { media_files: [61] }, { text: "", media_files: [61], price: 0 }],
    ["empty text beats a past schedule", "", { posted_at: at(-60_000) }, EMPTY_TEXT],
    ["text trimmed", "  Synthetic post \n", {}, body()],
    // html (formatting): the markup is sent instead of the text, never for empty text
    ["formatted text sent as markup", "Synthetic post", { html: "<p><b>Synthetic</b> post</p>" }, body({ text: "<p><b>Synthetic</b> post</p>" })],
    ["empty text with markup: no markup", "", { html: "<p></p>", media_files: [61] }, { text: "", media_files: [61], price: 0 }],
    // schedule (TOO_SOON: under a minute ahead)
    ["past schedule", "Synthetic post", { posted_at: at(-60_000) }, TOO_SOON],
    ["schedule now", "Synthetic post", { posted_at: at(0) }, TOO_SOON],
    ["schedule 59 s ahead", "Synthetic post", { posted_at: at(59_000) }, TOO_SOON],
    ["schedule exactly 60 s ahead", "Synthetic post", { posted_at: at(60_000) }, body({ posted_at: at(60_000) })],
    ["future schedule", "Synthetic post", { posted_at: at(86_400_000) }, body({ posted_at: at(86_400_000) })],
    ["save for later drops a past date", "Synthetic post", { save_for_later: true, posted_at: at(-60_000) }, body({ save_for_later: true })],
    ["TOO_SOON beats a bad poll", "Synthetic post", { posted_at: at(0), voting: { type: 1, options: ["Yes"] } }, TOO_SOON],
    // price (no limits here: postPriceLimits / readPrice enforce them)
    ["free: no price", "Synthetic post", {}, body({ price: 0 })],
    ["paid: price kept", "Synthetic post", { price: 5 }, body({ price: 5 })],
    // extras: passed through when set, absent when empty or 0
    ["tagged users sent", "Synthetic post", { tagged_users: [101, 102] }, body({ tagged_users: [101, 102] })],
    ["labels sent", "Synthetic post", { label_ids: [7] }, body({ label_ids: [7] })],
    ["no labels: no label_ids", "Synthetic post", { label_ids: [] }, body()],
    ["expire days sent", "Synthetic post", { expire_days: 3 }, body({ expire_days: 3 })],
    ["fundraising target sent", "Synthetic post", { fund_raising_target: 25 }, body({ fund_raising_target: 25 })],
    ["zero extras: none sent", "Synthetic post", { expire_days: 0, fund_raising_target: 0 }, body()],
    // poll / quiz options
    ["poll, one option", "Synthetic post", { voting: { type: 1, options: ["Yes"] } }, FEW_OPTIONS],
    ["poll, blanks don't count", "Synthetic post", { voting: { type: 1, options: ["Yes", " ", ""] } }, FEW_OPTIONS],
    ["poll, two options", "Synthetic post", { voting: { type: 1, options: ["Yes", "No"] } }, body({ voting_type: 1, voting_options: ["Yes", "No"], voting_due: 7 })],
    ["poll, options trimmed", "Synthetic post", { voting: { type: 1, options: [" Yes ", "No\n"] } }, body({ voting_type: 1, voting_options: ["Yes", "No"], voting_due: 7 })],
    ["poll, no limit sends no due", "Synthetic post", { voting: { type: 1, options: ["Yes", "No"] }, voting_due: 0 }, body({ voting_type: 1, voting_options: ["Yes", "No"] })],
    ["quiz, no correct answer", "Synthetic post", { voting: { type: 2, options: ["A", "B"] } }, NO_ANSWER],
    ["quiz, correct on a blank row", "Synthetic post", { voting: { type: 2, options: ["A", "", "B"], correct: 1 } }, NO_ANSWER],
    ["quiz, correct index among kept", "Synthetic post", { voting: { type: 2, options: ["A", "", "C"], correct: 2 } }, body({ voting_type: 2, voting_options: ["A", "C"], voting_due: 7, voting_correct_index: 1 })],
    // edit_id (the Queue's Edit post): never in the body; bindPost reads it off the draft
    ["edit_id not sent", "Synthetic post", { edit_id: "q-42", posted_at: at(3_600_000) }, body({ posted_at: at(3_600_000) })],
  ])("%s", (_name, text, patch, want) => {
    expect(collectPost(text, draft(patch), NOW)).toStrictEqual(want);
  });
});
