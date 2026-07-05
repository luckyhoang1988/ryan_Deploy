import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api, listOf } from "../api";
import { StatusBadge } from "../components/Layout";
import MachinePicker from "../components/MachinePicker";
import { ACTIONS, PACKAGE_ACTIONS, ADMIN_ONLY_ACTIONS } from "../constants/deployment";
import { useAuth } from "../auth";
import { subscribe } from "../ws";

export default function Deployments() {
  const { hasRole } = useAuth();
  const canWrite = hasRole("operator", "admin");
  const isAdmin = hasRole("admin");
  const [deployments, setDeployments] = useState([]);
  const [showWizard, setShowWizard] = useState(false);
  const [editDep, setEditDep] = useState(null);
  const [err, setErr] = useState("");
  const [msg, setMsg] = useState("");

  const load = () =>
    api.get("/deployments/").then((d) => setDeployments(listOf(d))).catch((e) => setErr(e.message));

  useEffect(() => {
    load();
  }, []);

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
      {showWizard && (
        <Wizard
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

function Wizard({ isAdmin, onClose, onDone }) {
  const [versions, setVersions] = useState([]);
  const [credentials, setCredentials] = useState([]);
  const [form, setForm] = useState({
    name: "", action: "install", package_version: "", credential: "", target_machines: [],
    scheduled_at: "", max_concurrency: 15, retry_limit: 1,
  });
  const [err, setErr] = useState("");
  const [busy, setBusy] = useState(false);
  const needsPackage = PACKAGE_ACTIONS.includes(form.action);
  const visibleActions = isAdmin ? ACTIONS : ACTIONS.filter((a) => !ADMIN_ONLY_ACTIONS.includes(a.value));

  useEffect(() => {
    api.get("/package-versions/").then((d) => setVersions(listOf(d)));
    api.get("/credentials/").then((d) => {
      const list = listOf(d);
      setCredentials(list);
      // Tự chọn credential mặc định (is_default) nếu người dùng chưa chọn gì.
      setForm((f) => (f.credential ? f : { ...f, credential: list.find((c) => c.is_default)?.id ?? f.credential }));
    }).catch(() => {});
  }, []);

  const set = (k) => (e) => setForm((f) => ({ ...f, [k]: e.target.value }));
  const selectedVersion = versions.find((v) => String(v.id) === String(form.package_version));
  const canSubmit = form.name.trim() && form.credential && form.target_machines.length > 0
    && (!needsPackage || form.package_version);

  const submit = async (e) => {
    e.preventDefault();
    setErr("");
    if (form.target_machines.length === 0) { setErr("Chọn ít nhất 1 máy đích."); return; }
    setBusy(true);
    try {
      const payload = {
        name: form.name,
        action: form.action,
        credential: form.credential,
        target_machines: form.target_machines,
        scheduled_at: form.scheduled_at ? new Date(form.scheduled_at).toISOString() : null,
        max_concurrency: Number(form.max_concurrency) || 1,
        retry_limit: Number(form.retry_limit) || 0,
      };
      // reboot/shutdown/inventory không gắn package_version (backend từ chối nếu gửi).
      if (needsPackage) payload.package_version = form.package_version;
      const dep = await api.post("/deployments/", payload);
      await api.post(`/deployments/${dep.id}/trigger/`, {});
      onDone();
    } catch (e2) {
      setErr(e2.message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="modal-bg" onClick={onClose}>
      <form className="modal modal-lg" onClick={(e) => e.stopPropagation()} onSubmit={submit}>
        <h3>Tạo & chạy deployment</h3>

        <div className="form-section">
          <div className="form-section-title">Thông tin chung</div>
          <label>Tên</label>
          <input value={form.name} onChange={set("name")} required />
          <label>Loại tác vụ</label>
          <select value={form.action} onChange={set("action")}>
            {visibleActions.map((a) => <option key={a.value} value={a.value}>{a.label}</option>)}
          </select>
          {needsPackage && (
            <>
              <label>Package version</label>
              <select value={form.package_version} onChange={set("package_version")} required>
                <option value="">— Chọn —</option>
                {versions.map((v) => (
                  <option key={v.id} value={v.id}>
                    {v.package_name} {v.version}{v.approved ? "" : " (chưa duyệt)"}
                  </option>
                ))}
              </select>
              {selectedVersion && !selectedVersion.approved && (
                <p className="warn-inline">Version này chưa được duyệt.</p>
              )}
            </>
          )}
        </div>

        <div className="form-section">
          <div className="form-section-title">Xác thực</div>
          <label>Credential deploy</label>
          <select value={form.credential} onChange={set("credential")} required>
            <option value="">— Chọn —</option>
            {credentials.map((c) => (
              <option key={c.id} value={c.id}>
                {c.name} — {c.domain ? `${c.domain}\\${c.username}` : c.username}{c.is_default ? " (mặc định)" : ""}
              </option>
            ))}
          </select>
        </div>

        <div className="form-section">
          <div className="form-section-title">Máy đích</div>
          <MachinePicker value={form.target_machines} onChange={(v) => setForm((f) => ({ ...f, target_machines: v }))} />
        </div>

        <details className="adv-details">
          <summary className="adv-summary">Tùy chọn nâng cao (lịch chạy, song song, thử lại)</summary>
          <div className="adv-body">
            <label>Lịch chạy (để trống = chạy ngay)</label>
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
          </div>
        </details>

        {err && <p className="error mt">{err}</p>}
        <div className="row spread mt">
          <button type="button" className="btn ghost" onClick={onClose}>Hủy</button>
          <button className="btn" disabled={busy || !canSubmit}>{busy ? "Đang chạy…" : "Tạo & Deploy"}</button>
        </div>
      </form>
    </div>
  );
}
