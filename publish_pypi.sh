#!/usr/bin/env bash

set -e

# ─────────────────────────────────────────────
# push_pypi.sh
# Builds and uploads twitch-play to PyPI.
#
# Usage:
#   chmod +x push_pypi.sh
#   ./push_pypi.sh
#
# Requirements:
#   pip install build twine
#
# You need a PyPI API token:
#   1. Go to https://pypi.org and create an account
#   2. Account Settings → API tokens → Add API token
#   3. Name it anything, scope: "Entire account" for first upload
#      (after first upload, scope it to "twitch-play" only)
#   4. Copy the token — it starts with "pypi-"
#   5. Paste it when prompted below
# ─────────────────────────────────────────────

echo "==> Checking dependencies..."
pip install --quiet --upgrade build twine

echo "==> Cleaning previous builds..."
rm -rf dist/ build/ *.egg-info

echo "==> Building package..."
python -m build

echo ""
echo "==> Ready to upload to PyPI."
echo "    Paste your API token when prompted (starts with 'pypi-')."
echo "    Get one at: https://pypi.org/manage/account/token/"
echo ""

python -m twine upload dist/*

echo ""
echo "==> Done! Install with:"
echo "    pipx install twitch-play"
echo "    twitch-play"
