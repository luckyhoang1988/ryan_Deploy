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

## 2026-07-10 — enroll_machine reject cứng "còn token active" gây deadlock enroll vô hạn khi agent mất token cục bộ; agent subprocess.run(shell=True, timeout=) treo vĩnh viễn trên Windows nếu installer sinh tiến trình cháu
**Bối cảnh:** Điều tra ZP-IT006 "hay mất kết nối" — SSH vào prod, đọc DB/log thật thay vì đoán,
phát hiện 2 lỗi độc lập cùng ngày. (1) `enroll_machine()` (`backend/apps/agents/services.py`)
từ chối cứng re-enroll nếu `AgentToken` active đã tồn tại — đúng cho trường hợp bị chiếm, nhưng
sai cho trường hợp agent tự mất token cục bộ (crash/mất ProgramData) rồi tự động re-enroll qua
`enrollment_secret` (`poll_loop.py::_recover_auth`): server luôn từ chối, agent lặp lại backoff
tới 300s **mãi mãi**, chỉ hết khi admin revoke tay — đã xảy ra 2 lần trong 1 ngày cho cùng 1 máy
(audit log ghi rõ lần đầu phải revoke thủ công). (2) `agent/ryandeploy_agent/executor.py::_run_command`
dùng `subprocess.run(shell=True, timeout=..., capture_output=True)` — trên Windows, khi timeout,
Python chỉ `kill()` được tiến trình con trực tiếp (cmd.exe), KHÔNG kill được tiến trình cháu mà
installer tự tách ra; cháu vẫn giữ handle pipe stdout/stderr mở khiến `communicate()` nội bộ gọi
lại NGAY SAU kill() treo vĩnh viễn chờ EOF không bao giờ tới — toàn bộ thread duy nhất của agent
(heartbeat+poll+execute dùng chung 1 thread) chết cứng, agent offline vĩnh viễn dù `job_timeout`
đã cấu hình.
**Bài học:**
1. Một EnrollmentError "reject cứng vì đã có tài nguyên active" cần phân biệt "tài nguyên đó có
   đang thực sự sống hay không" trước khi chặn tuyệt đối — dùng tín hiệu độc lập đã có sẵn
   (`Machine.is_online`, do watchdog `mark_stale_machines_offline` tự set False khi hết hạn
   heartbeat) làm điều kiện gate thay vì chỉ check "tồn tại token active". `is_online=False` ⇒
   token cũ nhiều khả năng đã chết cục bộ, an toàn tự thu hồi+cấp lại; `is_online=True` ⇒ giữ
   nguyên reject (vẫn còn 1 agent thật đang sống giữ token đó).
2. `subprocess.run(..., timeout=N)` trên Windows KHÔNG đảm bảo tiến trình con của tiến trình con
   bị dọn khi timeout — chỉ đúng với process tree phẳng (không tự spawn cháu/relaunch). Muốn
   timeout thật sự đáng tin với các lệnh có thể spawn cháu (đặc biệt installer .exe tự relaunch
   elevated), phải tự kill cả process tree (VD `taskkill /T /F /PID`), không dựa vào
   `Popen.kill()`/`subprocess.run(timeout=)` mặc định.
**Áp dụng:** Khi thấy 1 EnrollmentError/PermissionError "reject vì tài nguyên đã tồn tại" mà
tài nguyên đó do 1 tiến trình nền có thể chết âm thầm sở hữu — tìm tín hiệu "còn sống hay không"
độc lập đã có sẵn trong model (đừng thêm field mới nếu đã có) để gate auto-remediation an toàn.
Bất kỳ agent nào chạy job/lệnh dài với `timeout=` trên Windows qua `subprocess` — audit lại xem
lệnh có khả năng spawn tiến trình cháu không; nếu có, phải kill cả cây tiến trình khi timeout,
không tin `subprocess.run(timeout=)` tự dọn sạch.

---

## 2026-07-09 — purge_all CASCADE giết token → agent 401 vĩnh viễn nếu không còn enrollment_secret
**Bối cảnh:** Prod báo 0 máy online dù agent đã cài. Log: heartbeat/poll 401 liên tục từ
`10.0.193.251`. Timeline nginx: heartbeat 200 tới 14:09 → 401 từ 14:16; `purge_all` force
200 lúc 14:19 (và lại lúc 14:32, 15:54). DB: 0 AgentToken, secret #2 hết hạn 2026-07-08.
**Bài học:**
1. `Machine` delete CASCADE `AgentToken` — purge/sync lại AD tạo Machine mới cùng hostname
   nhưng token cũ trên đĩa client đã chết; agent chỉ tự re-enroll nếu `agent.ini` còn
   `enrollment_secret` (token cấp tay qua UI thường không có secret → kẹt 401 mãi).
2. Heartbeat 401 không kích hoạt `_recover_auth` — chỉ poll 401 mới đếm; khi debug “online”
   phải xem cả poll 401 và có/không gọi `/enroll`.
3. Gia hạn `EnrollmentSecret.expires_at=None` chỉ giúp máy còn secret trên đĩa; máy chỉ còn
   token chết vẫn cần xóa dòng `token=` (hoặc cấp token mới) rồi restart service.
**Áp dụng:** Trước purge_all force: backup/export token hoặc đảm bảo MSI/GPO còn secret.
Khi 401 hàng loạt sau purge → kiểm tra `AgentToken.count()==0` và secret còn hạn trước,
rồi sửa client `agent.ini` / provision lại — không chỉ nhìn UI online.

---

## 2026-07-09 — P1 harden: approved/zip-agent validate sớm; report+mode gate; release_slot Lua
**Bối cảnh:** Sau P0 cleanup, vá cụm P1: deploy version chưa duyệt, agent+zip fail muộn lúc
poll, AgentJobReportView không check connection_mode, bulk/PATCH đổi mode khi còn job active,
`release_slot` GET-then-DECR TOCTOU.
**Bài học:**
1. Validate agent+zip phải đọc `target_machines` đã resolve (list Machine) trong serializer
   `validate()`, kể cả partial update (fallback `instance.target_machines.all()`) — không chỉ
   dựa vào poll-time fail.
2. FakeRedis trong `test_semaphore.py` phải implement `eval()` khi `release_slot` chuyển sang
   Lua; test assert `eval` được gọi (không chỉ hành vi counter) để tránh regress về GET+DECR.
3. Bulk đổi mode: chỉ chặn máy **đang đổi** (`exclude(connection_mode=mode)`) còn job active —
   máy đã đúng mode vẫn no-op update được, tránh fail cả batch OU vì 1 máy đang deploy.
**Áp dụng:** Mọi gate “transport/mode” (poll, report, đổi mode) phải đối xứng. Semaphore
guarded counter trên Redis → luôn atomic script, không GET rồi DECR tách rời.

---

## 2026-07-09 — Collect timeout / stale RUNNING phải cleanup residue SMB (không chỉ cancel)
**Bối cảnh:** Review P0: `cleanup_now` chỉ gọi khi cancel giữa collect hoặc khi `poll_once`
đọc được `exit.code`. Nhánh timeout và watchdog `reconcile_stuck_deployments` đánh FAILED
mà không dọn → service `RyanDeployRunner_job{N}` + file dưới `ADMIN$\RyanDeploy\Runner\`
sót trên máy đích (LocalSystem).
**Bài học:** Mọi đường kết thúc job SMB mà **không** đi qua `poll_once` (đã đọc exit.code →
tự `_best_effort_cleanup`) đều phải gọi cùng helper cleanup. Đổi tên `_cleanup_cancelled_target`
→ `_cleanup_target_residue` vì dùng chung cancel/timeout/reconcile. Reconcile chỉ cleanup khi
`connection_mode=smb` (agent không dùng PushExecutor). Test reconcile phải stub
`_cleanup_target_residue` (không SMB thật); test timeout assert `cleanup_now_calls`.
**Áp dụng:** Khi thêm nhánh terminal mới cho job SMB (FAILED/CANCELLED mà chưa collect xong),
hỏi ngay: "ai dọn service/file trên máy đích?" — nếu không phải `poll_once` thì gọi
`_cleanup_target_residue`.

---

## 2026-07-06 — Tách blocking collect-loop khỏi PushExecutor: chuỗi start()/poll_once() qua 2 Celery task, 2 gotcha ordering dưới eager mode
**Bối cảnh:** `PushExecutor.run()` (executor.py) chiếm 1 Celery worker process suốt toàn bộ
thời gian cài đặt (tới 30 phút, `_collect_result` sleep-poll SMB mỗi 3s trong 1 task duy
nhất) — giới hạn số máy cài song song thực tế bằng số worker process, bất kể
`Deployment.max_concurrency`. Tách thành `start()` (precheck/copy/execute, nhanh) +
`poll_once()` (đọc exit.code 1 lần, không sleep-loop) trong `push_executor.py`, và tách
`deploy_to_machine` thành `_start_and_dispatch` + `collect_job_result` (task Celery mới tự
`self.retry(countdown=...)` để nhường worker giữa các lần poll) trong `jobs/tasks.py`.
**Bài học:**
1. **Đổi return-value contract của task khi tách hàm dễ làm mất field mà caller/test dựa
   vào.** Bản nháp đầu tách `_run_job`→`_start_and_dispatch` trả `bool` (handed_off) thay vì
   dict gốc `{"status":..., "error":...}` — làm `deploy_to_machine` trả `{"status":"handled"}`
   chung chung, vỡ `test_credential_failure.py` vốn assert `result["status"]=="failed"` và
   `result["error"]=="credential_decrypt_failed"`. Sửa: giữ nguyên dict trả về ở MỌI nhánh
   (kể cả nhánh mới "collecting"), suy ra `handed_off` từ `result.get("status")=="collecting"`
   thay vì có 1 biến bool riêng. Khi tách 1 hàm nội bộ có return-value được test/caller dựa
   vào từng field cụ thể, đừng đơn giản hoá kiểu trả về (bool/None) chỉ vì logic mới "chỉ cần
   biết có/không" — vẫn phải trả đủ shape cũ.
2. **`CELERY_TASK_ALWAYS_EAGER=True` (settings.test) làm `apply_async()` chạy task MỚI ĐỒNG BỘ
   TỚI HẾT (kể cả các `self.retry()` đệ quy bên trong) trước khi trả về** — không chỉ
   `.delay()`+`.get()` mới eager, mà bất kỳ `apply_async()` nào không gọi `.get()` cũng vẫn
   chạy xong toàn bộ trước khi statement tiếp theo chạy. Code ban đầu gọi
   `collect_job_result.apply_async(...)` RỒI MỚI `Job.objects.filter(...).update(output=...,
   celery_task_id=async_result.id)` — dưới eager, `collect_job_result` (và mọi lần retry của
   nó) đã ghi xong kết quả CUỐI CÙNG trước khi dòng `update()` đó chạy, nên nó ĐÈ LÊN log
   collect vừa ghi bằng log start() cũ (mất log collect) và set `celery_task_id` thành 1 giá
   trị của task đã xong từ lâu. Production (broker thật) không lộ bug này vì `apply_async` chỉ
   enqueue message rồi return ngay (task chưa chạy), che giấu race. Fix: tự sinh `task_id =
   uuid.uuid4().hex`, ghi DB (`output`, `celery_task_id=task_id`) TRƯỚC, rồi mới
   `apply_async(..., task_id=task_id)` — loại bỏ phụ thuộc thứ tự thực thi giữa 2 môi trường
   thay vì dựa vào `async_result.id` (chỉ có SAU khi gọi, và dưới eager thì "sau" nghĩa là
   "sau khi task đã chạy xong").
3. **Monkeypatch 1 method lên class fake trong 1 test rồi `del` để "khôi phục" là SAI** — nếu
   gán `_FakeExecutor.start = new_func` (ghi đè hẳn, không phải wrap), `del
   _FakeExecutor.start` xoá luôn thuộc tính, không "lộ lại" method gốc định nghĩa trong class
   body (không có gì để lộ lại — đã bị ghi đè mất). Test sau đó gọi `.start()` sẽ
   `AttributeError`. Phải lưu `orig = _FakeExecutor.start` trước khi gán đè, và khôi phục bằng
   `_FakeExecutor.start = orig` trong `finally`, không dùng `del`.
**Áp dụng:** Khi thay 1 vòng lặp block-worker bằng mô hình "start rồi tự poll qua
self.retry()", tách state cần thiết để RESUME (ở đây: `job_token` deterministic
`f"job{job.pk}"` có sẵn, không cần field DB mới) khỏi state chỉ tồn tại trong biến cục
bộ/instance (log của executor) — cái sau phải ghi xuống DB TRƯỚC KHI giao việc cho task tiếp
theo, không phải sau, để không phụ thuộc thứ tự thực thi giữa eager/broker thật. Khi test
Celery task tự retry bằng cách mock: luôn tự hỏi "dưới eager mode, dòng code SAU
apply_async()/self.retry() có bị đối thủ ghi đè trước không" trước khi tin thứ tự viết trong
code nguồn phản ánh đúng thứ tự chạy thực tế.

---

## 2026-07-06 — Sửa 10 finding High từ báo cáo review; 3 gotcha môi trường phải verify trước khi code
**Bối cảnh:** Sau khi vá xong 3 Critical, tiếp tục 10 finding High (core/credentials/machines/
deployments/jobs/executor/audit/frontend) từ cùng báo cáo review. Trước khi viết fix, verify
3 điểm kỹ thuật thay vì đoán — cả 3 đều đổi thiết kế fix ban đầu.
**Bài học:**
1. **`select_for_update()` trên SQLite không raise lỗi — âm thầm bỏ qua khoá** (test dùng
   `ryandeploy.settings.test`, sqlite; `connection.features.has_select_for_update == False`
   nhưng gọi vẫn chạy, chỉ là không khoá thật). Xác nhận bằng cách chạy thật trong Django
   shell trước khi dùng cho fix race-condition ở `UserViewSet` (khoá admin cuối cùng,
   `apps/core/views.py::_locked_admin_capable`). Production dùng PostgreSQL (`base.py`,
   `has_select_for_update == True`) nên khoá có hiệu lực thật ở đó — nhưng nghĩa là test
   trên SQLite KHÔNG thể chứng minh race thật sự bị chặn, chỉ xác nhận code path không lỗi.
   Codebase đã có tiền lệ dùng pattern này thành công (`deployments/tasks.py::trigger_due_schedules`,
   dòng ~139) — nên tái dùng, không phát minh cơ chế lock khác.
2. **pytest-django tự ép `DEBUG=False` cho MỌI test, bất kể `DEBUG` thật trong settings
   module đang dùng** (ở đây `ryandeploy.settings.test` đặt `DEBUG=True` nhưng pytest-django
   override lại). Fix ban đầu định gate 1 fallback (vault dev-key) bằng `settings.DEBUG` —
   sai hoàn toàn vì test sẽ luôn thấy `DEBUG=False` dù chạy trong môi trường "dev-like".
   Phát hiện qua chạy test thật (fail ngay ở lần chạy đầu), không phải đọc doc trước.
   **Áp dụng:** không bao giờ dùng `settings.DEBUG` làm tín hiệu môi trường trong logic mà
   test cần verify hành vi — dùng cờ config riêng, tường minh (VD `RYANDEPLOY["VAULT_DEV_FALLBACK"]`,
   set explicit trong từng settings module) thay vì suy diễn từ `DEBUG`.
3. **impacket không cài trong venv dự án** (chỉ pin trong `requirements.txt`, chưa `pip
   install`), nên không thể tự kiểm API (`is_directory()` trên entry trả về từ
   `SMBConnection.listPath()`) bằng cách import trực tiếp. `pip install`/`pip download`
   impacket qua mạng liên tục thất bại — tải xong `.tar.gz` (đúng size) nhưng file biến mất
   hoặc lỗi `OSError: Invalid argument` khi mở lại ngay sau đó, nhiều khả năng do AV/Defender
   quarantine âm thầm file nén có tên "impacket" (công cụ pentest hay bị heuristic chặn).
   **Áp dụng:** khi cần đọc source 1 thư viện pin nhưng không cài được do bị quarantine dạng
   archive, fetch trực tiếp TỪNG FILE `.py` qua raw.githubusercontent.com (tag đúng version,
   VD `impacket_0_12_0`) — file text đơn lẻ không bị flag như archive. Xác nhận được
   `SharedFile.is_directory()` (snake_case, trong `impacket/smb.py`) bằng cách này.
4. **Đổi `choices` của 1 `CharField` (thêm action mới vào `AuditLog.Action`) vẫn cần
   migration** dù không đổi kiểu cột/schema DB thật — Django track `choices` như 1 phần
   field state cho lịch sử migration. `makemigrations --check --dry-run` bắt được thiếu sót
   này; đừng bỏ qua bước này chỉ vì "chỉ thêm text choice, chắc không cần migration".

---

## 2026-07-05 — Vá 2/3 finding Critical audit ngoài; finding thứ 3 (command injection install_command) không xác nhận được
**Bối cảnh:** Sau /clear, tiếp tục xử lý báo cáo review 35 finding (3 Critical) từ phiên
trước. Đọc lại code hiện tại (đã có nhiều lớp hardening từ các phiên trước đó) để verify
từng finding trước khi sửa, theo đúng bài học 2026-07-05 "Verify lại 1 review ngoài".
**Bài học:**
1. **`credential.get_password()` (giải mã Fernet) không được bọc try/except tại
   `apps/jobs/tasks.py::_run_job`** — job đã claim `RUNNING` (update() atomic ở đầu hàm)
   trước khi gọi decrypt; nếu VAULT_KEY bị xoay hoặc ciphertext hỏng, `vault.decrypt()`
   ném `InvalidToken`/`ValueError` thoát thẳng khỏi Celery task, không còn nơi nào ghi
   `FAILED` → job kẹt `RUNNING` vĩnh viễn, phải sửa DB thủ công. Fix theo đúng pattern đã
   có sẵn cho lỗi đọc file installer (integrity check OSError, cùng hàm): bọc riêng lệnh
   decrypt, ghi `FAILED` qua `_write_job_result` rồi return, không audit JOB_FINISH (nhất
   quán với 2 nhánh integrity-fail hiện có, chúng cũng không audit).
2. **Archive `.zip` (InstallerType.ZIP) được `PushExecutor._copy_payload` giải nén bằng
   `tar -xf` NGAY TRÊN MÁY ĐÍCH dưới quyền SYSTEM, nhưng KHÔNG có bước validate nào trước
   đó** — cả 2 điểm tạo `PackageVersion` (upload thủ công qua `PackageVersionSerializer`,
   VÀ tải từ URL qua `downloader.fetch()` — đường này hoàn toàn KHÔNG đi qua serializer)
   đều thiếu kiểm tra zip-slip (entry `../` hoặc absolute path ghi đè file ngoài thư mục
   giải nén) và zip-bomb (tỉ lệ nén bất thường / tổng dung lượng giải nén làm đầy đĩa toàn
   fleet). Thêm `repository.validate_zip_archive()` dùng `zipfile.ZipFile(...).infolist()`
   (chỉ đọc central directory, KHÔNG giải nén thật nên an toàn để kiểm tra) — check
   `os.path.normpath()` không tuyệt đối/không bắt đầu bằng `..`/không có `:` (ổ đĩa
   Windows), tỉ lệ `file_size/compress_size` mỗi entry, và tổng `file_size` so với trần
   (mặc định `MAX_INSTALLER_MB * 10`). Gọi hàm này ở CẢ HAI điểm tạo (serializer
   `validate()` object-level — cần cả `installer_file` lẫn `installer_type` nên không đặt
   trong `validate_installer_file` field-level; và `downloader.fetch()` trước khi lưu
   file) — chỉ vá 1 điểm là không đủ vì đây là 2 đường tạo `PackageVersion` độc lập nhau.
3. **Finding thứ 3 ("command injection" ở `push_executor.py:301-306`, nơi
   `install_command`/`uninstall_command` ghép thẳng vào `.bat` không escape) KHÔNG xác
   nhận được là lỗ hổng phân biệt được với thiết kế có chủ đích** sau khi verify: (a)
   field này chỉ set được qua `PackageVersionSerializer`, và CẢ `PackageViewSet` lẫn
   `PackageVersionViewSet` đều `permission_classes = [IsAdmin]` — không có endpoint nào
   khác chạm được field; (b) tên file installer (kể cả suy từ `Content-Disposition` khi
   tải qua URL ở `downloader._filename_from`, vốn do SERVER NGOÀI kiểm soát) đều đi qua
   `FileSystemStorage.get_valid_name()` (Django) trước khi lưu — đã tự verify bằng
   `get_valid_filename('a" & del /q C:\\* & "b.exe')` → `'a__del_q_C__b.exe'`, tức dấu
   `"`/`&`/khoảng trắng đều bị strip, không có đường tiêm qua filename. Vậy
   `install_command` là 1 chuỗi lệnh HOÀN TOÀN do admin đã-qua-RBAC tự viết — đây chính là
   tính năng cốt lõi của công cụ (giống PDQ Deploy: admin viết silent-install command chạy
   SYSTEM trên máy đích theo thiết kế), không phải input từ nguồn kém tin cậy hơn để
   "tiêm". Đã hỏi user, chọn KHÔNG sửa (không có gì để "escape" một cách có ý nghĩa khi
   toàn bộ chuỗi CHÍNH LÀ lệnh cần chạy) — ghi chú lại thay vì ép fix cho có.
**Áp dụng:** Khi 1 report review liệt kê "command injection" cho 1 field text tự do mà
sản phẩm CỐ Ý cho phép admin viết lệnh tuỳ ý (deployment tool kiểu PDQ) — luôn kiểm tra
2 việc trước khi tin: (a) RBAC nào thực sự gate được field đó (đọc permission_classes của
ViewSet, không đoán), (b) có đường nào khác (vd tải từ URL ngoài, tên file server khác trả
về) đưa dữ liệu KÉM TIN CẬY HƠN vào cùng field không — nếu cả 2 đều "chỉ admin, không có
đường phụ" thì đây là ranh giới tin cậy có chủ đích, không phải bug. Archive `.zip` giải
nén trên máy đích luôn cần validate zip-slip + zip-bomb ở MỌI điểm tạo bản ghi (không chỉ
đường upload chính qua serializer — các đường "phụ" như tải-từ-URL dễ bị quên vì không đi
qua cùng 1 lớp validation).

---

## 2026-07-05 — "Deploy from Library": Wizard tách component dùng chung, vite proxy cần đúng port 8000
**Bối cảnh:** Thêm nút "Deploy" 1 chạm từ trang Packages (mở sẵn `DeploymentWizard` với package
version pre-fill), tách `Wizard` cục bộ của `Deployments.jsx` thành `components/DeploymentWizard.jsx`
dùng chung cho cả 2 trang. Verify bằng dev server thật (Django settings.test + Vite) + Chrome
headless/CDP (không có Playwright, theo pattern đã ghi ở bài học 2026-07-04/2026-07-05).
**Bài học:**
1. **`vite.config.js` proxy `/api`→`http://localhost:8000` là HARDCODE, không đọc env var** — chạy
   Django dev server ở port khác (vd 8123 để tránh xung đột) sẽ khiến mọi gọi API từ UI 404/lỗi
   CORS âm thầm mà trang vẫn "load" bình thường (chỉ rỗng dữ liệu). Phải chạy đúng port 8000, hoặc
   sửa `vite.config.js` nếu cần port khác — không giả định proxy tự thích ứng.
2. **Port 5173 có thể đã bị chiếm bởi tiến trình khác của máy** (không phải của mình) — Vite tự
   nhảy sang 5174 và in rõ trong log ("Port 5173 is in use, trying another one..."). Luôn đọc log
   khởi động để lấy ĐÚNG port thực tế trước khi điều hướng CDP, đừng giả định cổng mặc định.
3. **RBAC bằng Django Groups, không phải field `role` trên User** (xem `apps/core/permissions.py`):
   seed user test phải `Group.objects.get_or_create(name="admin"|"operator")` rồi `user.groups.set([g])`,
   KHÔNG set `user.role = "..."` (field không tồn tại, `get_or_create(role=...)` ném
   `FieldError` ngay).
4. **Xác nhận pre-fill đúng bằng cách đọc `select.value`/`selectedIndex` qua CDP `Runtime.evaluate`**
   (không chỉ chụp ảnh màn hình) — case này quan trọng vì mục tiêu chính của tính năng là
   "đúng version được chọn sẵn", một chi tiết dễ sai (off-by-one, so sánh string vs number) mà
   ảnh chụp không lộ nếu 2 version trùng tên hiển thị.
**Áp dụng:** Trước khi verify UI bằng dev server: đọc `vite.config.js` lấy đúng port backend cần
chạy (đừng tự chọn port tuỳ ý), đọc log Vite để lấy port thực tế nếu 5173 bận. Seed role test qua
Django Groups. Verify giá trị pre-fill của form control qua DOM property (`.value`), không chỉ
qua ảnh chụp màn hình.

## 2026-07-05 — Package .zip nhiều file (Office2016): {dir} token + tar.exe extract, quirk quoting {file}/{dir} có sẵn
**Bối cảnh:** Thêm `InstallerType.ZIP` để deploy được bộ cài nhiều file/thư mục (VD Office2016
offline source) — nén thành 1 file `.zip`, `PushExecutor` tự giải nén trên máy đích bằng `tar.exe`
vào thư mục con "extracted" TRƯỚC khi chạy `install_command`, token mới `{dir}` trỏ tới thư mục đó.
**Bài học:**
1. **`DEFAULT_SILENT_COMMANDS` đặt token NẰM TRONG dấu ngoặc kép của chính literal string** (VD
   `exe`: `'"{file}" /S'` — dấu `"` bao quanh cả `{file}`), trong khi `_copy_payload` lại thay
   `{file}`/`{dir}` bằng giá trị ĐÃ TỰ QUOTE (`f'"{payload_disk}"'`). Kết quả thực tế là chuỗi có
   dấu nháy kép LẶP ở đầu (`""C:\...\x.exe"` chứ không phải `"C:\...\x.exe"`) — đây là quirk CÓ SẴN
   từ trước cho msi/exe/msix (không phải bug tôi tạo ra khi thêm "zip"), và test không nên tự đoán
   chuỗi kỳ vọng bằng tay (dễ sai) mà phải tính `template.replace(token, f'"{disk}"')` giống hệt
   code thật rồi so sánh, hoặc chỉ assert các phần không phụ thuộc dấu ngoặc (VD `bat.index(...)`
   thứ tự trước/sau).
2. **`tar.exe` builtin của Windows (từ 10 1803 / Server 2019) giải nén được `.zip`** (dùng bsdtar
   nội bộ) — chọn thay vì `powershell Expand-Archive` vì không đụng `-ExecutionPolicy`/AMSI. CHƯA
   verify trên máy Windows thật (môi trường này không có máy đích Windows để chạy end-to-end) —
   chỉ verify được ở mức unit test (SMB giả lập ghi/đọc bat) + đọc tài liệu Microsoft xác nhận
   `tar.exe` có sẵn từ các phiên bản đó.
3. Thêm 1 member mới vào `TextChoices` (VD `InstallerType.ZIP`) LUÔN sinh migration `AlterField`
   dù cột DB không đổi kiểu — đã biết từ bài học 2026-07-03 (JsonFormatter) nhưng nhắc lại vì dễ
   quên chạy `makemigrations` sau khi sửa `choices`.
**Áp dụng:** Khi thêm placeholder/token mới cho command template trong engine này, kiểm tra xem
template mẫu có tự bọc quote quanh token không trước khi viết test so sánh chuỗi cuối. Tính năng
"giải nén trên máy đích" nào cũng nên ưu tiên `tar.exe`/binary có sẵn của Windows hơn PowerShell có
policy, nhưng ghi rõ trong PR/lesson là CHƯA test thật trên Windows nếu không có máy để verify.

## 2026-07-05 — rm -rf dọn dẹp sau verify: xóa nhầm backend/media/packages/ (không phải do mình tạo)
**Bối cảnh:** Sau khi verify UI redesign Wizard bằng backend thật (settings.test, sqlite), dọn
dẹp bằng `rm -f test_db.sqlite3 && rm -rf backend/media/packages 2>/dev/null` trong CÙNG một
lệnh Bash — đoán (sai) rằng thư mục `media/packages/` là do seed script của mình tạo ra, không
kiểm tra trước nội dung. Thực tế `media/packages/` không liên quan gì tới seed (installer của
mình đi vào `media/repository/...` qua `installer_upload_path`, đã grep xác nhận không có
`upload_to` nào trỏ vào `packages/`) — đây là dữ liệu thật còn sót lại từ trước, và `rm` trong
Git Bash xóa thẳng không qua Recycle Bin nên mất vĩnh viễn.
**Bài học:** Trước khi `rm -rf` bất kỳ thư mục nào để "dọn dẹp sau verify", PHẢI `ls`/kiểm tra
nội dung + mtime trước, và chỉ xóa đúng path mình đã tạo ra trong chính session đó (đối chiếu
lại lệnh đã dùng để TẠO nó, không suy đoán theo tên thư mục "nghe có vẻ liên quan"). Không bao
giờ gộp lệnh xóa dọn dẹp vào cùng 1 dòng với các lệnh khác mà không xem kỹ từng target — nguyên
tắc "đọc trước khi xoá" trong system prompt áp dụng cả cho thao tác dọn rác tưởng như vô hại,
không chỉ cho `git reset`/`checkout`.
**Áp dụng:** Với mọi bước dọn dẹp sau khi verify (xoá DB test, file tạm, thư mục scratch) — liệt
kê chính xác các path mình đã tạo trong session (từ lệnh tạo, không đoán), `ls -la` xem mtime/
nội dung trước khi xoá bất kỳ thư mục nào không chắc chắn 100% là của mình, và xoá riêng từng
lệnh một để dễ dừng lại nếu phát hiện sai.

## 2026-07-05 — CDP: React input cần native setter, không dùng execCommand; cookie dùng chung giữa các tab cùng Chrome profile
**Bối cảnh:** Verify redesign Wizard tạo deployment bằng Chrome headless + CDP thô (không có
Playwright/chromium-cli, theo pattern đã ghi ở bài học 2026-07-04). Cần đăng nhập với 2 role
khác nhau (admin/operator) để so sánh danh sách action hiển thị.
**Bài học:**
1. `document.execCommand('insertText', ...)` sau `el.focus()` KHÔNG kích hoạt React onChange
   một cách đáng tin cậy trong Chrome headless mới (149.x) — form vẫn gửi giá trị rỗng dù
   screenshot lúc điền trông như đã có chữ ở lần chạy trước đó (thực ra là do lỗi khác, xem
   mục 2). Cách chắc chắn: gọi thẳng native value setter rồi tự bắn event `input`:
   `Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value').set.call(el, value)`
   rồi `el.dispatchEvent(new Event('input', {bubbles: true}))` — đây là cách React nhận đúng
   thay đổi giá trị đến từ ngoài component (không qua bàn phím thật).
2. Mở "tab mới" bằng `PUT /json/new?url` trên CÙNG một Chrome instance (cùng `--user-data-dir`)
   nghĩa là CÙNG session cookie — đăng nhập user B ở tab mới trong khi tab/tiến trình trước còn
   cookie của user A sẽ không có tác dụng nếu app tự động điều hướng khỏi `/login` do đã có
   session hợp lệ (React Router guard), khiến trang không có form đăng nhập nữa và test lặng lẽ
   chạy với session CŨ. Phải `Network.enable` + `Network.clearBrowserCookies` trước khi test
   role khác trong cùng 1 Chrome profile, rồi mới `Page.navigate` tới `/login`.
3. Vite dev server (`server.port: 5173`, không set `host`) bind vào `::1` (IPv6 loopback), KHÔNG
   bind `127.0.0.1` — `curl http://127.0.0.1:5173` trả "Connection refused" dù server đã chạy
   ("ready in Nms"), phải gọi qua `http://localhost:5173` (hoặc `[::1]:5173`) mới thấy 200.
**Áp dụng:** Script CDP điền form React: luôn dùng native setter + dispatchEvent('input'), không
dùng execCommand/insertText. Test đa role trong cùng Chrome/CDP session: clear cookie trước mỗi
lần đổi user. Xác nhận Vite dev server còn sống: thử `localhost`, đừng chỉ thử `127.0.0.1`.

## 2026-07-05 — Verify lại 1 review ngoài: IsOperatorOrAbove không chặn được GET, test concurrency thật không khả thi trên SQLite
**Bối cảnh:** User đưa 1 báo cáo review liệt kê 4 bug (race condition trigger/cancel, viewer
đọc audit log, SSRF IPv4-mapped IPv6) yêu cầu kiểm chứng lại trước khi vá. 3/4 xác nhận đúng,
1/4 (SSRF) không xác nhận được là lỗ hổng thật trên Python 3.12 hiện tại.
**Bài học:**
1. **`IsOperatorOrAbove` (và `IsViewerOrAbove`) bỏ qua kiểm tra role hoàn toàn cho
   `SAFE_METHODS`** (`if request.method in SAFE_METHODS: return bool(authenticated)` — không
   gọi `has_role`). Với 1 `ReadOnlyModelViewSet` (mọi action đều GET), gắn `permission_classes
   = [IsOperatorOrAbove]` KHÔNG có tác dụng gì khác `IsViewerOrAbove` mặc định — vẫn cho MỌI
   user đã đăng nhập đọc. Review gốc đề xuất dùng class này để chặn viewer khỏi audit log là
   sai — chỉ `IsAdminStrict` (role check cho MỌI method, không có nhánh SAFE_METHODS) mới thực
   sự chặn được GET theo role. Trước khi áp dụng đề xuất "dùng permission class X" cho 1
   ReadOnlyModelViewSet, phải đọc code của X xem có nhánh SAFE_METHODS hay không.
2. **Không thể test concurrency thật (race condition) trên SQLite test DB** (đã ghi ở bài học
   2026-07-03 cho ThreadPoolExecutor, nay áp dụng cả cho request đồng thời). Cách verify race
   fix mà không cần thread thật: (a) gọi 2 lần liên tiếp CHÍNH câu `.filter(...).exclude(status=
   RUNNING).update(...)` dùng trong view, assert lần đầu trả về 1 dòng bị update, lần hai trả
   0 — chứng minh đúng ngữ nghĩa "chỉ 1 caller thắng" của bản thân câu SQL, không cần dựng race
   thật; (b) với race "ghi đè do đọc-rồi-save", monkeypatch 1 side-effect (vd `revoke()`) để tự
   thay đổi trạng thái DB ngay giữa hàm đang test — mô phỏng đúng cửa sổ race mà code cũ sẽ ghi
   đè còn code mới (UPDATE có điều kiện) sẽ bỏ qua.
3. Khi 1 finding không xác nhận được trên runtime hiện tại (SSRF IPv4-mapped IPv6 — code không
   dùng `is_global` như review giả định, và `ipaddress` Python 3.12 đã tự phân loại đúng) vẫn
   nên hỏi user có muốn thêm hardening chiều sâu hay bỏ qua, thay vì tự quyết định — không phải
   bug nhưng có thể là quyết định đáng để user biết và chọn.
**Áp dụng:** Luôn đọc implementation của permission class được đề xuất (đặc biệt nhánh
SAFE_METHODS) trước khi áp dụng cho ReadOnlyModelViewSet. Test race condition bằng cách gọi
trực tiếp câu UPDATE có điều kiện 2 lần liên tiếp (không cần thread), hoặc monkeypatch side-
effect để mô phỏng đúng cửa sổ race. Finding không xác nhận được trên runtime hiện tại → báo
rõ + hỏi user trước khi quyết định sửa hay bỏ qua.

## 2026-07-05 — check_all_online: rò kết nối DB trong ThreadPoolExecutor + is_online đứng hình khi disable máy
**Bối cảnh:** Review cơ chế xác định máy online (`apps/machines/tasks.py::check_all_online`,
Celery beat 15 phút, `ThreadPoolExecutor(max_workers=32)` gọi `refresh_machine_status` — có
`machine.save()`). Không phải yêu cầu fix cụ thể, tự phát hiện qua đọc code + grep xác nhận.
**Bài học:**
1. **Django chỉ tự đóng connection thread-local cho luồng CHÍNH của Celery task** (qua hook
   nội bộ khi task bắt đầu/kết thúc). Luồng con do `ThreadPoolExecutor` tạo bên trong task nằm
   NGOÀI vòng đời đó — connection Django mở trong các luồng này (do gọi `.save()`/query) không
   bao giờ được đóng tường minh (không có `CONN_MAX_AGE` hay `close_old_connections` nào chạm
   tới). Grep cả repo xác nhận không nơi nào xử lý việc này trước khi tôi thêm. Fix: viết 1
   wrapper (`_refresh_and_close`) bọc `try/finally: connections.close_all()` quanh hàm thật, rồi
   `pool.map(wrapper, ...)` thay vì map thẳng hàm gốc.
2. **Giữ nguyên tên hàm gốc ở dạng global reference (không rebind cục bộ trong wrapper) để
   monkeypatch cũ trong test vẫn ăn** — test hiện có patch `m_tasks.refresh_machine_status`
   (tên module-level); wrapper gọi `refresh_machine_status(machine)` (không gán biến khác) nên
   Python resolve tên đó lúc CALL TIME từ namespace module, patch vẫn có hiệu lực dù đã thêm 1
   lớp bọc.
3. **Field boolean kiểu "trạng thái do 1 tiến trình nền refresh định kỳ" (`is_online`) sẽ đứng
   hình vĩnh viễn nếu điều kiện lọc của tiến trình nền (ở đây `enabled=True`) đổi mà không có
   nơi nào chủ động reset field khi điều kiện đó tắt** (`enabled: True→False`). Vì các view
   thống kê (dashboard `stats`/`report`) không lọc theo `enabled`, giá trị cũ vẫn được cộng vào
   "machines_online" mãi mãi. Fix tại nguồn: override `perform_update` của ViewSet — nơi DUY
   NHẤT trong codebase thay đổi `enabled` (đã grep xác nhận) — để set `is_online=False` ngay khi
   phát hiện chuyển `True→False`, thay vì sửa từng query thống kê.
**Áp dụng:** Bất kỳ tác vụ Celery nào tự tạo `ThreadPoolExecutor`/luồng OS thủ công để chạy
song song và có ghi DB trong luồng con → PHẢI tự `connections.close_all()` cuối mỗi lần gọi
trong luồng con, đừng tin Celery tự dọn. Field trạng thái được 1 job nền refresh theo điều kiện
lọc → khi điều kiện lọc của record đổi (bị loại khỏi phạm vi refresh), phải chủ động reset field
đó tại đúng nơi điều kiện thay đổi, không chỉ dựa vào lần refresh tiếp theo (có thể không bao
giờ tới).

## 2026-07-05 — Vá 15 bug audit High/Medium: đảo ngược quyết định fail-open, seam mock đổi khi thêm SSRF guard
**Bối cảnh:** Từ 1 báo cáo audit ngoài, verify + vá 15 bug (purge_all ProtectedError, credential
lộ cho viewer, job log lộ output cho viewer, task_status không kiểm chủ sở hữu, schedule mất 1
chu kỳ khi launch lỗi, trigger thủ công 202/jobs:0, cancel không kiểm trạng thái,
finalize_deployment không idempotent, semaphore fail-open→fail-closed, verify_integrity
FileNotFoundError không bắt, server_stats disk path Windows, SSRF downloader.py, 2 bug frontend).
**Bài học:**
1. **Đảo ngược 1 quyết định thiết kế cũ đã ghi trong LESSONS (semaphore fail-open, xem bài học
   2026-07-03 "self.retry cho semaphore...") là hợp lệ khi có yêu cầu rõ ràng** — nhưng phải sửa
   CẢ docstring module lẫn code (semaphore.py dòng 9-12 mô tả "Thiết kế fail-open" ngay trong
   docstring, nếu chỉ đổi `return True`→`False` mà không sửa docstring thì lần sau đọc code sẽ
   hiểu sai chủ đích). Bài học cũ không tự động "đúng mãi" — luôn xác nhận với người yêu cầu khi
   đổi ngược 1 quyết định đã có lý do ghi lại, và cập nhật cả lý do bằng văn bản, không chỉ code.
2. **Guard idempotency cho 1 hàm (`finalize_deployment`: chỉ chạy khi `deployment.status ==
   RUNNING`) phá các test hiện có gọi thẳng hàm đó trên fixture mặc định KHÔNG set RUNNING**
   (`test_deployment_status.py`, `test_phase2.py::test_finalize_all_cancelled_is_cancelled`) —
   vì fixture tạo Deployment qua `Deployment.objects.create(...)` mặc định `status=DRAFT`. Thêm
   guard theo tiền điều kiện thực tế (chord callback/reconcile chỉ gọi khi đã RUNNING) luôn phải
   rà TOÀN BỘ nơi gọi hàm đó trong test suite, không chỉ trong production code — `grep -rn
   "finalize_deployment("` qua cả `tests/` mới thấy hết các lời gọi trực tiếp cần set RUNNING
   trước.
3. **Đổi seam mock khi thay `urlopen` bằng `build_opener(...).open(...)` (để thêm
   `HTTPRedirectHandler` tùy chỉnh chặn SSRF qua redirect):** test cũ patch thẳng
   `downloader.urlopen` (`test_catalog.py`) sẽ vỡ với `AttributeError` vì tên đó không còn tồn
   tại trong module. Phải đổi mock sang patch `downloader.build_opener` (trả 1 fake opener có
   `.open(req, timeout=...)`), và **cũng phải mock `downloader._ensure_public_host` thành no-op**
   cho các test không liên quan tới SSRF (dùng host giả `example.com`) — nếu không, test đơn vị
   sẽ âm thầm gọi `socket.getaddrinfo` thật (network call trong unit test, dễ flaky/chậm trên CI
   không có mạng).
**Áp dụng:** Khi đảo ngược 1 quyết định kỹ thuật cũ có ghi chú lý do → sửa đồng thời code +
docstring/comment giải thích lý do MỚI. Khi thêm guard theo trạng thái vào 1 hàm được gọi ở
nhiều nơi (task callback + lưới an toàn) → `grep` cả `tests/` để tìm lời gọi trực tiếp cần cập
nhật fixture. Khi đổi API gọi mạng (`urlopen`→`build_opener`) → cập nhật lại toàn bộ chỗ test
mock tên hàm cũ, và mock luôn các hàm validate mới (DNS/SSRF check) để test đơn vị không chạm
mạng thật.

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
