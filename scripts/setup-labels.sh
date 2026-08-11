#!/usr/bin/env bash
# Create (or update) the factory:* label set on one or more repositories.
#
# Usage:
#   GITHUB_TOKEN=ghp_xxx bash scripts/setup-labels.sh <owner> <repo> [<repo>...]
# Example:
#   GITHUB_TOKEN=... bash scripts/setup-labels.sh <owner> <repo-a> <repo-b>
set -euo pipefail

if [[ -z "${GITHUB_TOKEN:-}" ]]; then
  echo "GITHUB_TOKEN env var is required (repo scope)" >&2
  exit 1
fi
if [[ $# -lt 2 ]]; then
  echo "Usage: setup-labels.sh <owner> <repo> [<repo>...]" >&2
  exit 1
fi

OWNER="$1"; shift

# name|color|description  (state labels are mutually exclusive; one per issue.
# factory:release is the one exception: a KIND marker on release tracker issues,
# which also carry one factory:release-* state.)
LABELS=$(cat <<'EOF'
factory:backlog|8B949E|Filed, waiting for its release milestone to be approved
factory:release|24597A|Tracker issue for a release milestone (kind, not a state)
factory:release-planning|3F5D8A|Awaiting `Plan release` on the tracker (nothing running)
factory:release-ready|5C7CBF|Release plan posted, awaiting gate G0 approval
factory:release-approved|246B4A|Release approved (G0); its issues enter intake
factory:intake|0E5A8A|New requirement awaiting intake analysis
factory:spec-ready|4A90D9|Spec PR open, awaiting gate G1 approval
factory:spec-approved|2E7D4F|Spec approved (G1); released for planning
factory:planned|5B4A8A|tasks.md + sub-issues created, awaiting design
factory:design-ready|8E6BBF|design.md PR(s) open, awaiting gate G2 approval
factory:design-approved|1E6B45|Design approved (G2); released for implementation
factory:ready|B07D2B|Task unblocked; implementer may start
factory:in-review|C98A1B|Draft PR under agent review
factory:in-test|D4A017|QA verifying WHEN/THEN scenarios
factory:ready-to-ship|6AA84F|Green + approved; awaiting merge order and gate G3
factory:deployed|0B8043|In production; soak in progress
factory:fast-track|8C8C8C|Small change: Fast-Track implements it and opens a PR
factory:blocked|A63D40|Factory flow needs human attention
factory:incident|7A1F1F|Post-deploy regression under investigation
EOF
)

api() { # method path [json]
  local method="$1" path="$2" data="${3:-}"
  curl -sS -o /tmp/label_resp.json -w "%{http_code}" -X "$method" \
    -H "Authorization: Bearer ${GITHUB_TOKEN}" \
    -H "Accept: application/vnd.github+json" \
    ${data:+-d "$data"} \
    "https://api.github.com${path}"
}

for REPO in "$@"; do
  echo "== ${OWNER}/${REPO}"
  while IFS='|' read -r name color desc; do
    [[ -z "$name" ]] && continue
    payload=$(printf '{"name":"%s","color":"%s","description":"%s"}' "$name" "$color" "$desc")
    code=$(api POST "/repos/${OWNER}/${REPO}/labels" "$payload")
    if [[ "$code" == "201" ]]; then
      echo "  created  $name"
    elif [[ "$code" == "422" ]]; then
      # Already exists — update color/description in place
      encoded=$(printf '%s' "$name" | sed 's/:/%3A/g; s/ /%20/g')
      code=$(api PATCH "/repos/${OWNER}/${REPO}/labels/${encoded}" "$payload")
      if [[ "$code" == "200" ]]; then
        echo "  updated  $name"
      else
        echo "  FAILED ($code) updating $name"; cat /tmp/label_resp.json; echo
      fi
    else
      echo "  FAILED ($code) creating $name"; cat /tmp/label_resp.json; echo
    fi
  done <<< "$LABELS"
done
echo "Done."
