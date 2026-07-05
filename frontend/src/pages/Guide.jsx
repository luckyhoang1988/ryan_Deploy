import Icon from "../components/Icon";

// Trang "Hướng dẫn sử dụng" — nội dung tĩnh (đồng bộ với docs/HUONG_DAN_SU_DUNG.md),
// hiển thị ngay trong webapp và có thể "Tải PDF" qua print-to-PDF của trình duyệt
// (xem .guide-doc / @media print trong styles.css) — không cần thư viện PDF ngoài.
const TOC = [
  ["tong-quan", "1. Tổng quan hệ thống"],
  ["phan-quyen", "2. Vai trò và phân quyền"],
  ["dang-nhap", "3. Đăng nhập"],
  ["dashboard", "4. Dashboard"],
  ["may-tram", "5. Quản lý Máy trạm"],
  ["packages", "6. Quản lý Package"],
  ["deployments", "7. Quản lý Deployment"],
  ["schedules", "8. Lịch lặp"],
  ["updates", "9. Cập nhật phần mềm"],
  ["credentials", "10. Credential"],
  ["users", "11. Quản lý Người dùng"],
  ["audit", "12. Nhật ký kiểm toán"],
  ["quy-trinh", "13. Quy trình end-to-end"],
  ["trang-thai", "14. Ý nghĩa các trạng thái"],
  ["su-co", "15. Xử lý sự cố thường gặp"],
];

export default function Guide() {
  return (
    <div>
      <div className="topbar no-print">
        <h2>Hướng dẫn sử dụng</h2>
        <button className="btn" onClick={() => window.print()}>
          <Icon name="download" size={16} /> <span>Tải PDF</span>
        </button>
      </div>

      <nav className="guide-toc no-print">
        {TOC.map(([id, label]) => (
          <a key={id} href={`#${id}`}>
            {label}
          </a>
        ))}
      </nav>

      <div className="guide-doc">
        <p className="muted">
          Tài liệu hướng dẫn chi tiết cách sử dụng từng chức năng trên webapp RyanDeploy. Bản đầy
          đủ (Markdown) nằm tại <code>docs/HUONG_DAN_SU_DUNG.md</code> trong mã nguồn.
        </p>

        <Section id="tong-quan" title="1. Tổng quan hệ thống">
          <p>
            RyanDeploy là công cụ triển khai phần mềm hàng loạt lên nhiều máy Windows trong
            domain, theo mô hình <b>agentless</b> (không cần cài gì lên máy trạm — hệ thống dùng
            SMB/ADMIN$ và một Windows Service tạm để đẩy và chạy installer, xong tự dọn dẹp).
          </p>
          <Table
            headers={["Module", "Đường dẫn", "Mục đích"]}
            rows={[
              ["Dashboard", "/", "Xem tổng quan số liệu, biểu đồ"],
              ["Máy trạm", "/machines", "Quản lý danh sách máy, đồng bộ AD"],
              ["Packages", "/packages", "Quản lý gói cài đặt, version, thư viện phần mềm"],
              ["Deployments", "/deployments", "Tạo và theo dõi các đợt triển khai"],
              ["Lịch lặp", "/schedules", "Cấu hình triển khai tự động định kỳ"],
              ["Cập nhật", "/updates", "Phát hiện máy đang chạy bản cũ, cập nhật 1 chạm"],
              ["Credential", "/credentials", "Quản lý tài khoản dùng để đẩy cài đặt (chỉ admin)"],
              ["Người dùng", "/users", "Quản lý tài khoản đăng nhập webapp (chỉ admin)"],
            ]}
          />
        </Section>

        <Section id="phan-quyen" title="2. Vai trò và phân quyền (RBAC)">
          <Table
            headers={["Vai trò", "Quyền"]}
            rows={[
              ["viewer", "Chỉ xem — mọi trang đều xem được nhưng không tạo/sửa/xóa"],
              [
                "operator",
                "Xem + tạo/kích hoạt deployment, tạo lịch lặp (trừ hành động Khởi động lại/Tắt máy)",
              ],
              [
                "admin",
                "Toàn quyền — gồm cả quản lý Credential, Package, Máy trạm, Người dùng, và các hành động nguy hiểm (reboot/shutdown hàng loạt)",
              ],
            ]}
          />
          <ul>
            <li>
              Hành động <b>Khởi động lại (reboot)</b> và <b>Tắt máy (shutdown)</b> hàng loạt chỉ
              admin mới được kích hoạt, dù chạy thủ công hay qua lịch lặp.
            </li>
            <li>
              Trang <b>Credential</b>, <b>Người dùng</b> chỉ admin thấy và thao tác được.
            </li>
            <li>
              Không thể tự xóa/tự khóa/hạ quyền chính mình, và không thể xóa admin cuối cùng của
              hệ thống (tránh tự khóa toàn bộ hệ thống).
            </li>
          </ul>
        </Section>

        <Section id="dang-nhap" title="3. Đăng nhập">
          <ul>
            <li>
              Truy cập webapp, nhập <b>Tên đăng nhập</b> / <b>Mật khẩu</b> trên form đăng nhập.
            </li>
            <li>
              Hệ thống giới hạn <b>10 lần thử/phút</b> để chống dò mật khẩu (brute-force). Nếu bị
              chặn, đợi 1 phút rồi thử lại.
            </li>
            <li>Đăng xuất bằng nút "Đăng xuất" trên sidebar.</li>
            <li>
              Không có chức năng "Quên mật khẩu" trên UI — nếu quên mật khẩu, cần admin vào trang
              Người dùng để đặt lại.
            </li>
          </ul>
        </Section>

        <Section id="dashboard" title="4. Dashboard">
          <p>Trang chủ sau khi đăng nhập, chỉ để xem (không có thao tác ghi dữ liệu):</p>
          <ul>
            <li>
              <b>7 thẻ chỉ số</b>: Packages, Máy trạm, Đang online, Deployments, Đang chạy, Job
              thành công, Job thất bại.
            </li>
            <li>
              <b>Chỉ báo CPU/RAM/Ổ đĩa</b> của server, góc trên-phải, cập nhật mỗi 3 giây, đổi
              màu theo ngưỡng cảnh báo.
            </li>
            <li>
              <b>3 biểu đồ tròn (Donut)</b>: trạng thái Job, trạng thái Deployment, tỉ lệ máy
              Online/Offline.
            </li>
            <li>
              <b>Biểu đồ cột theo thời gian</b>: số job hoàn tất mỗi ngày trong 14 ngày gần nhất,
              tách màu thành công/thất bại.
            </li>
          </ul>
        </Section>

        <Section id="may-tram" title="5. Quản lý Máy trạm (/machines)">
          <h3>5.1. Xem danh sách</h3>
          <ul>
            <li>Danh sách máy có phân trang (25 máy/trang), tìm theo hostname, lọc theo trạng thái online/offline hoặc OU.</li>
            <li>3 thẻ thống kê Tổng máy / Online / Offline — bấm vào để lọc nhanh.</li>
          </ul>
          <h3>5.2. Nạp máy vào hệ thống</h3>
          <p>
            <b>Cách 1 — Đồng bộ từ Active Directory (khuyến nghị, chỉ admin):</b>
          </p>
          <ol>
            <li>
              Bấm "Cấu hình AD" → nhập LDAP server, base DN, OU cần quét, tài khoản bind (mật khẩu
              được mã hóa lưu trữ), tick <b>LDAPS</b> nếu dùng kết nối mã hóa, tick "Kích hoạt cấu
              hình này".
            </li>
            <li>Bấm "Test kết nối" để kiểm tra trước khi lưu.</li>
            <li>
              Bấm "Sync AD" — có thể tick thêm "Xóa máy ngoài phạm vi" nếu muốn dọn các máy không
              còn nằm trong kết quả AD. Quá trình chạy nền, có thanh tiến trình theo task_id.
            </li>
            <li>Hệ thống tự động Sync AD lại lúc 2:00 sáng mỗi ngày, không cần thao tác thủ công hằng ngày.</li>
          </ol>
          <p>
            <b>Cách 2 — Chờ tự động:</b> nếu đã cấu hình AD sẵn, chỉ cần chờ tác vụ nền chạy theo
            lịch.
          </p>
          <h3>5.3. Các thao tác khác</h3>
          <ul>
            <li>
              "Kiểm tra online" — quét SMB cổng 445 hàng loạt để cập nhật trạng thái online/offline
              (ai cũng bấm được, từ viewer trở lên). Tự động chạy lại mỗi 15 phút.
            </li>
            <li>"Xuất Excel" — xuất CSV (UTF-8 BOM) danh sách máy theo bộ lọc hiện tại.</li>
            <li>
              "Xóa tất cả máy" (admin, <b>nguy hiểm</b>) — xóa sạch danh sách máy, dùng khi cần
              làm lại từ đầu.
            </li>
            <li>
              Cờ <b>enabled</b> trên từng máy: tắt cờ này nghĩa là loại máy khỏi các đợt triển khai
              (máy sẽ không nhận job mới) mà không cần xóa khỏi danh sách.
            </li>
          </ul>
          <p className="guide-note">
            Lưu ý: chưa có màn hình riêng để quản lý nhóm máy (Machine Group) trên webapp — việc
            chọn máy đích khi tạo deployment hiện chỉ làm được bằng cách gõ tìm theo hostname/OU
            trong wizard, không chọn theo nhóm đã lưu sẵn.
          </p>
        </Section>

        <Section id="packages" title="6. Quản lý Package (/packages)">
          <h3>6.1. Cây thư mục (Package Library)</h3>
          <p>
            Giao diện dạng cây thư mục lồng nhau để tổ chức package theo danh mục (giống PDQ
            Deploy). Chỉ admin tạo/sửa/xóa thư mục.
          </p>
          <h3>6.2. Thêm phần mềm mới</h3>
          <p>Chỉ admin thao tác được:</p>
          <ol>
            <li>
              <b>"+ Upload version"</b> — chọn package có sẵn hoặc tạo package mới, upload file
              cài đặt (.msi/.exe/.msu/.msp/.msix/.zip), nhập số version. Hệ thống tự tính mã băm
              SHA-256 của file để chống giả mạo, gợi ý sẵn lệnh cài âm thầm (silent command) theo
              loại file (có thể sửa lại, dùng <code>{"{file}"}</code> làm placeholder cho tên file
              installer), và cho nhập thêm <b>tên hậu kiểm (verify_name)</b> — dùng để soi registry
              Uninstall sau khi cài, tránh trường hợp "báo thành công giả" (false success).
            </li>
            <li>
              <b>"↓ Tải từ URL"</b> — nhập URL trực tiếp tới file cài đặt + nhãn version, hệ thống
              tải nền, tự tính SHA-256, lưu lại trong Lịch sử tải.
            </li>
            <li>
              <b>"📚 Nạp Package Library mẫu"</b> — nạp sẵn metadata các phần mềm phổ biến trong
              doanh nghiệp (chưa kèm file cài đặt thật, cần upload file riêng).
            </li>
          </ol>
          <h3>6.2.1. Package nhiều file/thư mục (VD Office2016)</h3>
          <p>
            Một số bộ cài (Office, Adobe...) không phải 1 file mà là cả thư mục (<code>setup.exe</code>{" "}
            + nhiều thư mục con). RyanDeploy chỉ nhận đúng 1 file installer mỗi version, nên với các
            bộ cài này: nén toàn bộ thư mục cài đặt thành <b>1 file .zip</b>, upload như một version
            bình thường, rồi ở ô lệnh cài dùng token <code>{"{dir}"}</code> thay vì{" "}
            <code>{"{file}"}</code> — hệ thống tự giải nén file .zip vào thư mục tạm trên máy đích
            TRƯỚC khi chạy lệnh, <code>{"{dir}"}</code> trỏ tới thư mục đã giải nén. Ví dụ Office2016
            (Office Deployment Tool):
          </p>
          <p>
            <code>{'"{dir}\\setup.exe" /configure "{dir}\\configuration.xml"'}</code>
          </p>
          <p>
            Lưu ý: giới hạn dung lượng upload (biến môi trường{" "}
            <code>RYANDEPLOY_MAX_INSTALLER_MB</code>, mặc định 8192 MB) có thể cần tăng thêm nếu bộ
            cài quá lớn.
          </p>
          <h3>6.3. Quản lý version</h3>
          <ul>
            <li>
              <b>Duyệt (Approve)</b>: chỉ version đã duyệt mới được tính là "bản mới nhất" khi
              Deploy 1-chạm ở trang Cập nhật, hoặc khi dò cập nhật. Version upload thủ công mặc
              định đã duyệt sẵn.
            </li>
            <li>
              Sửa version: đổi version, lệnh cài/gỡ, tên hậu kiểm — <b>không</b> đổi được file,
              phải xóa và upload lại nếu cần đổi file installer.
            </li>
            <li>
              Xóa package/version: xóa luôn file installer trên đĩa. Bị chặn nếu đang có
              deployment nào tham chiếu tới version đó.
            </li>
          </ul>
          <h3>6.4. Lịch sử tải</h3>
          <p>
            Bảng ghi lại từng lần tải từ URL: thời gian, package/version, trạng thái (Đang tải /
            Thành công / Không đổi / Thất bại), kích thước file, thông báo lỗi nếu có.
          </p>
          <h3>6.5. Quyền</h3>
          <ul>
            <li>Xem: mọi vai trò.</li>
            <li>Ghi (upload, sửa, xóa, duyệt, nạp mẫu, tải từ URL): chỉ admin.</li>
          </ul>
        </Section>

        <Section id="deployments" title="7. Quản lý Deployment (/deployments)">
          <h3>7.1. Tạo deployment mới</h3>
          <p>Operator/admin bấm "+ Tạo deployment", wizard yêu cầu:</p>
          <ol>
            <li>Tên đợt triển khai.</li>
            <li>
              Loại tác vụ: Cài đặt, Gỡ cài đặt, Khởi động lại (reboot, chỉ admin), Tắt máy
              (shutdown, chỉ admin), Quét phần mềm (inventory) — thu thập danh sách phần mềm đã
              cài trên máy đích.
            </li>
            <li>Package version (bắt buộc nếu là Cài đặt/Gỡ cài đặt).</li>
            <li>Credential dùng để đẩy cài đặt.</li>
            <li>Máy đích — chọn qua ô tìm kiếm hostname/OU, có nút "Chọn hết"/"Bỏ chọn".</li>
          </ol>
          <p>Bấm Tạo → hệ thống tạo và trigger (kích hoạt) ngay lập tức.</p>
          <h3>7.2. Sửa / Xóa deployment</h3>
          <ul>
            <li>
              Sửa được: tên, giờ chạy đã lên lịch (scheduled_at), số máy chạy song song tối đa, số
              lần thử lại — chỉ khi deployment chưa chạy (không sửa được khi đang RUNNING).
            </li>
            <li>Không đổi được máy đích/package sau khi tạo — phải tạo deployment mới.</li>
            <li>Xóa deployment: bị chặn nếu đang RUNNING.</li>
          </ul>
          <h3>7.3. Trang chi tiết deployment (/deployments/:id)</h3>
          <ul>
            <li>Nút "Chạy lại" (trigger lại) và "Hủy" (cancel, operator/admin).</li>
            <li>Thanh tiến độ trực quan: đoạn xanh = thành công, đỏ = thất bại, vàng sọc = đang chạy.</li>
            <li>
              Bảng chi tiết theo từng máy: trạng thái, bước hiện tại (precheck → copy → execute →
              collect → verify → cleanup → done), exit code, số lần đã thử, nút "Log" xem log đầy
              đủ + lỗi.
            </li>
            <li>
              Cập nhật theo thời gian thực qua WebSocket (không cần bấm F5), có cơ chế polling dự
              phòng mỗi 3 giây.
            </li>
          </ul>
          <h3>7.4. Panel "Đang chạy"</h3>
          <p>
            Hiển thị trên sidebar ở mọi trang — liệt kê tất cả deployment đang chạy trên toàn hệ
            thống, bấm để nhảy nhanh tới trang chi tiết.
          </p>
          <h3>7.5. Nhắm mục tiêu có điều kiện (Targeting Rule)</h3>
          <p>
            Có thể cấu hình chỉ deploy lên máy thỏa điều kiện (ví dụ: chưa cài phần mềm X, hoặc
            đang có version cũ hơn Y). Hiện <b>chưa có ô nhập trực tiếp trên wizard UI</b> — cần
            cấu hình qua API/Django admin. Có endpoint xem trước danh sách máy sẽ nhận job trước
            khi chạy thật.
          </p>
        </Section>

        <Section id="schedules" title="8. Lịch lặp / Recurring (/schedules)">
          <p>
            Dùng khi muốn một deployment tự động lặp lại theo chu kỳ (khác với scheduled_at chỉ
            chạy 1 lần trong Deployment thường):
          </p>
          <ul>
            <li><b>Kiểu Interval</b>: chạy lại mỗi N phút.</li>
            <li><b>Kiểu Weekly</b>: chạy vào các ngày trong tuần + giờ cố định do bạn chọn.</li>
            <li>Form tạo giống hệt wizard Deployment (loại tác vụ, package, credential, máy đích) + phần cấu hình chu kỳ.</li>
            <li>Có nút bật/tắt nhanh (Đang bật/Đã tắt) mà không cần xóa cấu hình.</li>
            <li>Cột "Lần chạy cuối" cho biết lần kích hoạt gần nhất.</li>
            <li>
              Mỗi lần tới giờ, hệ thống tự tạo một Deployment mới (giữ lại lịch sử từng lần chạy,
              xem ở trang Deployments).
            </li>
          </ul>
        </Section>

        <Section id="updates" title="9. Cập nhật phần mềm (/updates)">
          <p>Tương tự tính năng "Updates" của PDQ Deploy:</p>
          <ol>
            <li>
              Trước tiên cần chạy deployment loại "Quét phần mềm (inventory)" trên các máy để hệ
              thống biết máy nào đang cài bản gì.
            </li>
            <li>
              Trang Cập nhật sẽ so sánh với version mới nhất đã duyệt trong Package Library, liệt
              kê tên phần mềm, bản mới nhất, số máy đang chạy bản lỗi thời (mở rộng dòng để xem
              chi tiết từng máy: đang ở bản nào → sẽ lên bản nào).
            </li>
            <li>
              Bấm "Deploy cập nhật" (operator/admin) → chọn credential → hệ thống tự tạo và
              trigger ngay một deployment cài bản mới nhất lên toàn bộ máy lỗi thời.
            </li>
            <li>Bấm "Làm mới" để tính toán lại danh sách sau khi có dữ liệu inventory mới.</li>
          </ol>
        </Section>

        <Section id="credentials" title="10. Credential (/credentials) — chỉ admin">
          <p>
            Quản lý tài khoản domain dùng để đẩy cài đặt lên máy trạm (tài khoản này cần được cấp
            quyền local admin trên máy trạm qua GPO).
          </p>
          <ul>
            <li>Danh sách: Tên gợi nhớ, Domain, Username, trạng thái mật khẩu (🔒 đã đặt), đánh dấu Mặc định.</li>
            <li>
              Tạo/sửa: tên, domain (NetBIOS), username, mật khẩu (write-only — không bao giờ hiển
              thị lại sau khi lưu), đặt làm mặc định.
            </li>
            <li>Mật khẩu được mã hóa Fernet trước khi lưu DB — kể cả truy cập trực tiếp CSDL cũng không đọc được plaintext.</li>
            <li>Trang này ẩn hoàn toàn với operator/viewer.</li>
          </ul>
        </Section>

        <Section id="users" title="11. Quản lý Người dùng (/users) — chỉ admin">
          <ul>
            <li>Bảng: Tên đăng nhập, Email, Vai trò, Trạng thái (Đang bật/Đã khóa), Đăng nhập gần nhất.</li>
            <li>Tạo user mới: username, email, vai trò (admin/operator/viewer), mật khẩu, tick kích hoạt.</li>
            <li>Sửa user: đổi email/vai trò/trạng thái, đổi mật khẩu (để trống = giữ nguyên mật khẩu cũ).</li>
            <li>Xóa user: không xóa được chính mình, không xóa được nếu là admin cuối cùng của hệ thống.</li>
            <li>Superuser Django (tạo qua createsuperuser) luôn được coi là admin, không đổi vai trò qua màn hình này.</li>
          </ul>
        </Section>

        <Section id="audit" title="12. Nhật ký kiểm toán (Audit Log)">
          <p>
            Hệ thống có ghi log toàn bộ hành động quan trọng: upload/sửa/xóa package & version,
            duyệt version, tải từ URL, tạo/sửa/xóa credential, tạo/sửa/xóa/trigger/hủy deployment,
            tạo/sửa/xóa lịch lặp, bắt đầu/kết thúc job, đồng bộ máy AD, nạp catalog mẫu, deploy cập
            nhật.
          </p>
          <p className="guide-note">
            Lưu ý quan trọng: hiện chưa có trang riêng trên webapp để xem Audit Log. Muốn xem lịch
            sử, admin cần vào Django admin (/admin/) hoặc gọi trực tiếp API GET /api/audit-logs/.
          </p>
        </Section>

        <Section id="quy-trinh" title="13. Quy trình sử dụng từ đầu đến cuối">
          <p>Ví dụ: deploy 1 phần mềm lên nhiều máy.</p>
          <ol>
            <li>
              (Một lần, ngoài webapp) IT hạ tầng tạo service account domain, gán quyền local admin
              trên máy trạm qua GPO, mở SMB 445 + ADMIN$ share.
            </li>
            <li>Vào Credential → tạo credential deploy trỏ tới service account đó.</li>
            <li>
              Vào Máy trạm → Cấu hình AD → Sync AD (hoặc chờ tự sync 2:00 sáng) → bấm Kiểm tra
              online để biết máy nào sẵn sàng.
            </li>
            <li>
              Vào Packages → Upload version (chọn file cài đặt, kiểm tra lệnh silent, nhập
              verify_name nếu cần) → đảm bảo version đã Duyệt.
            </li>
            <li>
              Vào Deployments → "+ Tạo deployment" → chọn Cài đặt, chọn package version,
              credential, máy đích → Tạo (sẽ chạy ngay). Muốn định kỳ: dùng Lịch lặp thay vì tạo
              thủ công mỗi lần.
            </li>
            <li>Theo dõi tiến độ tại trang chi tiết deployment (cập nhật real-time), xem log nếu có máy lỗi.</li>
            <li>
              Máy lỗi do mạng/offline tạm thời sẽ tự động thử lại theo số lần cấu hình (backoff
              30s→60s→120s...); lỗi credential/xác thực thì báo fail ngay không thử lại.
            </li>
            <li>(Tùy chọn) Chạy deployment loại Quét phần mềm định kỳ để nuôi dữ liệu cho trang Cập nhật.</li>
            <li>Cần gỡ lại: tạo deployment loại Gỡ cài đặt dùng lệnh uninstall đã cấu hình sẵn ở version.</li>
          </ol>
        </Section>

        <Section id="trang-thai" title="14. Ý nghĩa các trạng thái">
          <h3>Trạng thái Deployment</h3>
          <Table
            headers={["Trạng thái", "Ý nghĩa"]}
            rows={[
              ["Nháp (draft)", "Đã tạo, chưa từng kích hoạt"],
              ["Đã lên lịch (scheduled)", "Có giờ chạy trong tương lai, đang chờ tới giờ"],
              ["Đang chạy (running)", "Đang gửi job tới các máy đích"],
              ["Hoàn thành (completed)", "Toàn bộ máy chạy thành công"],
              ["Hoàn thành có lỗi (completed_errors)", "Có máy thành công lẫn máy thất bại"],
              ["Thất bại (failed)", "Toàn bộ máy thất bại, hoặc lỗi hệ thống lúc khởi chạy"],
              ["Đã hủy (cancelled)", "Bị hủy thủ công"],
            ]}
          />
          <h3>Trạng thái Job (từng máy)</h3>
          <Table
            headers={["Trạng thái", "Ý nghĩa"]}
            rows={[
              ["Chờ (pending)", "Mới khởi tạo"],
              ["Đã vào hàng đợi (queued)", "Chờ tới lượt chạy (theo giới hạn song song)"],
              ["Đang chạy (running)", "Đang thực hiện các bước trên máy đích"],
              ["Thành công (success)", "Exit code hợp lệ, hậu kiểm (nếu có) đạt"],
              ["Thành công · cần khởi động lại (success_reboot)", "Exit code = 3010"],
              [
                "Thất bại (failed)",
                "Sai exit code, lỗi kết nối/credential, hoặc hậu kiểm phát hiện false-success",
              ],
              ["Đã hủy (cancelled)", "Bị hủy thủ công"],
            ]}
          />
          <p>
            Các bước xử lý của 1 job (current_step): <b>precheck → copy → execute → collect →
            verify → cleanup → done</b>.
          </p>
          <h3>Trạng thái Máy</h3>
          <ul>
            <li>Online/Offline: cập nhật qua tác vụ Kiểm tra online (thủ công hoặc tự động mỗi 15 phút).</li>
            <li>enabled: máy bị tắt cờ này sẽ không nhận deployment mới.</li>
          </ul>
          <h3>Trạng thái tải Package</h3>
          <p>Đang tải / Thành công / Không đổi (nội dung trùng bản đã có) / Thất bại.</p>
        </Section>

        <Section id="su-co" title="15. Xử lý sự cố thường gặp">
          <Table
            headers={["Hiện tượng", "Nguyên nhân thường gặp", "Cách xử lý"]}
            rows={[
              [
                "Job fail ở bước precheck",
                "Máy offline, tắt tường lửa chặn SMB 445, sai hostname/DNS",
                "Kiểm tra máy có bật, chạy lại \"Kiểm tra online\"",
              ],
              [
                "Job fail ở bước copy",
                "Credential sai, tài khoản không có quyền local admin trên máy đích, ADMIN$ share bị tắt",
                "Kiểm tra lại Credential, kiểm tra GPO gán local admin",
              ],
              [
                "Job thành công nhưng phần mềm không thực sự cài",
                "Sai lệnh silent switch, hoặc thiếu verify_name để hậu kiểm",
                "Sửa lại install_command ở version, thêm verify_name để hệ thống tự phát hiện false-success lần sau",
              ],
              [
                "Không đăng nhập được (bị khóa tạm)",
                "Vượt quá 10 lần thử/phút (chống brute-force)",
                "Đợi 1 phút rồi thử lại",
              ],
              [
                "Không thấy máy nào trong danh sách",
                "Chưa cấu hình AD hoặc chưa Sync AD",
                "Vào Máy trạm → Cấu hình AD → Test kết nối → Sync AD",
              ],
              [
                "Không thấy trang Credential/Người dùng",
                "Tài khoản không phải admin",
                "Nhờ admin cấp quyền hoặc thao tác thay",
              ],
              [
                "Trang Cập nhật không có dữ liệu",
                "Chưa từng chạy deployment loại \"Quét phần mềm\"",
                "Tạo deployment loại Quét phần mềm cho các máy cần theo dõi",
              ],
            ]}
          />
          <p className="muted">
            Để biết thêm quy trình vận hành hạ tầng và sự cố ở tầng hệ thống, xem
            docs/RUNBOOK.md trong mã nguồn.
          </p>
        </Section>
      </div>
    </div>
  );
}

function Section({ id, title, children }) {
  return (
    <section id={id} className="guide-section">
      <h2>{title}</h2>
      {children}
    </section>
  );
}

function Table({ headers, rows }) {
  return (
    <table>
      <thead>
        <tr>
          {headers.map((h) => (
            <th key={h}>{h}</th>
          ))}
        </tr>
      </thead>
      <tbody>
        {rows.map((r, i) => (
          <tr key={i}>
            {r.map((c, j) => (
              <td key={j}>{c}</td>
            ))}
          </tr>
        ))}
      </tbody>
    </table>
  );
}
