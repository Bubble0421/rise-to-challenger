#!/usr/bin/env bash
# Creates a clean zip ready to upload to JupyterLab
# Usage: bash pack_for_upload.sh

set -e
cd "$(dirname "$0")"

ZIP_NAME="rise_to_challenger.zip"

echo "Packing project → $ZIP_NAME ..."

zip -r "$ZIP_NAME" . \
  --exclude ".venv/*" \
  --exclude ".git/*" \
  --exclude ".claude/*" \
  --exclude ".pytest_cache/*" \
  --exclude "__pycache__/*" \
  --exclude "*/__pycache__/*" \
  --exclude "*/.DS_Store" \
  --exclude ".env" \
  --exclude "streamlit.log" \
  --exclude "*.pyc" \
  --exclude "data/chromadb/*" \
  --exclude "$ZIP_NAME"

SIZE=$(du -sh "$ZIP_NAME" | cut -f1)
echo ""
echo "✅ Done: $ZIP_NAME ($SIZE)"
echo ""
echo "Next: upload this file to JupyterLab, then open Launch_Dashboard.ipynb"
