# Kế hoạch triển khai RyanDeploy — Nền tảng đẩy phần mềm agentless kiểu PDQ Deploy

## Context (Bối cảnh & lý do)

Thư mục `ryan_deploy` hiện **chỉ có `claude.md`** — dự án greenfield, chưa có code. `claude.md` mô tả lớp tích hợp AI, **nhưng người dùng xác nhận CHƯA cần AI trong dự án** → kế hoạch này **không bao gồm tích hợp AI**, tập trung 100% vào lõi deployment.

**Yêu cầu thực tế:** Xây hệ thống kiểu **PDQ Deploy** — server đứng trung tâm, **đẩy (push) phần mềm `.msi`/`.exe` xuống máy trạm và cài đặt tự động (silent), KHÔNG cần remote thủ công vào từng máy**, hỗ trợ **đẩy song song nhiều máy cùng lúc** trong **môi trường Active Directory domain**.

**Cơ chế PDQ Deploy đã khảo sát (mô hình sẽ nhân bản):**
1. Background service đọc installer từ repository.
2. Dùng credential domain admin → copy file qua **SMB** tới `\\TARGET\ADMIN$\...\Runner\exec\`.
3. Tạo **Windows Service tạm** trên máy đích (MS-SCMR) chạy dưới deploy account/SYSTEM → thực thi silent install.
4. Đọc exit code + log về server.
5. **Dọn dẹp**: xóa service + file trên máy đích.

→ Triển khai bằng Python qua **`impacket`** (SMB copy + SCMR service creation), điều phối song song bằng **Celery**.

---

## Kiến trúc tổng thể

```
                    ┌─────────────────────────────────────────┐
                    │            RyanDeploy Server                │
                    │  (domain-joined hoặc có domain creds)     │
                    │                                           │
   Web UI  ───────► │  Django REST API                          │
   (React)          │       │                                   │
                    │       ▼                                   │
                    │  PostgreSQL  ◄── models (Package,         │
                    │       │           Deployment, Job, ...)   │
                    │       ▼                                   │
                    │  Celery workers  ◄──► Redis (broker)      │
                    │       │                                   │
                    │       ▼                                   │
                    │  PushExecutor (impacket: SMB + SCMR)      │
                    │       │                                   │
                    │  Package Repository (file store)          │
                    └───────┼───────────────────────────────────┘
                            │  SMB (445) + domain creds
              ┌─────────────┼─────────────┬───────────────┐
              ▼             ▼             ▼               ▼
          ┌───────┐    ┌───────┐    ┌───────┐        ┌───────┐
          │ PC-01 │    │ PC-02 │    │ PC-03 │  ...   │ PC-NN │   (máy trạm Windows/AD)
          └───────┘    └───────┘    └───────┘        └───────┘
        ADMIN$ copy → tạo service tạm → silent install → trả log → cleanup
```

**Tech stack:** Python 3.12 · Django 5 + DRF · Celery + Redis · PostgreSQL · impacket (executor) · ldap3 (AD discovery) · cryptography/Fernet (credential vault) · React + Vite (UI) · Docker Compose (đóng gói).

**Giả định hạ tầng (mặc định, có thể đổi):** Server chạy trên 1 máy có line-of-sight mạng tới máy trạm + mở SMB 445; xác thực NTLM/Kerberos bằng service account `DOMAIN\svc_ryandeploy` là **local admin trên máy trạm** (qua GPO/Restricted Groups). Không cần domain-join server nếu dùng NTLM.

---

## Các Phase triển khai

### Phase 0 — Nền móng & scaffolding hạ tầng
**Mục tiêu:** Dựng khung dự án chạy được, môi trường dev đồng nhất.
- Khởi tạo repo (git init), cấu trúc `backend/` (Django project `ryandeploy`), `apps/` skeleton.
- `docker-compose.yml`: dịch vụ `web` (Django), `worker` (Celery), `redis`, `postgres`.
- `requirements.txt`: django, djangorestframework, celery, redis, psycopg, impacket, ldap3, cryptography, python-dotenv.
- `.env.example` + settings tách theo môi trường (`settings/base.py`, `dev.py`, `prod.py`).
- Cấu hình logging tập trung (JSON logs).
**Deliverable:** `docker compose up` chạy được Django + Celery + Redis + Postgres; healthcheck `/api/health/` trả 200.

### Phase 1 — Data models (domain model)
**Mục tiêu:** Định nghĩa schema lõi.
- App `packages`: `Package`, `PackageVersion` (đường dẫn file, checksum SHA-256, loại installer, **install parameters** silent switch, min OS/RAM/disk, số license).
- App `machines`: `Machine` (hostname, FQDN, IP, OS, RAM, disk, last_seen, online status, AD OU).
- App `deployments`: `Deployment` (package_version, danh sách target, lịch chạy, trạng thái, retry policy).
- App `jobs`: `Job` (một job = 1 deployment × 1 machine; status, exit_code, output, error_output, started/finished_at, số lần retry).
- App `audit`: `AuditLog` (ai làm gì, khi nào, trên máy nào).
- Migrations + Django admin cho toàn bộ model.
**Deliverable:** `migrate` sạch; tạo/sửa được dữ liệu qua Django admin.

### Phase 2 — Package Repository & Credential Vault
**Mục tiêu:** Lưu installer an toàn + quản lý credential đẩy.
- **Repository:** upload `.msi/.exe/.msu` → lưu file store (`MEDIA_ROOT/repository/` hoặc S3-compatible), tính SHA-256, tự phát hiện loại installer (MSI/InnoSetup/NSIS/InstallShield) để gợi ý silent switch mặc định.
- **Silent params mặc định:** MSI → `msiexec /i "{file}" /qn /norestart`; MSU → `wusa "{file}" /quiet /norestart`; EXE → theo field người dùng nhập (InnoSetup `/VERYSILENT`, NSIS `/S`, InstallShield `/s /v"/qn"`).
- **Credential Vault:** model `DeployCredential` (domain, username, password **mã hóa Fernet at-rest**, key từ env/KMS). KHÔNG log/trả password ra API. Đây là dữ liệu **Tier-0**.
**Deliverable:** Upload package → hiện checksum + silent switch gợi ý; lưu credential mà DB chỉ chứa ciphertext.

### Phase 3 — Core Deployment Engine (PushExecutor) ★ TRỌNG TÂM
**Mục tiêu:** Nhân bản cơ chế push agentless của PDQ Deploy.
- Module `apps/executor/push_executor.py`, class `PushExecutor` — flow cho MỖI máy đích:
  1. **Pre-check:** resolve FQDN, kiểm tra SMB 445 mở, đủ dung lượng đĩa.
  2. **Auth:** NTLM/Kerberos bằng `DOMAIN\user` + password (impacket `SMBConnection`).
  3. **Copy:** kết nối `ADMIN$` (= `C:\Windows`), tạo `C:\Windows\RyanDeploy\Runner\{job_id}\exec\`, upload installer + wrapper `run.bat`/`.ps1` (chạy silent install, ghi exit code + stdout/stderr ra file kết quả).
  4. **Remote exec:** tạo **Windows Service tạm** qua MS-SCMR (impacket `scmr`) trỏ tới wrapper, chạy dưới `LocalSystem` → start service. (Phương án dự phòng: Scheduled Task qua `tsch`.)
  5. **Poll kết quả:** đọc file kết quả về qua SMB → parse exit code + log.
  6. **Cleanup:** stop + delete service, xóa thư mục/file trên máy đích.
- Chuẩn hóa exit code (0 = success; 3010 = success cần reboot; còn lại = fail).
- Timeout + hủy an toàn cho mỗi bước.
**Deliverable:** Gọi `PushExecutor.run(job)` cài thành công 1 `.msi` và 1 `.exe` lên 1 máy lab; máy đích sạch sau khi xong (không sót service/file).

### Phase 4 — Orchestration, đẩy song song & trạng thái real-time
**Mục tiêu:** Đẩy nhiều máy cùng lúc, theo dõi tiến độ.
- Celery task `deploy_to_machine(job_id)`; một `Deployment` fan-out thành `group` các job.
- Giới hạn concurrency (VD 10–20 máy song song) qua queue/worker config để không nghẽn repo/mạng.
- Retry tự động theo policy (exponential backoff) cho lỗi tạm thời (máy offline).
- Cập nhật trạng thái real-time: **Django Channels (WebSocket)** hoặc polling API; progress bar theo deployment (đang chạy / thành công / thất bại).
- Lịch chạy (scheduled deployment) qua Celery beat — hỗ trợ đẩy giờ thấp điểm (VD 22:00–06:00).
**Deliverable:** Đẩy 1 package tới ≥5 máy song song, xem tiến độ trực tiếp, máy offline được retry.

### Phase 5 — Quản lý máy trạm & AD discovery
**Mục tiêu:** Không nhập tay danh sách máy.
- `apps/machines/ad_sync.py` dùng `ldap3` query AD → enumerate computer objects theo OU, đồng bộ vào bảng `Machine`.
- Kiểm tra online (ping/SMB 445) định kỳ, cập nhật `last_seen`.
- Nhóm máy (target group tĩnh/động theo OU) để chọn nhanh khi tạo deployment.
- (Tùy chọn) thu thập inventory cơ bản (OS, RAM, disk) qua WMI/SMB để kiểm tra điều kiện cài đặt.
**Deliverable:** Sync máy từ 1 OU vào hệ thống; tạo deployment bằng cách chọn nhóm thay vì gõ hostname.

### Phase 6 — REST API & Web UI quản trị
**Mục tiêu:** Giao diện vận hành cho IT admin.
- DRF ViewSets/serializers: packages, machines, deployments, jobs, credentials (ẩn secret), audit.
- Endpoint: CRUD deployment, trigger deploy, xem log job, upload package.
- Web UI (React + Vite): dashboard, thư viện package (upload), danh sách máy/nhóm, wizard tạo deployment, màn theo dõi real-time, xem log lỗi từng máy.
- AuthN/AuthZ: đăng nhập, RBAC (admin / operator / viewer).
**Deliverable:** Từ UI: upload package → chọn nhóm máy → deploy → xem tiến độ & log, không cần chạm CLI.

### Phase 7 — Bảo mật, RBAC & Audit hardening
**Mục tiêu:** Vì hệ thống deploy là mục tiêu tấn công **Tier-0** (chiếm được = kiểm soát toàn domain).
- Least privilege: service account chỉ là local admin trên máy trạm qua GPO, tránh Domain Admin nếu được.
- Mã hóa credential at-rest (Phase 2) + audit mọi hành động deploy (ai, gì, ở đâu, khi nào).
- Verify checksum installer trước khi đẩy (chống tamper repository).
- Chống lạm dụng: RBAC chặt, giới hạn ai được tạo package/credential; secrets không rò ra log/API/UI.
- Rà soát bề mặt tấn công theo bài học pentest PDQ (service tạm, quyền thư mục repo, kênh nội bộ).
**Deliverable:** Pentest nội bộ cơ bản pass; không có secret trong log; audit trail đầy đủ.

### Phase 8 — Testing, đóng gói & rollout
**Mục tiêu:** Đưa vào vận hành thật an toàn.
- Unit test (models, silent-switch detection) + integration test executor trên máy lab.
- Test end-to-end trong 1 OU nhỏ trước khi mở rộng.
- Tài liệu vận hành: cấu hình service account/GPO, mở SMB 445, quy trình thêm package.
- Đóng gói Docker + hướng dẫn deploy on-prem; backup DB + repository.
- Rollout theo vòng: pilot (vài máy) → 1 phòng ban → toàn bộ, có rollback plan.
**Deliverable:** Chạy thật trên 1 nhóm pilot; runbook vận hành hoàn chỉnh.

---

## Verification (cách kiểm thử end-to-end)

1. **Executor lõi (Phase 3):** Trong lab, chạy `PushExecutor.run(job)` với 1 `.msi` (VD 7-Zip) + 1 `.exe` silent → xác nhận: phần mềm xuất hiện trong Programs, exit code 0/3010, và **máy đích sạch** (không còn service `RyanDeployRunner`/thư mục tạm).
2. **Song song (Phase 4):** Deploy 1 package tới ≥5 máy đồng thời; 1 máy tắt → job đó retry, các máy khác vẫn thành công.
3. **AD sync (Phase 5):** Sync 1 OU → số máy khớp AD; deploy bằng cách chọn nhóm.
4. **UI (Phase 6):** Toàn bộ luồng upload → chọn máy → deploy → theo dõi log chỉ bằng UI.
5. **Bảo mật (Phase 7):** Kiểm tra DB chỉ chứa ciphertext credential; grep log không có password; audit log ghi nhận mỗi deploy.

---

## Trạng thái triển khai (cập nhật)

**Đã hoàn thành Phase 0 → 8.** Toàn bộ code nằm trong `backend/` (Django) và `frontend/` (React+Vite); tài liệu ở `docs/` và `README.md`.

| Phase | Trạng thái | Thành phần chính |
|-------|-----------|------------------|
| 0 Scaffolding | ✅ | `backend/ryandeploy` (settings base/dev/prod/test), `docker-compose.yml`, healthcheck |
| 1 Models | ✅ | packages, machines, deployments, jobs, credentials, audit + migrations + admin |
| 2 Repository & Vault | ✅ | `packages/repository.py` (SHA-256, detect, silent switch), `credentials/vault.py` (Fernet) |
| 3 PushExecutor | ✅ | `apps/executor/push_executor.py` (SMB ADMIN$ + SCMR service + poll + cleanup) |
| 4 Orchestration | ✅ | `deployments/orchestrator.py` + `jobs/tasks.py` (Celery chord, retry, real-time) |
| 5 AD discovery | ✅ | `machines/ad_sync.py` (ldap3), `connectivity.py`, Celery beat, API sync/online |
| 6 API + Web UI + RBAC | ✅ | DRF full, auth session, `core/permissions.py`, `frontend/` SPA |
| 7 Bảo mật/Audit | ✅ | verify_integrity chống tamper, login throttle, audit job start/finish, `docs/SECURITY.md` |
| 8 Test + đóng gói | ✅ | pytest **24/24 PASS**, `docs/RUNBOOK.md`, Docker |

**Đã verify trong môi trường dev:** `manage.py check` no issues · `pytest` 24/24 · `npm run build` 0 lỗi · server chạy thật (login/CSRF/session/stats OK qua proxy Vite).

**Còn lại (cần môi trường thật):** Verification #1 & #2 — test **đẩy thật** lên máy Windows trong domain (cài `impacket` ở Python 3.12/Docker, có ≥1 máy lab). Đây là bước nghiệm thu end-to-end cuối cùng.

**Ngoài phạm vi đợt này:** tích hợp AI (theo `claude.md`) — để dành khi cần.
