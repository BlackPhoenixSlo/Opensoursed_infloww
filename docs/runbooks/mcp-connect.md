# Connect Claude Code (or any MCP client) to Inflowwww

The app serves an MCP server at `https://<your app host>/admin/mcp` (`service/mcp_api.py`; design: `docs/plans/ultra-mode/issues/05-mcp-server.md`). Owners only. The same steps as a web page: https://inflowwww.com/mcp/

1. Add the server, no token and no header:

   ```sh
   claude mcp add --transport http inflowwww https://<your app host>/admin/mcp
   ```

2. In Claude Code: `/mcp`, pick `inflowwww`, choose **Authenticate** (from a terminal: `claude mcp login inflowwww`). The browser opens the app's sign-in page (`service/mcp_oauth.py`).
3. Log in as the Agency owner (2FA code if on) and press **Allow**. Claude Code is connected; `/mcp` lists its tools: reads (Creators, stats, vault search, folders, rules, bio pages, reports), folder and bio page edits, and `propose_plan` / `plan_status` for sends.

Allow mints an ordinary owner access token (the Access tokens card's code path), named `MCP <client name> <UTC time>`, 90 days, no refresh token: when it expires the next call's 401 sends the client back to step 2. Revoke it on **Settings → AI keys → Access tokens**. Employee logins and an owner viewing another Agency get a refusal page, no token. When the client's address is not on this computer (`https://`), the Allow page names that host in a warning. Clients that only speak stdio: `npx mcp-remote https://<your app host>/admin/mcp` (same browser sign-in).

How the client finds the sign-in: a token tool called with no token answers HTTP 401 with `WWW-Authenticate: Bearer resource_metadata="<host>/.well-known/oauth-protected-resource/admin/mcp"`; that names `<host>/.well-known/oauth-authorization-server` (RFC 8414), whose endpoints are `/auth/oauth/register` (RFC 7591, public clients, redirect URIs `http://localhost`, `http://127.0.0.1` or `https://`), `/auth/oauth/authorize` and `/auth/oauth/token` (authorization code + PKCE S256 only, codes single use, 60 s). `initialize` and `tools/list` stay open with no token, so Claude Code shows the server as connected with "Auth: not signed in" and offers Authenticate in `/mcp`.

Or with a token:

1. In the app: **Settings → AI keys → Access tokens** → create a token (shown once, starts `ifw_`).
2. Add the server with it (token goes in the config, never into the chat):

   ```sh
   claude mcp add --transport http inflowwww https://<your app host>/admin/mcp \
     --header "Authorization: Bearer ifw_…"
   ```

   Stdio only: `npx mcp-remote https://<your app host>/admin/mcp --header "Authorization: Bearer ifw_…"`.

No token yet and no browser: `register_account` (new Agency) or `login` (owner username + password, `code` with 2FA) returns a token straight away; `connect_account` returns the sign-up / log-in link that lands on the Access tokens card instead. Employee logins get no token. Each `register_account` / `login` call makes a new token (earlier ones keep working); revoke old ones on **Settings → AI keys → Access tokens**. OnlyFans logins are never an MCP tool: `connect_account`'s `logins_url` opens the Connect card where you paste them.

Notes
- Every result carries `open_url`: the app page that shows the same thing.
- Whole report files: `report_file` returns a `download_url` (15 min) for the same owner (any of their tokens, or their browser session). Save it with a token:
  `curl -H "Authorization: Bearer ifw_…" -o ~/Desktop/report.csv "<download_url>"`.
- Sends never go out on their own: `propose_plan` returns a link with the exact text and audience; the mass message or post goes out only after the owner presses OK on that page in the browser. `plan_status` tells the client what happened. Send tools are never listed.
- What a token can do: call this server's tools (reads, OnlyFans folder and bio page edits, proposing a plan) and download its report files. Every other app route refuses it (403, `service/token_auth.py`): no direct sends, no sign-in, keys, logins or sharing. Revoking the token on the Access tokens card (or "Log out other sessions") cuts the client off on its next call.
- The server refuses browser requests (any `Origin` header, or a cookie instead of a token).
