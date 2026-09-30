#!/usr/bin/env bash
# ==============================================================================
# FastAPI Multi-Provider AI Router Boilerplate - Commercial Packager Script
# ==============================================================================
# Cleans virtual environments, test caches, local .env files, and generates
# a clean, customer-ready zip package ready to upload to Paystack / Gumroad.
# ==============================================================================

set -euo pipefail

PACKAGE_NAME="fastapi-ai-router-starter-kit"
OUTPUT_ZIP="${PACKAGE_NAME}.zip"

echo "======================================================================"
echo " Preparing Commercial Release: ${PACKAGE_NAME}"
echo "======================================================================"

# Step 1: Verification of required files
echo "[1/4] Verifying essential product deliverables..."
REQUIRED_FILES=(
    "requirements.txt"
    ".env.example"
    ".gitignore"
    "Dockerfile"
    "docker-compose.yml"
    "README.md"
    "app/main.py"
    "app/core/config.py"
    "app/core/security.py"
    "app/schemas/chat.py"
    "app/services/llm_router.py"
    "app/api/v1/endpoints/chat.py"
    "app/api/v1/endpoints/health.py"
)

for file in "${REQUIRED_FILES[@]}"; do
    if [ ! -f "$file" ]; then
        echo "ERROR: Missing required deliverable '$file'!" >&2
        exit 1
    fi
done
echo "All required deliverables validated."

# Step 2: Cleanup temporary artifacts, virtualenvs, caches
echo "[2/4] Sanitizing repository (removing caches, pyc, venvs, and local secrets)..."
find . -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
find . -type f -name "*.py[cod]" -delete 2>/dev/null || true
find . -type d -name ".pytest_cache" -exec rm -rf {} + 2>/dev/null || true
find . -type d -name ".coverage" -delete 2>/dev/null || true
find . -type d -name "htmlcov" -exec rm -rf {} + 2>/dev/null || true
find . -type d -name ".venv" -exec rm -rf {} + 2>/dev/null || true
find . -type d -name "venv" -exec rm -rf {} + 2>/dev/null || true
find . -type d -name ".git" -exec rm -rf {} + 2>/dev/null || true
find . -type f -name ".DS_Store" -delete 2>/dev/null || true
find . -type f -name "Thumbs.db" -delete 2>/dev/null || true

# CRITICAL SECURITY STEP: Ensure developer's local .env is NEVER bundled into the release zip
if [ -f ".env" ]; then
    echo "NOTICE: Found local '.env' file. Excluding it from the commercial distribution archive."
fi
rm -f "${OUTPUT_ZIP}"

# Step 3: Create Zip Archive
echo "[3/4] Packaging starter kit into '${OUTPUT_ZIP}'..."
if command -v zip >/dev/null 2>&1; then
    zip -r -q "${OUTPUT_ZIP}" . \
        -x "*.git*" \
        -x "*.env" \
        -x "*.venv*" \
        -x "*venv*" \
        -x "*__pycache__*" \
        -x "*.pytest_cache*" \
        -x "*.zip"
else
    PY_CMD="python3"
    if ! command -v python3 >/dev/null 2>&1; then
        PY_CMD="python"
    fi
    $PY_CMD -c "
import zipfile, os
exclude_prefixes = ('.git', '.venv', 'venv', '__pycache__', '.pytest_cache')
exclude_files = ('.env', '${OUTPUT_ZIP}')
with zipfile.ZipFile('${OUTPUT_ZIP}', 'w', zipfile.ZIP_DEFLATED) as zipf:
    for root, dirs, files in os.walk('.'):
        dirs[:] = [d for d in dirs if not any(d.startswith(p) for p in exclude_prefixes)]
        for file in files:
            if file in exclude_files or file.endswith('.pyc') or file.endswith('.zip'):
                continue
            path = os.path.join(root, file)
            arcname = os.path.relpath(path, '.')
            zipf.write(path, arcname)
"
fi

# Step 4: Verification and Summary
echo "[4/4] Release archive created successfully!"
FILE_SIZE=$(ls -lh "${OUTPUT_ZIP}" | awk '{print $5}')
echo "======================================================================"
echo " Deliverable ready for upload:"
echo " Package Archive: ${OUTPUT_ZIP}"
echo " Package Size:    ${FILE_SIZE}"
echo " Target Platform: Paystack / Gumroad / LemonSqueezy"
echo "======================================================================"