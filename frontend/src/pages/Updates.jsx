import { Fragment, useEffect, useState } from "react";
import { api, listOf } from "../api";
import { useAuth } from "../auth";
import Icon from "../components/Icon";

// Trang "Cập nhật" — bản của riêng RyanDeploy cho "133 Updates" của PDQ Deploy: so version
// đã cài toàn fleet (InstalledSoftware) với version mới nhất đã duyệt trong catalog.
export default function Updates() {
  const { hasRole } = useAuth();
  const canDeploy = hasRole("operator", "admin");
  const [items, setItems] = useState([]);
  const [expanded, setExpanded] = useState(null);
  const [deployFor, setDeployFor] = useState(null); // package item đang mở modal deploy
  const [loading, setLoading] = useState(true);
  const [err, setErr] = useState("");
  const [msg, setMsg] = useState("");

  const load = () => {
    setLoading(true);
    api
      .get("/updates/")
      .then((d) => setItems(d.results || []))
      .catch((e) => setErr(e.message))
      .finally(() => setLoading(false));
  };

  useEffect(() => {
    load();
  }, []);

  const totalMachines = items.reduce((s, it) => s + it.count, 0);

  return (
    <div>
      <div className="topbar">
        <h2>Cập nhật</h2>
        <button className="btn ghost" onClick={load}>
          <Icon name="refreshCw" size={16} /> <span>Làm mới</span>
        </button>
      </div>
      <p className="muted">
        {loading
          ? "Đang dò…"
          : `${items.length} phần mềm có bản mới · ${totalMachines} máy lỗi thời (theo inventory gần nhất).`}
      </p>
      {msg && <p className="muted">{msg}</p>}
      {err && <p className="error">{err}</p>}
      <table>
        <thead>
          <tr>
            <th>Phần mềm</th>
            <th>Bản mới nhất</th>
            <th>Máy lỗi thời</th>
            {canDeploy && <th></th>}
          </tr>
        </thead>
        <tbody>
          {items.map((it) => {
            const isOpen = expanded === it.package_id;
            return (
              <Fragment key={it.package_id}>
                <tr>
                  <td>{it.package_name}</td>
                  <td>
                    <span className="badge success">{it.latest_version}</span>
                  </td>
                  <td>
                    <button
                      className="btn ghost"
                      style={{ padding: "2px 8px" }}
                      onClick={() => setExpanded(isOpen ? null : it.package_id)}
                    >
                      {isOpen ? "▾" : "▸"} {it.count} máy
                    </button>
                  </td>
                  {canDeploy && (
                    <td>
                      <button
                        className="btn"
                        style={{ padding: "4px 12px" }}
                        onClick={() => setDeployFor(it)}
                      >
                        <Icon name="download" size={14} /> Deploy cập nhật
                      </button>
                    </td>
                  )}
                </tr>
                {isOpen && (
                  <tr>
                    <td colSpan={canDeploy ? 4 : 3} style={{ background: "rgba(0,0,0,0.15)" }}>
                      <table style={{ margin: 0 }}>
                        <thead>
                          <tr>
                            <th>Máy</th>
                            <th>Đang cài</th>
                            <th>→ Sẽ lên</th>
                          </tr>
                        </thead>
                        <tbody>
                          {it.outdated.map((o) => (
                            <tr key={o.machine_id}>
                              <td>{o.hostname}</td>
                              <td className="muted">{o.installed_version || "—"}</td>
                              <td>{it.latest_version}</td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </td>
                  </tr>
                )}
              </Fragment>
            );
          })}
          {!loading && items.length === 0 && (
            <tr>
              <td colSpan={canDeploy ? 4 : 3} className="muted">
                Toàn bộ fleet đã cập nhật (hoặc chưa có dữ liệu inventory / version đã duyệt).
              </td>
            </tr>
          )}
        </tbody>
      </table>
      {deployFor && (
        <DeployUpdateModal
          item={deployFor}
          onClose={() => setDeployFor(null)}
          onDone={(n) => {
            setDeployFor(null);
            setMsg(`Đã tạo & chạy deployment cập nhật ${deployFor.package_name} tới ${n} máy.`);
            load();
          }}
        />
      )}
    </div>
  );
}

function DeployUpdateModal({ item, onClose, onDone }) {
  const [credentials, setCredentials] = useState([]);
  const [credential, setCredential] = useState("");
  const [err, setErr] = useState("");
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    api.get("/credentials/").then((d) => setCredentials(listOf(d))).catch(() => {});
  }, []);

  const submit = async (e) => {
    e.preventDefault();
    setErr("");
    setBusy(true);
    try {
      const res = await api.post(`/updates/${item.package_id}/deploy/`, { credential });
      onDone(res.jobs ?? item.count);
    } catch (e2) {
      setErr(e2.message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="modal-bg" onClick={onClose}>
      <form className="modal" onClick={(e) => e.stopPropagation()} onSubmit={submit}>
        <h3>Deploy cập nhật — {item.package_name}</h3>
        <p className="muted" style={{ marginTop: -4 }}>
          Cài <b>{item.latest_version}</b> lên <b>{item.count}</b> máy lỗi thời.
        </p>
        <label>Credential deploy</label>
        <select value={credential} onChange={(e) => setCredential(e.target.value)} required>
          <option value="">— Chọn —</option>
          {credentials.map((c) => (
            <option key={c.id} value={c.id}>
              {c.name}
            </option>
          ))}
        </select>
        {err && <p className="error mt">{err}</p>}
        <div className="row spread mt">
          <button type="button" className="btn ghost" onClick={onClose}>
            Hủy
          </button>
          <button className="btn" disabled={busy || !credential}>
            {busy ? "Đang chạy…" : "Tạo & Deploy"}
          </button>
        </div>
      </form>
    </div>
  );
}
