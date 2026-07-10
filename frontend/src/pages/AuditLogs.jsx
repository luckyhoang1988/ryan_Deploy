import { useCallback, useEffect, useState } from "react";
import { api, fetchAll } from "../api";
import { useAuth } from "../auth";
import Pagination from "../components/Pagination";

const PAGE_SIZE = 30;

const AUDIT_ACTION_OPTIONS = [
  ["package_upload", "Upload package"],
  ["package_update", "Sửa package"],
  ["package_delete", "Xóa package"],
  ["package_version_delete", "Xóa version"],
  ["package_fetch", "Tải version từ URL"],
  ["package_approve", "Duyệt version"],
  ["update_deploy", "Deploy cập nhật"],
  ["credential_create", "Tạo credential"],
  ["credential_update", "Sửa credential"],
  ["credential_delete", "Xóa credential"],
  ["deployment_create", "Tạo deployment"],
  ["deployment_update", "Sửa deployment"],
  ["deployment_delete", "Xóa deployment"],
  ["deployment_trigger", "Kích hoạt deployment"],
  ["deployment_cancel", "Hủy deployment"],
  ["schedule_create", "Tạo lịch lặp"],
  ["schedule_update", "Sửa lịch lặp"],
  ["schedule_delete", "Xóa lịch lặp"],
  ["job_start", "Bắt đầu job"],
  ["job_finish", "Kết thúc job"],
  ["machine_sync", "Đồng bộ máy từ AD"],
  ["catalog_seed", "Nạp Package Library mẫu"],
  ["user_update", "Sửa user"],
  ["user_delete", "Xóa user"],
];

export default function AuditLogs() {
  const { hasRole } = useAuth();
  const [logs, setLogs] = useState([]);
  const [totalCount, setTotalCount] = useState(0);
  const [page, setPage] = useState(1);
  const [filterAction, setFilterAction] = useState("");
  const [filterUserId, setFilterUserId] = useState("");
  const [dateFrom, setDateFrom] = useState("");
  const [dateTo, setDateTo] = useState("");
  const [users, setUsers] = useState([]);
  const [err, setErr] = useState("");

  if (!hasRole("admin")) {
    return (
      <div>
        <div className="topbar"><h2>Audit Log</h2></div>
        <p className="error">Chỉ quản trị viên (admin) mới được xem nhật ký kiểm toán.</p>
      </div>
    );
  }

  const buildQuery = useCallback((p) => {
    const params = new URLSearchParams();
    params.set("page", p);
    if (filterAction) params.set("action", filterAction);
    if (filterUserId) params.set("user", filterUserId);
    if (dateFrom) params.set("date_from", dateFrom);
    if (dateTo) params.set("date_to", dateTo);
    return params.toString();
  }, [filterAction, filterUserId, dateFrom, dateTo]);

  const load = useCallback((p = page) => {
    api.get(`/audit-logs/?${buildQuery(p)}`)
      .then((d) => {
        setLogs(d.results ?? []);
        setTotalCount(d.count ?? 0);
      })
      .catch((e) => setErr(e.message));
  }, [buildQuery, page]);

  useEffect(() => {
    load(page);
  }, [page, buildQuery]);

  useEffect(() => {
    setPage(1);
  }, [filterAction, filterUserId, dateFrom, dateTo]);

  useEffect(() => {
    fetchAll("/users/").then(setUsers).catch((e) => setErr(e.message));
  }, []);

  const exportCSV = () => {
    const params = new URLSearchParams();
    if (filterAction) params.set("action", filterAction);
    if (filterUserId) params.set("user", filterUserId);
    if (dateFrom) params.set("date_from", dateFrom);
    if (dateTo) params.set("date_to", dateTo);
    const q = params.toString();
    window.open(`/api/audit-logs/export/${q ? "?" + q : ""}`, "_blank");
  };

  const hasActiveFilter = filterAction || filterUserId || dateFrom || dateTo;
  const clearFilters = () => {
    setFilterAction("");
    setFilterUserId("");
    setDateFrom("");
    setDateTo("");
  };

  const formatDetail = (detail) => {
    const str = JSON.stringify(detail);
    const truncated = str.length > 60 ? str.slice(0, 60) + "…" : str;
    return { truncated, full: JSON.stringify(detail, null, 2) };
  };

  return (
    <div>
      <div className="topbar">
        <h2>Audit Log</h2>
      </div>
      {err && <p className="error">{err}</p>}

      <div className="filter-bar">
        <select value={filterAction} onChange={(e) => setFilterAction(e.target.value)} style={{ maxWidth: 250 }}>
          <option value="">Tất cả hành động</option>
          {AUDIT_ACTION_OPTIONS.map(([value, label]) => (
            <option key={value} value={value}>{label}</option>
          ))}
        </select>

        <select value={filterUserId} onChange={(e) => setFilterUserId(e.target.value)} style={{ maxWidth: 200 }}>
          <option value="">Tất cả người dùng</option>
          {users.map((u) => (
            <option key={u.id} value={u.id}>{u.username}</option>
          ))}
        </select>

        <input
          type="date"
          value={dateFrom}
          onChange={(e) => setDateFrom(e.target.value)}
          placeholder="Từ ngày"
          title="Từ ngày"
        />

        <input
          type="date"
          value={dateTo}
          onChange={(e) => setDateTo(e.target.value)}
          placeholder="Đến ngày"
          title="Đến ngày"
        />

        {hasActiveFilter && (
          <button className="btn ghost" style={{ padding: "6px 12px" }} onClick={clearFilters}>
            ✕ Xóa lọc
          </button>
        )}
        <div style={{ flex: 1 }} />
        <button className="btn ghost" onClick={exportCSV} title="Xuất danh sách audit log ra Excel (CSV)">
          📥 Xuất Excel
        </button>
      </div>

      <table>
        <thead>
          <tr>
            <th>Thời gian</th>
            <th>Người dùng</th>
            <th>Hành động</th>
            <th>Đối tượng</th>
            <th>Máy</th>
            <th>Chi tiết</th>
          </tr>
        </thead>
        <tbody>
          {logs.map((log) => {
            const detail = formatDetail(log.detail);
            return (
              <tr key={log.id}>
                <td className="muted">{new Date(log.created_at).toLocaleString("vi-VN")}</td>
                <td>{log.username || "—"}</td>
                <td>{log.action_display}</td>
                <td className="muted">
                  {log.target_type ? `${log.target_type} #${log.target_id}` : "—"}
                </td>
                <td className="muted">{log.machine_hostname || "—"}</td>
                <td>
                  <code title={detail.full} style={{ cursor: "help" }}>
                    {detail.truncated}
                  </code>
                </td>
              </tr>
            );
          })}
          {logs.length === 0 && <tr><td colSpan="6" className="muted">Chưa có audit log.</td></tr>}
        </tbody>
      </table>

      <Pagination page={page} totalCount={totalCount} pageSize={PAGE_SIZE} onPageChange={setPage} itemLabel="bản ghi" />
    </div>
  );
}
