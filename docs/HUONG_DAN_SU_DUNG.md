# Hướng Dẫn Sử Dụng RyanDeploy

Tài liệu này hướng dẫn chi tiết cách sử dụng từng chức năng trên webapp RyanDeploy dành cho người dùng cuối (IT admin, operator, viewer). Để biết quy trình vận hành hạ tầng (GPO, service account, backup...), xem [`RUNBOOK.md`](RUNBOOK.md). Để biết các kiểm soát bảo mật, xem [`SECURITY.md`](SECURITY.md).

---

## 1. Tổng quan hệ thống

RyanDeploy là công cụ triển khai phần mềm hàng loạt lên nhiều máy Windows trong domain, theo mô hình **agentless** (không cần cài gì lên máy trạm — hệ thống dùng SMB/ADMIN$ và một Windows Service tạm để đẩy và chạy installer, xong tự dọn dẹp).

Các module chính trên webapp:

| Module | Đường dẫn | Mục đích |
|---|---|---|
| Dashboard | `/` | Xem tổng quan số liệu, biểu đồ |
| Máy trạm | `/machines` | Quản lý danh sách máy, đồng bộ AD |
| Packages | `/packages` | Quản lý gói cài đặt, version, thư viện phần mềm |
| Deployments | `/deployments` | Tạo và theo dõi các đợt triển khai |
| Lịch lặp | `/schedules` | Cấu hình triển khai tự động định kỳ |
| Cập nhật | `/updates` | Phát hiện máy đang chạy bản cũ, cập nhật 1 chạm |
| Credential | `/credentials` | Quản lý tài khoản dùng để đẩy cài đặt (chỉ admin) |
| Người dùng | `/users` | Quản lý tài khoản đăng nhập webapp (chỉ admin) |

---

## 2. Vai trò và phân quyền (RBAC)

Hệ thống có 3 vai trò:

| Vai trò | Quyền |
|---|---|
| **viewer** | Chỉ xem — mọi trang đều xem được nhưng không tạo/sửa/xóa |
| **operator** | Xem + tạo/kích hoạt deployment, tạo lịch lặp (**trừ** hành động Khởi động lại/Tắt máy) |
| **admin** | Toàn quyền — gồm cả quản lý Credential, Package, Máy trạm, Người dùng, và các hành động nguy hiểm (reboot/shutdown hàng loạt) |

Ghi chú:
- Hành động **Khởi động lại (reboot)** và **Tắt máy (shutdown)** hàng loạt chỉ admin mới được kích hoạt, dù chạy thủ công hay qua lịch lặp.
- Trang **Credential**, **Người dùng** chỉ admin thấy và thao tác được.
- Không thể tự xóa/tự khóa/hạ quyền chính mình, và không thể xóa admin cuối cùng của hệ thống (tránh tự khóa toàn bộ hệ thống).

---

## 3. Đăng nhập

- Truy cập webapp, nhập **Tên đăng nhập** / **Mật khẩu** trên form đăng nhập.
- Hệ thống giới hạn **10 lần thử/phút** để chống dò mật khẩu (brute-force). Nếu bị chặn, đợi 1 phút rồi thử lại.
- Đăng xuất bằng nút **Đăng xuất** trên sidebar.
- Không có chức năng "Quên mật khẩu" trên UI — nếu quên mật khẩu, cần admin vào trang **Người dùng** để đặt lại.

---

## 4. Dashboard

Trang chủ sau khi đăng nhập, chỉ để xem (không có thao tác ghi dữ liệu):

- **7 thẻ chỉ số**: Packages, Máy trạm, Đang online, Deployments, Đang chạy, Job thành công, Job thất bại.
- **Chỉ báo CPU/RAM/Ổ đĩa** của server, góc trên-phải, cập nhật mỗi 3 giây, đổi màu theo ngưỡng cảnh báo.
- **3 biểu đồ tròn (Donut)**: trạng thái Job, trạng thái Deployment, tỉ lệ máy Online/Offline.
- **Biểu đồ cột theo thời gian**: số job hoàn tất mỗi ngày trong 14 ngày gần nhất, tách màu thành công/thất bại.

---

## 5. Quản lý Máy trạm (`/machines`)

### 5.1. Xem danh sách
- Danh sách máy có phân trang (25 máy/trang), tìm theo hostname, lọc theo trạng thái online/offline hoặc OU.
- 3 thẻ thống kê **Tổng máy / Online / Offline** — bấm vào để lọc nhanh.

### 5.2. Nạp máy vào hệ thống
Có 2 cách:

**Cách 1 — Đồng bộ từ Active Directory (khuyến nghị, chỉ admin):**
1. Bấm **"Cấu hình AD"** → nhập LDAP server, base DN, OU cần quét, tài khoản bind (mật khẩu được mã hóa lưu trữ), tick **LDAPS** nếu dùng kết nối mã hóa, tick **"Kích hoạt cấu hình này"**.
2. Bấm **"Test kết nối"** để kiểm tra trước khi lưu.
3. Bấm **"Sync AD"** — có thể tick thêm **"Xóa máy ngoài phạm vi"** nếu muốn dọn các máy không còn nằm trong kết quả AD. Quá trình chạy nền, có thanh tiến trình theo `task_id`.
4. Hệ thống tự động Sync AD lại lúc **2:00 sáng** mỗi ngày, không cần thao tác thủ công hằng ngày.

**Cách 2 — Chờ tự động:** nếu đã cấu hình AD sẵn, chỉ cần chờ tác vụ nền chạy theo lịch.

### 5.3. Các thao tác khác
- **"Kiểm tra online"** — quét SMB cổng 445 hàng loạt để cập nhật trạng thái online/offline (ai cũng bấm được, từ viewer trở lên). Tự động chạy lại mỗi 15 phút.
- **"Xuất Excel"** — xuất CSV (UTF-8 BOM) danh sách máy theo bộ lọc hiện tại.
- **"Xóa tất cả máy"** (admin, **nguy hiểm**) — xóa sạch danh sách máy, dùng khi cần làm lại từ đầu.
- Cờ **enabled** trên từng máy: tắt cờ này nghĩa là loại máy khỏi các đợt triển khai (máy sẽ không nhận job mới) mà không cần xóa khỏi danh sách.

> **Lưu ý:** Chưa có màn hình riêng để quản lý *nhóm máy* (Machine Group) trên webapp — việc chọn máy đích khi tạo deployment hiện chỉ làm được bằng cách gõ tìm theo hostname/OU trong wizard, không chọn theo nhóm đã lưu sẵn.

---

## 6. Quản lý Package (`/packages`)

### 6.1. Cây thư mục (Package Library)
- Giao diện dạng cây thư mục lồng nhau để tổ chức package theo danh mục (giống PDQ Deploy). Chỉ admin tạo/sửa/xóa thư mục.

### 6.2. Thêm phần mềm mới
Chỉ admin thao tác được:

1. **"+ Upload version"** — chọn package có sẵn hoặc tạo package mới, upload file cài đặt (`.msi/.exe/.msu/.msp/.msix/.zip`), nhập số version. Hệ thống tự:
   - Tính mã băm SHA-256 của file để chống giả mạo.
   - Gợi ý sẵn lệnh cài âm thầm (silent command) theo loại file (có thể sửa lại, dùng `{file}` làm placeholder cho tên file installer).
   - Cho nhập thêm **tên hậu kiểm (verify_name)** — dùng để soi registry Uninstall sau khi cài, tránh trường hợp "báo thành công giả" (false success).
2. **"↓ Tải từ URL"** — nhập URL trực tiếp tới file cài đặt + nhãn version, hệ thống tải nền, tự tính SHA-256, lưu lại trong **Lịch sử tải**.
3. **"📚 Nạp Package Library mẫu"** — nạp sẵn metadata các phần mềm phổ biến trong doanh nghiệp (chưa kèm file cài đặt thật, cần upload file riêng).

#### Package nhiều file/thư mục (VD Office2016)

Một số bộ cài (Office, Adobe...) không phải 1 file duy nhất mà là cả thư mục (`setup.exe` + nhiều thư mục con). RyanDeploy chỉ nhận **đúng 1 file installer** mỗi version, nên với các bộ cài này:

1. Nén toàn bộ thư mục cài đặt thành **1 file `.zip`** (VD nén cả thư mục nguồn Office2016 gồm `setup.exe`, `configuration.xml`, các thư mục ngôn ngữ...).
2. Upload file `.zip` đó như một version bình thường.
3. Ở ô **lệnh cài**, dùng token `{dir}` thay vì `{file}` — hệ thống sẽ tự giải nén file `.zip` vào một thư mục tạm trên máy đích TRƯỚC khi chạy lệnh, `{dir}` trỏ tới thư mục đã giải nén đó. Ví dụ với Office2016 (Office Deployment Tool):
   ```
   "{dir}\setup.exe" /configure "{dir}\configuration.xml"
   ```
4. Lưu ý: giới hạn dung lượng upload (`RYANDEPLOY_MAX_INSTALLER_MB`, mặc định 8192 MB) có thể cần tăng thêm qua biến môi trường nếu bộ cài quá lớn (nhiều ngôn ngữ/kiến trúc).

### 6.3. Quản lý version
- **Duyệt (Approve)**: chỉ version đã duyệt mới được tính là "bản mới nhất" khi Deploy 1-chạm ở trang Cập nhật, hoặc khi dò cập nhật. Version upload thủ công mặc định đã duyệt sẵn.
- Sửa version: đổi version, lệnh cài/gỡ, tên hậu kiểm — **không** đổi được file, phải xóa và upload lại nếu cần đổi file installer.
- Xóa package/version: xóa luôn file installer trên đĩa. Bị chặn nếu đang có deployment nào tham chiếu tới version đó.

### 6.4. Lịch sử tải
- Bảng ghi lại từng lần tải từ URL: thời gian, package/version, trạng thái (**Đang tải / Thành công / Không đổi / Thất bại**), kích thước file, thông báo lỗi nếu có.

### 6.5. Quyền
- **Xem**: mọi vai trò.
- **Ghi** (upload, sửa, xóa, duyệt, nạp mẫu, tải từ URL): **chỉ admin**.

---

## 7. Quản lý Deployment (`/deployments`)

### 7.1. Tạo deployment mới
Operator/admin bấm **"+ Tạo deployment"**, wizard yêu cầu:

1. **Tên** đợt triển khai.
2. **Loại tác vụ**:
   - Cài đặt
   - Gỡ cài đặt
   - Khởi động lại (reboot) — **chỉ admin**
   - Tắt máy (shutdown) — **chỉ admin**
   - Quét phần mềm (inventory) — thu thập danh sách phần mềm đã cài trên máy đích
3. **Package version** (bắt buộc nếu là Cài đặt/Gỡ cài đặt).
4. **Credential** dùng để đẩy cài đặt (xem mục 9).
5. **Máy đích** — chọn qua ô tìm kiếm hostname/OU, có nút "Chọn hết"/"Bỏ chọn".

Bấm **Tạo** → hệ thống **tạo và trigger (kích hoạt) ngay lập tức**.

### 7.2. Sửa / Xóa deployment
- Sửa được: tên, giờ chạy đã lên lịch (`scheduled_at`), số máy chạy song song tối đa, số lần thử lại — **chỉ khi deployment chưa chạy** (không sửa được khi đang RUNNING).
- Không đổi được máy đích/package sau khi tạo — phải tạo deployment mới.
- Xóa deployment: bị chặn nếu đang RUNNING.

### 7.3. Trang chi tiết deployment (`/deployments/:id`)
- Nút **"Chạy lại"** (trigger lại) và **"Hủy"** (cancel, operator/admin).
- Thanh tiến độ trực quan: đoạn xanh = thành công, đỏ = thất bại, vàng sọc = đang chạy.
- Bảng chi tiết theo từng máy: trạng thái, bước hiện tại (`precheck → copy → execute → collect → verify → cleanup → done`), exit code, số lần đã thử, nút **"Log"** xem log đầy đủ + lỗi.
- Cập nhật **theo thời gian thực** qua WebSocket (không cần bấm F5), có cơ chế polling dự phòng mỗi 3 giây.

### 7.4. Panel "Đang chạy"
- Hiển thị trên sidebar ở mọi trang — liệt kê tất cả deployment đang chạy trên toàn hệ thống, bấm để nhảy nhanh tới trang chi tiết.

### 7.5. Nhắm mục tiêu có điều kiện (Targeting Rule)
- Có thể cấu hình chỉ deploy lên máy thỏa điều kiện (ví dụ: chưa cài phần mềm X, hoặc đang có version cũ hơn Y). Hiện **chưa có ô nhập trực tiếp trên wizard UI** — cần cấu hình qua API/Django admin. Có endpoint xem trước danh sách máy sẽ nhận job trước khi chạy thật.

---

## 8. Lịch lặp / Recurring (`/schedules`)

Dùng khi muốn một deployment **tự động lặp lại** theo chu kỳ (khác với `scheduled_at` chỉ chạy 1 lần trong Deployment thường):

- **Kiểu Interval**: chạy lại mỗi N phút.
- **Kiểu Weekly**: chạy vào các ngày trong tuần + giờ cố định do bạn chọn.
- Form tạo giống hệt wizard Deployment (loại tác vụ, package, credential, máy đích) + phần cấu hình chu kỳ.
- Có nút bật/tắt nhanh (Đang bật/Đã tắt) mà không cần xóa cấu hình.
- Cột **"Lần chạy cuối"** cho biết lần kích hoạt gần nhất.
- Mỗi lần tới giờ, hệ thống tự tạo một **Deployment mới** (giữ lại lịch sử từng lần chạy, xem ở trang Deployments).

---

## 9. Cập nhật phần mềm (`/updates`)

Tương tự tính năng "Updates" của PDQ Deploy:

1. Trước tiên cần chạy deployment loại **"Quét phần mềm (inventory)"** trên các máy để hệ thống biết máy nào đang cài bản gì.
2. Trang Cập nhật sẽ so sánh với **version mới nhất đã duyệt** trong Package Library, liệt kê:
   - Tên phần mềm, bản mới nhất, số máy đang chạy bản lỗi thời (mở rộng dòng để xem chi tiết từng máy: đang ở bản nào → sẽ lên bản nào).
3. Bấm **"Deploy cập nhật"** (operator/admin) → chọn credential → hệ thống tự tạo và trigger ngay một deployment cài bản mới nhất lên toàn bộ máy lỗi thời.
4. Bấm **"Làm mới"** để tính toán lại danh sách sau khi có dữ liệu inventory mới.

---

## 10. Credential (`/credentials`) — chỉ admin

Quản lý tài khoản domain dùng để đẩy cài đặt lên máy trạm (tài khoản này cần được cấp quyền **local admin** trên máy trạm qua GPO — xem RUNBOOK).

- Danh sách: Tên gợi nhớ, Domain, Username, trạng thái mật khẩu (🔒 đã đặt), đánh dấu Mặc định.
- Tạo/sửa: tên, domain (NetBIOS), username, mật khẩu (**write-only** — không bao giờ hiển thị lại sau khi lưu), đặt làm mặc định.
- Mật khẩu được **mã hóa Fernet** trước khi lưu DB — kể cả truy cập trực tiếp CSDL cũng không đọc được plaintext.
- Trang này **ẩn hoàn toàn** với operator/viewer.

---

## 11. Quản lý Người dùng (`/users`) — chỉ admin

- Bảng: Tên đăng nhập, Email, Vai trò, Trạng thái (Đang bật/Đã khóa), Đăng nhập gần nhất.
- **Tạo user mới**: username, email, vai trò (admin/operator/viewer), mật khẩu, tick kích hoạt.
- **Sửa user**: đổi email/vai trò/trạng thái, đổi mật khẩu (để trống = giữ nguyên mật khẩu cũ).
- **Xóa user**: không xóa được chính mình, không xóa được nếu là admin cuối cùng của hệ thống.
- Superuser Django (tạo qua `createsuperuser`) luôn được coi là admin, không đổi vai trò qua màn hình này.

---

## 12. Nhật ký kiểm toán (Audit Log)

Hệ thống có ghi log toàn bộ hành động quan trọng: upload/sửa/xóa package & version, duyệt version, tải từ URL, tạo/sửa/xóa credential, tạo/sửa/xóa/trigger/hủy deployment, tạo/sửa/xóa lịch lặp, bắt đầu/kết thúc job, đồng bộ máy AD, nạp catalog mẫu, deploy cập nhật.

> **Lưu ý quan trọng:** hiện **chưa có trang riêng trên webapp** để xem Audit Log. Muốn xem lịch sử, admin cần vào **Django admin** (`/admin/`) hoặc gọi trực tiếp API `GET /api/audit-logs/`.

---

## 13. Quy trình sử dụng từ đầu đến cuối (ví dụ: deploy 1 phần mềm lên nhiều máy)

1. **(Một lần, ngoài webapp)** IT hạ tầng tạo service account domain, gán quyền local admin trên máy trạm qua GPO, mở SMB 445 + `ADMIN$` share.
2. Vào **Credential** → tạo credential deploy trỏ tới service account đó.
3. Vào **Máy trạm** → Cấu hình AD → Sync AD (hoặc chờ tự sync 2:00 sáng) → bấm Kiểm tra online để biết máy nào sẵn sàng.
4. Vào **Packages** → Upload version (chọn file cài đặt, kiểm tra lệnh silent, nhập verify_name nếu cần) → đảm bảo version đã **Duyệt**.
5. Vào **Deployments** → "+ Tạo deployment" → chọn Cài đặt, chọn package version, credential, máy đích → Tạo (sẽ chạy ngay).
   - Muốn định kỳ: dùng **Lịch lặp** thay vì tạo thủ công mỗi lần.
6. Theo dõi tiến độ tại trang chi tiết deployment (cập nhật real-time), xem log nếu có máy lỗi.
7. Máy lỗi do mạng/offline tạm thời sẽ **tự động thử lại** theo số lần cấu hình (backoff 30s→60s→120s...); lỗi credential/xác thực thì báo fail ngay không thử lại.
8. (Tùy chọn) Chạy deployment loại **Quét phần mềm** định kỳ để nuôi dữ liệu cho trang **Cập nhật**.
9. Cần gỡ lại: tạo deployment loại **Gỡ cài đặt** dùng lệnh uninstall đã cấu hình sẵn ở version.

---

## 14. Ý nghĩa các trạng thái

### Trạng thái Deployment
| Trạng thái | Ý nghĩa |
|---|---|
| Nháp (draft) | Đã tạo, chưa từng kích hoạt |
| Đã lên lịch (scheduled) | Có giờ chạy trong tương lai, đang chờ tới giờ |
| Đang chạy (running) | Đang gửi job tới các máy đích |
| Hoàn thành (completed) | Toàn bộ máy chạy thành công |
| Hoàn thành có lỗi (completed_errors) | Có máy thành công lẫn máy thất bại |
| Thất bại (failed) | Toàn bộ máy thất bại, hoặc lỗi hệ thống lúc khởi chạy |
| Đã hủy (cancelled) | Bị hủy thủ công |

### Trạng thái Job (từng máy)
| Trạng thái | Ý nghĩa |
|---|---|
| Chờ (pending) | Mới khởi tạo |
| Đã vào hàng đợi (queued) | Chờ tới lượt chạy (theo giới hạn song song) |
| Đang chạy (running) | Đang thực hiện các bước trên máy đích |
| Thành công (success) | Exit code hợp lệ, hậu kiểm (nếu có) đạt |
| Thành công · cần khởi động lại (success_reboot) | Exit code = 3010 |
| Thất bại (failed) | Sai exit code, lỗi kết nối/credential, hoặc hậu kiểm phát hiện false-success |
| Đã hủy (cancelled) | Bị hủy thủ công |

Các bước xử lý của 1 job (`current_step`): **precheck → copy → execute → collect → verify → cleanup → done**.

### Trạng thái Máy
- **Online/Offline**: cập nhật qua tác vụ Kiểm tra online (thủ công hoặc tự động mỗi 15 phút).
- **enabled**: máy bị tắt cờ này sẽ không nhận deployment mới.

### Trạng thái tải Package
Đang tải / Thành công / Không đổi (nội dung trùng bản đã có) / Thất bại.

---

## 15. Xử lý sự cố thường gặp

| Hiện tượng | Nguyên nhân thường gặp | Cách xử lý |
|---|---|---|
| Job fail ở bước **precheck** | Máy offline, tắt tường lửa chặn SMB 445, sai hostname/DNS | Kiểm tra máy có bật, chạy lại "Kiểm tra online" |
| Job fail ở bước **copy** | Credential sai, tài khoản không có quyền local admin trên máy đích, `ADMIN$` share bị tắt | Kiểm tra lại Credential, kiểm tra GPO gán local admin |
| Job thành công nhưng phần mềm không thực sự cài | Sai lệnh silent switch, hoặc thiếu `verify_name` để hậu kiểm | Sửa lại `install_command` ở version, thêm `verify_name` để hệ thống tự phát hiện false-success lần sau |
| Không đăng nhập được (bị khóa tạm) | Vượt quá 10 lần thử/phút (chống brute-force) | Đợi 1 phút rồi thử lại |
| Không thấy máy nào trong danh sách | Chưa cấu hình AD hoặc chưa Sync AD | Vào Máy trạm → Cấu hình AD → Test kết nối → Sync AD |
| Không thấy trang Credential/Người dùng | Tài khoản không phải admin | Nhờ admin cấp quyền hoặc thao tác thay |
| Trang Cập nhật không có dữ liệu | Chưa từng chạy deployment loại "Quét phần mềm" | Tạo deployment loại Quét phần mềm cho các máy cần theo dõi |

Để biết thêm quy trình vận hành hạ tầng và sự cố ở tầng hệ thống, xem [`RUNBOOK.md`](RUNBOOK.md).
