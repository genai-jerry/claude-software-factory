# log-reader — a read-only log tool for Compass → Investigate

A small MCP server that sits beside a production Docker stack and lets Compass's
Claude **search the logs** while investigating a problem. It is read-only and it
**masks personal data and secrets on the host, before anything leaves it.**

| Tool | What it does |
|---|---|
| `list_services` | The services logging here, and when each last wrote |
| `search_logs` | Find lines by text or regex in a time window (default last hour), by service and level |
| `error_summary` | The errors that repeat most in a window (default 24 h), grouped by message shape |

## What it can and cannot do
- It reads Docker's json-file logs from a **read-only mount**. No Docker socket, no shell, no writes, no other files.
- `LOG_SERVICES` limits it to the services you list.
- Every line is masked: phone numbers (`+91••••••3210`), emails (`j•••@example.com`), bearer tokens, API keys, JWTs, `password=` style values, and the values of fields like `body`, `text`, `first_name`. Searching runs on the masked line, so a guessed phone number finds nothing.
- Masking is best-effort on free text. If your code logs a customer's name inside a sentence, it is not caught. Fix that at the source (log ids, not names).
- There is **no switch to turn masking off.**

## Set up (about ten minutes)
1. Add the service from `docker-compose.snippet.yml` to the production stack and set `LOG_READER_TOKEN` (`openssl rand -hex 24`).
2. Give it a TLS host name through your reverse proxy, e.g. `https://logs.example.com/mcp`.
3. Check it: `curl -s https://logs.example.com/healthz` → `{"ok":true}`.
4. In Compass → **Tools** → Add an MCP server:
   - URL `https://logs.example.com/mcp`, transport Streamable HTTP
   - Header `Authorization` = `Bearer <your token>`
   - Name it "Production logs"; leave it on for **Shape/Ask** (Investigate uses them). Turn **Builds** off: build runs have no need of production logs.
5. Open **Investigate** in Compass and describe what you noticed.

To rotate the token: change `LOG_READER_TOKEN`, redeploy, and re-enter the header in Tools.

## Run it locally
```
LOG_READER_TOKEN=$(openssl rand -hex 24) LOG_DIR=/path/to/fake/containers python tools/log-reader/log_reader.py
```
Tests: `cd orchestrator && python -m pytest tests/test_log_reader.py`.
