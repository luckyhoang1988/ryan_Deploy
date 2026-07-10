# RyanDeploy — Runbook vận hành

Hướng dẫn cài đặt, cấu hình môi trường domain và rollout cho hệ thống đẩy phần mềm agentless.

---

## 1. Chuẩn bị môi trường domain

### 1.1. Service account đẩy phần mềm
Tạo một service account trong AD, VD `CORP\svc_ryandeploy`:
- **KHÔNG dùng Domain Admin.** Chỉ cần là **local admin trên máy trạm**.
- Cấp local admin qua GPO → *Restricted Groups* hoặc *Group Policy Preferences → Local Users and Groups*, thêm `svc_ryandeploy` vào nhóm `Administrators` của các máy đích.
- Đặt mật khẩu mạnh, bật "password never expires" hoặc có quy trình xoay vòng.

### 1.2. Mở đường mạng tới máy trạm
Trên máy trạm (qua GPO Firewall), cho phép từ IP server RyanDeploy:
- **TCP 445 (SMB)** — copy file + điều khiển service.
- `ADMIN$` share phải bật (mặc định Windows đã bật).

### 1.3. Kiểm tra nhanh 1 máy
Từ server, xác nhận truy cập được:
```
# Từ máy có bộ SysInternals/Windows:
net use \\PC-LAB-01\ADMIN$ /user:CORP\svc_ryandeploy
```
Nếu map được → RyanDeploy sẽ đẩy được.

---

## 2. Cài đặt server (Docker)

```bash
cp .env.example .env
# Sinh khóa vault:
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
# → RYANDEPLOY_VAULT_KEY trong .env

docker compose up --build -d
docker compose exec web python manage.py migrate
docker compose exec web python manage.py init_roles
docker compose exec web python manage.py createsuperuser
```

Cấu hình `.env` quan trọng:
- `RYANDEPLOY_VAULT_KEY` — khóa mã hóa credential (BẮT BUỘC, không được đổi sau khi đã lưu credential).
- `RYANDEPLOY_MAX_CONCURRENCY` — số máy đẩy song song (mặc định 15).
- `AD_SERVER / AD_BASE_DN / AD_BIND_USER / AD_BIND_PASSWORD` — để sync máy từ AD.

---

## 3. Quy trình vận hành hằng ngày

1. **Nạp máy**: `POST /api/machines/sync_ad/` (hoặc chờ beat 02:00). Kiểm tra online: nút "Kiểm tra online".
2. **Nạp credential**: tạo `DeployCredential` (chỉ admin) — trỏ tới `svc_ryandeploy`.
3. **Nạp package**: upload installer → kiểm/sửa lệnh silent (`{file}` là placeholder).
4. **Deploy**: tạo deployment (package + credential + máy) → Trigger. Theo dõi real-time ở trang chi tiết.
5. **Xử lý lỗi**: xem log từng job; máy offline được retry tự động theo `retry_limit`.

---

## 4. Rollout theo vòng (khuyến nghị)

| Vòng | Phạm vi | Mục tiêu |
|------|---------|----------|
| Pilot | 3–5 máy lab | Xác nhận silent switch đúng, máy sạch sau deploy |
| Phòng ban | 1 OU (~20–50 máy) | Kiểm tra concurrency, tỉ lệ thành công |
| Toàn bộ | Tất cả OU | Đẩy giờ thấp điểm (22:00–06:00) qua scheduled deployment |

**Rollback:** mỗi `PackageVersion` có thể có `uninstall_command`; tạo deployment gỡ cài khi cần.

---

## 5. Sao lưu & phục hồi

- **PostgreSQL**: `docker compose exec postgres pg_dump -U ryandeploy ryandeploy > backup.sql` (định kỳ).
- **Repository** (installer): backup volume `media` hoặc thư mục `backend/media/repository/`.
- **VAULT_KEY**: lưu an toàn (KMS/secret manager). Mất key = mất toàn bộ credential đã lưu.

---

## 6. Sự cố thường gặp

| Triệu chứng | Nguyên nhân | Xử lý |
|-------------|-------------|-------|
| Job fail ở `precheck` | Máy offline / firewall chặn 445 | Kiểm tra mạng, GPO firewall |
| Job fail ở `copy` | Sai credential / không có quyền ADMIN$ | Kiểm tra local admin của service account |
| Exit code ≠ 0/3010 | Silent switch sai | Sửa `install_command` của package version |
| "Toàn vẹn installer KHÔNG khớp" | File repository bị sửa | Upload lại installer đúng |
| Login bị chặn | Throttle 10/phút | Chờ 1 phút |
