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
# SECURITY: the mirrored code runs with this repository's CI credentials.
# Review the fork PR first, then pass the commit you reviewed so that nothing
# pushed after your review is mirrored.
#
# Usage:
#   scripts/fork-sync-pr.sh <PR_NUMBER> <REVIEWED_SHA>
#
# Requires push access to databrickslabs/ontos and an authenticated gh CLI.
# Run it again with a new SHA after the fork PR changes; the mirror branch is
# force-updated and the existing mirror PR reused. Close the mirror PR and
# delete its branch once the original PR is merged or closed.
#
# Adapted from databrickslabs/impulse (.github/scripts/fork-sync-pr.sh).
set -euo pipefail

UPSTREAM_REPO="databrickslabs/ontos"

if [ $# -ne 2 ]; then
  echo "Usage: $0 <PR_NUMBER> <REVIEWED_SHA>" >&2
  exit 2
fi
PR_NUMBER="$1"
REVIEWED_SHA="$2"
if ! [[ "$PR_NUMBER" =~ ^[0-9]+$ ]]; then
  echo "Error: PR_NUMBER must be a number, got '${PR_NUMBER}'." >&2
  exit 2
fi
if ! [[ "$REVIEWED_SHA" =~ ^[0-9a-f]{7,40}$ ]]; then
  echo "Error: REVIEWED_SHA must be 7-40 hex characters, got '${REVIEWED_SHA}'." >&2
  exit 2
fi
SYNC_BRANCH="fork-test/pr-${PR_NUMBER}"

command -v gh >/dev/null || { echo "Error: gh CLI is required." >&2; exit 1; }

# Find the remote that points to the upstream repository, whatever its name.
REMOTE=""
for r in $(git remote); do
  case "$(git remote get-url "$r")" in
    *"${UPSTREAM_REPO}"|*"${UPSTREAM_REPO}.git") REMOTE="$r"; break ;;
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
if [[ "$HEAD_SHA" != "$REVIEWED_SHA"* ]]; then
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
