# Browser sandbox template: Playwright for Python and Node with one pinned
# Chromium, so an agent can take a screenshot or drive a page without
# downloading a browser first — which a deny-by-default egress policy would
# not allow anyway. Everything else comes from sandbox-ubuntu.
ARG BASE_IMAGE=non-existing
FROM ${BASE_IMAGE}

SHELL ["/bin/bash", "-o", "pipefail", "-c"]

USER root

ARG DEBIAN_FRONTEND=noninteractive

# One version for both bindings: they share a browser only when their
# browsers.json agree, and a mismatch would bake a second Chromium.
ARG PLAYWRIGHT_VERSION=1.63.0

# Outside the home directory and root-owned, so a sandbox cannot leave itself
# without a browser, and both bindings resolve the same one.
ENV PLAYWRIGHT_BROWSERS_PATH=/ms-playwright

# Both bindings ship a `playwright` launcher in /usr/local/bin. npm's is a
# symlink into its package, so it goes before pip runs — pip could otherwise
# write through it and clobber Node's cli.js. Same version, same CLI either way.
#
# /node_modules makes the global install resolvable from any script, because
# Node walks parent directories for it. NODE_PATH would only cover require(),
# not `import`, and a project's own node_modules still takes precedence.
RUN npm install --global --no-fund --no-audit "playwright@${PLAYWRIGHT_VERSION}" && \
    npm cache clean --force && \
    ln -s /usr/local/lib/node_modules /node_modules && \
    rm /usr/local/bin/playwright && \
    pip install --no-cache-dir "playwright==${PLAYWRIGHT_VERSION}"

# Playwright's own dependency set for 26.04: Chromium's shared libraries plus
# the fonts its screenshots are tested with — IPA Gothic and WenQuanYi Zen Hei
# for CJK, Noto Color Emoji — so pages render without tofu. Following it
# rather than hand-listing packages keeps a version bump self-contained.
RUN playwright install --with-deps chromium && \
    chmod -R a+rX "${PLAYWRIGHT_BROWSERS_PATH}" && \
    apt-get clean && \
    rm -rf /var/lib/apt/lists/*

USER user
WORKDIR /home/user
