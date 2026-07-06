import { useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api";
import { StatusBadge } from "../components/Layout";
import DeploymentWizard from "../components/DeploymentWizard";
import Pagination from "../components/Pagination";
import { useAuth } from "../auth";
import { subscribe } from "../ws";

const PAGE_SIZE = 30;

// Nhãn tiếng Việt cho DeploymentStatus, khớp STATUS_META trong components/Layout.jsx.
const DEPLOYMENT_STATUS_OPTIONS = [
  ["draft", "Nháp"],
  ["scheduled", "Đã lên lịch"],
  ["running", "Đang chạy"],
  ["completed", "Hoàn thành"],
  ["completed_errors", "Hoàn thành (có lỗi)"],
  ["failed", "Thất bại"],
  ["cancelled", "Đã hủy"],
];

export default function Deployments() {
  const { hasRole } = useAuth();
  const canWrite = hasRole("operator", "admin");
  const isAdmin = hasRole("admin");
  const [deployments, setDeployments] = useState([]);
  const [totalCount, setTotalCount] = useState(0);
  const [page, setPage] = useState(1);
  const [filterStatus, setFilterStatus] = useState("");
  const [showWizard, setShowWizard] = useState(false);
  const [editDep, setEditDep] = useState(null);
  const [err, setErr] = useState("");
  const [msg, setMsg] = useState("");

  const buildQuery = useCallback((p) => {
    const params = new URLSearchParams();
    params.set("page", p);
    if (filterStatus) params.set("status", filterStatus);
    return params.toString();
  }, [filterStatus]);

  const load = useCallback((p = page) => {
    api.get(`/deployments/?${buildQuery(p)}`)
      .then((d) => {
        setDeployments(d.results ?? []);
        setTotalCount(d.count ?? 0);
      })
      .catch((e) => setErr(e.message));
  }, [buildQuery, page]);

  useEffect(() => {
    load(page);
  }, [page, buildQuery]);

  // Khi đổi filter trạng thái → reset về trang 1.
  useEffect(() => {
    setPage(1);
  }, [filterStatus]);

  const exportCSV = () => {
    const params = new URLSearchParams();
    if (filterStatus) params.set("status", filterStatus);
    const q = params.toString();
    window.open(`/api/deployments/export/${q ? "?" + q : ""}`, "_blank");
  };

  // WebSocket real-time: patch đúng dòng theo id thay vì phải load lại cả trang.
  useEffect(() => {
    return subscribe("deployment.update", (data) => {
      setDeployments((prev) => {
        // Deployment mới tạo lúc trang đang mở (vd lịch lặp tự kích hoạt) → không có
        // trong state hiện tại, bỏ qua thay vì chèn bản ghi thiếu field name/package_name.
        if (!prev.some((d) => d.id === data.id)) return prev;
        return prev.map((d) => (d.id === data.id ? { ...d, ...data } : d));
      });
    });
  }, []);

  const remove = async (d) => {
    if (!confirm(`Xóa deployment "${d.name}"? Toàn bộ lịch sử job của nó cũng bị xóa.`)) return;
    setErr(""); setMsg("");
    try {
      await api.del(`/deployments/${d.id}/`);
      setMsg(`Đã xóa "${d.name}".`);
      load();
    } catch (e) { setErr(e.message); }
  };

  return (
    <div>
      <div className="topbar">
        <h2>Deployments</h2>
        {canWrite && <button className="btn" onClick={() => setShowWizard(true)}>+ Tạo deployment</button>}
      </div>
      {msg && <p className="muted">{msg}</p>}
      {err && <p className="error">{err}</p>}

      <div className="filter-bar">
        <select value={filterStatus} onChange={(e) => setFilterStatus(e.target.value)} style={{ maxWidth: 200 }}>
          <option value="">Tất cả trạng thái</option>
          {DEPLOYMENT_STATUS_OPTIONS.map(([value, label]) => (
            <option key={value} value={value}>{label}</option>
          ))}
        </select>
        {filterStatus && (
          <button className="btn ghost" style={{ padding: "6px 12px" }} onClick={() => setFilterStatus("")}>
            ✕ Xóa lọc
          </button>
        )}
        <div style={{ flex: 1 }} />
        <button className="btn ghost" onClick={exportCSV} title="Xuất danh sách deployment ra Excel (CSV)">
          📥 Xuất Excel
        </button>
      </div>

      <table>
        <thead>
          <tr><th>Tên</th><th>Package</th><th>Trạng thái</th><th>Tiến độ</th><th></th></tr>
        </thead>
        <tbody>
          {deployments.map((d) => (
            <tr key={d.id}>
              <td>{d.name}</td>
              <td>{d.package_name} {d.version}</td>
              <td><StatusBadge status={d.status} /></td>
              <td className="muted">{d.success_count}✓ / {d.failed_count}✗ / {d.total_count} máy</td>
              <td>
                <div className="row" style={{ gap: 10, justifyContent: "flex-end" }}>
                  <Link to={`/deployments/${d.id}`}>Chi tiết →</Link>
                  {canWrite && (
                    <>
                      <button className="btn ghost" style={{ padding: "4px 10px" }} onClick={() => setEditDep(d)}>Sửa</button>
                      <button className="btn ghost danger" style={{ padding: "4px 10px" }} onClick={() => remove(d)}>Xóa</button>
                    </>
                  )}
                </div>
              </td>
            </tr>
          ))}
          {deployments.length === 0 && <tr><td colSpan="5" className="muted">Chưa có deployment.</td></tr>}
        </tbody>
      </table>

      <Pagination page={page} totalCount={totalCount} pageSize={PAGE_SIZE} onPageChange={setPage} itemLabel="deployment" />

      {showWizard && (
        <DeploymentWizard
          isAdmin={isAdmin}
          onClose={() => setShowWizard(false)}
          onDone={() => { setShowWizard(false); setMsg("Đã tạo deployment."); load(); }}
        />
      )}
      {editDep && (
        <EditModal
          dep={editDep}
          onClose={() => setEditDep(null)}
          onDone={() => { setEditDep(null); setMsg("Đã lưu deployment."); load(); }}
        />
      )}
    </div>
  );
}

// Định dạng datetime cho input datetime-local (yyyy-MM-ddThh:mm, theo giờ địa phương).
function toLocalInput(iso) {
  if (!iso) return "";
  const d = new Date(iso);
  const pad = (n) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`;
}

function EditModal({ dep, onClose, onDone }) {
  const [form, setForm] = useState({
    name: dep.name || "",
    scheduled_at: toLocalInput(dep.scheduled_at),
    max_concurrency: dep.max_concurrency ?? 15,
    retry_limit: dep.retry_limit ?? 1,
  });
  const [err, setErr] = useState("");
  const [busy, setBusy] = useState(false);

  const set = (k) => (e) => setForm((f) => ({ ...f, [k]: e.target.value }));

  const submit = async (e) => {
    e.preventDefault();
    setErr(""); setBusy(true);
    try {
      await api.patch(`/deployments/${dep.id}/`, {
        name: form.name,
        // datetime-local không có timezone → new Date() diễn giải theo giờ máy, gửi ISO UTC.
        scheduled_at: form.scheduled_at ? new Date(form.scheduled_at).toISOString() : null,
        max_concurrency: Number(form.max_concurrency) || 1,
        retry_limit: Number(form.retry_limit) || 0,
      });
      onDone();
    } catch (e2) {
      setErr(e2.message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="modal-bg" onClick={onClose}>
      <form className="modal" onClick={(e) => e.stopPropagation()} onSubmit={submit}>
        <h3>Sửa deployment</h3>
        <label>Tên</label>
        <input value={form.name} onChange={set("name")} required />
        <label>Lịch chạy (để trống = chạy ngay khi kích hoạt)</label>
        <input type="datetime-local" value={form.scheduled_at} onChange={set("scheduled_at")} />
        <div className="row" style={{ gap: 12 }}>
          <div style={{ flex: 1 }}>
            <label>Số máy chạy song song</label>
            <input type="number" min="1" value={form.max_concurrency} onChange={set("max_concurrency")} />
          </div>
          <div style={{ flex: 1 }}>
            <label>Số lần thử lại</label>
            <input type="number" min="0" value={form.retry_limit} onChange={set("retry_limit")} />
          </div>
        </div>
        <p className="muted" style={{ fontSize: 12, marginTop: -4 }}>
          Không sửa được deployment đang chạy — hãy hủy trước. Đổi máy đích/package thì tạo deployment mới.
        </p>
        {err && <p className="error mt">{err}</p>}
        <div className="row spread mt">
          <button type="button" className="btn ghost" onClick={onClose}>Hủy</button>
          <button className="btn" disabled={busy}>{busy ? "Đang lưu…" : "Lưu"}</button>
        </div>
      </form>
    </div>
  );
}
