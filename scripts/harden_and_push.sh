#!/usr/bin/env bash
set -euo pipefail

cd ~/mycelium

echo "[1/6] Creating production directories..."
mkdir -p core deploy tests scripts docs static .github/workflows

echo "[2/6] Enforcing strict .gitignore..."
cat << 'GITEOF' > .gitignore
__pycache__/
*.py[cod]
*$py.class
.venv/
venv/
env/
.env
*.db
*.sqlite3
knowledge.db
ledger.db
mycelium.db
secret.key
*.pem
pids/
.coverage
.pytest_cache/
*.zip
GITEOF

echo "[3/6] Purging tracked runtime secrets or databases from git index..."
git rm --cached -f secret.key *.db *.pem .coverage 2>/dev/null || true

echo "[4/6] Generating strong local secret if .env does not exist..."
if [ ! -f .env ]; then
  SECRET=$(python -c "import secrets; print(secrets.token_hex(32))")
  cp .env.example .env
  sed -i "s/CHANGE_ME_GENERATE_64_CHAR_HEX_SECRET/$SECRET/" .env
  echo "Generated new .env with strong 64-char MYCELIUM_SECRET_KEY."
fi

echo "[5/6] Running pytest verification suite..."
[ -d venv ] && source venv/bin/activate
set -a; [ -f .env ] && source .env; set +a
PYTHONPATH=. python -m pytest tests/test_production_hardening.py -v

echo "[6/6] Staging and pushing production-ready updates to GitHub..."
for path in .gitignore .env.example README.md requirements.txt core/ deploy/ tests/ scripts/ .github/; do
  [ -e "$path" ] && git add "$path"
done
git status -s
git commit -m "chore(prod): add fail-closed security middleware, TLS proxy, Docker, and hardening tests" || echo "Nothing new to commit"
git push -u origin main

echo "All updates verified and pushed to https://github.com/isgr870/mycelium"
