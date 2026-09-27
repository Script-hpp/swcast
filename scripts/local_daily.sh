#!/usr/bin/env bash
# scripts/local_daily.sh — local-cron alternative to .github/workflows/daily.yml
# for anyone who doesn't want to run this on GitHub Actions.
#
# Same steps as the workflow: tests, forecast, evaluation, OTS upgrade,
# commit + push. Intended to be invoked from a system cron/systemd timer at
# 22:30 UTC, e.g.:
#   30 22 * * * cd /path/to/swcast && ./scripts/local_daily.sh >> /path/to/swcast-cron.log 2>&1
#
# Like the workflow: if the forecast step fails, this script still runs
# evaluation, OTS upgrade and the commit/push (so the MISSED record and SWPC
# archive still reach the repo), but exits non-zero at the end so cron mail
# / a monitoring wrapper notices.

set -uo pipefail  # deliberately not -e: forecast/evaluate failures must not
                   # abort the script before commit+push, same as the
                   # workflow's `if: always()` steps.

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

export PYTHONPATH="$REPO_ROOT/src"

echo "[local_daily] $(date -u +%Y-%m-%dT%H:%M:%SZ) starting"

pytest -q
TEST_STATUS=$?
if [ "$TEST_STATUS" -ne 0 ]; then
    echo "[local_daily] tests FAILED (exit $TEST_STATUS) — aborting before any network calls"
    exit "$TEST_STATUS"
fi

python -m swcast.forecast
FORECAST_STATUS=$?

python -m swcast.evaluate
EVAL_STATUS=$?

find . -name '*.ots' -not -path './.git/*' -print0 \
    | xargs -0 -r -n1 -I{} sh -c 'ots upgrade "{}" || true'

git config user.name "swcast-bot" 2>/dev/null || true
git config user.email "swcast-bot@users.noreply.github.com" 2>/dev/null || true
git add -A -- forecasts archive/swpc reports/live_status.md reports/live_evaluation.csv '*.ots'

if git diff --cached --quiet; then
    echo "[local_daily] nothing to commit"
else
    git commit -m "chore(bot): daily forecast + evaluation $(date -u +%Y-%m-%dT%H:%M:%SZ)"
    git push
fi

echo "[local_daily] $(date -u +%Y-%m-%dT%H:%M:%SZ) done (forecast=$FORECAST_STATUS evaluate=$EVAL_STATUS)"

if [ "$FORECAST_STATUS" -ne 0 ]; then
    exit "$FORECAST_STATUS"
fi
exit "$EVAL_STATUS"
