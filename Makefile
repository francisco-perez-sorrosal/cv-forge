# Makefile for building and installing distributable packages

DIST_DIR   ?= dist
DIST_SKILL  = $(DIST_DIR)/skill

SKILLS = cv-analyst cv-tailoring

CLAUDE_DESKTOP_CONFIG = $(HOME)/Library/Application Support/Claude/claude_desktop_config.json
MCP_SERVER_KEY        = fps_cv_mcp
REMOTE_MCP_CONFIG     = config/cv_mcp.json

.PHONY: build-skill \
        install-claude-desktop install-claude-code install-skills \
        clean

# --- Build targets ---

# Package skills as zips for claude.ai (Settings > Features > Add Skill)
build-skill:
	mkdir -p $(DIST_SKILL)
	@for skill in $(SKILLS); do \
		cd plugins/cv/skills/$$skill && zip -r $(CURDIR)/$(DIST_SKILL)/$$skill.zip SKILL.md references/ && cd $(CURDIR); \
	done

# --- Install targets ---

# Install for Claude Desktop (remote connector only — MCPB packaging retired)
install-claude-desktop: build-skill
	@if [ ! -f "$(CLAUDE_DESKTOP_CONFIG)" ]; then \
		echo "Error: Claude Desktop config not found at $(CLAUDE_DESKTOP_CONFIG)"; \
		exit 1; \
	fi
	@if jq -e '.mcpServers.$(MCP_SERVER_KEY)' "$(CLAUDE_DESKTOP_CONFIG)" > /dev/null 2>&1; then \
		echo "MCP server: $(MCP_SERVER_KEY) already present in Claude Desktop config — skipping"; \
	else \
		jq --argjson cfg "$$(cat $(REMOTE_MCP_CONFIG))" \
			'.mcpServers.$(MCP_SERVER_KEY) = $$cfg' "$(CLAUDE_DESKTOP_CONFIG)" > "$(CLAUDE_DESKTOP_CONFIG).tmp" \
			&& mv "$(CLAUDE_DESKTOP_CONFIG).tmp" "$(CLAUDE_DESKTOP_CONFIG)"; \
		echo "MCP server: $(MCP_SERVER_KEY) injected into Claude Desktop config"; \
	fi
	@echo ""
	@echo "Skills built. Install manually in Claude Desktop:"
	@echo "  Skills: Open Settings > Features > Add Skill, upload each zip from $(DIST_SKILL)/"
	@echo ""

# Install Claude Code plugin
# Usage: make install-claude-code                      # local (default): local plugin + local MCP
#        make install-claude-code MCP_TARGET=remote     # marketplace plugin (remote MCP built-in)
MCP_TARGET ?= local
install-claude-code:
ifeq ($(MCP_TARGET),local)
	@jq --argjson cfg "$$(jq '.mcpServers.$(MCP_SERVER_KEY)' plugins/cv/.claude-plugin/mcp-local.json)" \
		'.mcpServers.$(MCP_SERVER_KEY) = $$cfg' .mcp.json > .mcp.json.tmp \
		&& mv .mcp.json.tmp .mcp.json
	@echo "MCP server: local (http via cv-forge serve) -> .mcp.json"
	claude plugin install --scope user ./plugins/cv
	@echo "Plugin: installed from local directory"
else ifeq ($(MCP_TARGET),remote)
	claude plugin marketplace add francisco-perez-sorrosal/bit-agora
	claude plugin install --scope user cv
	@echo "Plugin: cv installed from bit-agora marketplace"
endif

# --- Clean ---

clean:
	rm -rf $(DIST_DIR)/
