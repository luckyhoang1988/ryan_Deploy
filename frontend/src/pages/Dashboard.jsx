import { useEffect, useState } from "react";
import { api } from "../api";

const CARDS = [
  { key: "packages", label: "Packages" },
  { key: "machines", label: "Máy trạm" },
  { key: "machines_online", label: "Đang online" },
  { key: "deployments", label: "Deployments" },
  { key: "deployments_running", label: "Đang chạy" },
  { key: "jobs_success", label: "Job thành công" },
  { key: "jobs_failed", label: "Job thất bại" },
];

export default function Dashboard() {
  const [stats, setStats] = useState(null);
  const [err, setErr] = useState("");

  useEffect(() => {
    api.stats().then(setStats).catch((e) => setErr(e.message));
  }, []);

  return (
    <div>
      <h2>Dashboard</h2>
      {err && <p className="error">{err}</p>}
      <div className="cards">
        {CARDS.map((c) => (
          <div className="card" key={c.key}>
            <div className="value">{stats ? stats[c.key] : "—"}</div>
            <div className="label">{c.label}</div>
          </div>
        ))}
      </div>
    </div>
  );
}
