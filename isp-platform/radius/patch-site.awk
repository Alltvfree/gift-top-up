# Patches a stock FreeRADIUS 3.2 site file at image build time:
#  1. drop `listen { ... ipv6addr = ... }` blocks (NAS talk IPv4; avoids bind failures on IPv6-less hosts)
#  2. enable `sql` in `session { }` so Simultaneous-Use is enforced from radacct (one PPPoE login per account)
/^listen[ \t]*\{/ { buf = $0 "\n"; code = ""; depth = 1; inblk = 1; next }
inblk {
	buf = buf $0 "\n"
	line = $0; sub(/#.*/, "", line); code = code line "\n"
	depth += gsub(/\{/, "{", line) - gsub(/\}/, "}", line)
	if (depth == 0) { if (code !~ /ipv6addr[ \t]*=/) printf "%s", buf; inblk = 0 }
	next
}
/^session[ \t]*\{/ { insession = 1 }
insession && /^\}/ { insession = 0 }
insession && /^#[ \t]*sql[ \t]*$/ { print "\tsql"; next }
{ print }
