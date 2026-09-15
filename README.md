# CV Agent Toolkit

A suite of tools for working with Francisco Perez-Sorrosal's CV and professional information. Combines an MCP server, two agent skills, and two Claude Code plugins into installable packages.

## What It Does

- **MCP Server** — serves CV content in markdown, PDF, LaTeX, HTML, and Typst formats via 16 tools, plus semantic query capabilities and tailored CV rendering
- **`cv-analyst` Skill** — structured CV summarization for different audiences (hiring screens, executive briefings, technical reviews) with output in multiple formats
- **`cv-tailoring` Skill** — job-targeted CV tailoring that analyzes a job description, selects relevant content, and produces a page-constrained (2-3 pages) compiled PDF
- **Two Claude Code Plugins** — `cv` (consumer-facing) and `cv-forge` (maintainer-facing, editor + publisher)

## Installation

### Claude Code (Recommended)

#### First-time install

Install the consumer plugin from the marketplace:

```bash
claude plugin marketplace add francisco-perez-sorrosal/bit-agora
claude plugin install cv
```

Both the `cv` (consumer) and `cv-forge` (maintainer) plugins are available. Install `cv` for end-user CV access; additionally install `cv-forge` if you need to edit CV data or manage releases.

#### Configuration (for the maintainer plugin only)

If you install `cv-forge`, configure the plugin to find your cloned repositories:

```bash
claude plugin configure cv-forge --scope user --config cv_repo_path=/Users/you/dev/cv
```

Optionally add the `cv-forge` repository path:

```bash
claude plugin configure cv-forge --scope user --config cv_forge_path=/Users/you/dev/cv-forge
```

Both paths must be absolute. The `cv_repo_path` is required; `cv_forge_path` is optional (falls back to `cv-forge` on `PATH`).

#### Update plugins

To pick up new releases of the plugins:

```bash
claude plugin update cv
claude plugin update cv-forge
```

Then restart Claude Code.

### Claude Desktop

Add a custom connector:

1. Open Claude Desktop Settings
2. Go to Connections (or Extensions)
3. Add a custom connector with the MCP URL: `https://fps-cv-mcp.wasmer.app/mcp`

The MCP server fetches CV data from GitHub Release assets. If you have local CV data (the `cv` repository cloned), set `CV_DATA_DIR=<path>` to render against that instead.

## Usage

### Retrieve and Summarize the CV

- "Get Francisco's CV"
- "Summarize Francisco's CV for a startup executive briefing"
- "What is Francisco's Google Scholar profile link?"
- "Give me a 3 page summary of my CV for a hiring manager oriented towards an AI engineer position in HTML"
- "Give me the CV in LaTeX"

### Tailor the CV for a Job

Use the `cv-tailoring` skill to adapt the CV to a specific job description:

- "Tailor my CV for this job: [paste job description]"
- "Adapt my resume for a Senior ML Engineer position at Google"
- "Customize my CV for this LinkedIn job"

The tailoring pipeline analyzes the job description, assesses fit against CV content, reorders sections, filters entries, and renders a 2-3 page PDF.

### Publish (Maintainer Only)

Use the `cv-forge` plugin to edit CV data, open a PR, publish a release, and deploy updates:

- "Edit my CV: change my title at Yahoo to Principal Research Engineer"
- "Show me the diff and open a PR" (validation happens automatically)
- "Publish the CV" (tags and deploys to Wasmer)

## The Two Repositories

**`cv` (data repository)** — Contains the CV content in structured YAML format:
- `cv-data/resume.yaml` — Work experience, education, projects, publications, skills
- `cv-data/resume-semantics.yaml` — Semantic overlay with topic taxonomy and cross-references
- `schemas/` — JSON Schema pair for validation and structure definition

**`cv-forge` (this repository)** — Contains all the machinery:
- Python MCP server and CLI for rendering and serving
- Jinja2 templates for five output formats
- Two Claude Code plugins
- GitHub Actions for publishing and deploying
- Wasmer Edge apps for hosting

The two repositories share no code — only two pinned artifacts (a reusable GitHub workflow and mirrored schemas) and one runtime data source (GitHub Release assets).

## Rendered CV

The latest compiled CV is published as:
- **HTML (interactive)** — https://fps-cv.wasmer.app/
- **PDF** — GitHub Release asset at `releases/latest/download/resume.pdf`
- **LaTeX (moderncv)** — GitHub Release asset at `releases/latest/download/resume.tex`
- **Typst (moderner-cv)** — GitHub Release asset at `releases/latest/download/resume.typst`
- **Markdown** — GitHub Release asset at `releases/latest/download/resume.md`

All assets are regenerated every time the CV data is updated.

## Release Assets

Each release contains eight stable, version-free assets:

| Asset | Format | Purpose |
|-------|--------|---------|
| `resume.md` | Markdown | Full CV for AI consumption |
| `resume.tex` | LaTeX (moderncv) | Full CV for local compilation |
| `resume.html` | HTML | Interactive CV for web browsers |
| `resume.typst` | Typst (moderner-cv) | Full CV for Typst compilation |
| `resume.pdf` | PDF | Compiled full CV |
| `resume-tailored.tex` | LaTeX (tailored) | Tailored template (requires TailoringSpec) |
| `resume-tailored.typst` | Typst (tailored) | Tailored template (requires TailoringSpec) |
| `release.json` | JSON | Release metadata and asset manifest |

For developer documentation and deployment details, see [README_DEV.md](README_DEV.md) and [RELEASE_PROCESS.md](RELEASE_PROCESS.md).

For the CV data repository, see [github.com/francisco-perez-sorrosal/cv](https://github.com/francisco-perez-sorrosal/cv).

## Support

For technical issues or questions about the machinery, refer to this repository. For questions or corrections about CV content, refer to the `cv` data repository.
