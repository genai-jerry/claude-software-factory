# The LangGraph orchestration engine for the Claude Software Factory.
# Runs the webhook service; role runs shell out to the Claude Code CLI and
# git, both installed here.
FROM python:3.11-slim

# Node 22: Claude Code 2.1.198 and later declare engines node >=22, and on
# Node 20 npm quietly installed the last version that allowed it (2.1.197),
# which cannot run newer models — every run fell back from claude-opus-5-5
# with "version 2.1.280 or newer is required" (11 Nov 2026). The build prints
# the version it got, and fails if it is older than MIN_CLAUDE_CODE.
ARG MIN_CLAUDE_CODE=2.1.280
RUN apt-get update \
    && apt-get install -y --no-install-recommends git curl ca-certificates gnupg \
    && curl -fsSL https://deb.nodesource.com/setup_22.x | bash - \
    && apt-get install -y --no-install-recommends nodejs \
    && npm install -g @anthropic-ai/claude-code@latest \
    && got="$(claude --version | cut -d' ' -f1)" \
    && echo "Claude Code $got (need $MIN_CLAUDE_CODE or newer)" \
    && [ "$(printf '%s\n%s\n' "$MIN_CLAUDE_CODE" "$got" | sort -V | head -1)" = "$MIN_CLAUDE_CODE" ] \
    && apt-get purge -y gnupg && apt-get autoremove -y \
    && rm -rf /var/lib/apt/lists/*

# gh CLI: the role prompts instruct agents to use it for GitHub operations.
RUN curl -fsSL https://cli.github.com/packages/githubcli-archive-keyring.gpg \
      -o /usr/share/keyrings/githubcli-archive-keyring.gpg \
    && echo "deb [arch=$(dpkg --print-architecture) signed-by=/usr/share/keyrings/githubcli-archive-keyring.gpg] https://cli.github.com/packages stable main" \
      > /etc/apt/sources.list.d/github-cli.list \
    && apt-get update && apt-get install -y --no-install-recommends gh \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY pyproject.toml ./
COPY src ./src
# --timeout/--retries because this layer pulls psycopg's 5.3 MB binary wheel:
# pip's 15s default read timeout aborts the whole build on one slow chunk, and
# the failure looks like a dependency error rather than the network blip it is.
RUN pip install --no-cache-dir --timeout 120 --retries 10 ".[postgres]"

ENV PORT=8080
EXPOSE 8080
HEALTHCHECK --interval=30s --timeout=5s CMD curl -fsS http://localhost:8080/healthz || exit 1
CMD ["factory-orchestrator"]
