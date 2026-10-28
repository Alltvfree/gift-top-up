"""RouterOS v7 hardening + firewall generator, and a read-only audit of a live router.

Design notes for this network (core -> fiber/airFiber -> island MikroTik -> Huawei OLT -> ONT PPPoE):
* Island routers are the PPPoE servers (NAS). Customer sessions join interface list CUSTOMER via
  the PPP profile, so every rule can say "from customers" without listing dynamic <pppoe-...> ifaces.
* No FastTrack: fasttracked packets skip the simple queues RADIUS creates for Mikrotik-Rate-Limit,
  so plan speeds would stop being enforced.
* Management (SSH/Winbox/REST/SNMP) is reachable only from the MGMT/NMS address lists. A mistake
  here locks you out of a remote island, so apply via the change workflow (auto-rollback armed).
"""
import ipaddress
import re
from dataclasses import dataclass, field

TAG = "isp-platform"
NAME_RE = re.compile(r"^[A-Za-z0-9._/-]{1,40}$")
SECRET_RE = re.compile(r"^[A-Za-z0-9._@#%+=-]{8,64}$")

# Ports botnets scan for on customer CPE/ONTs (Mirai and friends): telnet, TR-069, SMB, NetBIOS, RPC.
CPE_ATTACK_TCP = "23,2323,7547,135,139,445"
# Reflection/amplification sources that should never be reachable on customer IPs from the internet.
AMPLIFICATION_UDP = "19,137,138,1900,11211"
BOGONS = ["0.0.0.0/8", "10.0.0.0/8", "100.64.0.0/10", "127.0.0.0/8", "169.254.0.0/16", "172.16.0.0/12",
          "192.0.0.0/24", "192.0.2.0/24", "192.168.0.0/16", "198.18.0.0/15", "198.51.100.0/24",
          "203.0.113.0/24", "224.0.0.0/4", "240.0.0.0/4"]


@dataclass
class FirewallInput:
    role: str                                  # core_router | island_router
    mgmt_networks: list[str]                   # NOC / jump-host subnets allowed to manage the router
    nms_addresses: list[str]                   # this platform's IPs (REST + SNMP polling)
    uplink_interfaces: list[str]               # toward core (island) or toward internet (core)
    backhaul_interfaces: list[str] = field(default_factory=list)  # links to other MikroTiks (core)
    customer_interfaces: list[str] = field(default_factory=list)  # OLT-facing ifaces/VLANs (island)
    mgmt_interfaces: list[str] = field(default_factory=list)      # out-of-band / NOC-facing ports
    customer_pools: list[str] = field(default_factory=list)       # PPPoE address pools (anti-spoofing)
    radius_servers: list[str] = field(default_factory=list)
    portal_ip: str | None = None               # payment page for suspended customers
    dns_cache: bool = True                     # router answers DNS for customers
    routing_protocol: str = "ospf"             # ospf | bgp | none
    snmp_community: str | None = None
    block_smtp_from_customers: bool = True
    isolate_customers: bool = True
    customers_have_public_ip: bool = False
    # Island PPPoE server + RADIUS client section
    pppoe_service_name: str = "isp"
    radius_secret: str | None = None
    radius_src_address: str | None = None
    radius_auth_port: int = 1812               # match RADIUS_AUTH_PORT / RADIUS_ACCT_PORT in the platform .env
    radius_acct_port: int = 1813
    local_address: str | None = None           # PPP profile local-address (router side)

    def validate(self):
        if self.role not in ("core_router", "island_router"):
            raise ValueError("role must be core_router or island_router")
        if not self.mgmt_networks:
            raise ValueError("At least one management network is required, or you will lock yourself out")
        if not self.uplink_interfaces:
            raise ValueError("At least one uplink interface is required")
        for n in self.mgmt_networks + self.customer_pools:
            ipaddress.ip_network(n, strict=False)
        for a in self.nms_addresses + self.radius_servers + [x for x in (self.portal_ip, self.radius_src_address, self.local_address) if x]:
            ipaddress.ip_address(a)
        for name in (self.uplink_interfaces + self.backhaul_interfaces + self.customer_interfaces
                     + self.mgmt_interfaces + [self.pppoe_service_name]):
            if not NAME_RE.match(name):
                raise ValueError(f"Bad interface/name: {name!r}")
        if self.snmp_community and not SECRET_RE.match(self.snmp_community):
            raise ValueError("SNMP community must be 8-64 chars of letters, digits and ._@#%+=-")
        if self.snmp_community and self.snmp_community.lower() in ("public", "private"):
            raise ValueError("Do not use public/private as the SNMP community")
        if self.radius_secret and not SECRET_RE.match(self.radius_secret):
            raise ValueError("RADIUS secret must be 8-64 chars of letters, digits and ._@#%+=-")
        for port in (self.radius_auth_port, self.radius_acct_port):
            if not isinstance(port, int) or not 1 <= port <= 65535:
                raise ValueError("RADIUS ports must be 1-65535")
        if self.routing_protocol not in ("ospf", "bgp", "none"):
            raise ValueError("routing_protocol must be ospf, bgp or none")
        if self.role == "island_router" and not self.customer_interfaces:
            raise ValueError("Island routers need the OLT-facing customer interface(s)")


def _addrs(items):
    return ",".join(items)


def generate(cfg: FirewallInput) -> str:
    cfg.validate()
    island = cfg.role == "island_router"
    mgmt_and_nms = cfg.mgmt_networks + cfg.nms_addresses
    L = []
    add = L.append

    add(f"# {TAG}: {cfg.role} hardening + firewall (RouterOS v7)")
    add("# Apply through the platform change workflow: it saves a backup and arms an auto-restore first.")
    add("# Re-running is safe: everything tagged comment=" + TAG + " is replaced.")
    add("# Rules are appended after any existing untagged rules: remove old catch-all drops first or they win.")
    add("")
    add("# ---------- clean previous run")
    for menu in ("/ip firewall filter", "/ip firewall raw", "/ip firewall nat", "/ip firewall mangle",
                 "/ip firewall address-list", "/interface list member"):
        add(f'{menu} remove [find where comment~"^{TAG}"]')
    add("")
    add("# ---------- interface lists")
    add("/interface list")
    lists = ["MGMT", "UPLINK", "CUSTOMER"] + (["BACKHAUL"] if cfg.backhaul_interfaces else []) + (["INTERNET"] if not island else [])
    for name in lists:
        add(f':if ([:len [find name={name}]] = 0) do={{ add name={name} comment="{TAG}" }}')
    add("/interface list member")
    members = [("UPLINK", i) for i in cfg.uplink_interfaces] + [("BACKHAUL", i) for i in cfg.backhaul_interfaces] \
        + [("CUSTOMER", i) for i in cfg.customer_interfaces] + [("MGMT", i) for i in cfg.mgmt_interfaces]
    if not island:
        members += [("INTERNET", i) for i in cfg.uplink_interfaces]
    for lst, iface in members:
        add(f'add list={lst} interface={iface} comment="{TAG}"')
    add("")
    add("# ---------- address lists")
    add("/ip firewall address-list")
    for lst, items in (("mgmt", cfg.mgmt_networks), ("nms", cfg.nms_addresses), ("radius-servers", cfg.radius_servers),
                       ("customer-pools", cfg.customer_pools), ("walled-garden", [cfg.portal_ip] if cfg.portal_ip else [])):
        for a in items:
            add(f'add list={lst} address={a} comment="{TAG}"')
    if not island:
        for b in BOGONS:
            add(f'add list=bogons address={b} comment="{TAG}"')
    add("")

    add("# ---------- services: only SSH, Winbox and REST (www-ssl), only from management")
    add("/ip service")
    for svc in ("telnet", "ftp", "www", "api", "api-ssl"):
        add(f"set {svc} disabled=yes")
    add(f"set ssh address={_addrs(cfg.mgmt_networks)} disabled=no")
    add(f"set winbox address={_addrs(cfg.mgmt_networks)} disabled=no")
    add(f"set www-ssl address={_addrs(mgmt_and_nms)}")
    add("/ip ssh set strong-crypto=yes")
    add("/tool mac-server set allowed-interface-list=none")
    add("/tool mac-server mac-winbox set allowed-interface-list=MGMT")
    add("/tool mac-server ping set enabled=no")
    add("/ip neighbor discovery-settings set discover-interface-list=MGMT")
    add("/tool bandwidth-server set enabled=no")
    add("/ip socks set enabled=no")
    add("/ip proxy set enabled=no")
    add("/ip upnp set enabled=no")
    add("/ip cloud set ddns-enabled=no update-time=no")
    add("/ip settings set tcp-syncookies=yes rp-filter=loose")
    add(f"/ip dns set allow-remote-requests={'yes' if cfg.dns_cache else 'no'}")
    if cfg.snmp_community:
        add(f'/snmp community set [find default=yes] name={cfg.snmp_community} addresses={_addrs(cfg.nms_addresses or cfg.mgmt_networks)}')
        add("/snmp set enabled=yes")
    if cfg.radius_servers:
        add("/radius incoming set accept=yes port=3799")
    add("")

    add("# ---------- RAW: drop junk before connection tracking (cheap on CPU during floods)")
    add("/ip firewall raw")
    add(f'add chain=prerouting action=drop src-address-list=blocklist comment="{TAG}: blocklisted (brute force / port scan)"')
    if not island:
        add(f'add chain=prerouting action=drop in-interface-list=INTERNET src-address-list=bogons comment="{TAG}: bogon source from internet"')
    if cfg.customer_pools:
        add(f'add chain=prerouting action=drop in-interface-list=CUSTOMER src-address-list=!customer-pools '
            f'comment="{TAG}: BCP38 anti-spoofing, customers may only use their own pool"')
    add("")

    add("# ---------- INPUT: traffic to the router itself")
    add("/ip firewall filter")
    f = lambda rule: add(f'add {rule}')  # noqa: E731
    f(f'chain=input action=accept connection-state=established,related,untracked comment="{TAG}: established"')
    f(f'chain=input action=drop connection-state=invalid comment="{TAG}: invalid"')
    f(f'chain=input action=accept protocol=icmp limit=50,100:packet comment="{TAG}: ICMP rate limited"')
    f(f'chain=input action=drop protocol=icmp comment="{TAG}: ICMP over limit"')
    # Port-scan detection from anywhere but our own management.
    f(f'chain=input action=add-src-to-address-list address-list=blocklist address-list-timeout=1d protocol=tcp '
      f'psd=21,3s,3,1 src-address-list=!mgmt comment="{TAG}: port scanner -> blocklist"')
    # Staged brute-force detection on management ports (NMS polls REST constantly, so it is exempt).
    mports = "22,8291,443"
    f(f'chain=input action=add-src-to-address-list address-list=blocklist address-list-timeout=1d protocol=tcp dst-port={mports} '
      f'connection-state=new src-address-list=bf-stage3 comment="{TAG}: brute force -> blocklist"')
    for src, dst in (("bf-stage2", "bf-stage3"), ("bf-stage1", "bf-stage2")):
        f(f'chain=input action=add-src-to-address-list address-list={dst} address-list-timeout=1m protocol=tcp dst-port={mports} '
          f'connection-state=new src-address-list={src} comment="{TAG}: brute force stage"')
    f(f'chain=input action=add-src-to-address-list address-list=bf-stage1 address-list-timeout=1m protocol=tcp dst-port={mports} '
      f'connection-state=new src-address-list=!nms comment="{TAG}: brute force stage"')
    f(f'chain=input action=accept protocol=tcp dst-port=22,8291 src-address-list=mgmt comment="{TAG}: SSH/Winbox from mgmt"')
    f(f'chain=input action=accept protocol=tcp dst-port=443 src-address-list=mgmt comment="{TAG}: REST from mgmt"')
    f(f'chain=input action=accept protocol=tcp dst-port=443 src-address-list=nms comment="{TAG}: REST from NMS"')
    f(f'chain=input action=accept protocol=udp dst-port=161 src-address-list=nms comment="{TAG}: SNMP from NMS"')
    if cfg.radius_servers:
        f(f'chain=input action=accept protocol=udp dst-port=3799 src-address-list=radius-servers comment="{TAG}: RADIUS CoA/Disconnect"')
    if cfg.routing_protocol == "ospf":
        # Core: OSPF only toward the islands, never on the internet uplink.
        if island:
            f(f'chain=input action=accept protocol=ospf in-interface-list=UPLINK comment="{TAG}: OSPF on uplink"')
        if cfg.backhaul_interfaces:
            f(f'chain=input action=accept protocol=ospf in-interface-list=BACKHAUL comment="{TAG}: OSPF on backhaul"')
    elif cfg.routing_protocol == "bgp":
        f(f'chain=input action=accept protocol=tcp dst-port=179 in-interface-list=UPLINK comment="{TAG}: BGP on uplink"')
        if cfg.backhaul_interfaces:
            f(f'chain=input action=accept protocol=tcp dst-port=179 in-interface-list=BACKHAUL comment="{TAG}: BGP on backhaul"')
    # Customers reach an island router directly, and the core through the backhaul.
    served = ["CUSTOMER"] + (["BACKHAUL"] if not island and cfg.backhaul_interfaces else [])
    for lst in served:
        if cfg.dns_cache:
            for proto in ("udp", "tcp"):
                f(f'chain=input action=accept protocol={proto} dst-port=53 in-interface-list={lst} comment="{TAG}: DNS for customers"')
        f(f'chain=input action=accept protocol=udp dst-port=123 in-interface-list={lst} comment="{TAG}: NTP for customers"')
    f(f'chain=input action=drop comment="{TAG}: drop everything else to the router (incl. open-resolver DNS from uplink)"')
    add("")

    add("# ---------- FORWARD: traffic through the router (no FastTrack - it bypasses RADIUS rate limits)")
    f(f'chain=forward action=accept connection-state=established,related,untracked comment="{TAG}: established"')
    f(f'chain=forward action=drop connection-state=invalid comment="{TAG}: invalid"')
    if cfg.portal_ip:
        f(f'chain=forward action=accept src-address-list=suspended dst-address-list=walled-garden comment="{TAG}: suspended -> payment portal"')
        f(f'chain=forward action=accept src-address-list=suspended protocol=udp dst-port=53 comment="{TAG}: suspended -> DNS"')
        f(f'chain=forward action=reject reject-with=icmp-admin-prohibited src-address-list=suspended comment="{TAG}: suspended customers"')
    # Toward customers: CUSTOMER on an island; on the core, the backhaul (drop junk before it uses airFiber capacity).
    toward = "CUSTOMER" if island or not cfg.backhaul_interfaces else "BACKHAUL"
    f(f'chain=forward action=drop protocol=tcp dst-port={CPE_ATTACK_TCP} in-interface-list=UPLINK out-interface-list={toward} '
      f'comment="{TAG}: protect ONTs/CPE from botnet scanning (telnet, TR-069, SMB)"')
    f(f'chain=forward action=drop protocol=udp dst-port={AMPLIFICATION_UDP} in-interface-list=UPLINK out-interface-list={toward} '
      f'comment="{TAG}: block reflection/amplification probes to customers"')
    if cfg.isolate_customers:
        f(f'chain=forward action=drop in-interface-list=CUSTOMER out-interface-list=CUSTOMER comment="{TAG}: customer-to-customer isolation (worm spread)"')
    if cfg.block_smtp_from_customers:
        f(f'chain=forward action=drop protocol=tcp dst-port=25 in-interface-list=CUSTOMER comment="{TAG}: block outbound SMTP (spam bots)"')
    f(f'chain=forward action=drop protocol=tcp tcp-flags=syn connection-state=new connection-limit=400,32 in-interface-list=CUSTOMER '
      f'comment="{TAG}: per-customer connection cap (infected hosts / floods)"')
    f(f'chain=forward action=accept in-interface-list=CUSTOMER comment="{TAG}: customers out"')
    if not island and cfg.backhaul_interfaces:
        f(f'chain=forward action=accept in-interface-list=BACKHAUL comment="{TAG}: islands out"')
    f(f'chain=forward action=accept in-interface-list=MGMT comment="{TAG}: management out"')
    if island:
        f(f'chain=forward action=accept in-interface-list=UPLINK src-address-list=mgmt comment="{TAG}: NOC to OLT/ONT management"')
        f(f'chain=forward action=accept in-interface-list=UPLINK src-address-list=nms comment="{TAG}: NMS to OLT/ONT management"')
    if cfg.customers_have_public_ip:
        f(f'chain=forward action=accept in-interface-list=UPLINK out-interface-list={toward} comment="{TAG}: inbound to public-IP customers"')
    f(f'chain=forward action=accept connection-nat-state=dstnat comment="{TAG}: port forwards"')
    f(f'chain=forward action=drop comment="{TAG}: drop unsolicited inbound"')
    add("")

    if cfg.portal_ip:
        add("# ---------- send suspended customers' web traffic to the payment page")
        add("/ip firewall nat")
        add(f'add chain=dstnat action=dst-nat to-addresses={cfg.portal_ip} to-ports=80 protocol=tcp dst-port=80 '
            f'src-address-list=suspended dst-address-list=!walled-garden comment="{TAG}: suspended -> portal"')
        add("")

    if island and cfg.radius_servers:
        add("# ---------- PPPoE server + RADIUS (island NAS)")
        if not cfg.radius_secret:
            add("# radius_secret not given: add /radius entries by hand")
        else:
            src = f" src-address={cfg.radius_src_address}" if cfg.radius_src_address else ""
            src += f" authentication-port={cfg.radius_auth_port} accounting-port={cfg.radius_acct_port}"
            add(f'/radius remove [find where comment="{TAG}"]')
            for r in cfg.radius_servers:
                add(f'/radius add service=ppp address={r} secret="{cfg.radius_secret}"{src} timeout=3s comment="{TAG}"')
        add("/ppp aaa set use-radius=yes accounting=yes interim-update=5m")
        local = f" local-address={cfg.local_address}" if cfg.local_address else ""
        add(f':if ([:len [/ppp profile find name={TAG}]] = 0) do={{ /ppp profile add name={TAG} }}')
        dns = f" dns-server={cfg.local_address}" if cfg.local_address and cfg.dns_cache else ""
        add(f"/ppp profile set [find name={TAG}]{local}{dns} interface-list=CUSTOMER only-one=yes change-tcp-mss=yes use-encryption=no")
        for iface in cfg.customer_interfaces:
            add(f':if ([:len [/interface pppoe-server server find interface={iface}]] = 0) do={{ '
                f'/interface pppoe-server server add interface={iface} service-name={cfg.pppoe_service_name} '
                f'default-profile={TAG} authentication=chap,mschap2 one-session-per-host=yes max-mtu=1492 max-mru=1492 disabled=no }}')
        add("")

    add(f':log info "{TAG}: firewall applied"')
    return "\n".join(line for line in L if line is not None) + "\n"


# ---------------------------------------------------------------- audit
def audit(snap: dict) -> list[dict]:
    """Read-only checks against MikroTik.firewall_snapshot(). Each finding: severity, check, detail."""
    out = []

    def finding(severity, check, detail):
        out.append({"severity": severity, "check": check, "detail": detail})

    services = {s.get("name"): s for s in snap.get("services") or [] if isinstance(s, dict)}
    for name in ("telnet", "ftp", "www", "api"):
        s = services.get(name)
        if s and s.get("disabled") == "false":
            finding("critical" if name in ("telnet", "ftp") else "warning", f"service:{name}",
                    f"{name} is enabled (plaintext). Disable it.")
    for name in ("ssh", "winbox", "www-ssl", "api-ssl"):
        s = services.get(name)
        if s and s.get("disabled") == "false" and s.get("address", "") in ("", "0.0.0.0/0"):
            finding("critical", f"service:{name}:open", f"{name} accepts connections from any address. Restrict to management networks.")

    for u in snap.get("users") or []:
        if isinstance(u, dict) and u.get("name") == "admin" and u.get("disabled") == "false":
            finding("warning", "user:admin", "Default 'admin' user is enabled. Create named users and disable admin.")

    dns = snap.get("dns") or {}
    filters = [r for r in (snap.get("filter") or []) if isinstance(r, dict) and r.get("disabled") != "true"]
    input_rules = [r for r in filters if r.get("chain") == "input"]
    if isinstance(dns, dict) and dns.get("allow-remote-requests") == "true":
        if not any(r.get("action") == "drop" and not r.get("protocol") and not r.get("dst-port") for r in input_rules):
            finding("critical", "dns:open-resolver", "DNS answers remote requests and input chain has no final drop: open resolver used for DDoS amplification.")
    if not input_rules:
        finding("critical", "firewall:input-empty", "No input firewall rules. The router itself is exposed.")
    elif input_rules[-1].get("action") != "drop":
        finding("critical", "firewall:input-no-final-drop", "Input chain does not end with a drop rule.")
    if not any(r.get("connection-state", "").find("invalid") >= 0 for r in filters):
        finding("warning", "firewall:invalid", "No rule drops connection-state=invalid.")
    if any(r.get("action") == "fasttrack-connection" for r in filters):
        finding("warning", "firewall:fasttrack", "FastTrack is on: it bypasses the simple queues RADIUS uses for plan speeds.")
    if not any("psd" in r for r in filters):
        finding("info", "firewall:no-portscan", "No port-scan detection (psd) rule.")

    for c in snap.get("snmp_communities") or []:
        if isinstance(c, dict) and c.get("name") in ("public", "private") and c.get("disabled") != "true":
            finding("critical", "snmp:default-community", f"SNMP community '{c.get('name')}' is active. Rename and restrict by address.")
        elif isinstance(c, dict) and c.get("addresses", "") in ("", "::/0", "0.0.0.0/0"):
            finding("warning", "snmp:open", f"SNMP community '{c.get('name')}' allows any address.")

    for key, label in (("mac_server", "MAC telnet"), ("mac_winbox", "MAC winbox")):
        v = snap.get(key) or {}
        if isinstance(v, dict) and v.get("allowed-interface-list") == "all":
            finding("warning", f"{key}:all", f"{label} is allowed on all interfaces (incl. customer-facing).")
    nd = snap.get("neighbor") or {}
    if isinstance(nd, dict) and nd.get("discover-interface-list") == "all":
        finding("warning", "neighbor:all", "Neighbor discovery runs on all interfaces; customers can see router identity/version.")
    for key, label in (("socks", "SOCKS proxy"), ("proxy", "Web proxy")):
        v = snap.get(key) or {}
        if isinstance(v, dict) and v.get("enabled") == "true":
            finding("critical", f"{key}:enabled", f"{label} is enabled (common malware abuse on MikroTik).")
    bw = snap.get("bandwidth_server") or {}
    if isinstance(bw, dict) and bw.get("enabled") == "true":
        finding("info", "bandwidth-server", "Bandwidth test server is enabled.")
    ips = snap.get("ip_settings") or {}
    if isinstance(ips, dict) and ips.get("tcp-syncookies") == "false":
        finding("info", "tcp-syncookies", "TCP SYN cookies are off.")

    version = (snap.get("resource") or {}).get("version", "") if isinstance(snap.get("resource"), dict) else ""
    m = re.match(r"(\d+)\.(\d+)", version or "")
    if m and int(m.group(1)) < 7:
        finding("warning", "routeros:v6", f"RouterOS {version}: v6 is end of life and has no REST API. Plan an upgrade to v7 long-term.")
    if not out:
        finding("info", "ok", "No issues found by the automated checks.")
    order = {"critical": 0, "warning": 1, "info": 2}
    return sorted(out, key=lambda x: order[x["severity"]])
