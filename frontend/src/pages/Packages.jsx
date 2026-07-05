import { Fragment, useEffect, useState } from "react";
import { api, listOf, fetchAll } from "../api";
import { useAuth } from "../auth";
import Icon from "../components/Icon";
import DeploymentWizard from "../components/DeploymentWizard";

export default function Packages() {
  const { hasRole } = useAuth();
  const isAdmin = hasRole("admin");
  // Deploy từ Package Library dùng chung quyền với trang Deployments (operator trở lên) —
  // tách khỏi isAdmin vì thao tác CRUD package (upload/sửa/xóa) vẫn chỉ admin.
  const canDeploy = hasRole("operator", "admin");
  const [packages, setPackages] = useState([]);
  const [folders, setFolders] = useState([]);
  const [selectedFolder, setSelectedFolder] = useState(null); // null = "Tất cả package"
  const [expandedFolders, setExpandedFolders] = useState(new Set());
  const [folderModal, setFolderModal] = useState(null); // {mode:'create'|'rename', folder?, parentId?}
  const [showUpload, setShowUpload] = useState(false);
  const [showFetch, setShowFetch] = useState(false);
  const [showHistory, setShowHistory] = useState(false);
  const [editPkg, setEditPkg] = useState(null); // package đang sửa
  const [editVer, setEditVer] = useState(null); // version đang sửa
  const [deployVersionId, setDeployVersionId] = useState(null); // version đang mở DeploymentWizard
  const [expanded, setExpanded] = useState(null); // id package đang mở versions
  const [err, setErr] = useState("");
  const [msg, setMsg] = useState("");

  const load = () =>
    api.get("/packages/").then((d) => setPackages(listOf(d))).catch((e) => setErr(e.message));
  const loadFolders = () =>
    fetchAll("/package-folders/").then(setFolders).catch((e) => setErr(e.message));

  useEffect(() => {
    load();
    loadFolders();
  }, []);

  const childrenOf = (parentId) => folders.filter((f) => (f.parent ?? null) === parentId);
  const toggleFolder = (id) =>
    setExpandedFolders((prev) => {
      const next = new Set(prev);
      next.has(id) ? next.delete(id) : next.add(id);
      return next;
    });

  const removeFolder = async (folder) => {
    if (!confirm(`Xóa thư mục "${folder.name}"?`)) return;
    setErr(""); setMsg("");
    try {
      await api.del(`/package-folders/${folder.id}/`);
      if (selectedFolder === folder.id) setSelectedFolder(null);
      setMsg(`Đã xóa thư mục "${folder.name}".`);
      loadFolders();
    } catch (e) { setErr(e.message); }
  };

  const shownPackages = selectedFolder === null
    ? packages
    : packages.filter((p) => p.folder === selectedFolder);

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
      <div className="pkg-layout">
        <aside className="pkg-tree">
          <div className={`tree-node${selectedFolder === null ? " active" : ""}`}>
            <span className="tree-toggle-spacer" />
            <span className="tree-label" onClick={() => setSelectedFolder(null)}>
              <Icon name="package" size={15} /> Tất cả package
            </span>
          </div>
          {childrenOf(null).map((f) => (
            <FolderNode
              key={f.id}
              folder={f}
              depth={0}
              childrenOf={childrenOf}
              expanded={expandedFolders}
              toggleExpand={toggleFolder}
              selectedFolder={selectedFolder}
              onSelect={setSelectedFolder}
              isAdmin={isAdmin}
              onRename={(folder) => setFolderModal({ mode: "rename", folder })}
              onDelete={removeFolder}
            />
          ))}
          {isAdmin && (
            <button
              className="btn ghost tree-add"
              onClick={() => setFolderModal({ mode: "create", parentId: selectedFolder })}
            >
              + Thư mục
            </button>
          )}
        </aside>
        <div className="pkg-main">
          <table>
            <thead>
              <tr>
                <th>Tên</th><th>Vendor</th><th>Versions</th><th>License khả dụng</th><th>Trạng thái</th>
                {canDeploy && <th></th>}
                {isAdmin && <th></th>}
              </tr>
            </thead>
            <tbody>
              {shownPackages.map((p) => {
                const isOpen = expanded === p.id;
                // Bản duyệt mới nhất — versions đã sort -created_at từ backend nên phần tử
                // đầu khớp approved là latest_version.
                const readyVersion = p.versions?.find((v) => v.approved);
                const colCount = 5 + (canDeploy ? 1 : 0) + (isAdmin ? 1 : 0);
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
                      <td>
                        {readyVersion
                          ? <span className="badge success">Sẵn sàng</span>
                          : <span className="badge default">Chưa có installer</span>}
                      </td>
                      {canDeploy && (
                        <td>
                          <button
                            className="btn ghost"
                            style={{ padding: "4px 10px" }}
                            disabled={!readyVersion}
                            title={readyVersion ? "" : "Chưa có version đã duyệt — Tải từ URL hoặc Upload trước"}
                            onClick={() => setDeployVersionId(readyVersion.id)}
                          >
                            🚀 Deploy
                          </button>
                        </td>
                      )}
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
                        <td colSpan={colCount} style={{ background: "rgba(0,0,0,0.15)" }}>
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
              {shownPackages.length === 0 && (
                <tr><td colSpan={5 + (canDeploy ? 1 : 0) + (isAdmin ? 1 : 0)} className="muted">Chưa có package.</td></tr>
              )}
            </tbody>
          </table>
          {showHistory && isAdmin && <DownloadHistory />}
        </div>
      </div>
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
      {deployVersionId && (
        <DeploymentWizard
          isAdmin={isAdmin}
          initialPackageVersionId={deployVersionId}
          onClose={() => setDeployVersionId(null)}
          onDone={() => { setDeployVersionId(null); setMsg("Đã tạo & chạy deployment."); }}
        />
      )}
      {editPkg && (
        <PackageModal
          pkg={editPkg}
          folders={folders}
          onClose={() => setEditPkg(null)}
          onDone={() => { setEditPkg(null); setMsg("Đã lưu package."); load(); }}
        />
      )}
      {folderModal && (
        <FolderModal
          mode={folderModal.mode}
          folder={folderModal.folder}
          parentId={folderModal.parentId}
          folders={folders}
          onClose={() => setFolderModal(null)}
          onDone={() => {
            setFolderModal(null);
            setMsg(folderModal.mode === "rename" ? "Đã lưu thư mục." : "Đã tạo thư mục.");
            loadFolders();
          }}
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

// Một nhánh của cây Package Library (mirror PDQ: Package Library > Packages > Custom
// Packages > Remove Updates...). Đệ quy qua children (parent adjacency-list).
function FolderNode({ folder, depth, childrenOf, expanded, toggleExpand, selectedFolder, onSelect, isAdmin, onRename, onDelete }) {
  const kids = childrenOf(folder.id);
  const isOpen = expanded.has(folder.id);
  const isSelected = selectedFolder === folder.id;
  return (
    <div>
      <div className={`tree-node${isSelected ? " active" : ""}`} style={{ paddingLeft: depth * 16 }}>
        {kids.length > 0 ? (
          <button className="tree-toggle" onClick={() => toggleExpand(folder.id)}>
            <Icon name={isOpen ? "chevronDown" : "chevronRight"} size={13} />
          </button>
        ) : <span className="tree-toggle-spacer" />}
        <span className="tree-label" onClick={() => onSelect(folder.id)}>
          <Icon name={isOpen ? "folderOpen" : "folder"} size={15} /> {folder.name}
        </span>
        {isAdmin && (
          <div className="tree-actions">
            <button className="tree-action" title="Đổi tên" onClick={() => onRename(folder)}>✎</button>
            <button className="tree-action" title="Xóa" onClick={() => onDelete(folder)}>✕</button>
          </div>
        )}
      </div>
      {isOpen && kids.map((k) => (
        <FolderNode
          key={k.id}
          folder={k}
          depth={depth + 1}
          childrenOf={childrenOf}
          expanded={expanded}
          toggleExpand={toggleExpand}
          selectedFolder={selectedFolder}
          onSelect={onSelect}
          isAdmin={isAdmin}
          onRename={onRename}
          onDelete={onDelete}
        />
      ))}
    </div>
  );
}

// Tạo/đổi tên thư mục — chọn thư mục cha qua <select> (không kéo-thả, đơn giản & đủ dùng).
function FolderModal({ mode, folder, parentId, folders, onClose, onDone }) {
  const [name, setName] = useState(folder?.name || "");
  const [parent, setParent] = useState(folder?.parent ?? parentId ?? "");
  const [err, setErr] = useState("");
  const [busy, setBusy] = useState(false);

  const submit = async (e) => {
    e.preventDefault();
    setErr(""); setBusy(true);
    try {
      const payload = { name, parent: parent || null };
      if (mode === "rename") {
        await api.patch(`/package-folders/${folder.id}/`, payload);
      } else {
        await api.post("/package-folders/", payload);
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
        <h3>{mode === "rename" ? "Đổi tên thư mục" : "Thư mục mới"}</h3>
        <label>Tên</label>
        <input value={name} onChange={(e) => setName(e.target.value)} required />
        <label>Thư mục cha (để trống = gốc)</label>
        <select value={parent || ""} onChange={(e) => setParent(e.target.value)}>
          <option value="">— Gốc —</option>
          {folders.filter((f) => f.id !== folder?.id).map((f) => (
            <option key={f.id} value={f.id}>{f.name}</option>
          ))}
        </select>
        {err && <p className="error mt">{err}</p>}
        <div className="row spread mt">
          <button type="button" className="btn ghost" onClick={onClose}>Hủy</button>
          <button className="btn" disabled={busy}>{busy ? "Đang lưu…" : "Lưu"}</button>
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

function PackageModal({ pkg, folders, onClose, onDone }) {
  const [form, setForm] = useState({
    name: pkg.name || "",
    vendor: pkg.vendor || "",
    description: pkg.description || "",
    folder: pkg.folder ?? "",
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
        folder: form.folder || null,
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
        <label>Thư mục (Package Library)</label>
        <select value={form.folder} onChange={set("folder")}>
          <option value="">— Không thuộc thư mục nào —</option>
          {folders.map((f) => <option key={f.id} value={f.id}>{f.name}</option>)}
        </select>
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
        <label>Lệnh cài (silent). Dùng {"{file}"} (file installer) hoặc {"{dir}"} (nếu installer là .zip, trỏ tới thư mục đã giải nén)</label>
        <input value={form.install_command} onChange={set("install_command")} placeholder='msiexec /i {file} /qn /norestart' />
        <label>Lệnh gỡ (tùy chọn). Dùng {"{file}"}/{"{dir}"} như trên nếu cần lại installer</label>
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
        <label>File installer (.msi/.exe/.msu/.msp/.msix/.zip)</label>
        <input type="file" onChange={(e) => setFile(e.target.files[0])} required />
        <label>Lệnh silent (để trống = tự gợi ý). Dùng {"{file}"} (file installer) hoặc {"{dir}"} (nếu upload .zip, trỏ tới thư mục đã giải nén — VD Office2016: "{"{dir}"}\setup.exe" /configure "{"{dir}"}\configuration.xml")</label>
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
