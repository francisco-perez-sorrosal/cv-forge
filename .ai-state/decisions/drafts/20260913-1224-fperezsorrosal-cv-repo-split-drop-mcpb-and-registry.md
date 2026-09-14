---
id: dec-draft-fb7c5d3f
title: Drop the MCPB bundle subsystem and the MCP registry entry; Claude Desktop uses the remote server as a custom connector
status: proposed
category: architectural
date: 2026-09-13
summary: The entire MCPB build path (`manifest.json`, `start_mcpb.sh`, `.mcpbignore`, `lib/` vendoring, wheel build, two CI workflows, two design docs, the release SHA256 step) is removed, along with the now-misleading `server.json` registry entry. Claude Desktop reaches the deployed HTTP server as a custom connector.
tags: [distribution, mcpb, build-system, simplification, mcp-registry]
made_by: fperezsorrosal
agent_type: systems-architect
branch: cv-repo-split
pipeline_tier: full
affected_files:
  - manifest.json
  - start_mcpb.sh
  - .mcpbignore
  - server.json
  - server.json.template
  - Makefile
  - pyproject.toml
  - scripts/release.sh
  - install.sh
  - .github/workflows/check-mcpb-creation.yml
  - .github/workflows/release-mcpb.yml
affected_reqs: [REQ-17]
---

## Context

The project ships a Claude Desktop Extension bundle. Producing one requires: building a wheel, regenerating `requirements.txt` via `uv export`, `pip install --target lib/` to vendor every dependency, detecting the CPython ABI from `lib/pydantic_core/*.so` and recording it in `lib/.python-version`, zipping via `npx @anthropic-ai/mcpb pack`, a launcher script (`start_mcpb.sh`) that locates a matching host Python at runtime, a `.mcpbignore` exclusion list, a `manifest.json`, two Make targets, five `pixi` tasks, two CI workflows, a SHA256 computation in `scripts/release.sh`, and two design documents. That subsystem is a meaningful fraction of this repository's complexity, and it exists to deliver a *local* copy of a server that is already deployed and reachable over HTTPS.

Current official guidance is explicit: *"MCPB is the secondary distribution path. Remote MCP servers are recommended for directory listing."* The documented fit criteria for MCPB are firewalled access, SSO/browser-session auth, zero-trust corporate boundaries, direct filesystem or hardware access, and privacy-sensitive data that must not leave the machine. This server has none of them — it is a public, unauthenticated, read-only document server whose entire content is already on the public internet. The remote-connector column ("cloud services and public APIs," "centralized updates pushed to all users," "public-facing integrations") describes it exactly.

The subsystem is also currently *broken* in a way nothing catches. `requirements.txt` and `uv.lock` omit `jinja2` entirely while including unused `pymupdf`/`pymupdf4llm`. Any bundle built from them would `ImportError` on every rendering path — `get_cv(format="html"|"latex"|"typst")` and `get_tailored_cv` — and `check-mcpb-creation.yml` tests bundle *creation* and extraction, never tool invocation, so it ships green.

`server.json`, the MCP registry entry, has a related problem: its only `packages` entry points at an `.mcpb` release asset (about to cease existing) with a `fileSha256`, and it carries no `remotes` entry at all despite the server having had a live streamable-HTTP deployment the whole time. Its schema reference (`2025-09-29`) is also two revisions behind the current `2025-12-11`.

## Decision

Delete the MCPB subsystem entirely: `manifest.json`, `start_mcpb.sh`, `.mcpbignore`, `lib/`, `requirements.txt`, `uv.lock`, the `python-bundle`/`update-mcpb-deps`/`mcp-bundle`/`pack`/`clean-bundles` pixi tasks, the `build-mcpb`/`install-claude-desktop` Make targets, `check-mcpb-creation.yml`, `release-mcpb.yml`, `MCPB_DEV_PRACTICES_IMPROVEMENTS.md`, `MCPB_TEST_CONSIDERATIONS.md`, and `install.sh`'s `desktop local` path. `scripts/release.sh` is reworked rather than deleted — its version-bump and tagging responsibilities survive; its bundle-build and SHA256 steps do not.

Delete `server.json` and `server.json.template` too, rather than reworking them. Keeping the file would mean keeping an entry that advertises a bundle which will not exist and a render.com URL being decommissioned; a stale registry listing is worse than no listing, because it sends users to a dead artifact. Re-listing later costs one file plus one `mcp-publisher publish` invocation, and is better scoped as its own task once the Wasmer URL has settled.

Claude Desktop users add the server through Settings → Connectors → Add custom connector, pointing at the deployed streamable-HTTP endpoint. No download, no local process, no ABI matching, centralised updates.

The stale-lockfile bug needs no separate fix: the files that carry it are deleted along with the consumer that reads them.

## Considered Options

### A. Delete MCPB and the registry entry (chosen)

- **Pro**: removes an entire build subsystem, two CI workflows, five pixi tasks and two documents; eliminates a latent runtime bug by deleting the artifact that carries it; aligns with current official guidance; removes the ABI-matching failure mode (a bundle built against one CPython minor version failing on a host with another).
- **Con**: Claude Desktop users must add a connector through the UI instead of double-clicking a file; the project loses its MCP registry visibility until it is re-listed; an offline or firewalled user has no path at all.

### B. Keep MCPB, fix the lockfile bug, add tool-invocation to CI

- **Pro**: preserves the one-click Desktop install and the offline/firewalled path.
- **Con**: keeps the entire subsystem alive, plus new CI to test what it currently does not; for a server whose value proposition is "read a public CV," the offline use case is close to hypothetical. This is maintenance spent on a path official guidance calls secondary for exactly this kind of server.

### C. Keep `server.json`, reworked with a `remotes` entry, and drop only MCPB

- **Pro**: the registry listing is genuinely orthogonal to MCPB (`remotes` and `packages` can coexist), and discoverability has real value. Costs one file.
- **Con**: it costs one file *plus* a publish step with registry authentication, which is either CI (contradicting the "zero CI" bar set for keeping it) or a manual step that will be forgotten. Worse, the entry would be published pointing at a URL that changes during this very migration — the render.com endpoint is being decommissioned and the Wasmer one is not yet verified. Publishing a registry entry mid-cutover advertises an unstable address.

## Consequences

**Positive**
- A large, brittle, currently-broken build path disappears. The `Makefile` shrinks to install targets; `pyproject.toml` loses five tasks.
- The ABI-matching class of bug (documented in the `Makefile`'s own 10-line explanatory comment) becomes structurally impossible.
- Users always get the current server; there is no stale local copy to update.
- CI loses two macOS-runner workflows.

**Negative**
- No MCP registry listing until deliberately re-added. Discoverability drops for users who browse the registry.
- No offline or firewalled distribution path exists at all. Accepted: the server reads a public CV, so an offline user has no data to read either.
- Desktop installation becomes a documented manual step rather than a downloadable file.

**Neutral**
- The two skills (`cv-analyst`, `cv-tailoring`) continue to be packageable as `.zip` for claude.ai; that path is independent of MCPB and is unaffected.

## Disconfirmation

**Activation**: no — official guidance is unambiguous for this server's profile, and the lens sweep would have reached the same result through the Simplicity lens alone.

**Falsifier.** This decision is wrong if users actually want the local path — concretely, if anyone requests an `.mcpb` bundle, or reports being unable to reach the remote server from a network that blocks it, within six months of the drop. Zero such reports over that window would confirm the offline use case was hypothetical.

A separate falsifier for the registry half: if MCP registry traffic turns out to be a meaningful discovery channel (measurable as referrer traffic or install reports), dropping the listing was the wrong half of the decision, and it should be re-added independently of MCPB.

**Steelmanned runner-up.** Option C — keep a reworked `server.json` with a `remotes` entry, drop only MCPB — is the closest call in this ADR, and a reasonable person could take it. `remotes` and `packages` coexist in the current registry schema, so the registry entry genuinely does not depend on MCPB; the file is small; and discoverability for a public read-only server is the *entire* point of a registry. The argument that carried the decision is timing rather than principle: the endpoint URL is being migrated in this very change and has not yet been verified live, so any entry published now would advertise an address that is about to move. Re-listing after the Wasmer endpoint has been stable for a while is strictly better information at strictly lower risk — which makes this a deferral, not a rejection.

**Reversal trigger.** Re-add `server.json` with a `remotes: [{type: "streamable-http", url: ...}]` entry against the current schema once the Wasmer MCP endpoint has served production traffic for one month without an address change. Re-adding MCPB requires a concrete user request, not a hypothetical one.
