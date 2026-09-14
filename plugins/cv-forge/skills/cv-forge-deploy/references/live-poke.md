# Live Poke

Exact commands for `cv-forge-deploy`'s step 3. Both checks target the app
just deployed (`https://<app-name>.wasmer.app`), not a hardcoded host --
substitute the app name from the skill's argument or its `fps-cv-mcp`
default.

## `GET /healthz` (REQ-13 shape, `INTERFACE_DESIGN.md § 3.2`)

```sh
curl -s https://<app-name>.wasmer.app/healthz | jq .
```

Expect the `200 ok` body:

```json
{ "status": "ok",
  "origin": { "kind": "release", "tag": "2026.09.13", "published_at": "..." },
  "release_tag": "2026.09.13", "loaded_at": "...",
  "refresh_state": "fresh", "consecutive_failures": 0,
  "last_success_at": "...", "cv_forge_version": "1.1.0" }
```

Checks, in order:

1. `.status == "ok"` (a `503` here means the deploy is up but has no
   validated snapshot yet -- report the `reason`/`detail` fields verbatim
   and stop; do not treat it as "deployed").
2. `.cv_forge_version` **equals the version of the tree just deployed**
   (read it from `pyproject.toml`'s `[project].version` in `cv_forge_path`
   before comparing). This is the field that proves *this* deploy landed --
   `release_tag` alone cannot, since a code-only deploy does not change it.
3. `.refresh_state` -- report whatever value is present (`pinned`, `fresh`,
   or `stale`); a `stale` value with a populated `last_error` is not a
   deploy failure (REQ-11 degrades freshness, not availability) but is
   worth surfacing in the closing summary rather than silently passing over.

## `POST /mcp` `tools/list` (no session header)

The MCP server builds a stateless streamable-HTTP app (`create_app(...,
stateless=True)`) -- no `initialize` handshake and no `Mcp-Session-Id`
header are required for a single request:

```sh
curl -s https://<app-name>.wasmer.app/mcp \
  -H "Content-Type: application/json" \
  -H "Accept: application/json, text/event-stream" \
  -d '{"jsonrpc": "2.0", "id": 1, "method": "tools/list"}'
```

The response is streamable-HTTP's SSE-framed body, e.g.:

```
event: message
data: {"jsonrpc":"2.0","id":1,"result":{"tools":[ ... 16 entries ... ]}}
```

Count entries in `.result.tools` (parse the `data:` line's JSON) -- expect
16. Repeat with `"method": "resources/list"` (`id: 2`) and count
`.result.resources` -- expect 17. A non-200 HTTP status, or a JSON-RPC
error object in place of `result`, means the deploy is not actually serving
MCP traffic even if `/healthz` returned `ok` -- report both outcomes, since
they test different layers (health probe vs. actual protocol traffic).

## What counts as "Deployed."

All three must hold: `/healthz` returns `200` with `status: "ok"` and the
expected `cv_forge_version`; `tools/list` returns exactly 16 tools;
`resources/list` returns exactly 17 resources. If any one fails, the skill
reports the specific failing check per the main SKILL.md's Failure
reporting section -- never prints "Deployed." on a partial match.
