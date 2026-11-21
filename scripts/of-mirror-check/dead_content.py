"""dead.py's ticket 32 rows (dead.py's MODULES): New message's list page
(messages/send/state-list-dropdown) composer tools, Wired on the Mass draft as in a chat. Data only: MARKED entries in
dead.py's shape (pages, selector, shown matches only, how many). Each tool keeps its Not-yet title (D1: until its
draft-only Live proof, ticket 53), but Scheduled messages, Message price, Add media from vault and Format Text: their
Live proofs passed (p2.list-schedule/price/vault/format, docs/of-manager/captures/messages--list-{schedule,price,vault,
format-text}.json), so they are "proven" PHASE1 rows (dead.py: found, Wired, no Not-yet title).
"""
LIST = "messages/send/state-list-dropdown"
MARKED = [
    (lambda p: p == LIST, "[aria-label='Add media']", False, 1),
    (lambda p: p == LIST, "button[aria-label='Add GIF'], button[aria-label='Record video'], "
                          "button[aria-label='Record voice'], button[aria-label='Format Text']", False, 4),
    (lambda p: p == LIST, "[at-attr='add_vault_media'], [at-attr='scheduled_msg'], [at-attr='price_btn'], "
                          "[at-attr='release_forms_btn']", False, 4),
]
PHASE1 = [(LIST, f"css:{sel}", "proven") for sel in ("button[at-attr='scheduled_msg']", "[at-attr='price_btn']",
                                                     "[at-attr='add_vault_media']", "button[aria-label='Format Text']")]
