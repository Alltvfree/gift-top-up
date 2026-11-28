# Starts the Telegram bot and restarts it if it stops. Run on the machine that has MT5 (open, logged in).
# Secrets must already be set as Windows environment variables (see README); this script never asks for or prints them.
$py = "C:\tilly-kronos\venv\Scripts\python.exe"
$env:PYTHONPATH = "C:\mt5-ai"
foreach ($n in "MT5_AI_TELEGRAM_TOKEN", "MT5_AI_TELEGRAM_ALLOWED_IDS") {
  if (-not [Environment]::GetEnvironmentVariable($n, "User")) { throw "$n is not set. See the README (Telegram bot)." }
}
# user-level variables are not always visible to an already-open console; load them explicitly
foreach ($n in "MT5_AI_TELEGRAM_TOKEN","MT5_AI_TELEGRAM_ALLOWED_IDS","MT5_AI_TELEGRAM_SYMBOL","MT5_AI_LLM_PROVIDER","MT5_AI_LLM_MODEL","ANTHROPIC_API_KEY","OPENAI_API_KEY","GOOGLE_API_KEY","MT5_AI_SYMBOLS","MT5_AI_API_TOKEN","MT5_AI_API_PORT","MT5_AI_API_HOST","MT5_AI_QUICK_HOLD","MT5_AI_QUICK_RR","MT5_AI_QUICK_STOP","MT5_AI_QUICK_SPREAD_MULT","MT5_AI_QUICK_BLOCK_FLAGS","MT5_AI_MAX_TRADES_PER_DAY","MT5_AI_MAX_DRIFT_TO_STOP","MT5_AI_MAX_RISK_PCT","MT5_AI_MAX_DAILY_LOSS_PCT") {
  $v = [Environment]::GetEnvironmentVariable($n, "User"); if ($v) { Set-Item -Path "Env:$n" -Value $v }
}
while ($true) {
  & $py -m mt5_ai.telegram_bot
  "Bot stopped (exit $LASTEXITCODE). Restarting in 10 seconds. Press Ctrl+C to quit."
  Start-Sleep -Seconds 10
}
