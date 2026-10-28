FROM nginx:1.27-alpine
COPY index.html app.css app.js /usr/share/nginx/html/
COPY vendor /usr/share/nginx/html/vendor
COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY allowlist.conf /etc/nginx/allowlist.conf
