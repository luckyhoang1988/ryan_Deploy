import { NavLink } from "react-router-dom";
import { useAuth } from "../auth";

export default function Layout({ children }) {
  const { user, logout } = useAuth();
  return (
    <div className="layout">
      <aside className="sidebar">
        <h1>PyDeploy</h1>
        <nav className="nav">
          <NavLink to="/" end>Dashboard</NavLink>
          <NavLink to="/packages">Packages</NavLink>
          <NavLink to="/machines">Máy trạm</NavLink>
          <NavLink to="/deployments">Deployments</NavLink>
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

export function StatusBadge({ status }) {
  const cls =
    status?.startsWith("success") || status === "completed"
      ? "success"
      : status === "failed"
      ? "failed"
      : ["running", "queued", "pending", "scheduled"].includes(status)
      ? "running"
      : "default";
  return <span className={`badge ${cls}`}>{status}</span>;
}
