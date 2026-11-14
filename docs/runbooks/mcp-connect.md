# Connect Claude Code (or any MCP client) to Inflowwww

The app serves an MCP server at `https://<your app host>/admin/mcp` (`service/mcp_api.py`; design: `docs/plans/ultra-mode/issues/05-mcp-server.md`). Owners only. The same steps as a web page: https://inflowwww.com/mcp/

1. In the app: **Settings → AI keys → Access tokens** → create a token (shown once, starts `ifw_`). No token yet? Connect without one: `register_account` (new Agency) or `login` (owner username + password, `code` with 2FA) returns a token straight away; `connect_account` returns the sign-up / log-in link that lands on that card instead. Employee logins get no token. Each `register_account` / `login` call makes a new token (earlier ones keep working); revoke old ones on **Settings → AI keys → Access tokens**. OnlyFans logins are never an MCP tool: `connect_account`'s `logins_url` opens the Connect card where you paste them.
2. Add the server (token goes in the config, never into the chat):

   ```sh
   claude mcp add --transport http inflowwww https://<your app host>/admin/mcp \
     --header "Authorization: Bearer ifw_…"
   ```

   Clients that only speak stdio: `npx mcp-remote https://<your app host>/admin/mcp --header "Authorization: Bearer ifw_…"`.
3. In Claude Code: `/mcp` shows `inflowwww` connected with its tools: reads (Creators, stats, vault search, folders, rules, bio pages, reports), folder and bio page edits, and `propose_plan` / `plan_status` for sends.

Notes
- Every result carries `open_url`: the app page that shows the same thing.
- Whole report files: `report_file` returns a `download_url` (15 min) for the same owner (any of their tokens, or their browser session). Save it with a token:
  `curl -H "Authorization: Bearer ifw_…" -o ~/Desktop/report.csv "<download_url>"`.
- Sends never go out on their own: `propose_plan` returns a link with the exact text and audience; the mass message or post goes out only after the owner presses OK on that page in the browser. `plan_status` tells the client what happened. Send tools are never listed.
- What a token can do: call this server's tools (reads, OnlyFans folder and bio page edits, proposing a plan) and download its report files. Every other app route refuses it (403, `service/token_auth.py`): no direct sends, no sign-in, keys, logins or sharing. Revoking the token on the Access tokens card (or "Log out other sessions") cuts the client off on its next call.
- The server refuses browser requests (any `Origin` header, or a cookie instead of a token).
