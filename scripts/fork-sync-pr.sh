#!/usr/bin/env bash
#
# Run CI for a pull request from a fork by mirroring it to an internal branch.
#
# CI cannot run on fork PRs: GitHub issues no OIDC token to them, so the JFrog
# auth step (and therefore every dependency install) fails. This script pushes
# the fork PR's head commit to `fork-test/pr-<N>` in databrickslabs/ontos and
# opens a "do not merge" mirror PR, where CI runs with OIDC on the protected
# runners.
#
# SECURITY: the mirrored code runs with this repository's CI credentials
# (the JFrog OIDC token of every job, and LOCKFILE_BOT_TOKEN in the lockfile
# job) on the protected runners. Review the fork PR first, then pass the full
# 40-character SHA of the commit you reviewed so that nothing pushed after
# your review is mirrored. The script refuses PRs that change CI or
# dependency files (see SENSITIVE_PATHS) unless --allow-sensitive-paths is
# given after reviewing those files too.
#
# Usage:
#   scripts/fork-sync-pr.sh [--allow-sensitive-paths] <PR_NUMBER> <REVIEWED_SHA>
#
# Requires push access to databrickslabs/ontos and an authenticated gh CLI.
# Run it again with a new SHA after the fork PR changes; the mirror branch is
# force-updated and the existing mirror PR reused. Close the mirror PR and
# delete its branch once the original PR is merged or closed.
#
# Adapted from databrickslabs/impulse (.github/scripts/fork-sync-pr.sh).
set -euo pipefail

UPSTREAM_REPO="databrickslabs/ontos"

# Files that control what CI runs or installs, or that handle its
# credentials: workflows and actions, CI scripts, and dependency manifests
# and lockfiles. Bash glob patterns matched against each changed path.
SENSITIVE_PATHS=(
  ".github/*"
  "scripts/*"
  "src/scripts/*"
  ".pre-commit-config.yaml"
  "pyproject.toml" "*/pyproject.toml"
  "hatch.toml" "*/hatch.toml"
  "setup.py" "*/setup.py" "setup.cfg" "*/setup.cfg"
  "requirements*" "*/requirements*"
  "package.json" "*/package.json"
  "package-lock.json" "*/package-lock.json"
  ".npmrc" "*/.npmrc"
  "*.lock" "pnpm-lock.yaml" "*/pnpm-lock.yaml"
)

usage() {
  echo "Usage: $0 [--allow-sensitive-paths] <PR_NUMBER> <REVIEWED_SHA>" >&2
  exit 2
}

ALLOW_SENSITIVE=false
if [ "${1:-}" = "--allow-sensitive-paths" ]; then
  ALLOW_SENSITIVE=true
  shift
fi
[ $# -eq 2 ] || usage
PR_NUMBER="$1"
REVIEWED_SHA="$2"
if ! [[ "$PR_NUMBER" =~ ^[0-9]+$ ]]; then
  echo "Error: PR_NUMBER must be a number, got '${PR_NUMBER}'." >&2
  exit 2
fi
# A short SHA could be matched by a different commit crafted to share its
# prefix: require the full SHA.
if ! [[ "$REVIEWED_SHA" =~ ^[0-9a-f]{40}$ ]]; then
  echo "Error: REVIEWED_SHA must be the full 40-character commit SHA, got '${REVIEWED_SHA}'." >&2
  exit 2
fi
SYNC_BRANCH="fork-test/pr-${PR_NUMBER}"

command -v gh >/dev/null || { echo "Error: gh CLI is required." >&2; exit 1; }

# Find the remote that points to the upstream repository, whatever its name.
REMOTE=""
for r in $(git remote); do
  case "$(git remote get-url "$r")" in
    "https://github.com/${UPSTREAM_REPO}" | "https://github.com/${UPSTREAM_REPO}.git" | \
      "git@github.com:${UPSTREAM_REPO}" | "git@github.com:${UPSTREAM_REPO}.git" | \
      "ssh://git@github.com/${UPSTREAM_REPO}" | "ssh://git@github.com/${UPSTREAM_REPO}.git")
      REMOTE="$r"; break ;;
  esac
done
if [ -z "$REMOTE" ]; then
  echo "Error: no git remote points to ${UPSTREAM_REPO}." >&2
  exit 1
fi

read -r IS_FORK HEAD_SHA BASE_REF PR_URL < <(
  gh pr view "$PR_NUMBER" --repo "$UPSTREAM_REPO" \
    --json isCrossRepository,headRefOid,baseRefName,url \
    --jq '"\(.isCrossRepository) \(.headRefOid) \(.baseRefName) \(.url)"'
)
if [ "$IS_FORK" != "true" ]; then
  echo "Error: PR #${PR_NUMBER} is not from a fork; its CI already runs." >&2
  exit 1
fi
# Refuse anything pushed to the fork after the review.
if [ "$HEAD_SHA" != "$REVIEWED_SHA" ]; then
  echo "Error: PR #${PR_NUMBER} head is ${HEAD_SHA}, not the reviewed ${REVIEWED_SHA}." >&2
  echo "Review the new commits, then run again with the new SHA." >&2
  exit 1
fi

# Fetch the PR head without checking anything out.
git fetch --no-tags "$REMOTE" "pull/${PR_NUMBER}/head"
FETCHED_SHA=$(git rev-parse FETCH_HEAD)
if [ "$FETCHED_SHA" != "$HEAD_SHA" ]; then
  echo "Error: fetched ${FETCHED_SHA}, expected ${HEAD_SHA}; the PR changed meanwhile." >&2
  exit 1
fi

# Refuse changes to CI or dependency files unless explicitly allowed.
git fetch --no-tags "$REMOTE" "refs/heads/${BASE_REF}"
MERGE_BASE=$(git merge-base FETCH_HEAD "$HEAD_SHA")
SENSITIVE_CHANGES=()
while IFS= read -r path; do
  for pattern in "${SENSITIVE_PATHS[@]}"; do
    # shellcheck disable=SC2053 # glob match on purpose
    if [[ "$path" == $pattern ]]; then
      SENSITIVE_CHANGES+=("$path")
      break
    fi
  done
done < <(git diff --name-only "$MERGE_BASE" "$HEAD_SHA")
if [ ${#SENSITIVE_CHANGES[@]} -gt 0 ]; then
  echo "PR #${PR_NUMBER} changes CI or dependency files:" >&2
  printf '  %s\n' "${SENSITIVE_CHANGES[@]}" >&2
  if [ "$ALLOW_SENSITIVE" != "true" ]; then
    echo "Error: these run with the CI credentials. Review them, then run again with --allow-sensitive-paths." >&2
    exit 1
  fi
  echo "Continuing: --allow-sensitive-paths was given." >&2
fi

echo "Mirroring PR #${PR_NUMBER} (${HEAD_SHA}) to ${REMOTE}/${SYNC_BRANCH}..."
git push --force "$REMOTE" "${HEAD_SHA}:refs/heads/${SYNC_BRANCH}"

EXISTING=$(gh pr list --repo "$UPSTREAM_REPO" --head "$SYNC_BRANCH" --state open \
  --json number --jq '.[0].number // empty')
if [ -n "$EXISTING" ]; then
  echo "Mirror PR #${EXISTING} updated; CI re-runs on ${HEAD_SHA}."
  exit 0
fi

gh label create do-not-merge --repo "$UPSTREAM_REPO" --color B60205 \
  --description "Never merge this PR" 2>/dev/null || true
gh label create fork-test --repo "$UPSTREAM_REPO" --color 0E8A16 \
  --description "Mirror of a fork PR, for CI only" 2>/dev/null || true

# The title must pass pr-title-lint (Conventional Commits, lowercase subject).
gh pr create --repo "$UPSTREAM_REPO" \
  --base "$BASE_REF" \
  --head "$SYNC_BRANCH" \
  --title "test(ci): mirror fork pr #${PR_NUMBER} for ci" \
  --label do-not-merge --label fork-test \
  --body "CI mirror of ${PR_URL} at ${HEAD_SHA}, created with \`scripts/fork-sync-pr.sh\`.

Do not merge this PR. Merge the original PR once CI is green here, then close this one and delete \`${SYNC_BRANCH}\`."
