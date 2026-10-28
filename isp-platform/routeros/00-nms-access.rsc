# One-time, per MikroTik (RouterOS v7.1+). Paste into a Winbox terminal opened in SAFE MODE (Ctrl+X).
# If the Winbox terminal garbles a long paste, run the commands inside { } one line at a time instead.
# Lets the ISP platform poll the router and apply reviewed changes over the REST API.
# Replace before pasting:  NMS_IP = the platform server, MGMT_NET = your NOC/VPN subnet, STRONG_PASSWORD.
# Everything runs as one block so the :local variables stay defined.
{
  :local nms "NMS_IP"
  :local mgmt "MGMT_NET"

  # 1. TLS certificate for the REST API (www-ssl), signed by a local CA. RouterOS 7.1x refuses to
  #    self-sign a plain server certificate ("failure: CA not found"), so make the CA first.
  :if ([:len [/certificate find name=isp-ca]] = 0) do={
    /certificate add name=isp-ca common-name=isp-ca days-valid=3650 key-usage=key-cert-sign,crl-sign
    /certificate sign isp-ca
    :delay 10s
  }
  :if ([:len [/certificate find name=isp-rest]] = 0) do={
    /certificate add name=isp-rest common-name=[/system identity get name] days-valid=3650 key-usage=digital-signature,key-encipherment,tls-server
    /certificate sign isp-rest ca=isp-ca
    :delay 10s
  }

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
