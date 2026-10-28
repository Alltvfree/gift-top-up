FROM freeradius/freeradius-server:3.2.3
COPY radius/mods-enabled-sql /etc/raddb/mods-enabled/sql
COPY radius/patch-site.awk /tmp/patch-site.awk
RUN for f in default inner-tunnel; do \
      awk -f /tmp/patch-site.awk /etc/raddb/sites-available/$f > /tmp/$f && cat /tmp/$f > /etc/raddb/sites-available/$f; \
    done \
 # never log passwords
 && sed -i 's/^\(\s*auth_badpass\s*=\).*/\1 no/; s/^\(\s*auth_goodpass\s*=\).*/\1 no/' /etc/raddb/radiusd.conf \
 && rm /tmp/patch-site.awk /tmp/default /tmp/inner-tunnel
