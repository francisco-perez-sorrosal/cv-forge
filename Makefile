# Makefile for building and installing distributable packages

DIST_DIR   ?= dist
DIST_SKILL  = $(DIST_DIR)/skill

SKILLS = cv-analyst cv-tailoring

MCP_SERVER_KEY = fps_cv_mcp

.PHONY: build-skill \
        install-claude-code install-skills \
        clean

# --- Build targets ---

# Package skills as zips for claude.ai (Settings > Features > Add Skill)
build-skill:
	mkdir -p $(DIST_SKILL)
	@for skill in $(SKILLS); do \
		cd plugins/cv/skills/$$skill && zip -r $(CURDIR)/$(DIST_SKILL)/$$skill.zip SKILL.md references/ && cd $(CURDIR); \
	done

# --- Install targets ---

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
