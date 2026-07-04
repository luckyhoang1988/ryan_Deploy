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

## 2026-07-04 — Catalog/Update-tracking: test API dưới Celery-eager phải mock task nền
**Bối cảnh:** Thêm Package Catalog (tải installer từ URL) + tab "Updates" (dò máy lỗi thời
qua InstalledSoftware). Viết test cho endpoint `POST /packages/<id>/fetch/` và
`POST /updates/<id>/deploy/`.
**Bài học:**
1. **CELERY_TASK_ALWAYS_EAGER=True (settings.test) khiến `.delay()`/chord chạy ĐỒNG BỘ ngay
   trong request.** Test endpoint `fetch` sẽ gọi `downloader.fetch` thật (tải mạng qua
   urllib), và endpoint `updates deploy` gọi `launch_deployment` → chord `deploy_to_machine`
   → đẩy SMB thật. Phải monkeypatch `apps.packages.downloader.fetch` và
   `apps.deployments.orchestrator.launch_deployment` trong test, nếu không test treo/lỗi mạng.
2. **View import task/orchestrator BÊN TRONG hàm** (`from .tasks import ...` / `from
   apps.deployments.orchestrator import launch_deployment` trong action) → monkeypatch trên
   MODULE NGUỒN có hiệu lực vì tên được bind lúc gọi, không phải lúc import view. Đây là seam
   sạch để test mà không cần patch chính view.
3. **"Latest version" không parse version vendor** — dùng version đã `approved` mới nhất theo
   `-created_at` (newest = latest). So máy lỗi thời bằng `packaging.version` (đã có trong
   venv), fallback so chuỗi khác nhau. Máy có nhiều bản ghi khớp (Chrome vs "Chrome Helper"):
   chọn đại diện tên NGẮN nhất, và nếu bất kỳ dòng nào == latest thì coi máy đã cập nhật.
4. **Downloader dùng urllib stdlib** (không `requests` — tránh đụng pin cryptography==42 của
   impacket): stream ra file tạm + đếm byte để chặn trần dung lượng giữa chừng; validate
   scheme http/https trước (chống SSRF file://); dedup theo SHA-256 để tải lại không tạo trùng.
**Áp dụng:** Mọi endpoint kích hoạt task nền mà test dưới eager → mock ở tầng downloader/
orchestrator, đừng để task chạm mạng/SMB. Feature "so version fleet" → compare ở Python với
packaging.version, không SQL; heuristic latest = newest-approved, không parse chuỗi vendor.

## 2026-07-04 — Biểu đồ SVG thuần: pathLength=100 + biến CSS phải qua style, không qua attribute
**Bối cảnh:** Dựng donut/bar báo cáo dashboard bằng SVG nội tuyến (không thêm thư viện chart).
**Bài học:**
1. **Donut không cần tính chu vi:** đặt `pathLength={100}` trên `<circle>` → `strokeDasharray`
   và `strokeDashoffset` tính theo đơn vị %; mỗi slice là 1 circle với dasharray `${pct} ${100-pct}`,
   `strokeDashoffset={-acc}` (acc = % cộng dồn), cả nhóm `transform="rotate(-90 cx cy)"` để bắt đầu
   từ đỉnh. Không phải nhân/chia 2πr.
2. **Gotcha màu:** biến CSS chỉ resolve khi là CSS property, KHÔNG resolve khi là presentation
   attribute. `fill="var(--green)"` (attribute) → không hiện màu; phải dùng `style={{ fill: "var(--green)" }}`
   hoặc `style={{ stroke: ... }}`. Áp dụng cho mọi màu theo theme trong SVG.
3. **Tooltip nhẹ không cần JS:** `<title>` con trong `<rect>`/`<circle>` cho hover text native,
   accessible — đủ cho chart đơn giản, khỏi state/portal.
**Áp dụng:** Chart SVG trong dự án này: pathLength=100 cho arc, màu theme qua `style` không qua
attribute, `<title>` cho hover. Verify bằng `npm run build` + gọi endpoint thật, không chỉ đọc code.

## 2026-07-03 — "False success": installer trả exit 0 nhưng không cài (Firefox stub) + hậu kiểm
**Bối cảnh:** Deploy Firefox báo "Thành công" (exit 0, 2/2 máy) nhưng máy không có Firefox.
File upload chỉ 493 KB = **Firefox online stub installer** (trình tải nhỏ), không phải bộ cài.
**Bài học:**
1. **Engine chỉ tin exit code → stub trả 0 = false success.** Stub `/S` chạy dưới SYSTEM/
   session-0 (service tạm, không desktop) thoát ngay với 0, stdout rỗng, không cài gì. Bộ
   cài đúng: MSI enterprise (msiexec /i /qn) hoặc EXE offline đầy đủ ~60MB (NSIS /S). KHÔNG
   dùng "Firefox Installer.exe" (~500KB).
2. **Giải bằng hậu kiểm registry** (opt-in field `PackageVersion.verify_name`): sau khi
   install/uninstall báo thành công, chạy LẦN 2 `PushExecutor.run()` với `verify_installed.ps1`
   kiểm `HKLM\...\Uninstall` có DisplayName khớp không → exit 0/1. Install kỳ vọng CÓ, uninstall
   kỳ vọng MẤT. Sai → job FAILED với thông báo rõ.
3. **Gotcha quan trọng:** nếu bước verify KHÔNG chạy tới nơi (`vres.exit_code is None` = lỗi
   SMB/precheck), phải GIỮ nguyên thành công, KHÔNG kết luận — nếu không sẽ biến install thật
   thành thất bại chỉ vì trục trặc kết nối lúc kiểm. Chỉ khi verify chạy xong (exit_code != None)
   mà != 0 mới đánh false-success.
4. **Tái dùng executor cho lần 2:** PushExecutor tích luỹ `self._log` qua các lần run() → phải
   tạo INSTANCE MỚI cho lần verify (factory `make_executor`), không gọi run() lại trên cùng obj.
**Áp dụng:** Bất kỳ tác vụ mà "mã trả về" không chứng minh được kết quả (installer, script,
network op) → thêm hậu kiểm độc lập, và luôn phân biệt "kiểm thất bại" vs "kiểm không chạy được".

## 2026-07-03 — Picker frontend chỉ hiện 25 bản ghi vì DRF PageNumberPagination
**Bối cảnh:** Wizard tạo deployment chọn máy đích chỉ hiện 25/264 máy. `api.get("/machines/")`
+ `listOf()` chỉ lấy `results` của TRANG ĐẦU.
**Bài học:** `REST_FRAMEWORK.PAGE_SIZE=25` áp cho MỌI list endpoint, và không có
`page_size_query_param` nên client không override được bằng `?page_size=`. Component kiểu
"picker" (chọn tất cả) phải lấy HẾT các trang: helper `fetchAll(path)` lặp theo `data.next`
(URL tuyệt đối → cắt tiền tố `/api` lấy path+query gọi tiếp). Trang quản lý Machines thì
đúng vì nó có UI phân trang thật; chỉ các dropdown/checklist "cần đủ" mới dính bug này.
**Áp dụng:** Bất kỳ list nạp vào picker/checklist/multiselect → dùng `fetchAll`, không
`api.get`+`listOf`. Với danh sách lớn (264 máy) thêm ô lọc + nút "chọn hết (đang hiện)".

## 2026-07-03 — Đa loại action deployment (uninstall/reboot/shutdown/inventory/MSIX)
**Bối cảnh:** Mở rộng deployment vốn chỉ install thành 5 loại action, tái dùng chord/
semaphore/cancel/UI. Tổng quát hoá `PushExecutor.run()` cho payload tuỳ chọn + branch
theo `Deployment.action` trong `_run_job`.
**Bài học:**
1. **run.bat bọc mọi command với `> stdout.log 2>&1` + ghi `exit.code`** → cơ chế collect
   hoàn toàn command-agnostic. Nhờ đó thêm action mới chỉ là đổi (command, payload):
   installer→command có `{file}`, reboot→command hằng không payload, inventory→đẩy .ps1
   rồi đọc stdout. Không cần đụng `_collect_result`. Đây là seam đúng để mở rộng.
2. **Reboot/shutdown phải có delay** (`shutdown /r /t 30`): lệnh trả về NGAY (đặt lịch tắt),
   `exit.code`=0 kịp ghi & thu về TRƯỚC khi máy tắt ~30s. Nếu `/t 0` thì SMB rớt giữa
   collect → job treo/lỗi oan. Dùng `success_exit_codes=[0]` (không phải [0,3010]).
3. **PowerShell `ConvertTo-Json` đổi hình dạng theo số phần tử:** 1 item → object (không
   phải array), 0 item → chuỗi rỗng. Parser phải `if isinstance(data, dict): data=[data]`
   và xử lý stdout rỗng. Registry Uninstall có bản ghi trùng → dedupe (name,version) trước
   bulk_create vì `unique_together`.
4. **DRF field `source="package_version.package.name"` an toàn khi FK None:** sau khi cho
   `package_version` nullable (reboot/shutdown/inventory), các read-only field lồng nhau tự
   trả None (DRF `get_attribute` ngắt chuỗi ở None) — không cần `allow_null`, không crash.
5. **So sánh version trong targeting phải làm ở Python**, không SQL (string compare sai:
   "118" > "1200"? theo lexicographic là sai). Tách "." → tuple int rồi so. Rule
   `min_version` chỉ loại máy có bản >= ngưỡng (máy bản cũ vẫn cần nâng cấp).
**Áp dụng:** Khi engine đã bọc command + thu exit-code/stdout theo file, mở rộng loại tác
vụ là bài toán "sinh command + payload", đừng viết executor mới. Bất kỳ tác vụ nào làm rớt
kết nối (reboot/shutdown/logoff) phải trì hoãn đủ để thu kết quả trước.

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
**Bài học:** Dự án có sẵn `ryandeploy.settings.test` chạy SQLite in-file, dành riêng cho
`check`/`makemigrations`/`pytest` không cần Postgres.
**Áp dụng:** Mọi lệnh Django cục bộ (check, makemigrations, migrate, pytest) đặt
`DJANGO_SETTINGS_MODULE=ryandeploy.settings.test`. Dùng python từ `.venv/Scripts/python.exe`.

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
