import { useEffect, useState } from "react";
import { api, fetchAll, listOf } from "../api";
import { useAuth } from "../auth";

// Action cần chọn package version; các action khác chạy không gắn package (khớp Deployments.jsx).
const ACTIONS = [
  { value: "install", label: "Cài đặt" },
  { value: "uninstall", label: "Gỡ cài đặt" },
  { value: "reboot", label: "Khởi động lại" },
  { value: "shutdown", label: "Tắt máy" },
  { value: "inventory", label: "Quét phần mềm (inventory)" },
];
const PACKAGE_ACTIONS = ["install", "uninstall"];
const ADMIN_ONLY_ACTIONS = ["reboot", "shutdown"];
const WEEKDAY_LABELS = ["Th 2", "Th 3", "Th 4", "Th 5", "Th 6", "Th 7", "CN"];

function recurrenceLabel(s) {
  if (s.recurrence_type === "interval") {
    return `Mỗi ${s.interval_minutes} phút`;
  }
  if (s.recurrence_type === "weekly") {
    const days = (s.weekly_days || []).map((d) => WEEKDAY_LABELS[d]).join(", ") || "—";
    return `${days} lúc ${(s.weekly_time || "").slice(0, 5)}`;
  }
  return "—";
}

export default function Schedules() {
  const { hasRole } = useAuth();
  const canWrite = hasRole("operator", "admin");
  const isAdmin = hasRole("admin");
  const [schedules, setSchedules] = useState([]);
  const [showWizard, setShowWizard] = useState(false);
  const [editSched, setEditSched] = useState(null);
  const [err, setErr] = useState("");
  const [msg, setMsg] = useState("");

  const load = () =>
    api.get("/deployment-schedules/").then((d) => setSchedules(listOf(d))).catch((e) => setErr(e.message));

  useEffect(() => {
    load();
  }, []);

  const toggleEnabled = async (s) => {
    setErr(""); setMsg("");
    try {
      await api.patch(`/deployment-schedules/${s.id}/`, { enabled: !s.enabled });
      load();
    } catch (e) { setErr(e.message); }
  };

  const remove = async (s) => {
    if (!confirm(`Xóa lịch "${s.name}"? Các deployment đã sinh ra trước đó vẫn giữ nguyên.`)) return;
    setErr(""); setMsg("");
    try {
      await api.del(`/deployment-schedules/${s.id}/`);
      setMsg(`Đã xóa lịch "${s.name}".`);
      load();
    } catch (e) { setErr(e.message); }
  };

  return (
    <div>
      <div className="topbar">
        <h2>Lịch lặp (Recurring)</h2>
        {canWrite && <button className="btn" onClick={() => setShowWizard(true)}>+ Tạo lịch lặp</button>}
      </div>
      <p className="muted" style={{ marginTop: -4 }}>
        Tự động sinh 1 deployment mới và chạy mỗi khi tới giờ — xem lịch sử từng lần chạy ở trang Deployments.
      </p>
      {msg && <p className="muted">{msg}</p>}
      {err && <p className="error">{err}</p>}
      <table>
        <thead>
          <tr>
            <th>Tên</th><th>Package</th><th>Lặp lại</th><th>Trạng thái</th><th>Lần chạy cuối</th><th></th>
          </tr>
        </thead>
        <tbody>
          {schedules.map((s) => (
            <tr key={s.id}>
              <td>{s.name}</td>
              <td>{s.package_name ? `${s.package_name} ${s.version}` : ACTIONS.find((a) => a.value === s.action)?.label}</td>
              <td className="muted">{recurrenceLabel(s)}</td>
              <td>
                {canWrite ? (
                  <button className="btn ghost" style={{ padding: "2px 8px" }} onClick={() => toggleEnabled(s)}>
                    <span className={`badge ${s.enabled ? "success" : "default"}`}>{s.enabled ? "Đang bật" : "Đã tắt"}</span>
                  </button>
                ) : (
                  <span className={`badge ${s.enabled ? "success" : "default"}`}>{s.enabled ? "Đang bật" : "Đã tắt"}</span>
                )}
              </td>
              <td className="muted">{s.last_triggered_at ? new Date(s.last_triggered_at).toLocaleString() : "Chưa chạy"}</td>
              <td>
                {canWrite && (
                  <div className="row" style={{ gap: 10, justifyContent: "flex-end" }}>
                    <button className="btn ghost" style={{ padding: "4px 10px" }} onClick={() => setEditSched(s)}>Sửa</button>
                    <button className="btn ghost danger" style={{ padding: "4px 10px" }} onClick={() => remove(s)}>Xóa</button>
                  </div>
                )}
              </td>
            </tr>
          ))}
          {schedules.length === 0 && <tr><td colSpan="6" className="muted">Chưa có lịch lặp.</td></tr>}
        </tbody>
      </table>
      {showWizard && (
        <ScheduleModal
          isAdmin={isAdmin}
          onClose={() => setShowWizard(false)}
          onDone={() => { setShowWizard(false); setMsg("Đã tạo lịch lặp."); load(); }}
        />
      )}
      {editSched && (
        <ScheduleModal
          sched={editSched}
          isAdmin={isAdmin}
          onClose={() => setEditSched(null)}
          onDone={() => { setEditSched(null); setMsg("Đã lưu lịch lặp."); load(); }}
        />
      )}
    </div>
  );
}

function ScheduleModal({ sched, isAdmin, onClose, onDone }) {
  const isEdit = !!sched;
  const [versions, setVersions] = useState([]);
  const [credentials, setCredentials] = useState([]);
  const [machines, setMachines] = useState([]);
  const [machineSearch, setMachineSearch] = useState("");
  const [form, setForm] = useState({
    name: sched?.name || "",
    action: sched?.action || "install",
    package_version: sched?.package_version || "",
    credential: sched?.credential || "",
    target_machines: sched?.target_machines || [],
    max_concurrency: sched?.max_concurrency ?? 15,
    retry_limit: sched?.retry_limit ?? 1,
    recurrence_type: sched?.recurrence_type || "interval",
    interval_minutes: sched?.interval_minutes ?? 60,
    weekly_days: sched?.weekly_days || [],
    weekly_time: sched?.weekly_time?.slice(0, 5) || "22:00",
    enabled: sched?.enabled ?? true,
  });
  const [err, setErr] = useState("");
  const [busy, setBusy] = useState(false);
  const needsPackage = PACKAGE_ACTIONS.includes(form.action);
  const adminActionBlocked = ADMIN_ONLY_ACTIONS.includes(form.action) && !isAdmin;

  useEffect(() => {
    api.get("/package-versions/").then((d) => setVersions(listOf(d)));
    api.get("/credentials/").then((d) => setCredentials(listOf(d))).catch(() => {});
    fetchAll("/machines/").then(setMachines).catch((e) => setErr(e.message));
  }, []);

  const q = machineSearch.trim().toLowerCase();
  const shownMachines = q ? machines.filter((m) => m.hostname.toLowerCase().includes(q)) : machines;

  const toggleMachine = (id) => {
    setForm((f) => {
      const has = f.target_machines.includes(id);
      return { ...f, target_machines: has ? f.target_machines.filter((x) => x !== id) : [...f.target_machines, id] };
    });
  };

  const toggleWeekday = (d) => {
    setForm((f) => {
      const has = f.weekly_days.includes(d);
      return { ...f, weekly_days: has ? f.weekly_days.filter((x) => x !== d) : [...f.weekly_days, d].sort() };
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
        max_concurrency: Number(form.max_concurrency) || 1,
        retry_limit: Number(form.retry_limit) || 0,
        recurrence_type: form.recurrence_type,
        enabled: form.enabled,
      };
      if (needsPackage) payload.package_version = form.package_version;
      if (form.recurrence_type === "interval") {
        payload.interval_minutes = Number(form.interval_minutes) || 0;
      } else {
        payload.weekly_days = form.weekly_days;
        payload.weekly_time = form.weekly_time;
      }
      if (isEdit) {
        await api.patch(`/deployment-schedules/${sched.id}/`, payload);
      } else {
        await api.post("/deployment-schedules/", payload);
      }
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
        <h3>{isEdit ? "Sửa lịch lặp" : "Tạo lịch lặp"}</h3>
        <label>Tên</label>
        <input value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} required />
        <label>Loại tác vụ</label>
        <select value={form.action} onChange={(e) => setForm({ ...form, action: e.target.value })}>
          {ACTIONS.map((a) => <option key={a.value} value={a.value}>{a.label}</option>)}
        </select>
        {adminActionBlocked && (
          <p className="error" style={{ fontSize: 12 }}>Chỉ admin được tạo lịch reboot/shutdown.</p>
        )}
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

        <hr style={{ border: 0, borderTop: "1px solid rgba(255,255,255,0.1)", margin: "14px 0 4px" }} />
        <label>Kiểu lặp</label>
        <select value={form.recurrence_type} onChange={(e) => setForm({ ...form, recurrence_type: e.target.value })}>
          <option value="interval">Mỗi N phút</option>
          <option value="weekly">Theo ngày trong tuần</option>
        </select>
        {form.recurrence_type === "interval" ? (
          <>
            <label>Chạy lại mỗi (phút)</label>
            <input type="number" min="1" value={form.interval_minutes}
              onChange={(e) => setForm({ ...form, interval_minutes: e.target.value })} required />
          </>
        ) : (
          <>
            <label>Ngày trong tuần</label>
            <div className="row" style={{ gap: 6, flexWrap: "wrap" }}>
              {WEEKDAY_LABELS.map((label, d) => (
                <button type="button" key={d}
                  className={`btn ${form.weekly_days.includes(d) ? "" : "ghost"}`}
                  style={{ padding: "4px 10px" }}
                  onClick={() => toggleWeekday(d)}>
                  {label}
                </button>
              ))}
            </div>
            <label>Giờ chạy</label>
            <input type="time" value={form.weekly_time} onChange={(e) => setForm({ ...form, weekly_time: e.target.value })} required />
          </>
        )}
        <label className="row" style={{ gap: 8, marginTop: 8 }}>
          <input type="checkbox" style={{ width: "auto" }} checked={form.enabled}
            onChange={(e) => setForm({ ...form, enabled: e.target.checked })} />
          <span>Bật lịch (bỏ chọn để tạm dừng)</span>
        </label>

        <hr style={{ border: 0, borderTop: "1px solid rgba(255,255,255,0.1)", margin: "14px 0 4px" }} />
        <label>Máy đích ({form.target_machines.length} chọn / {machines.length} máy)</label>
        <div className="row" style={{ gap: 8, marginBottom: 6 }}>
          <input
            type="text"
            placeholder="🔍 Lọc theo hostname…"
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
              <span>{m.hostname} {m.is_online ? "🟢" : "⚪"}</span>
            </label>
          ))}
          {machines.length === 0 && <span className="muted">Chưa có máy.</span>}
          {machines.length > 0 && shownMachines.length === 0 && <span className="muted">Không có máy khớp bộ lọc.</span>}
        </div>

        {err && <p className="error mt">{err}</p>}
        <div className="row spread mt">
          <button type="button" className="btn ghost" onClick={onClose}>Hủy</button>
          <button className="btn" disabled={busy || adminActionBlocked}>{busy ? "Đang lưu…" : "Lưu"}</button>
        </div>
      </form>
    </div>
  );
}
