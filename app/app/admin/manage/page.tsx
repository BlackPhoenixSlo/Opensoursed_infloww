"use client";

/**
 * /admin/manage — founder-only user management UI.
 *
 * Lives at /admin/manage (NOT /admin/users) on purpose: Next file-system
 * routes win over rewrites, so a page at /admin/users would shadow the
 * relay's /admin/users endpoint and the page's own fetch would resolve
 * to its own HTML. /admin/manage sidesteps the collision.
 *
 * Lets the founder:
 *   • View as another user (1h read-only impersonation overlay).
 *   • Grant / revoke individual OF accounts (no SQL-poking required).
 *   • Set an agency's AI keys.
 *   • Hard-delete a user with a two-step confirm (type "delete" + admin
 *     password).
 *
 * All four flows require the relay's ADMIN_PASSWORD env var value.
 *
 * Master only: both reads are `require_master` on the relay. Anyone else who
 * opens it by URL gets one "master account required" line and no request
 * (as ManagedAgencyKeysCard draws nothing for them).
 */

import { useCallback, useEffect, useReducer, useRef, useState } from "react";
import { useRouter } from "next/navigation";

import { relay } from "@/lib/relay";
import { AgencyKeysForm } from "@/components/setup/AgencyKeysForm";
import { AgencyKeyBadges } from "@/components/setup/AgencyKeyBadges";
import { useUser } from "@/contexts/UserContext";
import { errText } from "@/lib/errText";
import { TableSkeleton } from "@/components/ui/Skeleton";

import {
  canDelete,
  filterNote,
  initialManageState,
  manageReducer,
  visibleRows,
  type AdminUserRow,
  type AgencyKeyStatus,
  type Pane,
} from "./manageReducer";

interface GrantedAccount {
  account_id: string;
  nickname: string | null;
  color: string | null;
}

interface GrantOverview {
  granted: GrantedAccount[];
  available: GrantedAccount[];
}

const fmtDate = (iso: string) => new Date(iso).toLocaleString();

export default function AdminUsersPage() {
  const { user: me, loading } = useUser();
  // Nothing until the session is known (the master never sees the line flash); then anyone but the master (an
  // owner, or a chatter: no `me`) gets one line and no request, as both reads would 403.
  if (loading) return null;
  if (me?.is_admin !== true) {
    return (
      <main className="max-w-3xl mx-auto p-6 space-y-6">
        <h1 className="text-2xl font-semibold">Users</h1>
        <div className="text-sm text-fg-dim">master account required</div>
      </main>
    );
  }
  return <ManageUsers meId={me.user_id} />;
}

function ManageUsers({ meId }: { meId: string }) {
  const [state, dispatch] = useReducer(manageReducer, initialManageState);
  const { rows, keyStatus, liveOnly, error, open, refreshing } = state;
  const seqRef = useRef(0);

  const refresh = useCallback(async () => {
    const seq = ++seqRef.current;
    dispatch({ type: "refreshStart", seq });
    // Two calls, and they must fail INDEPENDENTLY. Both are master-only (a
    // list of every tenant; the roster adds their credential state), but they
    // are separate endpoints. Under Promise.all a roster failure
    // rejected the pair and left `rows` null — the page then rendered
    // "Loading…" forever and grant, revoke, delete and impersonate went with
    // it, because a badge could not be drawn. (What each outcome does:
    // manageReducer `refreshSettled`.)
    const [users, roster] = await Promise.allSettled([
      relay.get<AdminUserRow[]>("/admin/users"),
      relay.get<{ agencies: AgencyKeyStatus[] }>("/admin/users/llm-key-status"),
    ]);
    dispatch({ type: "refreshSettled", seq, users, roster });
  }, []);

  useEffect(() => { void refresh(); }, [refresh]);

  const shown = visibleRows(state);

  const togglePane = (userId: string, pane: Pane) => dispatch({ type: "togglePane", userId, pane });

  return (
    <main className="max-w-3xl mx-auto p-6 space-y-6">
      <header className="flex items-center justify-between">
        <h1 className="text-2xl font-semibold">Users</h1>
        <button
          type="button"
          onClick={() => void refresh()}
          disabled={refreshing}
          className="text-sm px-3 py-1.5 rounded-lg border border-fg/10 hover:bg-fg/5 disabled:opacity-50 inline-flex items-center gap-1.5"
        >
          <span className={refreshing ? "inline-block animate-spin" : "inline-block"}>↻</span>
          <span>{refreshing ? "Refreshing…" : "Refresh"}</span>
        </button>
      </header>

      {error && (
        <div className="text-sm text-err" role="alert">{error}</div>
      )}

      {rows === null ? (
        // Loading, or the first load failed: the alert above says why and
        // Refresh retries. Never "No users registered yet." — that is a
        // user list that LOADED empty.
        refreshing ? <TableSkeleton rows={5} /> : null
      ) : rows.length === 0 ? (
        <div className="text-sm text-fg-dim">No users registered yet.</div>
      ) : (
        <>
        {/* A dead session sends nothing, so a key pasted under its owner buys
            nothing until the session is re-captured — worth filtering FOR, but
            off by default here: see the note on `initialManageState`. */}
        <label className="flex items-center gap-2 text-xs text-fg-dim">
          <input
            type="checkbox"
            checked={liveOnly}
            onChange={(e) => dispatch({ type: "liveOnly", on: e.target.checked })}
          />
          Only agencies with a live model session
          <span className="text-fg-dim/70">{filterNote(state)}</span>
        </label>
        <ul className="divide-y divide-fg/10 border border-fg/10 rounded-xl">
          {shown.map((u) => {
            const pane = open?.userId === u.id ? open.pane : null;
            const isSelf = meId === u.id;
            const status = keyStatus?.[u.id];
            return (
              <li key={u.id} className="p-4 space-y-3">
                <div className="flex flex-wrap items-baseline gap-x-4 gap-y-1">
                  <div className="font-medium">@{u.username}</div>
                  <div className="text-xs text-fg-dim">
                    {u.account_count} account{u.account_count === 1 ? "" : "s"}
                  </div>
                  {status && (
                    <div className="flex items-center gap-3">
                      <AgencyKeyBadges agency={status} />
                    </div>
                  )}
                  <div className="text-xs text-fg-dim">
                    joined {fmtDate(u.created_at)}
                  </div>
                  <div className="text-xs text-fg-dim">
                    last seen {fmtDate(u.last_seen_at)}
                  </div>
                  <div className="ml-auto flex items-center gap-3">
                    <button
                      type="button"
                      className="text-xs text-warn hover:text-warn"
                      onClick={() => togglePane(u.id, "impersonate")}
                      disabled={isSelf}
                      title={isSelf ? "You can't impersonate yourself" : ""}
                    >
                      {pane === "impersonate" ? "Cancel" : "View as"}
                    </button>
                    <button
                      type="button"
                      className="text-xs text-fg-dim hover:text-fg"
                      onClick={() => togglePane(u.id, "grant")}
                    >
                      {pane === "grant" ? "Cancel" : "Grant access"}
                    </button>
                    <button
                      type="button"
                      className="text-xs text-fg-dim hover:text-fg"
                      onClick={() => togglePane(u.id, "keys")}
                    >
                      {pane === "keys" ? "Cancel" : "AI keys"}
                    </button>
                    <button
                      type="button"
                      className="text-xs text-err hover:text-err"
                      onClick={() => togglePane(u.id, "delete")}
                      disabled={isSelf}
                      title={isSelf ? "You can't delete yourself" : ""}
                    >
                      {pane === "delete" ? "Cancel" : "Delete user"}
                    </button>
                  </div>
                </div>
                {pane === "impersonate" && (
                  <ImpersonateForm
                    user={u}
                    onStarted={() => dispatch({ type: "closePane" })}
                  />
                )}
                {pane === "grant" && (
                  <GrantForm user={u} onChanged={() => void refresh()} />
                )}
                {pane === "keys" && (
                  <AgencyKeysForm user={u} onSaved={() => void refresh()} />
                )}
                {pane === "delete" && (
                  <DeleteForm user={u} onDeleted={() => { dispatch({ type: "closePane" }); void refresh(); }} />
                )}
              </li>
            );
          })}
        </ul>
        </>
      )}
    </main>
  );
}

function GrantForm({ user, onChanged }: { user: AdminUserRow; onChanged: () => void }) {
  const [overview, setOverview] = useState<GrantOverview | null>(null);
  const [adminPassword, setAdminPassword] = useState("");
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setError(null);
    try {
      const data = await relay.get<GrantOverview>(
        `/admin/users/${encodeURIComponent(user.id)}/accounts`,
      );
      setOverview(data);
    } catch (err) {
      setError(errText(err));
    }
  }, [user.id]);

  useEffect(() => { void load(); }, [load]);

  async function act(busyKey: string, call: () => Promise<unknown>) {
    if (!adminPassword) {
      setError("admin password required");
      return;
    }
    setError(null);
    setBusy(busyKey);
    try {
      await call();
      await load();
      onChanged();
    } catch (err) {
      setError(errText(err));
    } finally {
      setBusy(null);
    }
  }

  const grant = (accountId: string) => act(`grant:${accountId}`, () => relay.post(
    `/admin/users/${encodeURIComponent(user.id)}/accounts`,
    { account_id: accountId, admin_password: adminPassword },
  ));

  const revoke = (accountId: string) => act(`revoke:${accountId}`, () => relay.delete(
    `/admin/users/${encodeURIComponent(user.id)}/accounts/${encodeURIComponent(accountId)}`,
    undefined,
    { admin_password: adminPassword },
  ));

  return (
    <div className="grid gap-3 p-3 rounded-lg bg-fg/[0.02] border border-fg/10">
      <p className="text-sm text-fg-dim">
        Link an OF account to <strong>@{user.username}</strong>. They&apos;ll see it in
        their model switcher on next page load. Revoking just drops the link
        row — the underlying session bytes stay where they are.
      </p>
      <AdminPasswordField value={adminPassword} onChange={setAdminPassword} />
      {error && <div className="text-sm text-err" role="alert">{error}</div>}
      {overview === null ? (
        <TableSkeleton rows={4} />
      ) : (
        <div className="grid gap-3">
          <section>
            <h3 className="text-xs uppercase tracking-wide text-fg-dim mb-1">
              Currently granted ({overview.granted.length})
            </h3>
            {overview.granted.length === 0 ? (
              <div className="text-sm text-fg-dim italic">none</div>
            ) : (
              <ul className="grid gap-1">
                {overview.granted.map((a) => (
                  <li key={a.account_id} className="flex items-center gap-2 text-sm">
                    <AccountDot color={a.color} />
                    <span className="truncate flex-1">{a.nickname || a.account_id}</span>
                    <span className="text-[10px] text-fg-dim font-mono">{a.account_id}</span>
                    <button
                      type="button"
                      className="text-xs text-err hover:text-err disabled:opacity-40"
                      onClick={() => void revoke(a.account_id)}
                      disabled={busy !== null || !adminPassword}
                    >
                      {busy === `revoke:${a.account_id}` ? "…" : "Revoke"}
                    </button>
                  </li>
                ))}
              </ul>
            )}
          </section>
          <section>
            <h3 className="text-xs uppercase tracking-wide text-fg-dim mb-1">
              Available to grant ({overview.available.length})
            </h3>
            {overview.available.length === 0 ? (
              <div className="text-sm text-fg-dim italic">no other accounts on this relay</div>
            ) : (
              <ul className="grid gap-1">
                {overview.available.map((a) => (
                  <li key={a.account_id} className="flex items-center gap-2 text-sm">
                    <AccountDot color={a.color} />
                    <span className="truncate flex-1">{a.nickname || a.account_id}</span>
                    <span className="text-[10px] text-fg-dim font-mono">{a.account_id}</span>
                    <button
                      type="button"
                      className="text-xs text-ok hover:text-ok disabled:opacity-40"
                      onClick={() => void grant(a.account_id)}
                      disabled={busy !== null || !adminPassword}
                    >
                      {busy === `grant:${a.account_id}` ? "…" : "Grant"}
                    </button>
                  </li>
                ))}
              </ul>
            )}
          </section>
        </div>
      )}
    </div>
  );
}

function AdminPasswordField({ value, onChange }: { value: string; onChange: (v: string) => void }) {
  return (
    <label className="grid gap-1 text-sm">
      <span className="text-fg-dim">Admin password</span>
      <input
        type="password"
        value={value}
        onChange={(e) => onChange(e.target.value)}
        autoComplete="off"
        className="px-3 py-2 rounded-lg bg-bg border border-fg/10 focus:outline-none focus:border-fg/30"
      />
    </label>
  );
}

function AccountDot({ color }: { color: string | null }) {
  return (
    <span
      className="w-2 h-2 rounded-full shrink-0"
      style={{ background: color || "#666" }}
    />
  );
}

function ImpersonateForm({ user, onStarted }: { user: AdminUserRow; onStarted: () => void }) {
  const { startImpersonating } = useUser();
  const router = useRouter();
  const [adminPassword, setAdminPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!adminPassword || busy) return;
    setError(null);
    setBusy(true);
    try {
      await startImpersonating(user.id, adminPassword);
      onStarted();
      // Land on the home page so the founder sees the impersonated user's
      // dashboard from a clean route — staying on /admin/users would just
      // re-render the same list with the banner above it.
      router.push("/");
    } catch (err) {
      setError(errText(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <form
      onSubmit={onSubmit}
      className="grid gap-3 p-3 rounded-lg bg-warn/5 border border-warn/30"
    >
      <p className="text-sm text-fg-dim">
        Start a 1-hour read-only session as <strong>@{user.username}</strong>.
        The relay will refuse any mutating request (sends, deletes, edits) until
        you exit. A yellow banner stays pinned to the top so you don&apos;t forget
        you&apos;re viewing as someone else.
      </p>
      <AdminPasswordField value={adminPassword} onChange={setAdminPassword} />
      {error && <div className="text-sm text-err" role="alert">{error}</div>}
      <button
        type="submit"
        disabled={!adminPassword || busy}
        className="py-2 rounded-lg bg-warn text-black font-medium disabled:opacity-30"
      >
        {busy ? "Starting…" : "View as @" + user.username}
      </button>
    </form>
  );
}

function DeleteForm({ user, onDeleted }: { user: AdminUserRow; onDeleted: () => void }) {
  const [confirm, setConfirm] = useState("");
  const [adminPassword, setAdminPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const canSubmit = canDelete({ confirm, adminPassword, busy });

  async function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!canSubmit) return;
    setError(null);
    setBusy(true);
    try {
      await relay.delete(
        `/admin/users/${encodeURIComponent(user.id)}`,
        undefined,
        { confirm, admin_password: adminPassword },
      );
      onDeleted();
    } catch (err) {
      setError(errText(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <form onSubmit={onSubmit} className="grid gap-3 p-3 rounded-lg bg-err/5 border border-err/20">
      <p className="text-sm text-fg-dim">
        Removes <strong>@{user.username}</strong> and {user.account_count}{" "}
        account link{user.account_count === 1 ? "" : "s"}. The OF account rows themselves are kept.
        This cannot be undone.
      </p>
      <label className="grid gap-1 text-sm">
        <span className="text-fg-dim">Type the word <code className="px-1 bg-fg/10 rounded">delete</code></span>
        <input
          type="text"
          value={confirm}
          onChange={(e) => setConfirm(e.target.value)}
          autoComplete="off"
          className="px-3 py-2 rounded-lg bg-bg border border-fg/10 focus:outline-none focus:border-fg/30"
        />
      </label>
      <AdminPasswordField value={adminPassword} onChange={setAdminPassword} />
      {error && <div className="text-sm text-err" role="alert">{error}</div>}
      <button
        type="submit"
        disabled={!canSubmit}
        className="py-2 rounded-lg bg-err text-white font-medium disabled:opacity-30"
      >
        {busy ? "Deleting…" : "Permanently delete"}
      </button>
    </form>
  );
}
