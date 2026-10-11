#!/bin/bash
# Installs npm dependencies when a Claude Code cloud session starts,
# so career-ops scripts (doctor, scan, tracker, PDF) work immediately.
set -euo pipefail

# Only run in Claude Code on the web; local machines manage their own deps.
if [ "${CLAUDE_CODE_REMOTE:-}" != "true" ]; then
  exit 0
fi

cd "$CLAUDE_PROJECT_DIR"
# Chromium is preinstalled in the cloud image; skip Playwright's download.
PLAYWRIGHT_SKIP_BROWSER_DOWNLOAD=1 npm install --no-audit --no-fund
