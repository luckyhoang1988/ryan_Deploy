import { useEffect, useState } from "react";
import { api, listOf } from "../api";
import { useAuth } from "../auth";

const ROLES = [
  { value: "admin", label: "Quản trị (admin)" },
  { value: "operator", label: "Vận hành (operator)" },
  { value: "viewer", label: "Chỉ xem (viewer)" },
];
const ROLE_LABEL = { admin: "Quản trị", operator: "Vận hành", viewer: "Chỉ xem" };

function primaryRole(u) {
  if (u.roles?.includes("admin")) return "admin";
  if (u.roles?.includes("operator")) return "operator";
  if (u.roles?.includes("viewer")) return "viewer";
  return null;
}

export default function Users() {
  const { hasRole, user: me } = useAuth();
  const [users, setUsers] = useState([]);
  const [err, setErr] = useState("");
  const [msg, setMsg] = useState("");
  const [editing, setEditing] = useState(null); // đối tượng user, hoặc {} khi tạo mới

  const load = () =>
    api.get("/users/").then((d) => setUsers(listOf(d))).catch((e) => setErr(e.message));

  useEffect(() => {
    load();
  }, []);

  if (!hasRole("admin")) {
    return (
      <div>
        <div className="topbar"><h2>Người dùng</h2></div>
        <p className="error">Chỉ quản trị viên (admin) mới được quản lý người dùng.</p>
      </div>
    );
  }

  const remove = async (u) => {
    if (!window.confirm(`Xoá người dùng "${u.username}"?`)) return;
    setErr(""); setMsg("");
    try {
      await api.del(`/users/${u.id}/`);
      setMsg(`Đã xoá "${u.username}".`);
      load();
    } catch (e) { setErr(e.message); }
  };

  return (
    <div>
      <div className="topbar">
        <h2>Người dùng</h2>
        <button className="btn" onClick={() => { setErr(""); setMsg(""); setEditing({}); }}>
          + Thêm người dùng
        </button>
      </div>
      {msg && <p className="muted">{msg}</p>}
      {err && <p className="error">{err}</p>}
      <table>
        <thead>
          <tr>
            <th>Tên đăng nhập</th><th>Email</th><th>Vai trò</th>
            <th>Trạng thái</th><th>Đăng nhập gần nhất</th><th></th>
          </tr>
        </thead>
        <tbody>
          {users.map((u) => (
            <tr key={u.id}>
              <td>
                {u.username}
                {u.id === me.id && <span className="muted"> (bạn)</span>}
                {u.is_superuser && <span className="badge default" style={{ marginLeft: 6 }}>superuser</span>}
              </td>
              <td className="muted">{u.email || "—"}</td>
              <td>
                <span className={`badge ${primaryRole(u) === "admin" ? "success" : "default"}`}>
                  {ROLE_LABEL[primaryRole(u)] || "—"}
                </span>
              </td>
              <td>
                <span className={`badge ${u.is_active ? "success" : "failed"}`}>
                  {u.is_active ? "Đang bật" : "Đã khoá"}
                </span>
              </td>
              <td className="muted">
                {u.last_login ? new Date(u.last_login).toLocaleString("vi-VN") : "Chưa"}
              </td>
              <td className="row" style={{ justifyContent: "flex-end" }}>
                <button className="btn ghost" onClick={() => { setErr(""); setMsg(""); setEditing(u); }}>
                  Sửa
                </button>
                <button className="btn danger" onClick={() => remove(u)} disabled={u.id === me.id}>
                  Xoá
                </button>
              </td>
            </tr>
          ))}
          {users.length === 0 && (
            <tr><td colSpan="6" className="muted">Chưa có người dùng.</td></tr>
          )}
        </tbody>
      </table>
      {editing && (
        <UserModal
          user={editing}
          onClose={() => setEditing(null)}
          onSaved={(m) => { setMsg(m); setEditing(null); load(); }}
        />
      )}
    </div>
  );
}

function UserModal({ user, onClose, onSaved }) {
  const isNew = !user.id;
  const [form, setForm] = useState({
    username: user.username || "",
    email: user.email || "",
    role: isNew ? "viewer" : (primaryRole(user) || "viewer"),
    is_active: isNew ? true : !!user.is_active,
    password: "",
  });
  const [err, setErr] = useState("");
  const [busy, setBusy] = useState(false);

  const set = (k) => (e) => {
    const v = e.target.type === "checkbox" ? e.target.checked : e.target.value;
    setForm((f) => ({ ...f, [k]: v }));
  };

  const save = async (e) => {
    e?.preventDefault();
    setBusy(true); setErr("");
    try {
      const body = {
        username: form.username,
        email: form.email,
        role: form.role,
        is_active: form.is_active,
      };
      if (form.password) body.password = form.password;
      if (isNew) {
        await api.post("/users/", body);
        onSaved(`Đã tạo người dùng "${form.username}".`);
      } else {
        await api.patch(`/users/${user.id}/`, body);
        onSaved(`Đã cập nhật "${form.username}".`);
      }
    } catch (e2) {
      setErr(e2.message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="modal-bg" onClick={onClose}>
      <form className="modal" onClick={(e) => e.stopPropagation()} onSubmit={save}>
        <h3>{isNew ? "Thêm người dùng" : `Sửa: ${user.username}`}</h3>

        <label>Tên đăng nhập</label>
        <input value={form.username} onChange={set("username")} placeholder="vd: nva" required
          autoComplete="off" />

        <label>Email (tùy chọn)</label>
        <input type="email" value={form.email} onChange={set("email")} placeholder="nva@congty.vn" />

        <label>Vai trò</label>
        <select value={form.role} onChange={set("role")} disabled={user.is_superuser}>
          {ROLES.map((r) => <option key={r.value} value={r.value}>{r.label}</option>)}
        </select>
        {user.is_superuser && <p className="muted">Superuser luôn có quyền admin, không đổi được ở đây.</p>}

        <label>
          Mật khẩu {isNew ? "" : <span className="muted">(để trống nếu giữ nguyên)</span>}
        </label>
        <input type="password" value={form.password} onChange={set("password")}
          placeholder={isNew ? "Tối thiểu 8 ký tự" : "••••••••"}
          autoComplete="new-password" required={isNew} />

        <label className="row" style={{ gap: 8, alignItems: "center" }}>
          <input type="checkbox" checked={form.is_active} onChange={set("is_active")}
            style={{ width: "auto" }} />
          Kích hoạt tài khoản (bỏ chọn = khoá đăng nhập)
        </label>

        {err && <p className="error mt">{err}</p>}

        <div className="row spread mt">
          <button type="button" className="btn ghost" onClick={onClose}>Đóng</button>
          <button className="btn" disabled={busy}>{busy ? "Đang lưu…" : "Lưu"}</button>
        </div>
      </form>
    </div>
  );
}
