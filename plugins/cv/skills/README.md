# Skills

Agent Skills for working with Francisco Perez-Sorrosal's CV. Each skill is a handler that composes with the CV MCP server to provide structured workflows for retrieval, summarization, rendering, and job-targeted tailoring.

## Skills Catalog

| Skill | Purpose | Triggers | References |
|-------|---------|----------|------------|
| [cv-analyst](cv-analyst/SKILL.md) | CV retrieval, summarization, and rendering in markdown, plain text, PDF, HTML, LaTeX, and Typst formats. | "summarize CV", "HTML version", "LaTeX", "Typst", "quick overview" | [summary-presets.md](cv-analyst/references/summary-presets.md) — pre-configured profiles for hiring screens and executive briefings |
| [cv-tailoring](cv-tailoring/SKILL.md) | Job-targeted CV tailoring that analyzes a job description, generates a tailoring specification, and produces a page-constrained (2-3 pages) compiled PDF via LaTeX or Typst. | "tailor CV for this job", "adapt resume", "CV for job", "resume optimization" | [methodology.md](cv-tailoring/references/methodology.md) — tailoring methodology with strategic analysis, repositioning, and evaluation phases |

## Installation and Usage

The plugin connects to the CV MCP server via native HTTP at `https://fps-cv-mcp.wasmer.app/mcp` (configured in `plugins/cv/.claude-plugin/plugin.json`). Both skills route CV content retrieval through this server.

### Claude Code

Add the marketplace source and install the plugin:

```bash
claude plugin marketplace add francisco-perez-sorrosal/bit-agora
claude plugin install cv
```

### Claude Desktop

Build skill packages with `make build-skill`, then upload the zip files manually:

1. Run `make build-skill` to create `dist/skill/cv-analyst.zip` and `dist/skill/cv-tailoring.zip`
2. Open Claude Desktop Settings > Features > Add Skill
3. Upload each zip file (each skill is packaged separately with SKILL.md and references/)
4. Restart Claude Desktop

Skills follow the Agent-Skills spec for portability across compatible clients (Claude Code, Claude Desktop, Cursor, Gemini CLI, VS Code, and others).
