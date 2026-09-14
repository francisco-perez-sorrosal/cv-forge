# Skills

Maintainer skills for Francisco Perez-Sorrosal's CV — edit the data, publish releases, and deploy the MCP server. These skills are for the CV maintainer only; use the `cv` plugin for CV retrieval and tailoring.

## Skills Catalog

| Skill | Purpose | Invocation |
|-------|---------|-----------|
| [cv-data-edit](cv-data-edit/SKILL.md) | Edit `cv-data/*.yaml`, validate against the schema, preview renders, and open a PR. | Model-invocable via trigger phrases ("update my CV", "add this job", "edit resume.yaml") |
| [cv-publish](cv-publish/SKILL.md) | Tag a new CV release (or re-render an existing tag) and verify the release, workflow, and live site. | User-invoked only via `/cv-publish` command |
| [cv-forge-deploy](cv-forge-deploy/SKILL.md) | Deploy the cv-forge MCP server to Wasmer Edge and verify it is live. | User-invoked only via `/cv-forge-deploy` command |

## Setup

### Installation

Add the marketplace source and install the plugin:

```bash
claude plugin marketplace add francisco-perez-sorrosal/bit-agora
claude plugin install cv-forge
```

### Configuration

Configure two paths in the plugin settings:

- **`cv_repo_path`** (required) — Local clone of `github.com/francisco-perez-sorrosal/cv`. Must contain `cv-data/resume.yaml`. Used by `cv-data-edit` and `cv-publish`. Example: `/Users/fperez/dev/cv`

- **`cv_forge_path`** (optional) — Local checkout of `github.com/francisco-perez-sorrosal/cv-forge`. Only needed when `cv-forge` is not on PATH (for render preview in `cv-data-edit`) and required for `cv-forge-deploy`. Example: `/Users/fperez/dev/cv-forge`

### Prerequisites

- GitHub CLI (`gh`) authenticated
- Wasmer ≥ 7.0 (for `cv-forge-deploy`)
- `anybuild` on PATH (for `cv-forge-deploy`)
- TeX distribution (for PDF preview in `cv-data-edit`)
