#!/bin/zsh
# Gate: every Python script in scripts/ is tested, the tests pass, and each script
# has at least 95% line coverage on its own.
#
# The tests live in tests/test_<script>.py and use real fixtures: for example
# test_contact_sheet.py proves every tile is the frame at its time, and
# test_extract_audio.py proves the extracted audio is the video's own packets.
# A new script with no tests shows 0% here and blocks the push.
#
# Usage: gates/python-scripts.sh
set -uo pipefail
cd "$(dirname "$0")/.."
py=/opt/homebrew/bin/python3
min=95

if ! $py -c 'import coverage, PIL' 2>/dev/null; then
  print -u2 "FAIL python-scripts: the tests need Pillow and coverage in Homebrew Python."
  print -u2 "Fix: $py -m pip install --break-system-packages Pillow coverage"
  exit 1
fi

tmp=$(mktemp -d); trap 'rm -rf "$tmp"' EXIT
export COVERAGE_FILE="$tmp/.coverage"

if ! out=$($py -m coverage run --source=scripts -m unittest discover -s tests 2>&1); then
  print -u2 "$out"
  print -u2 ""
  print -u2 "FAIL python-scripts: the tests in tests/ have failures (above)."
  print -u2 "Fix the script or the test, then re-run: $py -m unittest discover -s tests"
  exit 1
fi

low=()
for script in scripts/*.py(N); do
  pct=$($py -m coverage report --include="$script" --format=total 2>/dev/null)
  (( ${pct:-0} < min )) && low+=("$script: ${pct:-0}%")
done

if (( ${#low} )); then
  print -u2 "FAIL python-scripts: line coverage is under the ${min}% floor for:"
  for l in $low; print -u2 "  - $l"
  print -u2 "Every script here keeps 95% coverage from tests with real assertions,"
  print -u2 "in tests/test_<script>.py. See the uncovered lines with:"
  print -u2 "  COVERAGE_FILE=/tmp/.cov $py -m coverage run --source=scripts -m unittest discover -s tests && \\"
  print -u2 "  COVERAGE_FILE=/tmp/.cov $py -m coverage report -m"
  exit 1
fi
print "ok   python-scripts (tests pass, every script at ${min}%+ coverage)"
