# Starts the Telegram bot and restarts it if it stops. Run on the machine that has MT5 (open, logged in).
# Secrets must already be set as Windows environment variables (see README); this script never asks for or prints them.
$py = "C:\tilly-kronos\venv\Scripts\python.exe"
$env:PYTHONPATH = "C:\mt5-ai"
foreach ($n in "MT5_AI_TELEGRAM_TOKEN", "MT5_AI_TELEGRAM_ALLOWED_IDS") {
  if (-not [Environment]::GetEnvironmentVariable($n, "User")) { throw "$n is not set. See the README (Telegram bot)." }
}
# user-level variables are not always visible to an already-open console; load them explicitly
foreach ($n in "MT5_AI_TELEGRAM_TOKEN","MT5_AI_TELEGRAM_ALLOWED_IDS","MT5_AI_TELEGRAM_SYMBOL","MT5_AI_LLM_PROVIDER","MT5_AI_LLM_MODEL","ANTHROPIC_API_KEY","OPENAI_API_KEY","GOOGLE_API_KEY","MT5_AI_SYMBOLS") {
  $v = [Environment]::GetEnvironmentVariable($n, "User"); if ($v) { Set-Item -Path "Env:$n" -Value $v }
}
while ($true) {
  & $py -m mt5_ai.telegram_bot
  "Bot stopped (exit $LASTEXITCODE). Restarting in 10 seconds. Press Ctrl+C to quit."
  Start-Sleep -Seconds 10
}
