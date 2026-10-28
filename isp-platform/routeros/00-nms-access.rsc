# One-time, per MikroTik (RouterOS v7.1+). Paste into a Winbox terminal opened in SAFE MODE (Ctrl+X).
# Lets the ISP platform poll the router and apply reviewed changes over the REST API.
# Replace before pasting:  NMS_IP = the platform server, MGMT_NET = your NOC/VPN subnet, STRONG_PASSWORD.
# Everything runs as one block so the :local variables stay defined.
{
  :local nms "NMS_IP"
  :local mgmt "MGMT_NET"

  # 1. TLS certificate for the REST API (www-ssl). Self-signed is fine on a private management network.
  /certificate add name=isp-rest common-name=[/system identity get name] days-valid=3650 key-usage=digital-signature,key-encipherment,tls-server
  /certificate sign isp-rest
  :delay 5s

  # 2. Only the platform and the NOC may reach REST; plaintext www stays off.
  /ip service set www-ssl certificate=isp-rest address=($nms . "/32," . $mgmt) disabled=no
  /ip service set www disabled=yes

  # 3. Dedicated platform login, usable only from the platform's IP.
  #    'full' is required to save backups, arm the auto-rollback scheduler and apply approved changes.
  #    For monitoring-only routers use group=read instead.
  /user add name=isp-nms group=full address=($nms . "/32") password="STRONG_PASSWORD" comment="isp-platform"

  # 4. Disconnect / CoA from RADIUS (suspensions take effect immediately)
  /radius incoming set accept=yes port=3799
}

# 5. Then, in the platform: Devices -> Add device (vendor MikroTik, mgmt IP, username isp-nms + password),
#    press "Security audit", and generate the firewall from Security.
