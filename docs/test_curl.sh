OWNER=wangyue6761
REPO=sentry-greptile
PR_NUMBER=1

curl -sS -X POST "http://127.0.0.1:8000/github/webhook" \
  -H "Content-Type: application/json" \
  -H "X-GitHub-Event: issue_comment" \
  --data-binary @- <<EOF
{
  "action": "created",
  "repository": { "full_name": "${OWNER}/${REPO}" },
  "issue": {
    "number": ${PR_NUMBER},
    "pull_request": { "url": "https://api.github.com/repos/${OWNER}/${REPO}/pulls/${PR_NUMBER}" }
  },
  "comment": { "id": $(date +%s), "body": "@cptbot review" },
  "sender": { "login": "localtester" }
}
EOF
echo
