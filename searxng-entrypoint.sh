#!/bin/sh
set -eu

template=/etc/searxng/settings.template.yml
target=/etc/searxng/settings.yml
placeholder=__BRAVE_SEARCH_API_KEY__

: "${SEARXNG_SECRET:?SEARXNG_SECRET is required}"
case "$SEARXNG_SECRET" in
    *[!A-Za-z0-9_-]*)
        echo "SEARXNG_SECRET contains unexpected characters" >&2
        exit 1
        ;;
esac

if [ -z "${BRAVE_SEARCH_API_KEY:-}" ]; then
    echo "BRAVE_SEARCH_API_KEY is required" >&2
    exit 1
fi

case "$BRAVE_SEARCH_API_KEY" in
    *[!A-Za-z0-9_-]*)
        echo "BRAVE_SEARCH_API_KEY contains unexpected characters" >&2
        exit 1
        ;;
esac

sed -e "s/$placeholder/$BRAVE_SEARCH_API_KEY/g" \
    -e "s/__SEARXNG_SECRET__/$SEARXNG_SECRET/g" "$template" > "$target"
chmod 600 "$target"

exec /usr/local/searxng/entrypoint.sh
