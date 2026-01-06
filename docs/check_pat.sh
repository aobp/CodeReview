#!/usr/bin/env bash
set -euo pipefail

# Quick permission probe for fine-grained PAT.
# - Validates token can read repo + PR
# - Tries to POST an issue comment to the PR, then DELETE it (cleanup)
#
# Usage:
#   export GITHUB_TOKEN=...
#   OWNER=... REPO=... PR_NUMBER=... bash docs/check_pat.sh
#
# Optional:
#   API_BASE_URL=https://api.github.com
#   CHECK_REVIEW=1   # also tries to create a PR review (not auto-deleted)

: "${GITHUB_TOKEN:?missing env GITHUB_TOKEN}"
: "${OWNER:?missing env OWNER}"
: "${REPO:?missing env REPO}"
: "${PR_NUMBER:?missing env PR_NUMBER}"

API_BASE_URL="${API_BASE_URL:-https://api.github.com}"
CHECK_REVIEW="${CHECK_REVIEW:-0}"

repo_full="$OWNER/$REPO"

hdr_auth=( -H "Authorization: token ${GITHUB_TOKEN}" -H "Accept: application/vnd.github+json" )

say() { printf "%s\n" "$*"; }

say "[1/4] GET /repos/${repo_full}"
repo_code=$(curl -sS -o /dev/null -w "%{http_code}" "${hdr_auth[@]}" "${API_BASE_URL}/repos/${repo_full}")
say "  http=${repo_code}"
if [[ "$repo_code" != "200" ]]; then
  say "  FAIL: token cannot read repo (check repo selection + Contents permission)"
  exit 1
fi

say "[2/4] GET /pulls/${PR_NUMBER} (read PR + get head sha)"
pr_json=$(curl -sS "${hdr_auth[@]}" "${API_BASE_URL}/repos/${repo_full}/pulls/${PR_NUMBER}")
head_sha=$(python -c 'import json,sys; print(json.load(sys.stdin)["head"]["sha"])' <<<"$pr_json")
base_ref=$(python -c 'import json,sys; print(json.load(sys.stdin)["base"]["ref"])' <<<"$pr_json")
say "  base_ref=${base_ref}"
say "  head_sha=${head_sha}"

say "[3/4] POST issue comment (should succeed) + DELETE cleanup"
probe_body="PAT probe from docs/check_pat.sh $(date -u +%Y-%m-%dT%H:%M:%SZ)"
probe_body_json=$(python -c 'import json,sys; print(json.dumps(sys.argv[1]))' "$probe_body")

comment_tmp=$(mktemp)
comment_code=$(curl -sS -o "$comment_tmp" -w "%{http_code}" "${hdr_auth[@]}" -X POST \
  "${API_BASE_URL}/repos/${repo_full}/issues/${PR_NUMBER}/comments" \
  -d "{\"body\": ${probe_body_json} }")

if [[ "$comment_code" != "201" ]]; then
  say "  http=${comment_code}"
  say "  FAIL: cannot create issue comment (need Issues: write permission)"
  say "  response:"
  sed -n '1,200p' "$comment_tmp"
  rm -f "$comment_tmp"
  exit 1
fi

comment_id=$(python -c 'import json,sys; print(json.load(sys.stdin).get("id",""))' <"$comment_tmp")
rm -f "$comment_tmp"

if [[ -z "$comment_id" ]]; then
  say "  FAIL: created comment but could not parse id"
  exit 1
fi
say "  created issue comment id=${comment_id}"

del_code=$(curl -sS -o /dev/null -w "%{http_code}" "${hdr_auth[@]}" -X DELETE \
  "${API_BASE_URL}/repos/${repo_full}/issues/comments/${comment_id}")
say "  delete http=${del_code}"
if [[ "$del_code" != "204" ]]; then
  say "  WARN: comment created but failed to delete (you may need to delete manually on GitHub)"
fi

if [[ "$CHECK_REVIEW" == "1" ]]; then
  say "[4/4] POST PR review (NOT auto-deleted)"
  review_body="PAT probe review from docs/check_pat.sh $(date -u +%Y-%m-%dT%H:%M:%SZ)"
  review_body_json=$(python -c 'import json,sys; print(json.dumps(sys.argv[1]))' "$review_body")
  review_code=$(curl -sS -o /dev/null -w "%{http_code}" "${hdr_auth[@]}" -X POST \
    "${API_BASE_URL}/repos/${repo_full}/pulls/${PR_NUMBER}/reviews" \
    -d "{\"commit_id\":\"${head_sha}\",\"event\":\"COMMENT\",\"body\": ${review_body_json} }")
  say "  http=${review_code}"
  if [[ "$review_code" != "200" && "$review_code" != "201" ]]; then
    say "  FAIL: cannot create PR review (check Pull requests: write permission)"
    exit 1
  fi
else
  say "[4/4] SKIP PR review check (set CHECK_REVIEW=1 to enable)"
fi

say "OK: PAT can post issue comments (and cleanup)."
