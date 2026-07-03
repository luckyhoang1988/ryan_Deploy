import { NavLink } from "react-router-dom";
import { useAuth } from "../auth";

export default function Layout({ children }) {
  const { user, logout, hasRole } = useAuth();
  return (
    <div className="layout">
      <aside className="sidebar">
        <h1>PyDeploy</h1>
        <nav className="nav">
          <NavLink to="/" end>Dashboard</NavLink>
          <NavLink to="/packages">Packages</NavLink>
          <NavLink to="/machines">Máy trạm</NavLink>
          <NavLink to="/deployments">Deployments</NavLink>
          {hasRole("admin") && <NavLink to="/users">Người dùng</NavLink>}
        </nav>
      </aside>
      <main className="content">
        <div className="topbar">
          <div />
          <div className="row">
            <span className="user">
              {user.username} · {user.roles?.join(", ") || "no-role"}
            </span>
            <button className="btn ghost" onClick={logout}>Đăng xuất</button>
          </div>
        </div>
        {children}
      </main>
    </div>
  );
}

// Nhãn tiếng Việt + class màu cho mọi trạng thái job & deployment. success_reboot được
// tách riêng (màu xanh dương "cần reboot") thay vì hiển thị raw status khó đọc.
const STATUS_META = {
  // Job
  pending: ["Chờ", "running"],
  queued: ["Trong hàng đợi", "running"],
  running: ["Đang chạy", "running"],
  success: ["Thành công", "success"],
  success_reboot: ["Thành công · cần reboot", "reboot"],
  failed: ["Thất bại", "failed"],
  skipped: ["Bỏ qua", "default"],
  cancelled: ["Đã hủy", "default"],
  // Deployment
  draft: ["Nháp", "default"],
  scheduled: ["Đã lên lịch", "running"],
  completed: ["Hoàn thành", "success"],
  completed_errors: ["Hoàn thành (có lỗi)", "warn"],
};

export function StatusBadge({ status }) {
  const [label, cls] = STATUS_META[status] || [status || "—", "default"];
  return <span className={`badge ${cls}`}>{label}</span>;
}
