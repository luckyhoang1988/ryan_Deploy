import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api, listOf } from "../api";
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

function Wizard({ onClose, onDone }) {
  const [versions, setVersions] = useState([]);
  const [credentials, setCredentials] = useState([]);
  const [machines, setMachines] = useState([]);
  const [form, setForm] = useState({ name: "", package_version: "", credential: "", target_machines: [] });
  const [err, setErr] = useState("");
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    api.get("/package-versions/").then((d) => setVersions(listOf(d)));
    api.get("/credentials/").then((d) => setCredentials(listOf(d))).catch(() => {});
    api.get("/machines/").then((d) => setMachines(listOf(d)));
  }, []);

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
      const dep = await api.post("/deployments/", {
        name: form.name,
        package_version: form.package_version,
        credential: form.credential,
        target_machines: form.target_machines,
      });
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
        <label>Package version</label>
        <select value={form.package_version} onChange={(e) => setForm({ ...form, package_version: e.target.value })} required>
          <option value="">— Chọn —</option>
          {versions.map((v) => <option key={v.id} value={v.id}>{v.package_name} {v.version}</option>)}
        </select>
        <label>Credential deploy</label>
        <select value={form.credential} onChange={(e) => setForm({ ...form, credential: e.target.value })} required>
          <option value="">— Chọn —</option>
          {credentials.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
        </select>
        <label>Máy đích ({form.target_machines.length} chọn)</label>
        <div className="log" style={{ maxHeight: 160 }}>
          {machines.map((m) => (
            <label key={m.id} className="row" style={{ margin: "2px 0" }}>
              <input type="checkbox" style={{ width: "auto" }}
                checked={form.target_machines.includes(m.id)}
                onChange={() => toggleMachine(m.id)} />
              <span>{m.hostname} {m.is_online ? "🟢" : "⚪"}</span>
            </label>
          ))}
          {machines.length === 0 && <span className="muted">Chưa có máy.</span>}
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
