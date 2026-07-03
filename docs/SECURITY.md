# RyanDeploy — Bảo mật (Phase 7)

Hệ thống deploy là **mục tiêu Tier-0**: chiếm được server = thực thi mã tùy ý (SYSTEM) trên mọi máy trạm.
Xử lý như tài sản có giá trị cao nhất.

## Kiểm soát đã triển khai

| Kiểm soát | Cơ chế | Vị trí |
|-----------|--------|--------|
| Mã hóa credential at-rest | Fernet (AES-128-CBC + HMAC), key ngoài DB | [vault.py](../backend/apps/credentials/vault.py) |
| Không lộ secret | password `write_only`, không trả API, không log | [credentials/serializers.py](../backend/apps/credentials/serializers.py) |
| RBAC | admin / operator / viewer theo Django Groups | [permissions.py](../backend/apps/core/permissions.py) |
| Quản lý credential chỉ admin | `IsAdmin` trên credential viewset | [credentials/views.py](../backend/apps/credentials/views.py) |
| Chống tamper repository | Verify SHA-256 installer trước mỗi lần đẩy | [tasks.py](../backend/apps/jobs/tasks.py) · [repository.py](../backend/apps/packages/repository.py) |
| Chống brute-force login | Throttle 10/phút | [core/views.py](../backend/apps/core/views.py) |
| Audit trail | Ghi mọi hành động (upload, credential, deploy, job start/finish, AD sync) | [audit/models.py](../backend/apps/audit/models.py) |
| Security headers (prod) | HSTS, secure cookies, nosniff | [settings/prod.py](../backend/ryandeploy/settings/prod.py) |
| Service dọn dẹp | Xóa service + file tạm trên máy đích sau mỗi job | [push_executor.py](../backend/apps/executor/push_executor.py) |

## Nguyên tắc vận hành

1. **Least privilege**: service account đẩy là **local admin trên máy trạm**, KHÔNG Domain Admin.
2. **Bảo vệ VAULT_KEY**: lưu ở KMS/secret manager, không commit, không đặt trong image.
3. **Giới hạn người tạo credential/package**: chỉ nhóm `admin`.
4. **Bảo vệ repository**: chỉ ghi qua ứng dụng; hash được kiểm mỗi lần đẩy.
5. **Rà soát audit log** định kỳ để phát hiện deploy bất thường.

## Checklist trước khi lên production

```
□ RYANDEPLOY_VAULT_KEY là key thật (32-byte urlsafe base64), lưu an toàn
□ DJANGO_SECRET_KEY thật, DEBUG=false (settings.prod)
□ HTTPS bật (reverse proxy), SESSION/CSRF cookie Secure
□ Service account KHÔNG phải Domain Admin
□ ALLOWED_HOSTS giới hạn đúng host
□ Backup DB + repository + lưu VAULT_KEY tách biệt
□ init_roles đã chạy; user được gán đúng nhóm
□ Pentest nội bộ cơ bản (đường ADMIN$, quyền thư mục repo, kênh service)
```
