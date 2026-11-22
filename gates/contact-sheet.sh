#!/bin/zsh
# Gate: the Contact Sheet script's tests pass, with at least 95% line coverage.
#
# The tests (tests/test_contact_sheet.py) build small videos with ffmpeg and check
# that every tile is the frame at its time, the seams straddle each 10 s mark, the
# sheet is laid out as specified, and failures turn into notifications.
#
# Usage: gates/contact-sheet.sh
set -uo pipefail
cd "$(dirname "$0")/.."
py=/opt/homebrew/bin/python3
min=95

if ! $py -c 'import coverage, PIL' 2>/dev/null; then
  print -u2 "FAIL contact-sheet: the tests need Pillow and coverage in Homebrew Python."
  print -u2 "Fix: $py -m pip install --break-system-packages Pillow coverage"
  exit 1
fi

tmp=$(mktemp -d); trap 'rm -rf "$tmp"' EXIT
export COVERAGE_FILE="$tmp/.coverage"

if ! out=$($py -m coverage run --source=scripts --include='scripts/contact_sheet.py' \
             -m unittest discover -s tests 2>&1); then
  print -u2 "$out"
  print -u2 ""
  print -u2 "FAIL contact-sheet: tests/test_contact_sheet.py has failures (above)."
  print -u2 "Fix the script or the test, then re-run: $py -m unittest discover -s tests"
  exit 1
fi

pct=$($py -m coverage report --format=total)
if (( pct < min )); then
  print -u2 "FAIL contact-sheet: scripts/contact_sheet.py line coverage is ${pct}%, the floor is ${min}%."
  print -u2 "Every script here keeps 95% coverage from tests with real assertions."
  print -u2 "See the uncovered lines with:"
  print -u2 "  COVERAGE_FILE=/tmp/.cov $py -m coverage run --source=scripts -m unittest discover -s tests && \\"
  print -u2 "  COVERAGE_FILE=/tmp/.cov $py -m coverage report -m"
  exit 1
fi
print "ok   contact-sheet (tests pass, ${pct}% coverage)"
