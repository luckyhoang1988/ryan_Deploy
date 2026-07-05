import { useEffect, useState } from "react";
import { api, listOf } from "../api";
import MachinePicker from "./MachinePicker";
import { ACTIONS, PACKAGE_ACTIONS, ADMIN_ONLY_ACTIONS } from "../constants/deployment";

// Modal tạo & chạy deployment — dùng chung giữa trang Deployments (wizard trống) và
// Packages (mở sẵn với 1 package version, kiểu "Deploy" 1 chạm từ Package Library).
export default function DeploymentWizard({ isAdmin, initialPackageVersionId, initialAction, onClose, onDone }) {
  const [versions, setVersions] = useState([]);
  const [credentials, setCredentials] = useState([]);
  const [form, setForm] = useState({
    name: "", action: initialAction || "install",
    package_version: initialPackageVersionId ? String(initialPackageVersionId) : "",
    credential: "", target_machines: [],
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
