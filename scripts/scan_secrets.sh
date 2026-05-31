#!/usr/bin/env bash
set -euo pipefail

# Lightweight local secret scanner for staged/working files.
# Uses gitleaks if available, otherwise regex fallback.

REPO_ROOT="$(git rev-parse --show-toplevel 2>/dev/null || pwd)"
cd "$REPO_ROOT"

if command -v gitleaks >/dev/null 2>&1; then
  echo "[scan] Running gitleaks..."
  gitleaks detect --no-git --source . --redact --verbose
  echo "[scan] gitleaks: no leaks found"
  exit 0
fi

echo "[scan] gitleaks not installed, using regex fallback..."
PATTERN='(AKIA[0-9A-Z]{16}|AIza[0-9A-Za-z\-_]{35}|ghp_[A-Za-z0-9]{36,}|github_pat_[A-Za-z0-9_]{20,}|xox[baprs]-[A-Za-z0-9-]+|-----BEGIN (RSA|EC|OPENSSH|DSA|PGP|PRIVATE) KEY-----|password\s*=|passwd\s*=|secret\s*=|token\s*=|api[_-]?key\s*=|Authorization:|Bearer\s+[A-Za-z0-9\-\._~\+\/]+=*)'

mapfile -t FILES < <(git ls-files | grep -Ev '(^docs/.*\.md$|^README\.md$|^CONTRIBUTING\.md$|^SECURITY\.md$|^scripts/scan_secrets\.sh$)')

if ((${#FILES[@]} > 0)) && grep -nEI "$PATTERN" "${FILES[@]}"; then
  echo "[scan] Potential secrets found. Review before commit."
  exit 1
fi

echo "[scan] No obvious secrets found"
