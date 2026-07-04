import { NavLink } from "react-router-dom";
import { useAuth } from "../auth";
import Icon from "./Icon";

const NAV = [
  { to: "/", end: true, label: "Dashboard", icon: "grid" },
  { to: "/packages", label: "Packages", icon: "package" },
  { to: "/machines", label: "Máy trạm", icon: "monitor" },
  { to: "/deployments", label: "Deployments", icon: "send" },
  { to: "/updates", label: "Cập nhật", icon: "refreshCw" },
];

export default function Layout({ children }) {
  const { user, logout, hasRole } = useAuth();
  const roles = user.roles?.join(", ") || "no-role";
  return (
    <div className="layout">
      <aside className="sidebar">
        <div className="brand">
          <Icon name="server" size={22} />
          <span>RyanDeploy</span>
        </div>
        <nav className="nav">
          {NAV.map((n) => (
            <NavLink key={n.to} to={n.to} end={n.end}>
              <Icon name={n.icon} /> <span>{n.label}</span>
            </NavLink>
          ))}
          {hasRole("admin") && (
            <NavLink to="/credentials">
              <Icon name="key" /> <span>Credential</span>
            </NavLink>
          )}
          {hasRole("admin") && (
            <NavLink to="/users">
              <Icon name="users" /> <span>Người dùng</span>
            </NavLink>
          )}
        </nav>
      </aside>
      <main className="content">
        <div className="topbar">
          <div />
          <div className="row">
            <div className="userchip">
              <span className="avatar">{user.username?.[0]?.toUpperCase() || "?"}</span>
              <span className="userinfo">
                <span className="uname">{user.username}</span>
                <span className="urole">{roles}</span>
              </span>
            </div>
            <button className="btn ghost" onClick={logout}>
              <Icon name="logOut" size={16} /> <span>Đăng xuất</span>
            </button>
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
