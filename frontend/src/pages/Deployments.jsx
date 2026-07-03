import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api, listOf, fetchAll } from "../api";
import { StatusBadge } from "../components/Layout";

export default function Deployments() {
  const [deployments, setDeployments] = useState([]);
  const [showWizard, setShowWizard] = useState(false);
  const [err, setErr] = useState("");

  const load = () =>
    api.get("/deployments/").then((d) => setDeployments(listOf(d))).catch((e) => setErr(e.message));

  useEffect(() => {
    load();
  }, []);

  return (
    <div>
      <div className="topbar">
        <h2>Deployments</h2>
        <button className="btn" onClick={() => setShowWizard(true)}>+ Tạo deployment</button>
      </div>
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
              <td><Link to={`/deployments/${d.id}`}>Chi tiết →</Link></td>
            </tr>
          ))}
          {deployments.length === 0 && <tr><td colSpan="5" className="muted">Chưa có deployment.</td></tr>}
        </tbody>
      </table>
      {showWizard && (
        <Wizard onClose={() => setShowWizard(false)} onDone={() => { setShowWizard(false); load(); }} />
      )}
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
