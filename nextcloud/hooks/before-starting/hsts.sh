#!/bin/sh
cat > /etc/apache2/conf-available/hsts.conf << 'CONF'
<IfModule mod_headers.c>
    Header always set Strict-Transport-Security "max-age=15552000; includeSubDomains"
</IfModule>
CONF
a2enconf hsts >/dev/null 2>&1
