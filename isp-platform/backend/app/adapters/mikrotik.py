"""MikroTik RouterOS v7 REST API client (https://<router>/rest/...).

Router side: enable `www-ssl` with a certificate, restrict it to the NMS address, and give the
platform its own user. Polling only needs group=read; applying changes needs group=full.
"""
import json
import re
import time

import httpx


class RouterOSError(Exception):
    pass


class RouterOS:
    def __init__(self, host: str, username: str, password: str, port: int | None = None,
                 verify_tls: bool | str = False, timeout: float = 10.0, transport: httpx.BaseTransport | None = None):
        # Island routers usually carry self-signed certs; pass a CA bundle path to verify.
        self.base = f"https://{host}:{port or 443}/rest"
        self.client = httpx.Client(auth=(username, password), verify=verify_tls, timeout=timeout, transport=transport)

    def close(self):
        self.client.close()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

    def _req(self, method: str, path: str, body=None):
        try:
            r = self.client.request(method, f"{self.base}/{path.lstrip('/')}", json=body)
        except httpx.HTTPError as exc:
            raise RouterOSError(f"{type(exc).__name__}: {exc}") from exc
        if r.status_code >= 400:
            try:
                detail = r.json().get("detail") or r.json().get("message")
            except ValueError:
                detail = r.text[:200]
            raise RouterOSError(f"HTTP {r.status_code}: {detail}")
        return r.json() if r.content else None

    def get(self, path):
        return self._req("GET", path)

    def run_script(self, script: str) -> str:
        """Run RouterOS CLI text via /execute; as-string waits for and returns the output."""
        out = self._req("POST", "execute", {"script": script, "as-string": ""})
        return out.get("ret", "") if isinstance(out, dict) else str(out or "")

    # ---- read-only polling
    def poll(self) -> dict:
        res = self.get("system/resource")
        total = int(res.get("total-memory", 0) or 0)
        free = int(res.get("free-memory", 0) or 0)
        ppp = self.get("ppp/active?.proplist=name")
        ifaces = self.get("interface?.proplist=name,type,running,disabled,rx-byte,tx-byte,link-downs")
        down = [i["name"] for i in ifaces if i.get("disabled") == "false" and i.get("running") == "false"
                and i.get("type") in ("ether", "sfp", "vlan", "bridge")]
        return {
            "cpu_load_pct": float(res.get("cpu-load", 0) or 0),
            "mem_used_pct": round(100 * (total - free) / total, 1) if total else None,
            "uptime_s": parse_uptime(res.get("uptime", "")),
            "extra": {
                "version": res.get("version"),
                "board": res.get("board-name"),
                "pppoe_active": len(ppp),
                "interfaces_down": down,
            },
        }

    def firewall_snapshot(self) -> dict:
        """Everything the security audit looks at, in one place."""
        snap = {}
        for key, path in {
            "services": "ip/service", "users": "user", "dns": "ip/dns",
            "filter": "ip/firewall/filter", "raw": "ip/firewall/raw",
            "mac_server": "tool/mac-server", "mac_winbox": "tool/mac-server/mac-winbox",
            "neighbor": "ip/neighbor/discovery-settings", "snmp_communities": "snmp/community",
            "ip_settings": "ip/settings", "resource": "system/resource", "radius_incoming": "radius/incoming",
            "socks": "ip/socks", "proxy": "ip/proxy", "bandwidth_server": "tool/bandwidth-server",
        }.items():
            try:
                snap[key] = self.get(path)
            except RouterOSError as exc:
                snap[key] = {"error": str(exc)}
        return snap

    # ---- threat protection
    def login_failures(self, cursor: int | None) -> tuple[list[dict], int | None]:
        """Failed Winbox/SSH/API logins logged since `cursor` (the numeric log .id)."""
        try:
            rows = self._req("POST", "log/print", {".proplist": [".id", "message"], ".query": ["topics=system,error,critical"]})
        except RouterOSError:
            rows = self.get("log?.proplist=.id,message")  # older v7 builds without query support
        ids = [int(r[".id"].lstrip("*"), 16) for r in rows if r.get(".id")]
        top = max(ids) if ids else cursor
        if cursor is not None and top is not None and top < cursor:
            cursor = None  # log restarted (reboot / cleared): read it all again
        events = []
        for r in rows:
            n = int(r[".id"].lstrip("*"), 16)
            if cursor is not None and n <= cursor:
                continue
            m = LOGIN_FAILURE.search(r.get("message", ""))
            if m:
                events.append({"src_ip": m["ip"], "username": m["user"][:64], "via": m["via"][:16],
                               "message": r["message"][:300]})
        return events, top

    def blocklist_entries(self) -> list[dict]:
        return self.get("ip/firewall/address-list?list=blocklist")

    def blocklist_add(self, address: str, timeout_s: int | None, comment: str):
        body = {"list": "blocklist", "address": address, "comment": comment}
        if timeout_s:
            body["timeout"] = ros_duration(timeout_s)
        self._req("PUT", "ip/firewall/address-list", body)

    def blocklist_remove(self, item_id: str):
        self._req("DELETE", f"ip/firewall/address-list/{item_id}")

    def blocklist_enforced(self) -> bool:
        """True if some enabled RAW-prerouting or input-filter rule drops src-address-list=blocklist."""
        for path, chains in (("ip/firewall/raw", ("prerouting",)), ("ip/firewall/filter", ("input",))):
            for r in self.get(path):
                if (r.get("src-address-list") == "blocklist" and r.get("action") == "drop"
                        and r.get("chain") in chains and r.get("disabled") != "true"):
                    return True
        return False

    # ---- change application with commit-confirm
    def apply_with_commit_confirm(self, change_id: int, script: str, confirm_minutes: int, reachable_check) -> str:
        """Back up, arm an auto-restore, apply, then disarm only if the router is still reachable.

        If the change cuts us off (wrong firewall rule, broken route to the island), the router
        restores the backup by itself after `confirm_minutes` and reboots.
        """
        name = f"isp-change-{change_id}"
        log = []
        self.run_script(f'/system backup save name={name} dont-encrypt=yes')
        self.run_script(f'/export file={name}')
        log.append(f"backup {name}.backup + {name}.rsc saved")
        self.run_script(
            f'/system scheduler add name={name} interval={confirm_minutes}m '
            f'on-event="/system scheduler remove [find name={name}]; /system backup load name={name}.backup password=\\"\\"" '
            f'comment="isp-platform auto-rollback"'
        )
        log.append(f"auto-rollback armed ({confirm_minutes} min)")
        try:
            out = self.run_script(script)
            log.append("script output: " + (out.strip() or "(none)"))
        except RouterOSError as exc:
            log.append(f"script error: {exc}; leaving auto-rollback armed")
            raise RouterOSError("\n".join(log)) from exc
        time.sleep(3)
        if not reachable_check():
            log.append("router unreachable after apply; auto-rollback will restore the backup")
            raise RouterOSError("\n".join(log))
        self.run_script(f'/system scheduler remove [find name={name}]')
        log.append("router reachable; auto-rollback disarmed")
        return "\n".join(log)


LOGIN_FAILURE = re.compile(r"login failure for user (?P<user>.*?) from (?P<ip>[0-9A-Fa-f:.]+) via (?P<via>\S+)")


def ros_duration(seconds: int) -> str:
    """Seconds -> RouterOS time ('6d23h59m')."""
    d, rem = divmod(max(int(seconds), 60), 86400)
    h, rem = divmod(rem, 3600)
    return f"{d}d{h}h{rem // 60}m" if d else f"{h}h{rem // 60}m"


def parse_uptime(text: str) -> int | None:
    """RouterOS uptime ('2d3h4m5s', or '1w2d03:04:05' on older builds) -> seconds."""
    if not text:
        return None
    total = 0
    clock = re.match(r"^(.*?)(\d+):(\d+):(\d+)$", text)
    if clock:
        text = clock.group(1)
        total += int(clock.group(2)) * 3600 + int(clock.group(3)) * 60 + int(clock.group(4))
    units = {"w": 604800, "d": 86400, "h": 3600, "m": 60, "s": 1}
    for num, unit in re.findall(r"(\d+)([wdhms])", text):
        total += int(num) * units[unit]
    return total


def dumps(obj) -> str:
    return json.dumps(obj, indent=2, sort_keys=True)
