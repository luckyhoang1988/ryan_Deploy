#!/usr/bin/env bash
#
# deploy.sh — Deploy RyanDeploy lên production (10.0.193.231) qua SSH + Docker Compose.
#
# Cách chạy (từ Git Bash trên máy dev, tại thư mục gốc repo):
#     ./deploy.sh
#
# Yêu cầu:
#   - SSH alias `ryandeploy` trong ~/.ssh/config (đã có).
#   - Node/npm để build frontend; tar + ssh trong PATH.
#
# Quy trình (KHÔNG git pull — server không phải repo):
#   1. Build frontend (npm run build).
#   2. Sync backend source (tar-over-ssh, loại cache/media/staticfiles/venv).
#   3. Swap frontend dist qua thư mục tạm (giữ dist.old để rollback).
#   4. Sync docker-compose.prod.yml lên server (docker-compose.host.yml chỉ tồn tại
#      trên server, không sync — sửa file đó thì tự scp riêng).
#   5. Rebuild + restart container (web tự migrate + collectstatic khi start).
#   6. Verify: container healthy + HTTPS 200.
#
set -euo pipefail

# ── Config ────────────────────────────────────────────────────────────────
# Thư mục triển khai trên server: /opt/ryandeploy (đã cutover hoàn toàn khỏi pydeploy —
# module Django, DB/role Postgres, volume, nginx đều dùng tên ryandeploy).
SSH_HOST="ryandeploy"
REMOTE_ROOT="/opt/ryandeploy"
COMPOSE="docker compose -f docker-compose.prod.yml -f docker-compose.host.yml"

# Chuyển về thư mục chứa script (thư mục gốc repo) dù gọi từ đâu.
cd "$(dirname "$0")"

log()  { printf '\n\033[1;36m▶ %s\033[0m\n' "$*"; }
ok()   { printf '\033[1;32m✔ %s\033[0m\n' "$*"; }
die()  { printf '\033[1;31m✘ %s\033[0m\n' "$*" >&2; exit 1; }

# ── 0. Pre-flight ─────────────────────────────────────────────────────────
log "Kiểm tra kết nối SSH tới $SSH_HOST"
ssh -o ConnectTimeout=10 "$SSH_HOST" 'echo ok >/dev/null' \
    || die "Không SSH được tới $SSH_HOST — kiểm tra ~/.ssh/config và VPN/mạng."
ok "SSH OK"

# ── 1. Build frontend ─────────────────────────────────────────────────────
log "Build frontend (npm run build)"
( cd frontend && npm run build ) || die "Frontend build thất bại."
[ -d frontend/dist ] || die "Không thấy frontend/dist sau khi build."
ok "Frontend build xong"

# ── 2. Sync backend source ────────────────────────────────────────────────
log "Sync backend source → $REMOTE_ROOT/backend"
tar czf - -C backend \
    --exclude=__pycache__ \
    --exclude='*.pyc' \
    --exclude=.pytest_cache \
    --exclude=media \
    --exclude=staticfiles \
    --exclude=.venv \
    --exclude='*.sqlite3' \
    . | ssh "$SSH_HOST" "tar xzf - -C $REMOTE_ROOT/backend"
ok "Backend đã sync"

# ── 3. Swap frontend dist (rollback-safe) ─────────────────────────────────
log "Đẩy frontend/dist → $REMOTE_ROOT/frontend/dist"
ssh "$SSH_HOST" "rm -rf $REMOTE_ROOT/frontend/dist.new && mkdir -p $REMOTE_ROOT/frontend/dist.new"
tar czf - -C frontend/dist . | ssh "$SSH_HOST" "tar xzf - -C $REMOTE_ROOT/frontend/dist.new"
ssh "$SSH_HOST" "
    set -e
    cd $REMOTE_ROOT/frontend
    rm -rf dist.old
    [ -d dist ] && mv dist dist.old || true
    mv dist.new dist
"
ok "Frontend dist đã swap (giữ dist.old để rollback)"

# ── 4. Sync docker-compose.prod.yml ───────────────────────────────────────
log "Sync docker-compose.prod.yml → $REMOTE_ROOT"
scp docker-compose.prod.yml "$SSH_HOST:$REMOTE_ROOT/docker-compose.prod.yml"
ok "docker-compose.prod.yml đã sync"

# ── 5. Rebuild + restart ──────────────────────────────────────────────────
log "Rebuild + restart container (web tự migrate + collectstatic)"
ssh "$SSH_HOST" "cd $REMOTE_ROOT && $COMPOSE up -d --build"
ok "Container đã rebuild"

# ── 6. Verify ─────────────────────────────────────────────────────────────
log "Kiểm tra trạng thái container"
ssh "$SSH_HOST" "cd $REMOTE_ROOT && $COMPOSE ps"

log "Kiểm tra HTTPS"
CODE=$(ssh "$SSH_HOST" "curl -sk -o /dev/null -w '%{http_code}' https://127.0.0.1/") || true
if [ "$CODE" = "200" ]; then
    ok "HTTPS 200 — https://10.0.193.231 đang live"
else
    die "HTTPS trả về HTTP $CODE (mong đợi 200). Kiểm tra log: ssh $SSH_HOST 'cd $REMOTE_ROOT && $COMPOSE logs --tail=50 web'"
fi

printf '\n\033[1;32m═══ DEPLOY THÀNH CÔNG ═══\033[0m\n'
printf 'URL: https://10.0.193.231\n'
printf 'Rollback frontend nếu cần: ssh %s "cd %s/frontend && rm -rf dist && mv dist.old dist"\n' "$SSH_HOST" "$REMOTE_ROOT"
