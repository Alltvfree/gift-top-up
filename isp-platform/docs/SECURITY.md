# Security model

## Platform
| Threat | Control |
|---|---|
| Password guessing / credential stuffing | scrypt hashes; 5 failures lock an account 15 min; 20 failures from one IP in 15 min → 429; nginx `limit_req` 5/min on login; identical error and timing for unknown users |
| Session theft / CSRF | random 256-bit token, stored hashed, HttpOnly + Secure + SameSite=Strict cookie, plus required `X-Requested-With` header on writes; sessions revoked on password change / disable |
| XSS | strict CSP (`script-src 'self'`, no inline JS), all output escaped |
| Bots / scanners | nginx allowlist (NOC/VPN only), scanner user-agent drop, per-IP request and connection limits, method allowlist, small body size, short timeouts |
| Insider mistakes | roles (admin / noc / billing / support), four-eyes approval for every router/OLT change, full audit log |
| Stolen database dump | device passwords encrypted with `APP_SECRET_KEY` (Fernet); RADIUS uses a separate least-privilege DB role |
| Router lockout on a remote island | commit-confirm: backup + auto-restore scheduler armed before every MikroTik change |
| OLT man-in-the-middle | pinned SSH host keys, never trust-on-first-use |

Known gaps to close before calling it production: MFA for admins, off-site encrypted DB backups with restore tests,
HA for RADIUS (second FreeRADIUS on another island/site), log shipping, and SNMPv3 instead of v2c.
PPPoE passwords stay in `radcheck` as cleartext because CHAP/MS-CHAPv2 need them; protect the database accordingly.

## Network (generated RouterOS firewall)
* Management (SSH, Winbox, REST, SNMP) only from your management networks and the platform; telnet/FTP/HTTP/API off.
* Brute-force (staged address lists) and port-scan (PSD) sources go to a 1-day blocklist dropped in RAW.
* BCP38: customers can only send from their own pool; bogons dropped at the internet edge.
* ONTs/CPE are shielded from internet scans of telnet, TR-069 (7547), SMB, NetBIOS — the Mirai-family targets.
* Amplification probes (SSDP, memcached, chargen, NetBIOS) to customers dropped; DNS answers only customers (no open resolver).
* Customer-to-customer traffic blocked (stops worm spread); outbound SMTP blocked (spam bots);
  per-customer new-connection cap (infected hosts / floods); TCP SYN cookies on.
* MAC-Winbox, neighbour discovery limited to the MGMT interface list; SOCKS, proxy, UPnP, bandwidth-test, cloud DDNS off.

Volumetric DDoS against your internet uplink cannot be filtered on the island routers; that needs your upstream's
blackholing/scrubbing service (ask your transit provider for RTBH communities).
