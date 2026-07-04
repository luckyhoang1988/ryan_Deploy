# RyanDeploy

Nền tảng **đẩy phần mềm agentless** kiểu PDQ Deploy cho môi trường Active Directory domain.
Server đẩy `.msi/.exe` xuống máy trạm và cài đặt silent **mà không cần remote thủ công vào từng máy**, hỗ trợ **đẩy song song nhiều máy cùng lúc**.

> Phạm vi hiện tại: **Phase 0–8** (nền móng → models → repository/vault → engine đẩy → orchestration
> song song → AD discovery → REST API + Web UI + RBAC → hardening bảo mật/audit → test + đóng gói + runbook).
> Kế hoạch đầy đủ: xem file plan trong `.claude/plans/`.
> Vận hành: [docs/RUNBOOK.md](docs/RUNBOOK.md) · Bảo mật: [docs/SECURITY.md](docs/SECURITY.md).

## Cơ chế (nhân bản PDQ Deploy)

Mỗi máy đích trải qua 5 bước, không cần agent:

1. **precheck** — kiểm tra SMB 445.
2. **copy** — kết nối `ADMIN$` (= `C:\Windows`), tạo thư mục tạm, upload installer + wrapper `run.bat`.
3. **execute** — tạo **Windows Service tạm** (MS-SCMR) chạy dưới LocalSystem → thực thi silent install.
4. **collect** — đọc `exit.code` + `stdout.log` về qua SMB.
5. **cleanup** — stop + delete service, xóa file/thư mục trên máy đích.

Engine: [`apps/executor/push_executor.py`](backend/apps/executor/push_executor.py) (dùng `impacket`).
Điều phối song song: Celery chord trong [`apps/deployments/orchestrator.py`](backend/apps/deployments/orchestrator.py) + task [`apps/jobs/tasks.py`](backend/apps/jobs/tasks.py).

## Kiến trúc

```
Web/API → Django (DRF) → PostgreSQL
                       → Celery workers ↔ Redis
                                        → PushExecutor (impacket: SMB + SCMR) → máy trạm (ADMIN$)
```

## Cấu trúc thư mục

```
backend/
  ryandeploy/            # Django project (settings tách base/dev/prod/test, celery)
  apps/
    core/              # base model, healthcheck, auth (login/me), RBAC permissions, stats
    credentials/       # DeployCredential + vault Fernet (mã hóa at-rest)
    packages/          # Package/PackageVersion + repository (SHA-256, detect installer, silent switch)
    machines/          # Machine, MachineGroup + AD sync (ldap3) + online check
    deployments/       # Deployment + orchestrator (fan-out song song)
    jobs/              # Job + Celery tasks (nối Job ↔ PushExecutor)
    executor/          # PushExecutor — engine đẩy agentless
    audit/             # AuditLog
frontend/              # Web UI: React + Vite (dashboard, packages, machines, deployment wizard, monitor)
docker-compose.yml     # web + worker + beat + redis + postgres
```

## Web UI (frontend)

```bash
cd frontend
npm install
npm run dev          # http://localhost:5173 (proxy /api -> :8000)
```

Trang: Login · Dashboard · Packages (upload) · Máy trạm (Sync AD / kiểm tra online) ·
Deployments (wizard tạo & chạy) · Chi tiết deployment (theo dõi job real-time, xem log).

## Phân quyền (RBAC)

3 nhóm: `admin` / `operator` / `viewer`. Khởi tạo: `python manage.py init_roles`.
- **viewer**: chỉ đọc.
- **operator**: đọc + tạo/kích hoạt deployment.
- **admin**: toàn quyền (gồm quản lý credential). superuser luôn là admin.

Gán user vào nhóm qua Django admin (Groups).

## Đồng bộ máy từ AD

Cấu hình `AD_SERVER / AD_BASE_DN / AD_BIND_USER / AD_BIND_PASSWORD` trong `.env`, rồi:
`POST /api/machines/sync_ad/`. Celery beat cũng tự sync 02:00 hằng đêm và kiểm tra online mỗi 15 phút.

## Chạy bằng Docker (khuyến nghị)

```bash
cp .env.example .env
# Sinh VAULT_KEY (khóa mã hóa credential):
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
# → dán vào RYANDEPLOY_VAULT_KEY trong .env

docker compose up --build
# API: http://localhost:8000/api/health/
docker compose exec web python manage.py createsuperuser
```

## Chạy để phát triển (không Docker)

```bash
cd backend
python -m venv .venv && .venv\Scripts\activate      # Windows
pip install -r requirements.txt
set DJANGO_SETTINGS_MODULE=ryandeploy.settings.dev     # cần Postgres + Redis đang chạy
python manage.py migrate
uvicorn ryandeploy.asgi:application --reload            # KHÔNG dùng "manage.py runserver" —
                                                          # đó là WSGI thuần, không phục vụ được
                                                          # WebSocket real-time (/ws/updates/)
celery -A ryandeploy worker -l info                     # terminal khác
```

## Quy trình sử dụng (qua Django admin / API)

1. **Credential**: tạo `DeployCredential` (domain, user, password) — password lưu mã hóa. User phải là **local admin** trên máy trạm (đặt qua GPO/Restricted Groups).
2. **Package**: tạo `Package` + upload `PackageVersion` (installer). Hệ thống tự tính SHA-256, đoán loại installer, gợi ý lệnh silent. Kiểm/sửa `install_command` (dùng `{file}` làm placeholder).
3. **Machine**: thêm máy trạm (Phase 5 sẽ tự sync từ AD).
4. **Deployment**: tạo deployment (chọn package version, credential, danh sách máy), rồi `POST /api/deployments/{id}/trigger/`.
5. Theo dõi qua `GET /api/jobs/?deployment={id}`.

## Yêu cầu môi trường đích

- Máy trạm mở **SMB (445)**, bật `ADMIN$` share.
- Service account là **local admin** trên máy trạm.
- Server có line-of-sight mạng tới máy trạm (cùng LAN/VPN).

## Kiểm thử đã chạy

- `manage.py check` — no issues.
- `makemigrations` + `migrate` (sqlite test settings) — OK.
- Smoke test: vault roundtrip, repository detect/checksum, executor path + `{file}` substitution — PASS.
- **pytest: 77/77 PASS** — vault, repository + verify_integrity (chống tamper), executor
  path/command + DNS precheck + phân loại lỗi auth/hủy, permissions/RBAC (gồm nhóm máy),
  semaphore concurrency, scheduling/reconcile (kẹt RUNNING, timeout), log JSON, và API
  (login, stats, credential mã hóa + audit create/update/delete, viewer bị chặn 403, chặn ẩn danh).
  Chạy: `cd backend && DJANGO_SETTINGS_MODULE=ryandeploy.settings.test pytest` (cài `pip install -r requirements-dev.txt`).
- Frontend `npm run build` — build thành công (0 lỗi).

> Test **end-to-end đẩy thật** cần 1 máy Windows lab trong domain (xem mục Verification #1/#2 trong plan) — chưa chạy trong môi trường này vì không có máy đích.
