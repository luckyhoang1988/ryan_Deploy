import { useEffect, useState } from "react";
import { api } from "../api";
import Icon from "../components/Icon";

const CARDS = [
  { key: "packages", label: "Packages", icon: "package", tone: "cyan" },
  { key: "machines", label: "Máy trạm", icon: "monitor", tone: "blue" },
  { key: "machines_online", label: "Đang online", icon: "wifi", tone: "green" },
  { key: "deployments", label: "Deployments", icon: "send", tone: "cyan" },
  { key: "deployments_running", label: "Đang chạy", icon: "activity", tone: "amber" },
  { key: "jobs_success", label: "Job thành công", icon: "checkCircle", tone: "green" },
  { key: "jobs_failed", label: "Job thất bại", icon: "xCircle", tone: "red" },
];

export default function Dashboard() {
  const [stats, setStats] = useState(null);
  const [err, setErr] = useState("");

  useEffect(() => {
    api.stats().then(setStats).catch((e) => setErr(e.message));
  }, []);

  return (
    <div>
      <div className="page-head">
        <h2>Dashboard</h2>
        <p className="muted">Tổng quan hệ thống triển khai</p>
      </div>
      {err && <p className="error">{err}</p>}
      <div className="cards">
        {CARDS.map((c) => (
          <div className="card stat" key={c.key}>
            <div className={`card-icon ${c.tone}`}>
              <Icon name={c.icon} size={20} />
            </div>
            <div className="stat-body">
              <div className="value">{stats ? stats[c.key] : "—"}</div>
              <div className="label">{c.label}</div>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
