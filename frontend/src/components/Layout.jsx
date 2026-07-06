import { useEffect, useState } from "react";
import { NavLink, useNavigate } from "react-router-dom";
import { api, listOf } from "../api";
import { useAuth } from "../auth";
import DeployProgress from "./DeployProgress";
import Icon from "./Icon";
import { subscribe } from "../ws";

const NAV = [
  { to: "/", end: true, label: "Dashboard", icon: "grid" },
  { to: "/packages", label: "Packages", icon: "package" },
  { to: "/machines", label: "Máy trạm", icon: "monitor" },
  { to: "/deployments", label: "Deployments", icon: "send" },
  { to: "/schedules", label: "Lịch lặp", icon: "clock" },
  { to: "/updates", label: "Cập nhật", icon: "refreshCw" },
  { to: "/guide", label: "Hướng dẫn", icon: "book" },
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
          {hasRole("admin") && (
            <NavLink to="/audit-logs">
              <Icon name="activity" /> <span>Audit Log</span>
            </NavLink>
          )}
        </nav>
        <RunningPanel />
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

// Panel "Đang chạy" toàn cục (kiểu PDQ Deploy) — luôn hiện ở mọi trang, cập nhật real-time
// qua WebSocket. Nạp danh sách ban đầu 1 lần; sau đó tự thêm/gỡ/patch theo message
// "deployment.update" thay vì poll.
function RunningPanel() {
  const navigate = useNavigate();
  const [running, setRunning] = useState([]);

  useEffect(() => {
    api.get("/deployments/?status=running").then((d) => setRunning(listOf(d))).catch(() => {});
  }, []);

  useEffect(() => {
    return subscribe("deployment.update", (data) => {
      if (data.status !== "running") {
        setRunning((prev) => prev.filter((d) => d.id !== data.id));
        return;
      }
      setRunning((prev) => {
        if (prev.some((d) => d.id === data.id)) {
          return prev.map((d) => (d.id === data.id ? { ...d, ...data } : d));
        }
        // Deployment vừa chuyển sang "running", panel chưa có đủ field (name/package_name)
        // — nạp bản đầy đủ trong nền rồi thêm vào panel.
        api
          .get(`/deployments/${data.id}/`)
          .then((full) => setRunning((p2) => (p2.some((d) => d.id === full.id) ? p2 : [...p2, full])))
          .catch(() => {});
        return prev;
      });
    });
  }, []);

  if (running.length === 0) return null;

  return (
    <div className="running-panel">
      <div className="running-panel-title">Đang chạy ({running.length})</div>
      {running.map((d) => (
        <button key={d.id} className="running-item" onClick={() => navigate(`/deployments/${d.id}`)}>
          <div className="running-item-name">{d.name}</div>
          <DeployProgress dep={d} compact />
        </button>
      ))}
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
