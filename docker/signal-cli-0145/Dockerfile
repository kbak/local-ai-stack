# Thin overlay on bbernhard/signal-cli-rest-api that swaps the bundled
# signal-cli for the reviewed upstream 0.14.6 release.
#
# Originally needed because Signal stopped including `serverGuid` in some
# sealed-sender envelopes; signal-cli <=0.14.4.1 throws
# `getServerGuid(...) must not be null` and DROPS every incoming message
# (sends are unaffected). Fixed upstream in signal-cli 0.14.5
# (AsamK/signal-cli#2059, milestone 0.14.5). bbernhard had not shipped an
# image with the fix, so we drop the official JVM dist in ourselves. Keeping
# the overlay makes the deployed signal-cli version explicit and reproducible.
#
# Remove this image and revert docker-compose to the plain bbernhard tag once
# their :latest (or latest-dev) ships signal-cli >=0.14.5.
FROM bbernhard/signal-cli-rest-api:latest-dev

ARG SIGNAL_CLI_VERSION=0.14.6

# The official dist carries its own bin/signal-cli launcher with the correct
# version-pinned classpath and bundles the matching libsignal-client jar
# (native .so self-extracts at runtime), so we just unpack it and repoint the
# launcher symlink. Runs on the base image's JDK.
RUN set -eux; \
    curl -fsSL -o /tmp/signal-cli.tar.gz \
      "https://github.com/AsamK/signal-cli/releases/download/v${SIGNAL_CLI_VERSION}/signal-cli-${SIGNAL_CLI_VERSION}.tar.gz"; \
    tar -xzf /tmp/signal-cli.tar.gz -C /opt; \
    rm -f /tmp/signal-cli.tar.gz; \
    rm -f /usr/bin/signal-cli; \
    ln -s "/opt/signal-cli-${SIGNAL_CLI_VERSION}/bin/signal-cli" /usr/bin/signal-cli; \
    signal-cli --version
