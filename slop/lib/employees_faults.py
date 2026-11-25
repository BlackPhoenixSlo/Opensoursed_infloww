from __future__ import annotations

EMP_MODALS_ONE = ("employees: each of Add, Edit, Set role, Reset password and Access limits opens as exactly one "
                  "dialog with its title, and closing it leaves none")
EMP_MODAL_REPLACE = "employees: opening Edit while Set role is open replaces it (one dialog, Edit employee)"
EMP_ADD_LOGIN = ("employees: Add (Create login) POSTs /admin/employees/login with username + password + setup; "
                 "the login row is listed with its name, group, Creators and role")
EMP_ADD_LINK = ("employees: Add (Existing login) POSTs /admin/chatters/link with the username, no password; "
                "the other Agency's login is listed here with its name and group")
EMP_ADD_INVITE = ("employees: Add (Invite link) POSTs /admin/chatters/invite with the setup only and shows the link; "
                  "its token is a pending invite with that name and group")
EMP_EDIT = ("employees: Edit saves name, role and group with one PUT /admin/employees/{id}/setup; "
            "GET /admin/employees and the roles blob show them")
EMP_ACCESS_SAVED = "employees: Access limits Save access shows 'Saved.' and it stays after the save's refetch"
EMP_ACCESS_STORED = ("employees: Access limits' save stores the limited Creator and the folder grant "
                     "(GET /admin/chatters/{id}/access)")
EMP_ACCESS_REFETCH = ("employees: Access limits edits made while a save is in flight survive the save's access "
                      "refetch (the draft is seeded once)")
EMP_ACCESS_RESAVED = "employees: the next Save access stores those edits too (GET /admin/chatters/{id}/access)"
EMP_ACCESS_SAVED_STALE = ("employees: Access limits shows no 'Saved.' after a save when an edit was made while it "
                          "was in flight (that edit is not stored yet)")
EMP_ACCESS_PARTIAL = ("employees: Access limits save whose account-access PUT lands and folder-access PUT fails says "
                      "'Accounts saved; folders failed — <error>', no 'Saved.', refetches the access and the employee "
                      "list, and the API holds the new Creators with the old folders")
EMP_ADD_PHONE = ("employees: Add on a 390x844 phone: the 'How they sign in' control's box stays inside the dialog (it "
                 "may scroll sideways itself), the page has no sideways scroll, each option scrolls into the control's "
                 "visible box, and tapping Existing login switches the form (no Password, the existing-username box)")
EMP_NO_5XX = "employees: no 5xx on any request the browser made"


def register(Fault) -> dict:
    return {
        "employee-access-drops-folders": Fault(None, (EMP_ACCESS_STORED, EMP_ACCESS_RESAVED), browser=(
            (r"visible\.has\(aid\) && entry\?\.limit \? entry\.grants : \[\]", "false ? entry.grants : []"),
        )),
        "employee-access-saved-beside-unsaved-edit": Fault(None, (EMP_ACCESS_SAVED_STALE,), browser=(
            (r"state\.savingRev === state\.rev \? action\.at : null", "action.at"),
        )),
        # Pinned by the arrow's body, not its key: a pattern starting at `onSettled:` never matched the served JS (measured).
        "employee-access-partial-not-invalidated": Fault(None, (EMP_ACCESS_PARTIAL,), browser=(
            (r'\(\)\s*=>\s*\{(?=(?:\\n|\s)*void qc\.invalidateQueries\(\{(?:\\n|\s)*queryKey: \[(?:\\n|\s)*'
             r'\\?"admin\\?",(?:\\n|\s)*\\?"chatters\\?",(?:\\n|\s)*chatterId,)',
             "(_d, err)=>{ if (err) return;"),
        )),
    }
