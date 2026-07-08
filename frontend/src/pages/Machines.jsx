import { useEffect, useState, useCallback } from "react";
import { api, waitForTask } from "../api";
import { useAuth } from "../auth";
import Pagination from "../components/Pagination";

const PAGE_SIZE = 25;

export default function Machines() {
  const { hasRole } = useAuth();
  const [machines, setMachines] = useState([]);
  const [totalCount, setTotalCount] = useState(0);
  const [page, setPage] = useState(1);
  const [msg, setMsg] = useState("");
  const [err, setErr] = useState("");
  const [busy, setBusy] = useState("");
  const [showConfig, setShowConfig] = useState(false);
  const [showSyncModal, setShowSyncModal] = useState(false);
  const [showEnrollModal, setShowEnrollModal] = useState(false);
  const [agentModalMachine, setAgentModalMachine] = useState(null);

  // Filters
  const [search, setSearch] = useState("");
  const [filterStatus, setFilterStatus] = useState(""); // "" | "true" | "false"
  const [filterOU, setFilterOU] = useState("");

  // Stats
  const [stats, setStats] = useState({ total: 0, online: 0, offline: 0 });

  const buildQuery = useCallback((p) => {
    const params = new URLSearchParams();
    params.set("page", p);
    if (search.trim()) params.set("search", search.trim());
    if (filterStatus) params.set("is_online", filterStatus);
    if (filterOU.trim()) params.set("ad_ou", filterOU.trim());
    return params.toString();
  }, [search, filterStatus, filterOU]);

  const load = useCallback((p = page) => {
    api.get(`/machines/?${buildQuery(p)}`)
      .then((d) => {
        if (d && d.results) {
          setMachines(d.results);
          setTotalCount(d.count || 0);
        } else if (Array.isArray(d)) {
          setMachines(d);
          setTotalCount(d.length);
        }
      })
      .catch((e) => setErr(e.message));
  }, [buildQuery, page]);

  const loadStats = useCallback(() => {
    // Stats không cần filter — luôn lấy tổng thể
    api.get("/machines/stats/").then(setStats).catch(() => {});
  }, []);

  useEffect(() => {
    load(page);
  }, [page, buildQuery]);

  useEffect(() => {
    loadStats();
  }, []);

  // Khi đổi filter → reset về trang 1
  useEffect(() => {
    setPage(1);
  }, [search, filterStatus, filterOU]);

  const syncAd = async (purge = false) => {
    setBusy("ad"); setErr(""); setMsg("");
    try {
      const { task_id } = await api.post("/machines/sync_ad/", { purge });
      const t = await waitForTask(task_id);
      if (t.state === "FAILURE") { setErr(`AD sync: ${t.error}`); return; }
      const r = t.result || {};
      if (r.error) { setErr(`AD sync: ${r.error}`); return; }
      const parts = [`+${r.created} mới`, `${r.updated} cập nhật`];
      if (r.deleted) parts.push(`${r.deleted} đã xóa`);
      setMsg(`AD sync: ${parts.join(", ")}`);
      setPage(1);
      load(1);
      loadStats();
    } catch (e) { setErr(e.message); } finally { setBusy(""); }
  };

  const purgeAll = async () => {
    if (!confirm("Xóa TẤT CẢ máy trong hệ thống? Hành động này không thể hoàn tác.")) return;
    setBusy("purge"); setErr(""); setMsg("");
    try {
      const r = await api.post("/machines/purge_all/", {});
      setMsg(`Đã xóa ${r.deleted} máy. Bấm Sync AD để đồng bộ lại.`);
      setPage(1);
      load(1);
      loadStats();
    } catch (e) { setErr(e.message); } finally { setBusy(""); }
  };

  const exportCSV = () => {
    const params = new URLSearchParams();
    if (search.trim()) params.set("search", search.trim());
    if (filterStatus) params.set("is_online", filterStatus);
    if (filterOU.trim()) params.set("ad_ou", filterOU.trim());
    const q = params.toString();
    window.open(`/api/machines/export/${q ? "?" + q : ""}`, "_blank");
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
            <button className="btn ghost" onClick={() => setShowSyncModal(true)} disabled={busy}>
              {busy === "ad" ? "Đang sync…" : "Sync AD"}
            </button>
          )}
          {hasRole("admin") && (
            <button className="btn ghost" onClick={() => setShowEnrollModal(true)} disabled={busy}>
              Enrollment Secrets
            </button>
          )}
          {hasRole("admin") && (
            <button className="btn ghost danger" onClick={purgeAll} disabled={busy}>
              {busy === "purge" ? "Đang xóa…" : "Xóa tất cả máy"}
            </button>
          )}
        </div>
      </div>

      {/* Stats Cards */}
      <div className="cards" style={{ marginBottom: 16 }}>
        <div className="card stat" onClick={() => setFilterStatus("")} style={{ cursor: "pointer" }}>
          <div className="card-icon cyan">
            <svg className="icon" width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><rect x="2" y="3" width="20" height="14" rx="2"/><path d="M8 21h8M12 17v4"/></svg>
          </div>
          <div><div className="value">{stats.total}</div><div className="label">Tổng máy</div></div>
        </div>
        <div className="card stat" onClick={() => setFilterStatus("true")} style={{ cursor: "pointer" }}>
          <div className="card-icon green">
            <svg className="icon" width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><circle cx="12" cy="12" r="10"/><path d="M8 12l3 3 5-5"/></svg>
          </div>
          <div><div className="value">{stats.online}</div><div className="label">Online</div></div>
        </div>
        <div className="card stat" onClick={() => setFilterStatus("false")} style={{ cursor: "pointer" }}>
          <div className="card-icon red">
            <svg className="icon" width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><circle cx="12" cy="12" r="10"/><path d="M15 9l-6 6M9 9l6 6"/></svg>
          </div>
          <div><div className="value">{stats.offline}</div><div className="label">Offline</div></div>
        </div>
      </div>

      {/* Filter Bar */}
      <div className="filter-bar">
        <input
          type="text"
          placeholder="🔍 Tìm hostname…"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          style={{ maxWidth: 220 }}
        />
        <select value={filterStatus} onChange={(e) => setFilterStatus(e.target.value)} style={{ maxWidth: 160 }}>
          <option value="">Tất cả trạng thái</option>
          <option value="true">Online</option>
          <option value="false">Offline</option>
        </select>
        <input
          type="text"
          placeholder="Lọc theo OU…"
          value={filterOU}
          onChange={(e) => setFilterOU(e.target.value)}
          style={{ maxWidth: 220 }}
        />
        {(search || filterStatus || filterOU) && (
          <button className="btn ghost" style={{ padding: "6px 12px" }} onClick={() => { setSearch(""); setFilterStatus(""); setFilterOU(""); }}>
            ✕ Xóa lọc
          </button>
        )}
        <div style={{ flex: 1 }} />
        <button className="btn ghost" onClick={exportCSV} title="Xuất danh sách ra Excel (CSV)">
          📥 Xuất Excel
        </button>
      </div>

      {msg && <p className="muted">{msg}</p>}
      {err && <p className="error">{err}</p>}
      <table>
        <thead>
          <tr>
            <th>Hostname</th><th>FQDN</th><th>OS</th><th>OU</th><th>Trạng thái</th>
            <th>Kết nối</th><th>Agent</th>
            {hasRole("admin") && <th></th>}
          </tr>
        </thead>
        <tbody>
          {machines.map((m) => (
            <tr key={m.id}>
              <td>{m.hostname}</td>
              <td className="muted">{m.fqdn || "—"}</td>
              <td>{m.os_name || "—"}</td>
              <td className="muted">{m.ad_ou || "—"}</td>
              <td>
                <span className={`badge ${m.is_online ? "success" : "default"}`}>
                  {m.is_online ? "Online" : "Offline"}
                </span>
              </td>
              <td>
                <span className={`badge ${m.connection_mode === "agent" ? "info" : "default"}`}>
                  {m.connection_mode === "agent" ? "Agent" : "SMB"}
                </span>
              </td>
              <td className="muted">{m.agent_version || "—"}</td>
              {hasRole("admin") && (
                <td>
                  <button className="btn ghost" style={{ padding: "4px 10px" }} onClick={() => setAgentModalMachine(m)}>
                    Agent…
                  </button>
                </td>
              )}
            </tr>
          ))}
          {machines.length === 0 && <tr><td colSpan="8" className="muted">Không tìm thấy máy nào.</td></tr>}
        </tbody>
      </table>

      <Pagination page={page} totalCount={totalCount} pageSize={PAGE_SIZE} onPageChange={setPage} itemLabel="máy" />

      {showConfig && (
        <ADConfigModal
          onClose={() => setShowConfig(false)}
          onSaved={() => setMsg("Đã lưu cấu hình AD.")}
        />
      )}
      {showSyncModal && (
        <SyncADModal
          onClose={() => setShowSyncModal(false)}
          onSync={(purge) => { setShowSyncModal(false); syncAd(purge); }}
          busy={busy}
        />
      )}
      {agentModalMachine && (
        <AgentTokenModal
          machine={agentModalMachine}
          onClose={() => setAgentModalMachine(null)}
          onChanged={() => load(page)}
        />
      )}
      {showEnrollModal && (
        <EnrollmentSecretsModal onClose={() => setShowEnrollModal(false)} />
      )}
    </div>
  );
}

function AgentTokenModal({ machine, onClose, onChanged }) {
  const [connectionMode, setConnectionMode] = useState(machine.connection_mode || "smb");
  const [token, setToken] = useState("");
  const [tokenInfo, setTokenInfo] = useState(null);
  const [msg, setMsg] = useState("");
  const [err, setErr] = useState("");
  const [busy, setBusy] = useState("");

  const loadTokenInfo = useCallback(async () => {
    try {
      const d = await api.get(`/machines/${machine.id}/`);
      setTokenInfo(d.agent_token || null);
    } catch (e) { /* không chặn modal nếu load info lỗi */ }
  }, [machine.id]);

  useEffect(() => { loadTokenInfo(); }, [loadTokenInfo]);

  const fmt = (iso) => (iso ? new Date(iso).toLocaleString() : "—");

  const saveMode = async () => {
    setBusy("mode"); setErr(""); setMsg("");
    try {
      await api.patch(`/machines/${machine.id}/`, { connection_mode: connectionMode });
      setMsg("Đã lưu chế độ kết nối.");
      onChanged?.();
    } catch (e) { setErr(e.message); } finally { setBusy(""); }
  };

  const provisionToken = async () => {
    if (!confirm(`Cấp token agent mới cho ${machine.hostname}? Token cũ (nếu có) sẽ bị thu hồi ngay.`)) return;
    setBusy("provision"); setErr(""); setMsg(""); setToken("");
    try {
      const r = await api.post(`/machines/${machine.id}/provision_agent_token/`, {});
      setToken(r.token);
      setMsg("Đã cấp token mới — chỉ hiển thị MỘT LẦN, hãy sao chép ngay.");
      await loadTokenInfo();
    } catch (e) { setErr(e.message); } finally { setBusy(""); }
  };

  const revokeToken = async () => {
    if (!confirm(`Thu hồi token agent hiện tại của ${machine.hostname}?`)) return;
    setBusy("revoke"); setErr(""); setMsg(""); setToken("");
    try {
      const r = await api.post(`/machines/${machine.id}/revoke_agent_token/`, {});
      setMsg(r.revoked ? "Đã thu hồi token." : "Máy này chưa có token nào đang hoạt động.");
      await loadTokenInfo();
    } catch (e) { setErr(e.message); } finally { setBusy(""); }
  };

  return (
    <div className="modal-bg" onClick={onClose}>
      <div className="modal" onClick={(e) => e.stopPropagation()} style={{ width: 480 }}>
        <h3>Agent — {machine.hostname}</h3>

        <label>Chế độ kết nối</label>
        <div className="row" style={{ gap: 8 }}>
          <select value={connectionMode} onChange={(e) => setConnectionMode(e.target.value)} style={{ flex: 1 }}>
            <option value="smb">SMB push (agentless)</option>
            <option value="agent">Agent (outbound HTTPS)</option>
          </select>
          <button className="btn ghost" onClick={saveMode} disabled={busy}>
            {busy === "mode" ? "Đang lưu…" : "Lưu"}
          </button>
        </div>

        <hr style={{ margin: "16px 0", border: "none", borderTop: "1px solid var(--border, #333)" }} />

        <div className="row spread" style={{ alignItems: "center" }}>
          <div>
            <div><strong>Token agent</strong></div>
            <div className="muted" style={{ fontSize: 12 }}>
              Cấp mới sẽ thu hồi token cũ ngay lập tức. Chỉ hiển thị đúng 1 lần.
            </div>
          </div>
          <div className="row" style={{ gap: 8 }}>
            <button className="btn ghost" onClick={revokeToken} disabled={busy}>
              {busy === "revoke" ? "Đang thu hồi…" : "Thu hồi"}
            </button>
            <button className="btn" onClick={provisionToken} disabled={busy}>
              {busy === "provision" ? "Đang cấp…" : "Cấp token mới"}
            </button>
          </div>
        </div>

        {token && (
          <div className="mt" style={{ background: "var(--panel, #1a1a1a)", padding: 10, borderRadius: 6 }}>
            <code style={{ wordBreak: "break-all", userSelect: "all" }}>{token}</code>
          </div>
        )}

        <div className="mt" style={{ fontSize: 12 }}>
          {tokenInfo ? (
            <>
              <div>
                Token hiện tại: <code>{tokenInfo.token_prefix}…</code>{" "}
                <span className={`badge ${tokenInfo.is_active ? "info" : "default"}`}>
                  {tokenInfo.is_active ? "Đang hoạt động" : "Đã thu hồi"}
                </span>
              </div>
              <div className="muted">Cấp lúc: {fmt(tokenInfo.created_at)}</div>
              <div className="muted">Lần dùng cuối: {fmt(tokenInfo.last_used_at)}</div>
              {tokenInfo.revoked_at && (
                <div className="muted">Thu hồi lúc: {fmt(tokenInfo.revoked_at)}</div>
              )}
            </>
          ) : (
            <span className="muted">Máy này chưa từng được cấp token agent.</span>
          )}
        </div>

        {msg && <p className="muted mt">{msg}</p>}
        {err && <p className="error mt">{err}</p>}

        <div className="row spread mt">
          <button type="button" className="btn ghost" onClick={onClose}>Đóng</button>
        </div>
      </div>
    </div>
  );
}

function EnrollmentSecretsModal({ onClose }) {
  const [secrets, setSecrets] = useState([]);
  const [adOu, setAdOu] = useState("");
  const [expiresInHours, setExpiresInHours] = useState("48");
  const [maxUses, setMaxUses] = useState("");
  const [note, setNote] = useState("");
  const [newSecret, setNewSecret] = useState("");
  const [msg, setMsg] = useState("");
  const [err, setErr] = useState("");
  const [busy, setBusy] = useState("");

  const load = useCallback(() => {
    api.get("/enrollment-secrets/")
      .then((d) => setSecrets(d && d.results ? d.results : Array.isArray(d) ? d : []))
      .catch((e) => setErr(e.message));
  }, []);

  useEffect(() => { load(); }, [load]);

  const fmt = (iso) => (iso ? new Date(iso).toLocaleString() : "—");

  const create = async (e) => {
    e?.preventDefault();
    if (!adOu.trim() && !confirm(
      "Để trống OU nghĩa là secret này dùng được cho MỌI máy trong toàn domain (global), " +
      "không giới hạn phạm vi. Rủi ro cao hơn nếu bị lộ. Vẫn tiếp tục?"
    )) return;
    setBusy("create"); setErr(""); setMsg(""); setNewSecret("");
    try {
      const body = { ad_ou: adOu.trim(), note: note.trim() };
      if (expiresInHours) body.expires_in_hours = expiresInHours;
      if (maxUses) body.max_uses = maxUses;
      const r = await api.post("/enrollment-secrets/", body);
      setNewSecret(r.secret);
      setMsg("Đã tạo secret mới — chỉ hiển thị MỘT LẦN, hãy sao chép ngay.");
      setAdOu(""); setNote(""); setMaxUses("");
      load();
    } catch (e2) { setErr(e2.message); } finally { setBusy(""); }
  };

  const revoke = async (secret) => {
    if (!confirm(`Thu hồi secret ${secret.secret_prefix}… (${secret.ad_ou || "Global"})? Máy chưa enroll bằng secret này sẽ không thể enroll nữa.`)) return;
    setBusy(`revoke-${secret.id}`); setErr(""); setMsg("");
    try {
      const r = await api.post(`/enrollment-secrets/${secret.id}/revoke/`, {});
      setMsg(r.revoked ? "Đã thu hồi secret." : "Secret này đã bị thu hồi từ trước.");
      load();
    } catch (e) { setErr(e.message); } finally { setBusy(""); }
  };

  return (
    <div className="modal-bg" onClick={onClose}>
      <div className="modal" onClick={(e) => e.stopPropagation()} style={{ width: 640 }}>
        <h3>Enrollment Secrets — self-enrollment hàng loạt</h3>
        <p className="muted" style={{ fontSize: 12 }}>
          Cấp 1 secret dùng chung cho nhiều máy (giới hạn theo OU hoặc để trống = global), publish
          qua GPO Startup Script (<code>gpo_startup_enroll.ps1</code>) giống hệt cho toàn bộ máy
          đích — agent tự đổi secret lấy token thật của riêng nó lúc khởi động, không cần cấp
          token thủ công từng máy.
        </p>

        <form onSubmit={create}>
          <div className="row" style={{ gap: 8, flexWrap: "wrap" }}>
            <div style={{ flex: "1 1 200px" }}>
              <label>OU (để trống = global, mọi máy)</label>
              <input value={adOu} onChange={(e) => setAdOu(e.target.value)}
                placeholder="OU=Workstations,DC=corp,DC=local" />
            </div>
            <div style={{ flex: "0 1 120px" }}>
              <label>Hạn dùng (giờ)</label>
              <input type="number" min="1" value={expiresInHours}
                onChange={(e) => setExpiresInHours(e.target.value)} />
            </div>
            <div style={{ flex: "0 1 120px" }}>
              <label>Số lần dùng tối đa (tùy chọn)</label>
              <input type="number" min="1" value={maxUses}
                onChange={(e) => setMaxUses(e.target.value)} placeholder="Không giới hạn" />
            </div>
          </div>
          <label>Ghi chú (tùy chọn)</label>
          <input value={note} onChange={(e) => setNote(e.target.value)} placeholder="VD: rollout Office 2024 khối kế toán" />
          {!adOu.trim() && (
            <p className="muted" style={{ fontSize: 12, color: "var(--warn, #d9a441)" }}>
              ⚠️ Đang để trống OU — secret sẽ dùng được cho MỌI máy trong domain.
            </p>
          )}
          <div className="row spread mt">
            <span />
            <button className="btn" disabled={busy}>
              {busy === "create" ? "Đang tạo…" : "Tạo secret"}
            </button>
          </div>
        </form>

        {newSecret && (
          <div className="mt" style={{ background: "var(--panel, #1a1a1a)", padding: 10, borderRadius: 6 }}>
            <code style={{ wordBreak: "break-all", userSelect: "all" }}>{newSecret}</code>
          </div>
        )}
        {msg && <p className="muted mt">{msg}</p>}
        {err && <p className="error mt">{err}</p>}

        <hr style={{ margin: "16px 0", border: "none", borderTop: "1px solid var(--border, #333)" }} />

        <table>
          <thead>
            <tr>
              <th>OU</th><th>Secret</th><th>Hết hạn</th><th>Dùng</th><th>Trạng thái</th><th></th>
            </tr>
          </thead>
          <tbody>
            {secrets.map((s) => (
              <tr key={s.id}>
                <td className="muted">{s.ad_ou || "Global"}</td>
                <td><code>{s.secret_prefix}…</code></td>
                <td className="muted">{fmt(s.expires_at)}</td>
                <td className="muted">{s.use_count}{s.max_uses ? ` / ${s.max_uses}` : ""}</td>
                <td>
                  <span className={`badge ${s.is_active ? "info" : "default"}`}>
                    {s.is_active ? "Đang hoạt động" : s.revoked_at ? "Đã thu hồi" : "Hết hạn"}
                  </span>
                </td>
                <td>
                  {s.is_active && (
                    <button className="btn ghost" style={{ padding: "4px 10px" }}
                      onClick={() => revoke(s)} disabled={busy}>
                      {busy === `revoke-${s.id}` ? "Đang thu hồi…" : "Thu hồi"}
                    </button>
                  )}
                </td>
              </tr>
            ))}
            {secrets.length === 0 && <tr><td colSpan="6" className="muted">Chưa có secret nào.</td></tr>}
          </tbody>
        </table>

        <div className="row spread mt">
          <button type="button" className="btn ghost" onClick={onClose}>Đóng</button>
        </div>
      </div>
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
      setTestMsg("✓ Đã lưu cấu hình AD.");
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

function SyncADModal({ onClose, onSync, busy }) {
  const [purge, setPurge] = useState(false);

  return (
    <div className="modal-bg" onClick={onClose}>
      <div className="modal" onClick={(e) => e.stopPropagation()} style={{ width: 420 }}>
        <h3>Đồng bộ máy từ AD</h3>
        <p className="muted" style={{ fontSize: 14, margin: "8px 0 16px" }}>
          Đồng bộ danh sách máy tính từ Active Directory theo cấu hình Search OU hiện tại.
        </p>

        <label className="row" style={{ gap: 8, alignItems: "flex-start", cursor: "pointer" }}>
          <input
            type="checkbox"
            checked={purge}
            onChange={(e) => setPurge(e.target.checked)}
            style={{ width: "auto", marginTop: 3 }}
          />
          <span>
            <strong>Xóa máy ngoài phạm vi</strong>
            <br />
            <span className="muted" style={{ fontSize: 12 }}>
              Sau khi sync, xóa tất cả máy trong DB mà không còn nằm trong kết quả AD.
              Bật tùy chọn này khi bạn đã đổi Search OU và muốn dọn máy cũ.
            </span>
          </span>
        </label>

        <div className="row spread mt">
          <button type="button" className="btn ghost" onClick={onClose}>Hủy</button>
          <button
            className="btn"
            onClick={() => onSync(purge)}
            disabled={busy}
          >
            {busy === "ad" ? "Đang sync…" : purge ? "Sync & Xóa máy cũ" : "Sync AD"}
          </button>
        </div>
      </div>
    </div>
  );
}
