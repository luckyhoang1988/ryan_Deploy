import { useEffect, useState } from "react";
import { api, listOf } from "../api";
import { useAuth } from "../auth";

export default function Credentials() {
  const { hasRole } = useAuth();
  const isAdmin = hasRole("admin");
  const [creds, setCreds] = useState([]);
  const [editing, setEditing] = useState(null); // null = đóng, {} = tạo mới, {id..} = sửa
  const [err, setErr] = useState("");
  const [msg, setMsg] = useState("");

  const load = () =>
    api.get("/credentials/").then((d) => setCreds(listOf(d))).catch((e) => setErr(e.message));

  useEffect(() => {
    load();
  }, []);

  const remove = async (c) => {
    if (!confirm(`Xóa credential "${c.name}"? Deployment đang dùng nó sẽ không chạy được.`)) return;
    setErr(""); setMsg("");
    try {
      await api.del(`/credentials/${c.id}/`);
      setMsg(`Đã xóa "${c.name}".`);
      load();
    } catch (e) { setErr(e.message); }
  };

  return (
    <div>
      <div className="topbar">
        <h2>Credential deploy</h2>
        {isAdmin && <button className="btn" onClick={() => setEditing({})}>+ Thêm credential</button>}
      </div>
      <p className="muted" style={{ fontSize: 14, marginTop: -4 }}>
        Tài khoản domain có quyền local admin trên máy đích (dùng để kết nối SMB khi deploy).
        Mật khẩu được mã hóa at-rest, không bao giờ hiển thị lại.
      </p>
      {msg && <p className="muted">{msg}</p>}
      {err && <p className="error">{err}</p>}
      <table>
        <thead>
          <tr><th>Tên</th><th>Domain</th><th>Username</th><th>Mật khẩu</th><th>Mặc định</th><th></th></tr>
        </thead>
        <tbody>
          {creds.map((c) => (
            <tr key={c.id}>
              <td>{c.name}</td>
              <td className="muted">{c.domain || "—"}</td>
              <td>{c.username}</td>
              <td>{c.has_password ? "🔒 đã đặt" : <span className="error">chưa có</span>}</td>
              <td>{c.is_default ? "✓" : ""}</td>
              <td>
                {isAdmin && (
                  <div className="row" style={{ gap: 6 }}>
                    <button className="btn ghost" style={{ padding: "4px 10px" }} onClick={() => setEditing(c)}>Sửa</button>
                    <button className="btn ghost danger" style={{ padding: "4px 10px" }} onClick={() => remove(c)}>Xóa</button>
                  </div>
                )}
              </td>
            </tr>
          ))}
          {creds.length === 0 && (
            <tr><td colSpan="6" className="muted">Chưa có credential. {isAdmin ? "Bấm “Thêm credential”." : "Liên hệ admin để tạo."}</td></tr>
          )}
        </tbody>
      </table>
      {editing && (
        <CredentialModal
          cred={editing}
          onClose={() => setEditing(null)}
          onDone={() => { setEditing(null); setMsg("Đã lưu credential."); load(); }}
        />
      )}
    </div>
  );
}

function CredentialModal({ cred, onClose, onDone }) {
  const isEdit = !!cred.id;
  const [form, setForm] = useState({
    name: cred.name || "",
    domain: cred.domain || "",
    username: cred.username || "",
    password: "",
    is_default: !!cred.is_default,
  });
  const [err, setErr] = useState("");
  const [busy, setBusy] = useState(false);

  const set = (k) => (e) => {
    const v = e.target.type === "checkbox" ? e.target.checked : e.target.value;
    setForm((f) => ({ ...f, [k]: v }));
  };

  const submit = async (e) => {
    e.preventDefault();
    setErr(""); setBusy(true);
    try {
      const body = { name: form.name, domain: form.domain, username: form.username, is_default: form.is_default };
      // Chỉ gửi password khi có nhập (sửa mà để trống = giữ mật khẩu cũ).
      if (form.password) body.password = form.password;
      if (isEdit) await api.put(`/credentials/${cred.id}/`, body);
      else await api.post("/credentials/", body);
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
        <h3>{isEdit ? "Sửa credential" : "Thêm credential deploy"}</h3>
        <label>Tên gợi nhớ</label>
        <input value={form.name} onChange={set("name")} placeholder="svc_ryandeploy" required />
        <label>Domain (NetBIOS)</label>
        <input value={form.domain} onChange={set("domain")} placeholder="CORP" />
        <label>Username</label>
        <input value={form.username} onChange={set("username")} placeholder="svc_ryandeploy" required />
        <label>
          Mật khẩu {isEdit && <span className="muted">(để trống = giữ nguyên)</span>}
        </label>
        <input type="password" value={form.password} onChange={set("password")}
          placeholder={isEdit ? "••••••••" : "Nhập mật khẩu"} autoComplete="new-password"
          required={!isEdit} />
        <label className="row" style={{ gap: 8, alignItems: "center" }}>
          <input type="checkbox" checked={form.is_default} onChange={set("is_default")} style={{ width: "auto" }} />
          Đặt làm credential mặc định
        </label>
        {err && <p className="error mt">{err}</p>}
        <div className="row spread mt">
          <button type="button" className="btn ghost" onClick={onClose}>Hủy</button>
          <button className="btn" disabled={busy}>{busy ? "Đang lưu…" : "Lưu"}</button>
        </div>
      </form>
    </div>
  );
}
