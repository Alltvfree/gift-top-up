/**
 * Seed data for the console UI.
 *
 * This is the fallback shown before/while the live backend is wired in
 * (bots + positions land in Task 4). Market quotes are already live via
 * `api.market.*`; everything here is clearly placeholder domain data.
 */
export type Side = "BUY" | "SELL";

export const account = {
  netLiquidity: 284912,
  changePct: 2.41,
  openTrades: 7,
  dayPnl: 1204,
  riskPct: 18.2,
  model: "TILLY-AI v1.0",
  equityCurve: [40, 55, 48, 62, 58, 70, 64, 80, 74, 88, 100],
};

export const signals = [
  {
    id: "sig-1",
    symbol: "XAU/USD",
    side: "BUY" as Side,
    confidence: 91,
    note: "Momentum breakout",
    tp: "2,424.00",
    sl: "2,391.00",
    move: 0.62,
    time: "14:02:11",
    timeframe: "M15",
    live: true,
  },
  {
    id: "sig-2",
    symbol: "XAU/USD",
    side: "SELL" as Side,
    confidence: 78,
    note: "Volatility compression unwind",
    tp: "2,311.00",
    sl: "2,360.00",
    move: -0.34,
    time: "13:47:52",
    timeframe: "M5",
    live: true,
  },
  {
    id: "sig-3",
    symbol: "XAU/USD",
    side: "BUY" as Side,
    confidence: 85,
    note: "Mean-reversion re-entry",
    tp: "2,398.40",
    sl: "2,361.00",
    move: 0.18,
    time: "13:31:20",
    timeframe: "H1",
    live: false,
  },
  {
    id: "sig-4",
    symbol: "XAU/USD",
    side: "SELL" as Side,
    confidence: 66,
    note: "Session liquidity sweep",
    tp: "2,340.00",
    sl: "2,372.00",
    move: -0.11,
    time: "12:58:04",
    timeframe: "M15",
    live: false,
  },
];

export const positions = [
  {
    id: "pos-1",
    symbol: "XAU/USD",
    side: "LONG" as const,
    volume: "0.50",
    entry: "2,339.10",
    market: "2,347.58",
    tp: "2,370.00",
    sl: "2,325.00",
    pnl: 312,
  },
  {
    id: "pos-2",
    symbol: "XAU/USD",
    side: "SHORT" as const,
    volume: "0.30",
    entry: "2,348.00",
    market: "2,347.58",
    tp: "2,311.00",
    sl: "2,360.00",
    pnl: -86,
  },
];

export const closedTrades = [
  { id: "t-1", side: "LONG", volume: "0.40", opened: "Sep 09 09:12", closed: "Sep 09 11:04", pnl: 418 },
  { id: "t-2", side: "SHORT", volume: "0.25", opened: "Sep 09 07:40", closed: "Sep 09 08:55", pnl: -132 },
  { id: "t-3", side: "LONG", volume: "0.60", opened: "Sep 08 16:22", closed: "Sep 08 18:01", pnl: 906 },
  { id: "t-4", side: "LONG", volume: "0.20", opened: "Sep 08 12:10", closed: "Sep 08 12:48", pnl: -64 },
];

export const riskSettings = [
  { label: "MAX DAILY LOSS", value: "3.0%" },
  { label: "MAX DRAWDOWN", value: "6.0%" },
  { label: "RISK PER TRADE", value: "0.8%" },
  { label: "MAX OPEN LOTS", value: "2.50" },
  { label: "MIN CONFIDENCE", value: "75%" },
  { label: "MAX SPREAD", value: "35 pts" },
];

export const riskEvents = [
  { id: "r-1", time: "13:22:04", level: "WARN", text: "Spread widened to 41 pts — entry skipped" },
  { id: "r-2", time: "11:08:47", level: "INFO", text: "Daily loss usage at 34% of limit" },
  { id: "r-3", time: "09:01:12", level: "WARN", text: "Correlation guard blocked second long" },
];

export const accounts = [
  { id: "a-1", broker: "EXNESS", login: "5518042", mode: "LIVE", equity: 254310, status: "connected" },
  { id: "a-2", broker: "IC-MARKETS", login: "8842190", mode: "PAPER", equity: 30602, status: "connected" },
  { id: "a-3", broker: "XM", login: "1093442", mode: "PAPER", equity: 0, status: "offline" },
];

export const auditLog = [
  { id: "l-1", time: "14:02:11", actor: "engine", text: "Signal executed · BUY 0.50 XAUUSD" },
  { id: "l-2", time: "13:40:02", actor: "admin", text: "Strategy GRID-07 switched to LIVE" },
  { id: "l-3", time: "12:15:33", actor: "engine", text: "Preset reloaded (balanced)" },
  { id: "l-4", time: "08:59:10", actor: "admin", text: "Risk per trade changed 1.0% → 0.8%" },
];

export const systemHealth = [
  { label: "API GATEWAY", value: "OK", ok: true },
  { label: "METAAPI BRIDGE", value: "OK", ok: true },
  { label: "BOT ENGINE", value: "OK", ok: true },
  { label: "DATA FEED LAG", value: "82 ms", ok: true },
];
