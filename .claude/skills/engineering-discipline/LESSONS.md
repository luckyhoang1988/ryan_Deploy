# LESSONS — Bài học tích lũy

Ghi lại điều **không suy ra được** từ code/git: gotcha, hành vi bất ngờ, quyết định
kỹ thuật. Mỗi bài học ngắn gọn, có bối cảnh + cách áp dụng lần sau. Mới nhất ở trên.

Định dạng:

```
## <ngày YYYY-MM-DD> — <tiêu đề ngắn>
**Bối cảnh:** điều gì đã xảy ra.
**Bài học:** kết luận rút ra.
**Áp dụng:** lần sau làm thế nào.
```

---

## 2026-07-03 — JsonFormatter: lọc field `extra` bằng danh sách reserved của LogRecord
**Bối cảnh:** Viết JsonFormatter opt-in (env DJANGO_LOG_JSON) để log JSON cho ELK/Datadog.
Muốn gộp field `extra` (vd `logger.info(..., extra={"job_id": 5})`) vào JSON nhưng không
biết field nào là chuẩn của LogRecord, field nào do người dùng thêm.
**Bài học:** `logging.makeLogRecord({}).__dict__.keys()` cho đúng bộ field chuẩn của một
LogRecord rỗng → lấy hiệu để tách `extra`. Nhớ bù thêm `message`/`asctime`/`taskName`
(được sinh lúc format, không có trong record rỗng). Thêm CHOICES vào CharField (vd
AuditLog.Action) VẪN sinh migration AlterField dù không đổi schema DB — phải chạy
makemigrations, nếu không `check`/CI báo "changes not reflected".
**Áp dụng:** Formatter/serializer log tuỳ biến: đừng hardcode danh sách field chuẩn — suy
ra từ record rỗng. Mọi thay đổi choices/help_text/verbose_name của field đều cần migration.

## 2026-07-03 — Hardening trigger/cancel: hai gotcha (update() bỏ auto_now, progress_cb nuốt exception)
**Bối cảnh:** Fix deployment kẹt RUNNING khi launch_deployment ném lỗi, và cancel giữa
chừng không dừng được executor đang chạy (chờ collect tới 30 phút).
**Bài học:**
1. **`QuerySet.update()` KHÔNG kích hoạt `auto_now`/không set field không liệt kê.** Claim
   SCHEDULED→RUNNING bằng `.update(status=RUNNING)` nên `updated_at` không đổi và `started_at`
   vẫn None → reconcile không có mốc thời gian tin cậy để phát hiện "RUNNING kẹt bao lâu".
   Giải: set `started_at=now` NGAY trong lệnh `.update()` của claim, rồi reconcile so
   `now - started_at > ngưỡng`. Đừng dựa vào auto_now cho state-transition kiểu update().
2. **`progress_cb` được gọi trong `try/except Exception` (để progress không làm hỏng deploy)
   → KHÔNG thể dùng nó để báo hủy** (raise sẽ bị nuốt). Phải thêm kênh riêng `cancel_check`
   trả bool, gọi ở mốc mỗi bước + trong vòng chờ collect, raise `CancelledError`. Sau
   `executor.run()` phải `refresh_from_db(fields=["status"])` và nếu CANCELLED thì return
   sớm — nếu không nhánh xử-lý-thất-bại sẽ ghi đè CANCELLED thành FAILED (hoặc tệ hơn:
   retry nếu step ∈ transient).
**Áp dụng:** Reconcile/lưới-an-toàn cần timestamp do chính transition ghi (không phải
auto_now). Cancel hợp tác cho task dài: kênh poll DB riêng, không tái dùng progress_cb;
luôn re-read trạng thái sau bước dài trước khi kết luận kết quả.

## 2026-07-03 — Bốn gotcha khi hardening Phase 2 (annotate/DRF/Celery-eager/SQLite-thread)
**Bối cảnh:** Sửa N+1 list deployment, chuyển sync AD/online check sang async + endpoint
poll task, viết test cho cả hai.
**Bài học:**
1. **@property trùng tên annotation:** Model có `@property total_count`... nên KHÔNG thể
   `.annotate(total_count=...)` (property chặn setattr, và response sau create không có
   annotation). Giải: annotate tên khác (`n_total`) + `SerializerMethodField` fallback
   `getattr(obj, "n_total", None)` → property. Vừa hết N+1 (list) vừa an toàn create-response.
2. **annotate(Count) làm mất ordering:** Aggregation thêm GROUP BY khiến `QuerySet.ordered`
   thành False dù có `Meta.ordering` → DRF bắn `UnorderedObjectListWarning`, phân trang
   không ổn định. Phải `.order_by(...)` tường minh trên queryset đã annotate.
3. **Celery eager KHÔNG lưu result mặc định:** endpoint `/tasks/<id>/` đọc `AsyncResult`
   sẽ rỗng trong test. Bật `CELERY_TASK_STORE_EAGER_RESULT = True` ở settings.test (kèm
   result backend django-db) thì mới đọc được state/result.
4. **ThreadPoolExecutor + ghi DB dưới SQLite test = "database table is locked":** task
   `check_all_online` chạy `refresh_machine_status` (có DB write) trong 32 thread; pytest bọc
   test trong transaction → thread khác không ghi được. Test luồng async thì monkeypatch
   hàm ghi-DB-per-thread thành no-op; chỉ Postgres thật mới chịu được concurrency này.
**Áp dụng:** Ba mục 1–3 là pattern chuẩn cho mọi list-endpoint có count phái sinh + mọi tác
vụ nền có endpoint poll. Mục 4: bất kỳ task đa luồng ghi DB nào cũng không test trực tiếp
được trên SQLite — tách logic hoặc monkeypatch tầng ghi.

## 2026-07-03 — self.retry cho semaphore đụng độ với retry-vì-lỗi (dùng chung request.retries)
**Bối cảnh:** Thêm giới hạn max_concurrency per-deployment bằng Redis semaphore trong
`deploy_to_machine`. Khi hết slot phải `self.retry` để CHỜ — nhưng logic retry-vì-lỗi
sẵn có lại gate trên `self.request.retries < deployment.retry_limit`. Hai loại "retry"
(chờ slot vs lỗi thật) dùng chung `request.retries` → chờ slot vài lần sẽ ăn hết ngân
sách retry lỗi, và `max_retries=5` có thể fail oan job chỉ vì phải chờ.
**Bài học:** Khi tái dùng `self.retry` cho mục đích chờ tài nguyên (không phải lỗi), phải
TÁCH bộ đếm: gate retry-vì-lỗi trên một counter riêng (ở đây là `job.attempts`, chỉ tăng
khi thực sự chạy executor), và đặt `max_retries=None` để lần chờ không chạm trần cứng.
Semaphore vẫn đảm bảo tiến triển vì slot được giải phóng khi job xong.
**Áp dụng:** Chord-safe khi cần chờ trong task: dùng `self.retry` (giữ nguyên task trong
chord) chứ KHÔNG `apply_async` task mới (sẽ phá chord callback). Semaphore fail-open khi
Redis lỗi (không biến sự cố hạ tầng thành sự cố deploy) + TTL chống rò slot.

## 2026-07-03 — Không có Docker CLI; validate compose bằng pyyaml của system Python
**Bối cảnh:** Sửa/tạo `docker-compose.prod.yml`, muốn `docker compose config` nhưng Docker
CLI không cài trong môi trường (exit 127). Venv dự án (`.venv`) cũng không có `pyyaml`.
**Bài học:** System Python tại `C:\Users\v260154\AppData\Local\Programs\Python\Python314\python.exe`
CÓ sẵn `pyyaml`. Nhưng file compose có ký tự tiếng Việt → phải `open(path, encoding='utf-8')`,
nếu không sẽ `UnicodeDecodeError` (default cp1252 trên Windows).
**Áp dụng:** Không có Docker để test compose runtime; validate cú pháp + cấu trúc bằng
`python -c "import yaml; yaml.safe_load(open(p, encoding='utf-8'))"` với system Python đó,
kiểm tra services/ports/volumes/healthcheck qua dict.

## 2026-07-02 — makemigrations/pytest phải dùng settings.test (sqlite)
**Bối cảnh:** `manage.py makemigrations` với settings `dev` fail vì `dev` dùng PostgreSQL
nhưng venv chưa cài `psycopg`; lỗi `ImproperlyConfigured: Error loading psycopg2`.
**Bài học:** Dự án có sẵn `pydeploy.settings.test` chạy SQLite in-file, dành riêng cho
`check`/`makemigrations`/`pytest` không cần Postgres.
**Áp dụng:** Mọi lệnh Django cục bộ (check, makemigrations, migrate, pytest) đặt
`DJANGO_SETTINGS_MODULE=pydeploy.settings.test`. Dùng python từ `.venv/Scripts/python.exe`.

## 2026-07-02 — PowerShell here-string vỡ với ký tự tiếng Việt trong git commit -m
**Bối cảnh:** `git commit -m @'...'@` chứa "Cấu hình AD" bị PowerShell tách sai thành
nhiều pathspec → commit fail ("pathspec 'hình' did not match").
**Bài học:** Here-string PowerShell không đáng tin khi message có dấu tiếng Việt.
**Áp dụng:** Viết commit message ra file rồi `git commit -F <file>` (dùng Write tool tạo
file trong scratchpad). Ổn định với mọi ký tự Unicode.

## 2026-07-02 — Import "apps.*" bị linter báo đỏ nhưng runtime đúng
**Bối cảnh:** IDE báo `Cannot find module apps.credentials.vault` cho các import kiểu
`from apps.xxx import ...` trong backend.
**Bài học:** Đây là false positive — Django chạy với thư mục `backend/` trong sys.path
nên `apps.*` hợp lệ lúc runtime (đã có tiền lệ `from apps.core.models import ...`).
**Áp dụng:** Bỏ qua cảnh báo resolve-path của linter cho `apps.*`; xác nhận bằng
`manage.py check`/pytest thay vì đổi cách import.
