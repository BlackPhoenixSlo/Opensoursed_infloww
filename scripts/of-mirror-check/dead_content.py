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
