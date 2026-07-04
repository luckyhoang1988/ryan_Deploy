import { useEffect, useState } from "react";
import { api } from "../api";
import Icon from "../components/Icon";
import { Donut, TimelineBars } from "../components/Charts";

const CARDS = [
  { key: "packages", label: "Packages", icon: "package", tone: "cyan" },
  { key: "machines", label: "Máy trạm", icon: "monitor", tone: "blue" },
  { key: "machines_online", label: "Đang online", icon: "wifi", tone: "green" },
  { key: "deployments", label: "Deployments", icon: "send", tone: "cyan" },
  { key: "deployments_running", label: "Đang chạy", icon: "activity", tone: "amber" },
  { key: "jobs_success", label: "Job thành công", icon: "checkCircle", tone: "green" },
  { key: "jobs_failed", label: "Job thất bại", icon: "xCircle", tone: "red" },
];

// Nhãn + màu (theo trạng thái, dùng biến CSS của theme) cho từng slice donut.
const JOB_SLICES = [
  { key: "success", label: "Thành công", color: "var(--green)" },
  { key: "failed", label: "Thất bại", color: "var(--red)" },
  { key: "running", label: "Đang chạy / chờ", color: "var(--amber)" },
  { key: "skipped", label: "Bỏ qua", color: "#94a3b8" },
  { key: "cancelled", label: "Đã hủy", color: "#64748b" },
];

const DEP_SLICES = [
  { key: "completed", label: "Hoàn thành", color: "var(--green)" },
  { key: "completed_errors", label: "Hoàn thành (có lỗi)", color: "var(--amber)" },
  { key: "running", label: "Đang chạy", color: "var(--blue)" },
  { key: "scheduled", label: "Đã lên lịch", color: "var(--accent)" },
  { key: "failed", label: "Thất bại", color: "var(--red)" },
  { key: "cancelled", label: "Đã hủy", color: "#64748b" },
  { key: "draft", label: "Nháp", color: "#475569" },
];

const MACHINE_SLICES = [
  { key: "online", label: "Online", color: "var(--green)" },
  { key: "offline", label: "Offline", color: "#64748b" },
];

function toDonutData(slices, counts) {
  return slices.map((s) => ({ ...s, value: counts?.[s.key] ?? 0 }));
}

export default function Dashboard() {
  const [stats, setStats] = useState(null);
  const [report, setReport] = useState(null);
  const [err, setErr] = useState("");

  useEffect(() => {
    api.stats().then(setStats).catch((e) => setErr(e.message));
    api.report().then(setReport).catch((e) => setErr(e.message));
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

      <div className="page-head mt-lg">
        <h3>Báo cáo</h3>
        <p className="muted">Phân bố trạng thái và hoạt động 14 ngày gần nhất</p>
      </div>
      <div className="chart-grid">
        <div className="card">
          <div className="chart-title">Trạng thái Job</div>
          <Donut data={toDonutData(JOB_SLICES, report?.jobs_by_status)} />
        </div>
        <div className="card">
          <div className="chart-title">Trạng thái Deployment</div>
          <Donut data={toDonutData(DEP_SLICES, report?.deployments_by_status)} />
        </div>
        <div className="card">
          <div className="chart-title">Máy trạm</div>
          <Donut data={toDonutData(MACHINE_SLICES, report?.machines)} />
        </div>
        <div className="card chart-span">
          <div className="chart-title">Job hoàn tất theo ngày (14 ngày)</div>
          {report ? (
            <TimelineBars data={report.timeline} />
          ) : (
            <p className="muted">Đang tải…</p>
          )}
        </div>
      </div>
    </div>
  );
}
