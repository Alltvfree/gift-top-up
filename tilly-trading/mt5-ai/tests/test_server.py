"""The MCP surface: which tools exist, how they are annotated, and that a
call travels all the way through to the fake terminal."""
import asyncio
import json

from fake_mt5 import FakeMT5
from mt5_ai.broker import Mt5Broker
from mt5_ai.config import Settings
from mt5_ai.server import build_server
from mt5_ai.service import Mt5Service

READ_ONLY = {"account_overview", "symbol_details", "get_quote", "get_candles", "list_positions",
             "list_pending_orders", "todays_summary", "kronos_forecast", "rule_setup_status", "simulate_trade_plan"}
ORDER_TOOLS = {"place_prepared_trade", "move_stop", "close_position"}


def _server(tmp_path):
    mt5 = FakeMT5()
    return mt5, build_server(Mt5Service(Mt5Broker(mt5), Settings(state_dir=tmp_path)))


def _payload(result):
    """Tool results come back as (content blocks, structured) or content blocks."""
    blocks = result[0] if isinstance(result, tuple) else result
    return json.loads(blocks[0].text)


def test_exactly_the_intended_tools_exist_and_there_is_no_generic_order_tool(tmp_path):
    _, server = _server(tmp_path)
    names = {t.name for t in asyncio.run(server.list_tools())}
    assert names == READ_ONLY | ORDER_TOOLS | {"prepare_trade", "halt_trading"}
    assert not {n for n in names if "close_all" in n or "send_order" in n or n == "place_order"}


def test_read_only_tools_are_annotated_so_clients_can_auto_approve_only_those(tmp_path):
    _, server = _server(tmp_path)
    tools = {t.name: t for t in asyncio.run(server.list_tools())}
    for name in READ_ONLY:
        assert tools[name].annotations.readOnlyHint is True, name
    for name in ORDER_TOOLS:
        assert tools[name].annotations.readOnlyHint is False and tools[name].annotations.destructiveHint is True, name
    assert tools["prepare_trade"].annotations.readOnlyHint is False and tools["prepare_trade"].annotations.destructiveHint is False


def test_the_server_tells_claude_the_rules(tmp_path):
    _, server = _server(tmp_path)
    text = server.instructions
    for rule in ("explicit yes", "BLOCK", "Demo accounts only", "never widen"):
        assert rule.lower() in text.lower()


def test_a_full_prepare_then_place_round_trip_through_mcp(tmp_path):
    mt5, server = _server(tmp_path)
    prep = _payload(asyncio.run(server.call_tool("prepare_trade", {"symbol": "XAUUSD", "side": "BUY", "sl": 4995.0, "tp": 5010.0})))
    assert prep["verdict"] == "PASS" and mt5.sent == []
    placed = _payload(asyncio.run(server.call_tool("place_prepared_trade", {"ticket_id": prep["ticket_id"]})))
    assert placed["placed"] is True and len(mt5.sent) == 1


def test_read_tool_call_returns_data(tmp_path):
    _, server = _server(tmp_path)
    overview = _payload(asyncio.run(server.call_tool("account_overview", {})))
    assert overview["mode"] == "DEMO"


def test_skills_are_well_formed_and_name_the_real_order_tools():
    import re
    from pathlib import Path

    skills = Path(__file__).resolve().parent.parent / "skills"
    folders = sorted(p for p in skills.iterdir() if p.is_dir())
    assert [p.name for p in folders] == ["mt5-analyze", "mt5-execute", "mt5-plan-trade", "mt5-review", "mt5-setup"]
    for folder in folders:
        text = (folder / "SKILL.md").read_text()
        front = re.match(r"---\nname: (.+)\ndescription: >-\n((?:  .+\n)+)---\n", text)
        assert front and front.group(1) == folder.name, folder.name
    setup = (skills / "mt5-setup" / "SKILL.md").read_text()
    for tool in ORDER_TOOLS:
        assert f"`{tool}`" in setup, f"{tool} must be called out as Needs approval"
    all_text = "\n".join((f / "SKILL.md").read_text() for f in folders)
    assert "explicit yes" in all_text and "halt_trading" in all_text
