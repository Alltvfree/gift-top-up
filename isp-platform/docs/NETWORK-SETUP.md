# Network setup — core, islands, airFiber, Huawei OLT, ONT

Your path: **FreeRADIUS (core) ← core MikroTik → fiber / airFiber → island MikroTik (PPPoE server) → Huawei OLT → ONT (PPPoE client)**.
Roll out to one island first, then the rest.

## 0. Platform server
* Ubuntu VM in the core, on the management network, with routes to every island's management subnet.
* `cp .env.example .env`, fill every value (generate `APP_SECRET_KEY` and **back it up** — it decrypts all stored device passwords).
* `./scripts/make-selfsigned-cert.sh noc.example.local` (or put your internal CA cert in `certs/`).
* Edit `frontend/allowlist.conf` to your NOC/VPN ranges.
* `docker compose up --build -d`, then create the first admin:
  `docker compose exec api python -m app.cli create-admin yourname`
* Create a second admin: config changes need a *different* admin to approve (four-eyes).

## 1. RADIUS
* FreeRADIUS runs in the `radius` container on UDP 1812/1813 and reads the same database.
* For each island router add a **NAS** under *RADIUS → Add NAS*: the router's RADIUS source IP and a unique 12+ char secret.
  Restart FreeRADIUS after adding NAS clients: `docker compose restart radius`.
* What subscribers get:
  * active → plan speed via `Mikrotik-Rate-Limit` (e.g. `10M/50M` = 10 up / 50 down)
  * suspended → `256k/256k` + address-list `suspended` → redirected to your payment portal
  * pending / wrong password / already online elsewhere → reject (`Simultaneous-Use := 1`)
* Suspend/activate/plan change sends a RADIUS Disconnect to the island router so it applies immediately.
  CoA packets leave from the platform host's IP: that IP must be the RADIUS server address configured on the router.

## 2. MikroTik (core and every island)
1. Paste `routeros/00-nms-access.rsc` (edit placeholders) in a Safe-Mode terminal.
2. Add the router under *Devices* with the `isp-nms` login. Polling starts within a minute (ping, CPU, memory, PPPoE count, down interfaces).
3. *Device → Security audit*: lists telnet/FTP/API exposure, open DNS resolver, default `admin`, SNMP `public`, SOCKS/proxy, FastTrack, missing final drop, etc.
4. *Security*: generate the firewall/hardening script for the router's role. Choosing a device creates a change request; after a second admin approves, *Apply* does:
   backup + export → arm a scheduler that restores the backup in `COMMIT_CONFIRM_MINUTES` (default 5) → run script →
   if the platform can still ping the router, disarm. **If the change cuts you off, the router restores itself.**
   Test this once on a lab router before trusting it on a remote island.
5. Island routers: the generator also sets up the PPPoE server on the OLT-facing VLAN with RADIUS, accounting (interim 5 min), and the `CUSTOMER` interface list via the PPP profile.

> No FastTrack on PPPoE routers: it bypasses the queues RADIUS creates, so plan speeds stop working.

## 3. airFiber backhaul
* Enable SNMP v2c (or v3) on each radio, restricted to the platform IP, with a non-default community.
* Add the radio as *vendor Ubiquiti, role backhaul* with the SNMP community. Uptime and reachability work out of the box.
* Radio-specific values (capacity, RSSI) vary by model/firmware. Find them with
  `snmpwalk -v2c -c <community> <radio-ip> 1.3.6.1.4.1.41112`, then set `AIRFIBER_OIDS` in `.env`. Don't guess OIDs.
* Add a *Backhaul link* (side A = core-side device, side B = island-side device). Link status follows both ends.

## 4. Huawei OLT (MA5608T / MA5683T / MA5800)
* Create a dedicated SSH user on the OLT; disable telnet; restrict SSH with an ACL to the platform/NOC IPs.
* Get the OLT's SSH host key fingerprint **from the console**, and paste it (`SHA256:...`) in the device's *Pinned SSH host key*.
  The platform refuses to connect to an OLT whose key is unknown or has changed.
* Device settings JSON: `{"gpon_slots": [1]}` — the GPON board slot(s) to scan.
* Every `OLT_POLL_EVERY_N` cycles the worker reads ONT state and optical levels; ONT Rx below `ONT_LOW_RX_DBM` (−27) raises an alert.
* *Smart OLT → Autofind* lists unregistered ONTs; *Provision* builds a change request:
  ```
  interface gpon 0/1
  ont add 3 5 sn-auth "48575443A1B2C3D4" omci ont-lineprofile-id 10 ont-srvprofile-id 10 desc "A1001"
  ont ipconfig 3 5 ip-index 0 pppoe vlan 100 priority 0 user-account username "a1001.hdh" password "..."
  ont internet-config 3 5 ip-index 0
  quit
  service-port vlan 100 gpon 0/1/3 ont 5 gemport 1 multi-service user-vlan 100 tag-transform translate
  ```
  with a rollback (`undo service-port`, `ont delete`). Line/service profiles and the VLAN must already exist on the OLT.
  CLI syntax differs across firmware: run one provisioning by hand, compare, and adjust `app/adapters/huawei.py` if needed.

## 5. Alerts
Set `ALERT_WEBHOOK_URL` to any endpoint that accepts `{"text": "..."}` (Slack/Mattermost/Teams, or a small Telegram/Viber bridge).
