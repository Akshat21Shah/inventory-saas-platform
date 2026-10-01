#!/bin/sh
# Refuse a commit that adds a secret (ADR-055): the `gitleaks` hook in .pre-commit-config.yaml,
# installed by `make setup` (pre-commit install).
# Uses a local gitleaks (brew install gitleaks) or, failing that, its Docker image.
GITLEAKS_IMAGE="zricethezav/gitleaks:v8.30.1"
root="$(git rev-parse --show-toplevel)"
if command -v gitleaks >/dev/null 2>&1; then
  gitleaks git --staged --config "$root/.gitleaks.toml" --redact --no-banner "$root"
elif docker info >/dev/null 2>&1; then
  docker run --rm -v "$root":/repo "$GITLEAKS_IMAGE" \
    git --staged --config /repo/.gitleaks.toml --redact --no-banner /repo
else
  echo "pre-commit: gitleaks isn't available (brew install gitleaks, or start Docker)." >&2
  echo "pre-commit: refusing to commit without a secrets scan." >&2
  exit 1
fi
status=$?
if [ "$status" -ne 0 ]; then
  echo "pre-commit: possible secret in the staged changes (above). Remove it, or if it is a" >&2
  echo "public dev or test value, add its exact value to .gitleaks.toml." >&2
fi
exit "$status"
