# n8n with the MT5 bot (laptop first, server later)

n8n does the **glue**: schedules, reports, AI reviews. It never trades. The bot keeps the broker connection, the risk rules and the
Approve button. n8n talks to the bot through a small local API that has **no endpoint to place, close or modify an order**.

```
n8n (Docker)  --token-->  automation API (inside the bot, 127.0.0.1:8765)  -->  same risk-checked service as Telegram / Claude Desktop
      |                                  |
  AI provider (optional)        /prepare makes a TICKET -> Telegram -> a human taps Approve
```

## 1. Turn the API on (same machine as the bot)

In PowerShell (type the real values yourself; the token is a password, so keep it out of chats and screenshots):

```powershell
$t = [guid]::NewGuid().ToString("N") + [guid]::NewGuid().ToString("N")
setx MT5_AI_API_TOKEN $t
$t      # shows it once: copy it into n8n in step 3, then clear the screen
```

Open a NEW PowerShell and start the bot as usual (`C:\mt5-ai\start_bot.ps1`). It prints
`automation API for n8n listening on 127.0.0.1:8765`. Without the token the API does not start.

## 2. Run n8n in Docker (bound to this laptop only)

```powershell
docker run -d --name n8n --restart unless-stopped -p 127.0.0.1:5678:5678 -v n8n_data:/home/node/.n8n -e GENERIC_TIMEZONE=UTC -e TZ=UTC -e N8N_DIAGNOSTICS_ENABLED=false docker.n8n.io/n8nio/n8n
```

Change `UTC` to your own time zone (for example `Asia/Karachi`) so the schedules fire at your local time. Open `http://127.0.0.1:5678`
and create the owner account. (n8n is "fair-code": free to self-host; check its current licence terms for anything beyond personal use.)

Workflows reach the bot at `http://host.docker.internal:8765`. If a call is refused, tell me: the fallback is running n8n with npm
instead of Docker and changing that address to `http://127.0.0.1:8765`.

## 3. Credentials (created in the n8n UI, never in files or chats)

1. **Credentials > Add > Header Auth**, name it exactly `mt5-ai token`: Name `Authorization`, Value `Bearer <the token from step 1>`.
2. Only for the AI workflows: another **Header Auth** named `anthropic key`: Name `x-api-key`, Value = your Anthropic API key.
   (Using OpenAI or Google instead means changing the "Ask the AI" node's URL, headers and body; ask me and I will give you those versions.)

## 4. Import the workflows

n8n: **Workflows > Import from file**, for each file in `n8n/workflows/`. In each HTTP node pick the matching credential. Run once by hand.

| Workflow | What it does | Trigger |
| --- | --- | --- |
| `daily_report.json` | Reads status, positions and the journal; sends a summary to Telegram | every day 21:00 |
| `weekly_journal_review.json` | An AI agent describes your journal honestly (too-few-trades warnings, no advice to size up) | Sundays 18:00 |
| `risk_review_on_demand.json` | A veto-only AI reviewer challenges a trade you are considering | manual |

All three were checked for structure and syntax here, but not imported into a running n8n (none was available). If an import
complains, send me the message.

## The agents' rules (also in `prompts/`)

Agents may only **inform or reduce risk**: warn, say SKIP, suggest smaller size, fewer trades, stopping for the day. They never approve,
never place, never suggest a bigger size or a direction. `risk_review_on_demand` ends with `NO OBJECTION` at best, never "approved".
The tests fail if a shipped workflow references any order endpoint.

## Endpoints

`GET /health` (open), then with the bearer token: `GET /status`, `/positions`, `/journal`, `/quote?symbol=`, `/context?symbol=&side=&sl=&tp=`,
`/bundle?...`; `POST /prepare` (ticket + Telegram buttons, tagged `source:n8n`), `POST /notify`, `POST /halt`. Rate limited, 4 KB bodies.

## Moving it to the server later

Same files, same steps. Keep the API on `127.0.0.1` and put n8n on the same machine as the bot. If they must be on different machines,
set `MT5_AI_API_HOST` to a private address only, keep the token, and firewall the port; never expose it to the internet.
