# Connect Claude Code (or any MCP client) to Inflowwww

The app serves a read-only MCP server at `https://<your app host>/admin/mcp` (`service/mcp_api.py`; design: `docs/plans/ultra-mode/issues/05-mcp-server.md`). Owners only.

1. In the app: **Settings → AI keys → Access tokens** → create a token (shown once, starts `ifw_`). No account yet? Connect without a token and call the `connect_account` tool: it returns the sign-up / log-in link that lands on that card.
2. Add the server (token goes in the config, never into the chat):

   ```sh
   claude mcp add --transport http inflowwww https://<your app host>/admin/mcp \
     --header "Authorization: Bearer ifw_…"
   ```

   Clients that only speak stdio: `npx mcp-remote https://<your app host>/admin/mcp --header "Authorization: Bearer ifw_…"`.
3. In Claude Code: `/mcp` shows `inflowwww` connected with its tools (Creators, stats, vault search, folders, rules, bio pages, reports).

Notes
- Every result carries `open_url`: the app page that shows the same thing.
- Whole report files: `report_file` returns a `download_url` (15 min). Save it with the same token:
  `curl -H "Authorization: Bearer ifw_…" -o ~/Desktop/report.csv "<download_url>"`.
- What a token can do: call this server's tools (read Creators, stats, vault, folders, rules, bio pages, reports) and download its report files. Every other app route refuses it (403, `service/token_auth.py`): no sends, no writes, no sign-in, keys, logins or sharing. Revoking the token on the Access tokens card (or "Log out other sessions") cuts the client off on its next call.
- The server refuses browser requests (any `Origin` header, or a cookie instead of a token).
