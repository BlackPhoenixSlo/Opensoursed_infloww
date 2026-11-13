# Send chain for tool-written text

Type: grilling
Status: open
Blocked by: 04

`mass_send`, `post_create` and automation rules can carry text the model wrote. CLAUDE.md requires model replies to OF to run `finalize_draft → shape_parts → apply_typo_throttle → hold_with_typing`, but the routes forward text raw (`service/server.py:3899-3918`, `:5854-5868`). Where does the chain run for tool calls: inside `toolbox.call` for send tools, as a route flag (`model_written: true`), or in the Caption writer? Which stages fit a mass/post (no typing hold)? Release blocker for Ultra and MCP sends.
