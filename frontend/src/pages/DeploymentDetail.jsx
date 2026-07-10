import { useCallback, useEffect, useState } from "react";
import { useParams, Link } from "react-router-dom";
import { api } from "../api";
import { useAuth } from "../auth";
import { StatusBadge } from "../components/Layout";
import DeployProgress from "../components/DeployProgress";
import Pagination from "../components/Pagination";
import { subscribe } from "../ws";

// Deployment ở các trạng thái này đã kết thúc → ngừng poll.
const TERMINAL = ["completed", "completed_errors", "failed", "cancelled"];

const PAGE_SIZE = 30;

// Nhãn tiếng Việt cho JobStatus, khớp STATUS_META trong components/Layout.jsx.
const JOB_STATUS_OPTIONS = [
  ["pending", "Chờ"],
  ["queued", "Trong hàng đợi"],
  ["running", "Đang chạy"],
  ["success", "Thành công"],
  ["success_reboot", "Thành công · cần reboot"],
  ["failed", "Thất bại"],
  ["skipped", "Bỏ qua"],
  ["cancelled", "Đã hủy"],
];

export default function DeploymentDetail() {
  const { id } = useParams();
  const { hasRole } = useAuth();
  const canWrite = hasRole("operator", "admin");
  const [dep, setDep] = useState(null);
  const [jobs, setJobs] = useState([]);
  const [totalCount, setTotalCount] = useState(0);
  const [page, setPage] = useState(1);
  const [filterStatus, setFilterStatus] = useState("");
  const [selected, setSelected] = useState(null);
  const [err, setErr] = useState("");
  const [busy, setBusy] = useState("");

  const buildJobsQuery = useCallback((p) => {
    const params = new URLSearchParams();
    params.set("deployment", id);
    params.set("page", p);
    if (filterStatus) params.set("status", filterStatus);
    return params.toString();
  }, [id, filterStatus]);

  const load = useCallback(async (p = page) => {
    try {
      const [d, j] = await Promise.all([
        api.get(`/deployments/${id}/`),
        api.get(`/jobs/?${buildJobsQuery(p)}`),
      ]);
      setDep(d);
      setJobs(j.results ?? []);
      setTotalCount(j.count ?? 0);
    } catch (e) {
      setErr(e.message);
    }
  }, [id, buildJobsQuery, page]);

  useEffect(() => {
    load(page);
  }, [page, buildJobsQuery]);

  // Khi đổi filter trạng thái → reset về trang 1.
  useEffect(() => {
    setPage(1);
  }, [filterStatus]);

  // Poll real-time mỗi 3s, nhưng DỪNG khi deployment đã kết thúc (tránh gọi API vô hạn).
  // Vẫn giữ làm lưới an toàn — WebSocket bên dưới cập nhật ngay lập tức, poll chỉ để
  // trang không "đứng hình" nếu WS rớt kết nối.
  useEffect(() => {
    if (!dep || TERMINAL.includes(dep.status)) return;
    const t = setInterval(() => load(), 3000);
    return () => clearInterval(t);
  }, [dep?.status, load]);

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
    setBusy("trigger");
    setErr("");
    try {
      await api.post(`/deployments/${id}/trigger/`, {});
      load();
    } catch (e) {
      setErr(e.message);
    } finally {
      setBusy("");
    }
  };
  const cancel = async () => {
    if (!window.confirm(`Hủy deployment "${dep.name}"? Các job đang chạy sẽ bị dừng.`)) return;
    setBusy("cancel");
    setErr("");
    try {
      await api.post(`/deployments/${id}/cancel/`, {});
      load();
    } catch (e) {
      setErr(e.message);
    } finally {
      setBusy("");
    }
  };

  const exportCSV = () => {
    const params = new URLSearchParams();
    params.set("deployment", id);
    if (filterStatus) params.set("status", filterStatus);
    window.open(`/api/jobs/export/?${params.toString()}`, "_blank");
  };

  // err chỉ gate toàn trang khi CHƯA có dep (lỗi ở lần load đầu) — lỗi từ retrigger/cancel
  // sau khi đã có dep hiển thị inline bên dưới, không được xoá mất toàn bộ trang.
  if (err && !dep) return <p className="error">{err}</p>;
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
              <button className="btn ghost" onClick={retrigger} disabled={!!busy}>Chạy lại</button>
              <button className="btn danger" onClick={cancel} disabled={!!busy}>Hủy</button>
            </>
          )}
        </div>
      </div>

      {err && <p className="error">{err}</p>}

      <div className="row" style={{ gap: 20 }}>
        <div><span className="muted">Package: </span>{dep.package_name} {dep.version}</div>
        <StatusBadge status={dep.status} />
        <div className="muted">{dep.success_count}✓ / {dep.failed_count}✗ / {dep.skipped_count}⏭ / {dep.pending_count}⏳ / {dep.total_count} máy</div>
      </div>

      <DeployProgress dep={dep} />

      <div className="filter-bar">
        <select value={filterStatus} onChange={(e) => setFilterStatus(e.target.value)} style={{ maxWidth: 200 }}>
          <option value="">Tất cả trạng thái</option>
          {JOB_STATUS_OPTIONS.map(([value, label]) => (
            <option key={value} value={value}>{label}</option>
          ))}
        </select>
        {filterStatus && (
          <button className="btn ghost" style={{ padding: "6px 12px" }} onClick={() => setFilterStatus("")}>
            ✕ Xóa lọc
          </button>
        )}
        <div style={{ flex: 1 }} />
        <button className="btn ghost" onClick={exportCSV} title="Xuất danh sách máy ra Excel (CSV)">
          📥 Xuất Excel
        </button>
      </div>

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

      <Pagination page={page} totalCount={totalCount} pageSize={PAGE_SIZE} onPageChange={setPage} itemLabel="máy" />

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
