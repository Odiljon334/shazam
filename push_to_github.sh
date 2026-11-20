#!/usr/bin/env bash
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

SSH_KEY="/home/mr-x/.ssh/id_ed25519"

if [ ! -f "$SSH_KEY" ]; then
    echo "❌ SSH kalit topilmadi: $SSH_KEY"
    exit 1
fi

echo "🚀 GitHub'ga 'shazam' repositoriyasiga push qilinmoqda..."
export GIT_SSH_COMMAND="ssh -i $SSH_KEY -o StrictHostKeyChecking=accept-new"

git push -u origin main
echo "✅ Muvaffaqiyatli yuklandi: https://github.com/Odiljon334/shazam"
