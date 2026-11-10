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

## Set up on Beacon's production server
Beacon's production is one VPS running `docker-compose.prod.yml` with Traefik, and every service logs to Docker's `json-file` driver. That is what this reads. The service is already in beacon-infra's compose file, **off until you switch it on**, and its image is published to `ghcr.io/genai-jerry/log-reader` when this lands on `main`.

1. **Image.** After this is on `main`, the "Publish the log-reader image" workflow runs and pushes `log-reader:main`. (Run it by hand from the Actions tab if you want it sooner.)
2. **DNS.** Add an A record `logs.<BEACON_DOMAIN>` → the server, the same as `api.`.
3. **Server settings.** In `.env.prod` on the server:
   ```
   LOG_READER_TOKEN=<output of: openssl rand -hex 24>
   COMPOSE_PROFILES=logs
   ```
4. **Deploy.** `scripts/deploy.sh` as usual (or `scripts/deploy.sh log-reader=main`). Traefik gets the certificate by itself.
5. **Check:** `curl -s https://logs.<BEACON_DOMAIN>/healthz` → `{"ok":true}`.
6. **Connect Compass.** In Compass → **Tools** → Add an MCP server:
   - URL `https://logs.<BEACON_DOMAIN>/mcp`, transport Streamable HTTP
   - Header `Authorization` = `Bearer <the token>`
   - Name it "Production logs". Leave **Shape** and **Ask** on, and turn **Builds** off: build runs have no need of production logs.
7. Open **Investigate** in Compass and describe what you noticed.

To turn it off: remove `COMPOSE_PROFILES=logs` and redeploy, then `docker compose rm -sf log-reader`.

**How far back it can see:** Beacon keeps 5 files of 20 MB per service. A busy service may rotate within hours, so investigate soon after something happens. Raise `max-size` / `max-file` in `x-logging` for a longer reach.

If production moves to Kubernetes, this needs a different source: Kubernetes logs are not Docker json-file logs.

To rotate the token: change `LOG_READER_TOKEN`, redeploy, and re-enter the header in Tools.

## Run it locally
```
LOG_READER_TOKEN=$(openssl rand -hex 24) LOG_DIR=/path/to/fake/containers python tools/log-reader/log_reader.py
```
Tests: `cd orchestrator && python -m pytest tests/test_log_reader.py`.
