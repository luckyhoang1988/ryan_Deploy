import { useEffect, useState } from "react";
import { useParams, Link } from "react-router-dom";
import { api, listOf } from "../api";
import { useAuth } from "../auth";
import { StatusBadge } from "../components/Layout";
import DeployProgress from "../components/DeployProgress";
import { subscribe } from "../ws";

// Deployment ở các trạng thái này đã kết thúc → ngừng poll.
const TERMINAL = ["completed", "completed_errors", "failed", "cancelled"];

export default function DeploymentDetail() {
  const { id } = useParams();
  const { hasRole } = useAuth();
  const canWrite = hasRole("operator", "admin");
  const [dep, setDep] = useState(null);
  const [jobs, setJobs] = useState([]);
  const [selected, setSelected] = useState(null);
  const [err, setErr] = useState("");

  const load = async () => {
    try {
      const [d, j] = await Promise.all([
        api.get(`/deployments/${id}/`),
        api.get(`/jobs/?deployment=${id}`),
      ]);
      setDep(d);
      setJobs(listOf(j));
    } catch (e) {
      setErr(e.message);
    }
  };

  useEffect(() => {
    load();
  }, [id]);

  // Poll real-time mỗi 3s, nhưng DỪNG khi deployment đã kết thúc (tránh gọi API vô hạn).
  // Vẫn giữ làm lưới an toàn — WebSocket bên dưới cập nhật ngay lập tức, poll chỉ để
  // trang không "đứng hình" nếu WS rớt kết nối.
  useEffect(() => {
    if (!dep || TERMINAL.includes(dep.status)) return;
    const t = setInterval(load, 3000);
    return () => clearInterval(t);
  }, [id, dep?.status]);

  // WebSocket real-time: patch state ngay khi có message khớp deployment/job này.
  useEffect(() => {
    const offDep = subscribe("deployment.update", (data) => {
      if (String(data.id) !== String(id)) return;
      setDep((prev) => (prev ? { ...prev, ...data } : prev));
    });
    const offJob = subscribe("job.update", (data) => {
      if (String(data.deployment_id) !== String(id)) return;
      setJobs((prev) => prev.map((j) => (j.id === data.id ? { ...j, ...data } : j)));
    });
    return () => {
      offDep();
      offJob();
    };
  }, [id]);

  const retrigger = async () => {
    // Xác nhận trước: chạy lại có thể đẩy tới hàng trăm máy — tránh click nhầm.
    if (!window.confirm(`Chạy lại deployment "${dep.name}"? Sẽ đẩy tới các máy đích.`)) return;
    await api.post(`/deployments/${id}/trigger/`, {});
    load();
  };
  const cancel = async () => {
    if (!window.confirm(`Hủy deployment "${dep.name}"? Các job đang chạy sẽ bị dừng.`)) return;
    await api.post(`/deployments/${id}/cancel/`, {});
    load();
  };

  if (err) return <p className="error">{err}</p>;
  if (!dep) return <p>Đang tải…</p>;

  return (
    <div>
      <div className="topbar">
        <div>
          <Link to="/deployments" className="muted">← Deployments</Link>
          <h2 style={{ margin: "6px 0" }}>{dep.name}</h2>
        </div>
        <div className="row">
          {canWrite && (
            <>
              <button className="btn ghost" onClick={retrigger}>Chạy lại</button>
              <button className="btn danger" onClick={cancel}>Hủy</button>
            </>
          )}
        </div>
      </div>

      <div className="row" style={{ gap: 20 }}>
        <div><span className="muted">Package: </span>{dep.package_name} {dep.version}</div>
        <StatusBadge status={dep.status} />
        <div className="muted">{dep.success_count}✓ / {dep.failed_count}✗ / {dep.pending_count}⏳ / {dep.total_count} máy</div>
      </div>

      <DeployProgress dep={dep} />

      <table className="mt">
        <thead>
          <tr><th>Máy</th><th>Trạng thái</th><th>Step</th><th>Exit code</th><th>Lần thử</th><th></th></tr>
        </thead>
        <tbody>
          {jobs.map((j) => (
            <tr key={j.id}>
              <td>{j.machine_hostname}</td>
              <td><StatusBadge status={j.status} /></td>
              <td className="muted">{j.current_step || "—"}</td>
              <td>{j.exit_code ?? "—"}</td>
              <td>{j.attempts}</td>
              <td><button className="btn ghost" onClick={() => setSelected(j)}>Log</button></td>
            </tr>
          ))}
          {jobs.length === 0 && <tr><td colSpan="6" className="muted">Chưa có job.</td></tr>}
        </tbody>
      </table>

      {selected && (
        <div className="modal-bg" onClick={() => setSelected(null)}>
          <div className="modal" onClick={(e) => e.stopPropagation()}>
            <h3>{selected.machine_hostname}</h3>
            {selected.error_output && <p className="error">{selected.error_output}</p>}
            <div className="log">{selected.output || "(chưa có log)"}</div>
            <div className="row spread mt">
              <span />
              <button className="btn ghost" onClick={() => setSelected(null)}>Đóng</button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
