import { Fragment, useEffect, useState } from "react";
import { api, listOf } from "../api";
import { useAuth } from "../auth";

export default function Packages() {
  const { hasRole } = useAuth();
  const isAdmin = hasRole("admin");
  const [packages, setPackages] = useState([]);
  const [showUpload, setShowUpload] = useState(false);
  const [showFetch, setShowFetch] = useState(false);
  const [showHistory, setShowHistory] = useState(false);
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

  const approveVersion = async (v) => {
    setErr(""); setMsg("");
    try {
      await api.post(`/package-versions/${v.id}/approve/`, {});
      setMsg(`Đã duyệt version "${v.version}".`);
      load();
    } catch (e) { setErr(e.message); }
  };

  const seedCatalog = async () => {
    setErr(""); setMsg("");
    try {
      const r = await api.post("/packages/seed_catalog/", {});
      setMsg(`Đã nạp Package Library mẫu: tạo mới ${r.created}, bỏ qua ${r.skipped} (đã có).`);
      load();
    } catch (e) { setErr(e.message); }
  };

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
        <div className="row" style={{ gap: 8 }}>
          {isAdmin && (
            <button className="btn ghost" onClick={() => setShowHistory((s) => !s)}>
              {showHistory ? "Ẩn lịch sử tải" : "Lịch sử tải"}
            </button>
          )}
          {isAdmin && (
            <button className="btn ghost" onClick={seedCatalog} title="Tạo sẵn Package (tên/vendor) cho phần mềm phổ biến — chưa kèm installer">
              📚 Nạp Package Library mẫu
            </button>
          )}
          {isAdmin && <button className="btn ghost" onClick={() => setShowFetch(true)}>↓ Tải từ URL</button>}
          {isAdmin && <button className="btn" onClick={() => setShowUpload(true)}>+ Upload version</button>}
        </div>
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
                        onApprove={approveVersion}
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
      {showHistory && isAdmin && <DownloadHistory />}
      {showUpload && (
        <UploadModal
          packages={packages}
          onClose={() => setShowUpload(false)}
          onDone={() => { setShowUpload(false); setMsg("Đã upload version."); load(); }}
        />
      )}
      {showFetch && (
        <FetchModal
          packages={packages}
          onClose={() => setShowFetch(false)}
          onDone={() => { setShowFetch(false); setMsg("Đang tải trong nền — làm mới sau ít phút để thấy version mới."); }}
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

function VersionList({ pkg, isAdmin, onEdit, onDelete, onApprove }) {
  if (!pkg.versions?.length) return <span className="muted">Chưa có version nào.</span>;
  return (
    <table style={{ margin: 0 }}>
      <thead>
        <tr>
          <th>Version</th><th>Loại</th><th>Nguồn</th><th>Duyệt</th><th>SHA-256</th>
          {isAdmin && <th></th>}
        </tr>
      </thead>
      <tbody>
        {pkg.versions.map((v) => (
          <tr key={v.id}>
            <td>{v.version}</td>
            <td className="muted">{v.installer_type}</td>
            <td className="muted">{v.source === "url" ? "↓ URL" : "Upload"}</td>
            <td>
              {v.approved
                ? <span className="badge success">Đã duyệt</span>
                : <span className="badge warn">Chờ duyệt</span>}
            </td>
            <td className="muted" style={{ fontFamily: "monospace", fontSize: 11 }} title={v.sha256}>{v.sha256 ? v.sha256.slice(0, 10) + "…" : "—"}</td>
            {isAdmin && (
              <td>
                <div className="row" style={{ gap: 6 }}>
                  {!v.approved && (
                    <button className="btn ghost" style={{ padding: "3px 8px" }} onClick={() => onApprove(v)}>Duyệt</button>
                  )}
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

// Modal tải một version từ URL ngoài (bất đồng bộ qua Celery — mirror "Download Selected").
function FetchModal({ packages, onClose, onDone }) {
  const [packageId, setPackageId] = useState("");
  const [url, setUrl] = useState("");
  const [version, setVersion] = useState("");
  const [err, setErr] = useState("");
  const [busy, setBusy] = useState(false);

  // Chọn package → gợi ý download_url đã lưu (nếu có).
  const onPick = (id) => {
    setPackageId(id);
    const p = packages.find((x) => String(x.id) === String(id));
    if (p?.download_url && !url) setUrl(p.download_url);
  };

  const submit = async (e) => {
    e.preventDefault();
    setErr(""); setBusy(true);
    try {
      await api.post(`/packages/${packageId}/fetch/`, { url, version });
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
        <h3>Tải version từ URL</h3>
        <label>Package</label>
        <select value={packageId} onChange={(e) => onPick(e.target.value)} required>
          <option value="">— Chọn package —</option>
          {packages.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}
        </select>
        <label>URL installer (http/https)</label>
        <input value={url} onChange={(e) => setUrl(e.target.value)} placeholder="https://vendor.com/app.msi" required />
        <label>Nhãn version</label>
        <input value={version} onChange={(e) => setVersion(e.target.value)} placeholder="120.0" required />
        <p className="muted" style={{ fontSize: 12, marginTop: -4 }}>
          Server tải file về repository, tự tính SHA-256 và tạo version. Nếu nội dung trùng bản đã có → bỏ qua.
        </p>
        {err && <p className="error mt">{err}</p>}
        <div className="row spread mt">
          <button type="button" className="btn ghost" onClick={onClose}>Hủy</button>
          <button className="btn" disabled={busy || !packageId}>{busy ? "Đang gửi…" : "Tải về"}</button>
        </div>
      </form>
    </div>
  );
}

// Download History — nhật ký các lần tải từ URL (mirror tab "Download History" của PDQ).
function DownloadHistory() {
  const [rows, setRows] = useState([]);
  const [err, setErr] = useState("");

  useEffect(() => {
    api.get("/package-downloads/").then((d) => setRows(listOf(d))).catch((e) => setErr(e.message));
  }, []);

  const STATUS = {
    success: ["Thành công", "success"],
    unchanged: ["Không đổi", "default"],
    downloading: ["Đang tải", "running"],
    failed: ["Thất bại", "failed"],
  };

  return (
    <div style={{ marginTop: 18 }}>
      <h3>Lịch sử tải từ URL</h3>
      {err && <p className="error">{err}</p>}
      <table>
        <thead>
          <tr><th>Thời gian</th><th>Package</th><th>Version</th><th>Trạng thái</th><th>Kích thước</th><th>Ghi chú</th></tr>
        </thead>
        <tbody>
          {rows.map((r) => {
            const [label, cls] = STATUS[r.status] || [r.status, "default"];
            return (
              <tr key={r.id}>
                <td className="muted">{new Date(r.created_at).toLocaleString()}</td>
                <td>{r.package_name}</td>
                <td>{r.version_str}</td>
                <td><span className={`badge ${cls}`}>{label}</span></td>
                <td className="muted">{r.file_size ? (r.file_size / (1024 * 1024)).toFixed(1) + " MB" : "—"}</td>
                <td className="muted" style={{ maxWidth: 280, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }} title={r.error || r.url}>{r.error || r.url}</td>
              </tr>
            );
          })}
          {rows.length === 0 && <tr><td colSpan="6" className="muted">Chưa có lần tải nào.</td></tr>}
        </tbody>
      </table>
    </div>
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
    download_url: pkg.download_url || "",
    auto_download: pkg.auto_download || "manual",
    auto_approve_after_days: pkg.auto_approve_after_days ?? 7,
    inventory_name: pkg.inventory_name || "",
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
        download_url: form.download_url,
        auto_download: form.auto_download,
        auto_approve_after_days: Number(form.auto_approve_after_days) || 0,
        inventory_name: form.inventory_name,
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
        <hr style={{ border: 0, borderTop: "1px solid rgba(255,255,255,0.1)", margin: "14px 0 4px" }} />
        <label>URL tải (evergreen — dùng cho "Tải từ URL" & auto-download)</label>
        <input value={form.download_url} onChange={set("download_url")} placeholder="https://vendor.com/latest/app.msi" />
        <label>Tên trong registry để dò cập nhật (để trống = suy từ hậu kiểm)</label>
        <input value={form.inventory_name} onChange={set("inventory_name")} placeholder="Google Chrome" />
        <div className="row" style={{ gap: 12 }}>
          <div style={{ flex: 2 }}>
            <label>Chính sách auto-download</label>
            <select value={form.auto_download} onChange={set("auto_download")}>
              <option value="manual">Thủ công (admin duyệt)</option>
              <option value="immediate">Duyệt ngay khi tải</option>
              <option value="automatic">Tự duyệt sau N ngày</option>
            </select>
          </div>
          <div style={{ flex: 1 }}>
            <label>N ngày chờ duyệt</label>
            <input type="number" min="0" value={form.auto_approve_after_days} onChange={set("auto_approve_after_days")} disabled={form.auto_download !== "automatic"} />
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
