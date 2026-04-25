FROM nginx:alpine

# Static-only frontend that talks to the SwarmUI API on host port 7801.
# Files are bind-mounted via compose so edits apply without a rebuild.
COPY image-gen-ui/static /usr/share/nginx/html
COPY image-gen-ui/nginx.conf /etc/nginx/conf.d/default.conf

EXPOSE 7802
