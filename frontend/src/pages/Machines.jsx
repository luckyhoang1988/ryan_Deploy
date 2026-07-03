import { useEffect, useState } from "react";
import { api, listOf, waitForTask } from "../api";
import { useAuth } from "../auth";
import { StatusBadge } from "../components/Layout";

export default function Machines() {
  const { hasRole } = useAuth();
  const [machines, setMachines] = useState([]);
  const [msg, setMsg] = useState("");
  const [err, setErr] = useState("");
  const [busy, setBusy] = useState("");
  const [showConfig, setShowConfig] = useState(false);

  const load = () =>
    api.get("/machines/").then((d) => setMachines(listOf(d))).catch((e) => setErr(e.message));

  useEffect(() => {
    load();
  }, []);

  const syncAd = async () => {
    setBusy("ad"); setErr(""); setMsg("");
    try {
      const { task_id } = await api.post("/machines/sync_ad/", {});
      const t = await waitForTask(task_id);
      if (t.state === "FAILURE") { setErr(`AD sync: ${t.error}`); return; }
      const r = t.result || {};
      if (r.error) { setErr(`AD sync: ${r.error}`); return; }
      setMsg(`AD sync: +${r.created} mới, ${r.updated} cập nhật`);
      load();
    } catch (e) { setErr(e.message); } finally { setBusy(""); }
  };

  const checkOnline = async () => {
    setBusy("online"); setErr(""); setMsg("");
    try {
      const { task_id } = await api.post("/machines/check_online/", {});
      const t = await waitForTask(task_id);
      if (t.state === "FAILURE") { setErr(`Online check: ${t.error}`); return; }
      const r = t.result || {};
      setMsg(`Online check: ${r.online}/${r.checked} máy online`);
      load();
    } catch (e) { setErr(e.message); } finally { setBusy(""); }
  };

  return (
    <div>
      <div className="topbar">
        <h2>Máy trạm</h2>
        <div className="row">
          {hasRole("admin") && (
            <button className="btn ghost" onClick={() => setShowConfig(true)} disabled={busy}>
              Cấu hình AD
            </button>
          )}
          {hasRole("admin") && (
            <button className="btn ghost" onClick={syncAd} disabled={busy}>
              {busy === "ad" ? "Đang sync…" : "Sync AD"}
            </button>
          )}
          <button className="btn ghost" onClick={checkOnline} disabled={busy}>
            {busy === "online" ? "Đang kiểm tra…" : "Kiểm tra online"}
          </button>
        </div>
      </div>
      {msg && <p className="muted">{msg}</p>}
      {err && <p className="error">{err}</p>}
      <table>
        <thead>
          <tr><th>Hostname</th><th>FQDN</th><th>OS</th><th>OU</th><th>Trạng thái</th></tr>
        </thead>
        <tbody>
          {machines.map((m) => (
            <tr key={m.id}>
              <td>{m.hostname}</td>
              <td className="muted">{m.fqdn || "—"}</td>
              <td>{m.os_name || "—"}</td>
              <td className="muted">{m.ad_ou || "—"}</td>
              <td><StatusBadge status={m.is_online ? "success" : "failed"} /></td>
            </tr>
          ))}
          {machines.length === 0 && <tr><td colSpan="5" className="muted">Chưa có máy. Bấm “Sync AD”.</td></tr>}
        </tbody>
      </table>
      {showConfig && (
        <ADConfigModal
          onClose={() => setShowConfig(false)}
          onSaved={() => setMsg("Đã lưu cấu hình AD.")}
        />
      )}
    </div>
  );
}

function ADConfigModal({ onClose, onSaved }) {
  const [form, setForm] = useState({
    server: "",
    base_dn: "",
    search_ou: "",
    bind_user: "",
    bind_password: "",
    use_ssl: false,
    enabled: false,
  });
  const [hasPassword, setHasPassword] = useState(false);
  const [err, setErr] = useState("");
  const [testMsg, setTestMsg] = useState("");
  const [busy, setBusy] = useState("");

  useEffect(() => {
    api.get("/ad-config/").then((d) => {
      setForm((f) => ({
        ...f,
        server: d.server || "",
        base_dn: d.base_dn || "",
        search_ou: d.search_ou || "",
        bind_user: d.bind_user || "",
        use_ssl: !!d.use_ssl,
        enabled: !!d.enabled,
      }));
      setHasPassword(!!d.has_password);
    }).catch((e) => setErr(e.message));
  }, []);

  const set = (k) => (e) => {
    const v = e.target.type === "checkbox" ? e.target.checked : e.target.value;
    setForm((f) => ({ ...f, [k]: v }));
  };

  const save = async (e) => {
    e?.preventDefault();
    setBusy("save"); setErr(""); setTestMsg("");
    try {
      const body = { ...form };
      if (!body.bind_password) delete body.bind_password; // giữ mật khẩu cũ
      const d = await api.put("/ad-config/", body);
      setHasPassword(!!d.has_password);
      setForm((f) => ({ ...f, bind_password: "" }));
      onSaved?.();
    } catch (e2) { setErr(e2.message); } finally { setBusy(""); }
  };

  const test = async () => {
    // Lưu trước rồi test cấu hình đã lưu.
    setBusy("test"); setErr(""); setTestMsg("");
    try {
      const body = { ...form };
      if (!body.bind_password) delete body.bind_password;
      await api.put("/ad-config/", body);
      setForm((f) => ({ ...f, bind_password: "" }));
      setHasPassword(true);
      const r = await api.post("/ad-config/test/", {});
      const found = r.computers_found != null ? `, tìm thấy ${r.computers_found} máy` : "";
      setTestMsg(`✓ Kết nối OK (bind: ${r.bound_as})${found}`);
    } catch (e2) {
      setErr(e2.message);
    } finally { setBusy(""); }
  };

  return (
    <div className="modal-bg" onClick={onClose}>
      <form className="modal" onClick={(e) => e.stopPropagation()} onSubmit={save}>
        <h3>Cấu hình kết nối AD / LDAP</h3>

        <label>Server (host hoặc URI)</label>
        <input value={form.server} onChange={set("server")} placeholder="dc01.corp.local" required />

        <label>Base DN</label>
        <input value={form.base_dn} onChange={set("base_dn")} placeholder="DC=corp,DC=local" />

        <label>Search OU (tùy chọn — giới hạn phạm vi sync)</label>
        <input value={form.search_ou} onChange={set("search_ou")} placeholder="OU=Workstations,DC=corp,DC=local" />

        <label>Bind user</label>
        <input value={form.bind_user} onChange={set("bind_user")} placeholder="CORP\svc_deploy" required />

        <label>Bind password {hasPassword && <span className="muted">(đã lưu — để trống nếu giữ nguyên)</span>}</label>
        <input type="password" value={form.bind_password} onChange={set("bind_password")}
          placeholder={hasPassword ? "••••••••" : "Nhập mật khẩu"} autoComplete="new-password" />

        <label className="row" style={{ gap: 8, alignItems: "center" }}>
          <input type="checkbox" checked={form.use_ssl} onChange={set("use_ssl")} style={{ width: "auto" }} />
          Dùng LDAPS (SSL, cổng 636)
        </label>

        <label className="row" style={{ gap: 8, alignItems: "center" }}>
          <input type="checkbox" checked={form.enabled} onChange={set("enabled")} style={{ width: "auto" }} />
          Kích hoạt cấu hình này (ưu tiên hơn biến môi trường)
        </label>

        {testMsg && <p className="muted mt">{testMsg}</p>}
        {err && <p className="error mt">{err}</p>}

        <div className="row spread mt">
          <button type="button" className="btn ghost" onClick={onClose}>Đóng</button>
          <div className="row">
            <button type="button" className="btn ghost" onClick={test} disabled={busy}>
              {busy === "test" ? "Đang test…" : "Test kết nối"}
            </button>
            <button className="btn" disabled={busy}>{busy === "save" ? "Đang lưu…" : "Lưu"}</button>
          </div>
        </div>
      </form>
    </div>
  );
}
