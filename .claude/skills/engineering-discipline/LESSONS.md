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

## 2026-07-04 — Verify UI bằng CDP thô khi không có chromium-cli/Playwright (Windows)
**Bối cảnh:** Thêm Gauge CPU/RAM real-time vào Dashboard, cần "chạy thật trong trình duyệt"
nhưng máy Windows này không có `chromium-cli` lẫn Python `playwright` (chưa cài, tải browser
sẽ chậm/tốn).
**Bài học:**
1. Chrome hệ thống có sẵn tại `C:\Program Files\Google\Chrome\Application\chrome.exe`. Chạy
   `--headless=new --remote-debugging-port=<port> --user-data-dir=<scratch>` rồi lấy
   `webSocketDebuggerUrl` qua `GET http://127.0.0.1:<port>/json/version`. Mở tab mới phải
   dùng **PUT** `http://127.0.0.1:<port>/json/new?<url>` (Chrome bản mới từ chối GET, trả 405).
2. Package `websockets` đã có sẵn trong venv (dùng cho Channels) — đủ để tự viết driver CDP
   tối giản (~60 dòng): gửi `{id, method, params}` qua JSON, khớp response theo `id`.
3. **Điền input React controlled** không dùng `el.value=...` (không bắn onChange) mà dùng
   `el.focus(); document.execCommand('insertText', false, text)` — bắn input event thật,
   React nhận đúng. `form.requestSubmit()` để submit như người dùng thật.
4. Venv của dự án nằm ở **gốc repo** (`ryan_deploy/.venv`), không phải `backend/.venv`.
5. **Gotcha nguy hiểm:** `taskkill //F //IM node.exe //T` giết TẤT CẢ tiến trình node.exe
   trên máy (kể cả của project/tool khác đang chạy), không chỉ tiến trình Vite mình vừa mở.
   Phải tìm đúng PID (qua `netstat -ano` lọc theo port, hoặc lưu PID lúc `disown`) rồi
   `taskkill //F //PID <pid>` — không bao giờ diệt theo tên process dùng chung như node/python.
**Áp dụng:** Khi cần chụp màn hình xác nhận UI trên máy Windows không có sẵn công cụ
automation: dùng Chrome hệ thống + CDP thô qua `websockets`. Luôn dọn sạch (kill đúng PID,
xoá `test_db.sqlite3`/profile tạm) sau khi verify xong, và không bao giờ `taskkill` theo tên
tiến trình dùng chung.

## 2026-07-04 — Channels/WebSocket: daphne xung đột impacket, channels.testing cũng ăn theo
**Bối cảnh:** Thêm real-time (Django Channels) cho panel "Đang chạy" + live progress deploy,
theo kế hoạch ban đầu dùng `daphne` làm ASGI server (khuyến nghị phổ biến cho Channels).
**Bài học:**
1. **`daphne` KHÔNG tương thích với dự án này** — nó ghim cứng `twisted[tls]>=22.4`, mà
   `twisted[tls]` đòi `pyopenssl>=25.2.0`; trong khi `impacket==0.12.0` ghim cứng
   `pyOpenSSL==24.0.0` (xem [[cryptography-pin-impacket-conflict]]). Hai ràng buộc này
   loại trừ nhau tuyệt đối — không có version daphne nào né được vì pin nằm ở tầng
   twisted, không phải ở daphne. Giải: dùng **uvicorn + websockets** (thuần Python, không
   phụ thuộc OpenSSL binding nào) làm ASGI server thay thế; `INSTALLED_APPS` KHÔNG cần
   thêm `"daphne"` (đó là trick riêng của daphne để `manage.py runserver` tự ASGI-aware) —
   thay vào đó dev/prod phải chạy `uvicorn ryandeploy.asgi:application` tường minh
   (`manage.py runserver` vẫn chỉ là WSGI, không phục vụ được WebSocket).
2. **`channels.testing` (package, không phải submodule) import cứng `daphne.testing` ngay
   ở `__init__.py`** — nên dù chỉ cần `WebsocketCommunicator`, bất kỳ import nào xuyên qua
   `channels.testing.*` đều crash nếu không cài daphne (import submodule cũng không né
   được vì Python luôn chạy `__init__.py` của package cha trước). Giải: tự viết lại
   `WebsocketCommunicator` tối giản (~30 dòng) trên `asgiref.testing.ApplicationCommunicator`
   (lớp nền thật sự, nằm ngoài `channels.testing`) — xem `backend/tests/test_realtime.py`.
3. **Trước khi pin version mới cho bất kỳ lib nào, chạy `pip install` thật trong venv rồi
   `pip check`** — phát hiện xung đột sớm (ở đây: cài xong mới thấy `cryptography` bị kéo
   lên 49.0.0, `pyOpenSSL` lên 26.3.0, phá pin cũ) thay vì chỉ đọc changelog/tin vào version
   number. `pip index versions <pkg>` cho danh sách version thật để chọn bản mới nhất hợp lệ
   thay vì đoán.
4. **Kiểm thử real-time qua HTTP+WS thật (không chỉ pytest với scope tự dựng) lộ ra bug mà
   test giả không thấy:** script smoke test dùng `requests` (login lấy session cookie thật)
   + `websockets` client thật gọi `/ws/updates/` với header `Cookie`, xác nhận
   `AuthMiddlewareStack` đọc đúng session. Bug thực tế gặp: gửi `target_machines: []` khi
   tạo Deployment bị 400 (M2M không `blank=True` mặc định `allow_empty=False`, giống lỗi cũ
   ở DeploymentSchedule) nhưng code không kiểm `status_code` trước khi dùng `.json()["id"]`
   → không lỗi ngay mà TREO VÔ HẠN ở `await ws.recv()` chờ message không bao giờ tới. Luôn
   `assert r.status_code == 201` trước khi dùng response, và bọc `ws.recv()` bằng
   `asyncio.wait_for(..., timeout=N)` để lỗi hiện ngay thay vì treo.
**Áp dụng:** Dự án này VĨNH VIỄN không dùng được `daphne`/bất kỳ gì kéo theo
`twisted[tls]` trong khi còn ghim `impacket`. Channel layer dùng lại Redis đã có sẵn cho
Celery (không cần hạ tầng mới). Khi viết test Channels, tự dựng communicator tối giản thay
vì import `channels.testing`.

## 2026-07-04 — Recurring schedule: model "template" tách khỏi Deployment "instance" để giữ lịch sử
**Bối cảnh:** Thêm lịch lặp (interval/weekly, kiểu PDQ Repeating/Recurring). Deployment vốn
đã có `scheduled_at` cho lịch CHẠY-1-LẦN, và `Job` có `unique_together(deployment, machine)`
nên không thể tái dùng cùng 1 Deployment cho nhiều lần chạy lặp lại (lần 2 sẽ update_or_create
đè job của lần 1, mất lịch sử).
**Bài học:**
1. Tạo model riêng `DeploymentSchedule` (cấu hình mẫu: action/package_version/credential/
   target_machines/targeting_rule + recurrence_type/interval_minutes/weekly_days/weekly_time
   + enabled/last_triggered_at) KHÔNG kế thừa/dùng chung bảng với `Deployment`. Mỗi lần
   `is_due()` đúng, `spawn_deployment()` tạo Deployment MỚI (clone field + set target_machines)
   rồi gọi `launch_deployment()` y hệt luồng thủ công — không phải sửa orchestrator/executor.
2. `Deployment.schedule` (FK nullable, SET_NULL) trỏ ngược về lịch đã sinh ra nó — cho UI liệt
   kê lịch sử các lần chạy của 1 lịch mà không cần bảng phụ.
3. **`is_due()` cho weekly phải làm việc ở LOCAL time**, không phải `timezone.now()` (UTC):
   dùng `timezone.localtime(now)` để lấy đúng `weekday()`/giờ theo `TIME_ZONE` server, rồi so
   `last_triggered_at` (cũng phải `localtime()`) với mốc giờ hẹn hôm nay để biết "đã chạy hôm
   nay chưa" — so sánh thẳng bằng UTC sẽ sai ngày/giờ ở gần nửa đêm.
4. **Double-trigger guard**: `select_for_update()` + re-check `is_due()` TRONG transaction,
   set `last_triggered_at` xong mới launch NGOÀI transaction (giống pattern claim SCHEDULED→
   RUNNING của `trigger_scheduled_deployments`). sqlite không lock thật (chỉ Postgres prod mới
   chặn race thật) nhưng logic vẫn đúng đơn luồng cho test.
5. **DRF M2M field trên model không `blank=True` mặc định `allow_empty=False`**: POST
   `target_machines: []` bị chặn "This list may not be empty." — test API phải luôn kèm
   ít nhất 1 id, không thể để rỗng như khi tạo qua ORM trực tiếp.
**Áp dụng:** Bất kỳ tính năng "lặp lại tự động" nào sinh ra bản ghi audit/lịch sử → tách model
CẤU HÌNH khỏi model KẾT QUẢ MỘT LẦN CHẠY, đừng tái dùng unique_together của bảng kết quả.
So sánh ngày/giờ theo lịch địa phương luôn qua `timezone.localtime()`, không thao tác trực
tiếp trên datetime UTC của `timezone.now()`.

## 2026-07-04 — Package catalog: property lọc (`.filter().first()`) không ăn cache của prefetch_related thường
**Bối cảnh:** Review toàn bộ backend so với PDQ Deploy để tìm bug/tối ưu. `Package.latest_version`
là `@property` gọi `self.versions.filter(approved=True).first()`. `updates.compute_updates()` và
`PackageViewSet` đều gọi `prefetch_related("versions")` tưởng đã tránh N+1, nhưng KHÔNG — vì
`.filter()` luôn phát sinh query mới, bỏ qua cache prefetch (cache chỉ dùng được cho `.all()`
không lọc thêm). Tệ hơn: `match_name` gọi lại `self.latest_version` lần 2 trên CÙNG instance →
double query mỗi package. Đo thực tế bằng `CaptureQueriesContext`: `compute_updates()` với 20
package tốn ~62 query trước fix, 22 sau fix; `GET /api/packages/` còn 6 query cố định (trước đó
tỉ lệ thuận số package).
**Bài học:** 2 lớp fix riêng biệt cần cả hai mới hết N+1:
1. Đổi `@property` → `@cached_property` để tránh gọi lại query trên CÙNG instance (vd property A
   gọi property B cùng nguồn dữ liệu).
2. Dùng `Prefetch(rel, queryset=..., to_attr="_cache_attr")` riêng (không phải `prefetch_related("rel")`
   trơn) rồi trong property check `getattr(self, "_cache_attr", None)` trước khi query — đây là
   cách DUY NHẤT để property có điều kiện lọc (`.filter()...first()`) ăn được cache prefetch khi
   liệt kê nhiều instance. Có thể dùng CÙNG lúc 2 Prefetch khác `to_attr` cho cùng 1 relation
   (vd "versions" đầy đủ cho serializer + "_approved_versions_prefetched" đã lọc cho property).
**Áp dụng:** Bất kỳ property nào gọi `related_manager.filter(...).first()/.exists()` (không phải
`.all()`) mà được dùng trong list/loop nhiều instance → không tin `prefetch_related("rel")` trơn
là đủ; phải verify bằng `CaptureQueriesContext` thực tế, và nếu cần cache thì bắt buộc `Prefetch(to_attr=...)`
+ property tự đọc `getattr`. `cached_property` giải quyết double-query trong CÙNG instance nhưng
không giải quyết N+1 giữa các instance — cần cả hai.

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
