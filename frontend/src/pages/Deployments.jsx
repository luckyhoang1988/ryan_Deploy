import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api, listOf, fetchAll } from "../api";
import { StatusBadge } from "../components/Layout";
import { useAuth } from "../auth";
import { subscribe } from "../ws";

export default function Deployments() {
  const { hasRole } = useAuth();
  const canWrite = hasRole("operator", "admin");
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
        <Wizard onClose={() => setShowWizard(false)} onDone={() => { setShowWizard(false); setMsg("Đã tạo deployment."); load(); }} />
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

// Action cần chọn package version; các action khác chạy không gắn package.
const ACTIONS = [
  { value: "install", label: "Cài đặt" },
  { value: "uninstall", label: "Gỡ cài đặt" },
  { value: "reboot", label: "Khởi động lại" },
  { value: "shutdown", label: "Tắt máy" },
  { value: "inventory", label: "Quét phần mềm (inventory)" },
];
const PACKAGE_ACTIONS = ["install", "uninstall"];

// Lấy OU lá (OU= đầu tiên trong DN) để hiển thị gọn cạnh hostname.
function ouLabel(dn) {
  if (!dn) return "";
  const m = dn.match(/OU=([^,]+)/i);
  return m ? m[1] : "";
}

function Wizard({ onClose, onDone }) {
  const [versions, setVersions] = useState([]);
  const [credentials, setCredentials] = useState([]);
  const [machines, setMachines] = useState([]);
  const [machineSearch, setMachineSearch] = useState("");
  const [form, setForm] = useState({ name: "", action: "install", package_version: "", credential: "", target_machines: [] });
  const [err, setErr] = useState("");
  const [busy, setBusy] = useState(false);
  const needsPackage = PACKAGE_ACTIONS.includes(form.action);

  useEffect(() => {
    api.get("/package-versions/").then((d) => setVersions(listOf(d)));
    api.get("/credentials/").then((d) => setCredentials(listOf(d))).catch(() => {});
    // Lấy TẤT CẢ máy qua mọi trang (không chỉ 25 máy trang đầu).
    fetchAll("/machines/").then(setMachines).catch((e) => setErr(e.message));
  }, []);

  // Lọc theo hostname HOẶC OU (full DN). Khớp chuỗi con trên DN nên gõ tên OU cha sẽ
  // bao gồm cả máy nằm trong các OU con (DN của OU con chứa tên OU cha).
  const q = machineSearch.trim().toLowerCase();
  const shownMachines = q
    ? machines.filter((m) => `${m.hostname} ${m.ad_ou || ""}`.toLowerCase().includes(q))
    : machines;

  const toggleMachine = (id) => {
    setForm((f) => {
      const has = f.target_machines.includes(id);
      return { ...f, target_machines: has ? f.target_machines.filter((x) => x !== id) : [...f.target_machines, id] };
    });
  };

  const submit = async (e) => {
    e.preventDefault();
    setErr(""); setBusy(true);
    try {
      const payload = {
        name: form.name,
        action: form.action,
        credential: form.credential,
        target_machines: form.target_machines,
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
      <form className="modal" onClick={(e) => e.stopPropagation()} onSubmit={submit}>
        <h3>Tạo & chạy deployment</h3>
        <label>Tên</label>
        <input value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} required />
        <label>Loại tác vụ</label>
        <select value={form.action} onChange={(e) => setForm({ ...form, action: e.target.value })}>
          {ACTIONS.map((a) => <option key={a.value} value={a.value}>{a.label}</option>)}
        </select>
        {needsPackage && (
          <>
            <label>Package version</label>
            <select value={form.package_version} onChange={(e) => setForm({ ...form, package_version: e.target.value })} required>
              <option value="">— Chọn —</option>
              {versions.map((v) => <option key={v.id} value={v.id}>{v.package_name} {v.version}</option>)}
            </select>
          </>
        )}
        <label>Credential deploy</label>
        <select value={form.credential} onChange={(e) => setForm({ ...form, credential: e.target.value })} required>
          <option value="">— Chọn —</option>
          {credentials.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
        </select>
        <label>Máy đích ({form.target_machines.length} chọn / {machines.length} máy)</label>
        <div className="row" style={{ gap: 8, marginBottom: 6 }}>
          <input
            type="text"
            placeholder="🔍 Lọc theo hostname hoặc OU…"
            value={machineSearch}
            onChange={(e) => setMachineSearch(e.target.value)}
            style={{ flex: 1 }}
          />
          <button type="button" className="btn ghost" style={{ padding: "6px 10px" }}
            onClick={() => setForm((f) => ({ ...f, target_machines: [...new Set([...f.target_machines, ...shownMachines.map((m) => m.id)])] }))}>
            Chọn hết ({shownMachines.length})
          </button>
          {form.target_machines.length > 0 && (
            <button type="button" className="btn ghost" style={{ padding: "6px 10px" }}
              onClick={() => setForm((f) => ({ ...f, target_machines: [] }))}>
              Bỏ chọn
            </button>
          )}
        </div>
        <div className="log" style={{ maxHeight: 160 }}>
          {shownMachines.map((m) => (
            <label key={m.id} className="row" style={{ margin: "2px 0" }}>
              <input type="checkbox" style={{ width: "auto" }}
                checked={form.target_machines.includes(m.id)}
                onChange={() => toggleMachine(m.id)} />
              <span>
                {m.hostname} {m.is_online ? "🟢" : "⚪"}
                {ouLabel(m.ad_ou) && <span className="muted" style={{ marginLeft: 6, fontSize: 12 }}>· {ouLabel(m.ad_ou)}</span>}
              </span>
            </label>
          ))}
          {machines.length === 0 && <span className="muted">Chưa có máy.</span>}
          {machines.length > 0 && shownMachines.length === 0 && <span className="muted">Không có máy khớp bộ lọc.</span>}
        </div>
        {err && <p className="error mt">{err}</p>}
        <div className="row spread mt">
          <button type="button" className="btn ghost" onClick={onClose}>Hủy</button>
          <button className="btn" disabled={busy}>{busy ? "Đang chạy…" : "Tạo & Deploy"}</button>
        </div>
      </form>
    </div>
  );
}
