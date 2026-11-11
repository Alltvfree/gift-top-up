"""Launch the real entry point (`python -m mt5_ai`) as a subprocess and talk
MCP to it over stdio, with a shim MetaTrader5 module backed by the fake
terminal — proves the packaging, settings and handshake, not just the logic."""
import asyncio
import json
import sys
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

TESTS = Path(__file__).resolve().parent
ROOT = TESTS.parent


def test_the_server_starts_over_stdio_and_serves_tools(tmp_path):
    shim = tmp_path / "shim"
    shim.mkdir()
    (shim / "MetaTrader5.py").write_text(
        f"import sys\nsys.path.insert(0, {str(TESTS)!r})\nfrom fake_mt5 import FakeMT5\n_f = FakeMT5()\n"
        "def __getattr__(name):\n    return getattr(_f, name)\n"
    )
    params = StdioServerParameters(
        command=sys.executable, args=["-m", "mt5_ai"],
        env={"PYTHONPATH": f"{shim}:{ROOT}", "MT5_AI_STATE_DIR": str(tmp_path / "state"), "PATH": "/usr/bin:/bin",
             "SYSTEMROOT": "", "HOME": str(tmp_path)},
    )

    async def session():
        async with stdio_client(params) as (read, write):
            async with ClientSession(read, write) as s:
                await s.initialize()
                tools = {t.name for t in (await s.list_tools()).tools}
                overview = await s.call_tool("account_overview", {})
                prep = await s.call_tool("prepare_trade", {"symbol": "XAUUSD", "side": "BUY", "sl": 4995.0, "tp": 5010.0})
                return tools, json.loads(overview.content[0].text), json.loads(prep.content[0].text)

    tools, overview, prep = asyncio.run(asyncio.wait_for(session(), timeout=60))
    assert {"prepare_trade", "place_prepared_trade", "kronos_forecast"} <= tools
    assert overview["mode"] == "DEMO" and overview["account"] == "***789"
    assert prep["verdict"] == "PASS"
