import { Fragment, useEffect, useState } from "react";
import { api, listOf } from "../api";
import { useAuth } from "../auth";

export default function Packages() {
  const { hasRole } = useAuth();
  const isAdmin = hasRole("admin");
  const [packages, setPackages] = useState([]);
  const [showUpload, setShowUpload] = useState(false);
  const [editPkg, setEditPkg] = useState(null); // package đang sửa
  const [editVer, setEditVer] = useState(null); // version đang sửa
  const [expanded, setExpanded] = useState(null); // id package đang mở versions
  const [err, setErr] = useState("");
  const [msg, setMsg] = useState("");

  const load = () =>
    api.get("/packages/").then((d) => setPackages(listOf(d))).catch((e) => setErr(e.message));

  useEffect(() => {
    load();
  }, []);

  const removePkg = async (p) => {
    if (!confirm(`Xóa package "${p.name}" và toàn bộ ${p.versions?.length || 0} version của nó?`)) return;
    setErr(""); setMsg("");
    try {
      await api.del(`/packages/${p.id}/`);
      setMsg(`Đã xóa package "${p.name}".`);
      load();
    } catch (e) { setErr(e.message); }
  };

  const removeVersion = async (p, v) => {
    if (!confirm(`Xóa version "${v.version}" của "${p.name}"? File installer sẽ bị xóa khỏi repository.`)) return;
    setErr(""); setMsg("");
    try {
      await api.del(`/package-versions/${v.id}/`);
      setMsg(`Đã xóa version "${v.version}".`);
      load();
    } catch (e) { setErr(e.message); }
  };

  return (
    <div>
      <div className="topbar">
        <h2>Packages</h2>
        {isAdmin && <button className="btn" onClick={() => setShowUpload(true)}>+ Upload version</button>}
      </div>
      {msg && <p className="muted">{msg}</p>}
      {err && <p className="error">{err}</p>}
      <table>
        <thead>
          <tr>
            <th>Tên</th><th>Vendor</th><th>Versions</th><th>License khả dụng</th>
            {isAdmin && <th></th>}
          </tr>
        </thead>
        <tbody>
          {packages.map((p) => {
            const isOpen = expanded === p.id;
            return (
              <Fragment key={p.id}>
                <tr>
                  <td>{p.name}</td>
                  <td className="muted">{p.vendor || "—"}</td>
                  <td>
                    <button className="btn ghost" style={{ padding: "2px 8px" }}
                      onClick={() => setExpanded(isOpen ? null : p.id)}>
                      {isOpen ? "▾" : "▸"} {p.versions?.length || 0} version
                    </button>
                  </td>
                  <td>{p.available_licenses}</td>
                  {isAdmin && (
                    <td>
                      <div className="row" style={{ gap: 6 }}>
                        <button className="btn ghost" style={{ padding: "4px 10px" }} onClick={() => setEditPkg(p)}>Sửa</button>
                        <button className="btn ghost danger" style={{ padding: "4px 10px" }} onClick={() => removePkg(p)}>Xóa</button>
                      </div>
                    </td>
                  )}
                </tr>
                {isOpen && (
                  <tr>
                    <td colSpan={isAdmin ? 5 : 4} style={{ background: "rgba(0,0,0,0.15)" }}>
                      <VersionList
                        pkg={p}
                        isAdmin={isAdmin}
                        onEdit={setEditVer}
                        onDelete={(v) => removeVersion(p, v)}
                      />
                    </td>
                  </tr>
                )}
              </Fragment>
            );
          })}
          {packages.length === 0 && (
            <tr><td colSpan={isAdmin ? 5 : 4} className="muted">Chưa có package.</td></tr>
          )}
        </tbody>
      </table>
      {showUpload && (
        <UploadModal
          packages={packages}
          onClose={() => setShowUpload(false)}
          onDone={() => { setShowUpload(false); setMsg("Đã upload version."); load(); }}
        />
      )}
      {editPkg && (
        <PackageModal
          pkg={editPkg}
          onClose={() => setEditPkg(null)}
          onDone={() => { setEditPkg(null); setMsg("Đã lưu package."); load(); }}
        />
      )}
      {editVer && (
        <VersionModal
          version={editVer}
          onClose={() => setEditVer(null)}
          onDone={() => { setEditVer(null); setMsg("Đã lưu version."); load(); }}
        />
      )}
    </div>
  );
}

function VersionList({ pkg, isAdmin, onEdit, onDelete }) {
  if (!pkg.versions?.length) return <span className="muted">Chưa có version nào.</span>;
  return (
    <table style={{ margin: 0 }}>
      <thead>
        <tr>
          <th>Version</th><th>Loại</th><th>Lệnh cài</th><th>Hậu kiểm</th><th>SHA-256</th>
          {isAdmin && <th></th>}
        </tr>
      </thead>
      <tbody>
        {pkg.versions.map((v) => (
          <tr key={v.id}>
            <td>{v.version}</td>
            <td className="muted">{v.installer_type}</td>
            <td className="muted" style={{ maxWidth: 260, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }} title={v.install_command}>{v.install_command || "—"}</td>
            <td className="muted">{v.verify_name || "—"}</td>
            <td className="muted" style={{ fontFamily: "monospace", fontSize: 11 }} title={v.sha256}>{v.sha256 ? v.sha256.slice(0, 10) + "…" : "—"}</td>
            {isAdmin && (
              <td>
                <div className="row" style={{ gap: 6 }}>
                  <button className="btn ghost" style={{ padding: "3px 8px" }} onClick={() => onEdit(v)}>Sửa</button>
                  <button className="btn ghost danger" style={{ padding: "3px 8px" }} onClick={() => onDelete(v)}>Xóa</button>
                </div>
              </td>
            )}
          </tr>
        ))}
      </tbody>
    </table>
  );
}

function PackageModal({ pkg, onClose, onDone }) {
  const [form, setForm] = useState({
    name: pkg.name || "",
    vendor: pkg.vendor || "",
    description: pkg.description || "",
    min_os: pkg.min_os || "",
    min_ram_gb: pkg.min_ram_gb ?? 0,
    min_disk_gb: pkg.min_disk_gb ?? 0,
    total_licenses: pkg.total_licenses ?? 0,
  });
  const [err, setErr] = useState("");
  const [busy, setBusy] = useState(false);

  const set = (k) => (e) => setForm((f) => ({ ...f, [k]: e.target.value }));

  const submit = async (e) => {
    e.preventDefault();
    setErr(""); setBusy(true);
    try {
      await api.patch(`/packages/${pkg.id}/`, {
        name: form.name,
        vendor: form.vendor,
        description: form.description,
        min_os: form.min_os,
        min_ram_gb: Number(form.min_ram_gb) || 0,
        min_disk_gb: Number(form.min_disk_gb) || 0,
        total_licenses: Number(form.total_licenses) || 0,
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
        <h3>Sửa package</h3>
        <label>Tên</label>
        <input value={form.name} onChange={set("name")} required />
        <label>Vendor</label>
        <input value={form.vendor} onChange={set("vendor")} placeholder="Microsoft, Mozilla…" />
        <label>Mô tả</label>
        <textarea value={form.description} onChange={set("description")} rows={2} />
        <label>Yêu cầu OS tối thiểu</label>
        <input value={form.min_os} onChange={set("min_os")} placeholder="Windows 10 21H2" />
        <div className="row" style={{ gap: 12 }}>
          <div style={{ flex: 1 }}>
            <label>RAM tối thiểu (GB)</label>
            <input type="number" min="0" value={form.min_ram_gb} onChange={set("min_ram_gb")} />
          </div>
          <div style={{ flex: 1 }}>
            <label>Đĩa tối thiểu (GB)</label>
            <input type="number" min="0" value={form.min_disk_gb} onChange={set("min_disk_gb")} />
          </div>
          <div style={{ flex: 1 }}>
            <label>Tổng license</label>
            <input type="number" min="0" value={form.total_licenses} onChange={set("total_licenses")} />
          </div>
        </div>
        {err && <p className="error mt">{err}</p>}
        <div className="row spread mt">
          <button type="button" className="btn ghost" onClick={onClose}>Hủy</button>
          <button className="btn" disabled={busy}>{busy ? "Đang lưu…" : "Lưu"}</button>
        </div>
      </form>
    </div>
  );
}

function VersionModal({ version, onClose, onDone }) {
  const [form, setForm] = useState({
    version: version.version || "",
    install_command: version.install_command || "",
    uninstall_command: version.uninstall_command || "",
    verify_name: version.verify_name || "",
  });
  const [err, setErr] = useState("");
  const [busy, setBusy] = useState(false);

  const set = (k) => (e) => setForm((f) => ({ ...f, [k]: e.target.value }));

  const submit = async (e) => {
    e.preventDefault();
    setErr(""); setBusy(true);
    try {
      // Version viewset chỉ nhận multipart/form — gửi FormData qua PATCH (không đổi file).
      const fd = new FormData();
      fd.append("version", form.version);
      fd.append("install_command", form.install_command);
      fd.append("uninstall_command", form.uninstall_command);
      fd.append("verify_name", form.verify_name);
      await api.patchForm(`/package-versions/${version.id}/`, fd);
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
        <h3>Sửa version — {version.package_name}</h3>
        <label>Version</label>
        <input value={form.version} onChange={set("version")} required />
        <label>Lệnh cài (silent). Dùng {"{file}"}</label>
        <input value={form.install_command} onChange={set("install_command")} placeholder='msiexec /i {file} /qn /norestart' />
        <label>Lệnh gỡ (tùy chọn)</label>
        <input value={form.uninstall_command} onChange={set("uninstall_command")} />
        <label>Hậu kiểm — tên phần mềm (tùy chọn)</label>
        <input value={form.verify_name} onChange={set("verify_name")} placeholder="Firefox" />
        <p className="muted" style={{ fontSize: 12, marginTop: -4 }}>
          Không thể đổi file installer ở đây — xóa version và upload lại nếu cần thay file.
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

function UploadModal({ packages, onClose, onDone }) {
  const [packageId, setPackageId] = useState("");
  const [newName, setNewName] = useState("");
  const [version, setVersion] = useState("");
  const [file, setFile] = useState(null);
  const [installCommand, setInstallCommand] = useState("");
  const [verifyName, setVerifyName] = useState("");
  const [err, setErr] = useState("");
  const [busy, setBusy] = useState(false);

  const submit = async (e) => {
    e.preventDefault();
    setErr("");
    setBusy(true);
    try {
      let pid = packageId;
      if (!pid) {
        const pkg = await api.post("/packages/", { name: newName });
        pid = pkg.id;
      }
      const fd = new FormData();
      fd.append("package", pid);
      fd.append("version", version);
      fd.append("installer_file", file);
      if (installCommand) fd.append("install_command", installCommand);
      if (verifyName.trim()) fd.append("verify_name", verifyName.trim());
      await api.postForm("/package-versions/", fd);
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
        <h3>Upload package version</h3>
        <label>Package có sẵn</label>
        <select value={packageId} onChange={(e) => setPackageId(e.target.value)}>
          <option value="">— Tạo package mới —</option>
          {packages.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}
        </select>
        {!packageId && (
          <>
            <label>Tên package mới</label>
            <input value={newName} onChange={(e) => setNewName(e.target.value)} required={!packageId} />
          </>
        )}
        <label>Version</label>
        <input value={version} onChange={(e) => setVersion(e.target.value)} required />
        <label>File installer (.msi/.exe)</label>
        <input type="file" onChange={(e) => setFile(e.target.files[0])} required />
        <label>Lệnh silent (để trống = tự gợi ý). Dùng {"{file}"}</label>
        <input value={installCommand} onChange={(e) => setInstallCommand(e.target.value)} placeholder='msiexec /i {file} /qn /norestart' />
        <label>Hậu kiểm — tên phần mềm (tùy chọn, để trống = không kiểm)</label>
        <input value={verifyName} onChange={(e) => setVerifyName(e.target.value)} placeholder='Firefox' />
        <p className="muted" style={{ fontSize: 12, marginTop: -4 }}>
          Sau khi cài, kiểm registry xem có phần mềm chứa tên này không. Nếu không → báo THẤT BẠI
          (chống trường hợp installer trả "thành công" nhưng không cài gì).
        </p>
        {err && <p className="error mt">{err}</p>}
        <div className="row spread mt">
          <button type="button" className="btn ghost" onClick={onClose}>Hủy</button>
          <button className="btn" disabled={busy}>{busy ? "Đang upload…" : "Upload"}</button>
        </div>
      </form>
    </div>
  );
}
