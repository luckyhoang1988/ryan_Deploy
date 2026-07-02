import { useEffect, useState } from "react";
import { api, listOf } from "../api";

export default function Packages() {
  const [packages, setPackages] = useState([]);
  const [showUpload, setShowUpload] = useState(false);
  const [err, setErr] = useState("");

  const load = () =>
    api.get("/packages/").then((d) => setPackages(listOf(d))).catch((e) => setErr(e.message));

  useEffect(() => {
    load();
  }, []);

  return (
    <div>
      <div className="topbar">
        <h2>Packages</h2>
        <button className="btn" onClick={() => setShowUpload(true)}>+ Upload version</button>
      </div>
      {err && <p className="error">{err}</p>}
      <table>
        <thead>
          <tr><th>Tên</th><th>Vendor</th><th>Versions</th><th>License khả dụng</th></tr>
        </thead>
        <tbody>
          {packages.map((p) => (
            <tr key={p.id}>
              <td>{p.name}</td>
              <td>{p.vendor || "—"}</td>
              <td>{p.versions?.map((v) => v.version).join(", ") || "—"}</td>
              <td>{p.available_licenses}</td>
            </tr>
          ))}
          {packages.length === 0 && <tr><td colSpan="4" className="muted">Chưa có package.</td></tr>}
        </tbody>
      </table>
      {showUpload && (
        <UploadModal
          packages={packages}
          onClose={() => setShowUpload(false)}
          onDone={() => { setShowUpload(false); load(); }}
        />
      )}
    </div>
  );
}

function UploadModal({ packages, onClose, onDone }) {
  const [packageId, setPackageId] = useState("");
  const [newName, setNewName] = useState("");
  const [version, setVersion] = useState("");
  const [file, setFile] = useState(null);
  const [installCommand, setInstallCommand] = useState("");
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
        {err && <p className="error mt">{err}</p>}
        <div className="row spread mt">
          <button type="button" className="btn ghost" onClick={onClose}>Hủy</button>
          <button className="btn" disabled={busy}>{busy ? "Đang upload…" : "Upload"}</button>
        </div>
      </form>
    </div>
  );
}
