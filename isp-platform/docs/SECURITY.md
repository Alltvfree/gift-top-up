# Security model

## Platform
| Threat | Control |
|---|---|
| Stolen admin password | Two-factor sign-in (TOTP authenticator app) mandatory for admins (`MFA_REQUIRED_ROLES`), optional for others. An admin who hasn't enrolled can only enrol until they do. Codes are single-use (replay-protected); 5 wrong codes kill the sign-in attempt and count toward the account lock. 10 single-use recovery codes; another admin (or `app.cli reset-mfa` on the server) can reset a lost phone. Secrets are encrypted at rest. |
| Password guessing / credential stuffing | scrypt hashes; 5 failures lock an account 15 min; 20 failures from one IP in 15 min → 429; nginx `limit_req` 5/min on login; identical error and timing for unknown users |
| Session theft / CSRF | random 256-bit token, stored hashed, HttpOnly + Secure + SameSite=Strict cookie, plus required `X-Requested-With` header on writes; sessions revoked on password change / disable |
| XSS | strict CSP (`script-src 'self'`, no inline JS), all output escaped |
| Bots / scanners | nginx allowlist (NOC/VPN only), scanner user-agent drop, per-IP request and connection limits, method allowlist, small body size, short timeouts |
| Insider mistakes | roles (admin / noc / billing / support), four-eyes approval for every router/OLT change, full audit log |
| Stolen database dump | device passwords encrypted with `APP_SECRET_KEY` (Fernet); RADIUS uses a separate least-privilege DB role |
| Router lockout on a remote island | commit-confirm: backup + auto-restore scheduler armed before every MikroTik change |
| OLT man-in-the-middle | pinned SSH host keys, never trust-on-first-use |

First enrolment is trust-on-first-use: whoever first signs in to a new admin account with its password enrols the phone.
Create admin accounts with a strong one-time password and have the person enrol straight away.

Known gaps to close before calling it production: off-site encrypted DB backups with restore tests,
HA for RADIUS (second FreeRADIUS on another island/site), log shipping, and SNMPv3 instead of v2c.
PPPoE passwords stay in `radcheck` as cleartext because CHAP/MS-CHAPv2 need them; protect the database accordingly.

## Threat protection (network-wide blocklist)
Every poll (1 min) the worker reads new `login failure for user … from <IP> via winbox|ssh|api` lines from each
MikroTik's log. A public IP with `THREAT_FAILURES` failures within `THREAT_WINDOW_MIN` is blocked on **all**
MikroTiks for `THREAT_BLOCK_HOURS`; once `THREAT_SUBNET_AFTER` addresses of one /24 are blocked (bots rotating through a
range) the whole /24 is blocked instead. Blocks are pushed to each router's `blocklist` address list, tagged
`isp-block:`; the platform never adds or removes entries without that tag.

Safety rails: private, CGNAT, loopback and documentation ranges are never auto-blocked (an attack from inside raises an
alert instead: infected customer device or misconfigured tool); neither are `THREAT_NEVER_BLOCK`, any device's
management IP or any RADIUS client, even manually; nothing larger than a /16 can be blocked; auto-blocks expire.

A router only *drops* the list if it has a rule for it. The generated firewall includes one; for other routers
*Threat protection → Enable* creates a one-rule change request (four-eyes approval, auto-rollback like any change):
`/ip firewall raw add chain=prerouting action=drop src-address-list=blocklist`.

Blocking addresses is a second line of defence. The first is that Winbox/SSH/API must not answer on WAN at all.

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
