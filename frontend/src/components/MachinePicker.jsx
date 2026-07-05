import { useEffect, useMemo, useState } from "react";
import { fetchAll } from "../api";
import { ouLabel } from "../constants/deployment";

// Picker máy đích dùng chung cho Wizard tạo deployment và form lịch lặp.
// Controlled: value = mảng id máy đã chọn, onChange(newValue) cập nhật state form cha.
export default function MachinePicker({ value, onChange, maxHeight = 300 }) {
  const [machines, setMachines] = useState([]);
  const [groups, setGroups] = useState([]);
  const [search, setSearch] = useState("");
  const [groupFilter, setGroupFilter] = useState("");
  const [loadErr, setLoadErr] = useState("");

  useEffect(() => {
    fetchAll("/machines/").then(setMachines).catch((e) => setLoadErr(e.message));
    fetchAll("/machine-groups/").then(setGroups).catch(() => {});
  }, []);

  const q = search.trim().toLowerCase();
  const shown = useMemo(() => {
    let list = machines;
    if (groupFilter) {
      const g = groups.find((g) => String(g.id) === groupFilter);
      if (g) list = list.filter((m) => g.machines.includes(m.id));
    }
    if (q) list = list.filter((m) => `${m.hostname} ${m.ad_ou || ""}`.toLowerCase().includes(q));
    return list;
  }, [machines, groups, groupFilter, q]);

  const toggle = (id) =>
    onChange(value.includes(id) ? value.filter((x) => x !== id) : [...value, id]);

  // Chỉ chọn hết máy CÒN BẬT — máy enabled=false bị targeting bỏ qua lúc chạy nên
  // đưa vào "chọn hết" sẽ tạo ảo tưởng đã chọn nhưng thực chất không chạy.
  const selectableShown = shown.filter((m) => m.enabled);
  const selectAllShown = () =>
    onChange([...new Set([...value, ...selectableShown.map((m) => m.id)])]);
  const clearAll = () => onChange([]);
  const addGroup = (g) => onChange([...new Set([...value, ...g.machines])]);

  return (
    <div className="machine-picker">
      <div className="row" style={{ gap: 8, marginBottom: 6, flexWrap: "wrap" }}>
        <input
          type="text"
          placeholder="🔍 Lọc theo hostname hoặc OU…"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          style={{ flex: 1, minWidth: 160 }}
        />
        {groups.length > 0 && (
          <select value={groupFilter} onChange={(e) => setGroupFilter(e.target.value)} style={{ maxWidth: 200 }}>
            <option value="">Mọi nhóm</option>
            {groups.map((g) => <option key={g.id} value={g.id}>{g.name} ({g.machine_count})</option>)}
          </select>
        )}
        <button type="button" className="btn ghost" style={{ padding: "6px 10px" }} onClick={selectAllShown}>
          Chọn hết ({selectableShown.length})
        </button>
        {value.length > 0 && (
          <button type="button" className="btn ghost" style={{ padding: "6px 10px" }} onClick={clearAll}>
            Bỏ chọn
          </button>
        )}
      </div>

      {groups.length > 0 && (
        <div className="row" style={{ gap: 6, flexWrap: "wrap", marginBottom: 8 }}>
          {groups.map((g) => (
            <button key={g.id} type="button" className="chip-group" onClick={() => addGroup(g)}>
              + {g.name} ({g.machine_count})
            </button>
          ))}
        </div>
      )}

      <div className="log machine-list" style={{ maxHeight }}>
        {shown.map((m) => (
          <label key={m.id} className={`machine-row${m.enabled ? "" : " is-disabled"}`}>
            <input type="checkbox" checked={value.includes(m.id)} onChange={() => toggle(m.id)} />
            <span
              className={`status-dot ${m.enabled ? (m.is_online ? "online" : "offline") : "disabled"}`}
              title={m.enabled ? (m.is_online ? "Online" : "Offline") : "Đã tắt — sẽ không chạy"}
            />
            <span className="machine-name">{m.hostname}</span>
            {ouLabel(m.ad_ou) && <span className="muted machine-ou">· {ouLabel(m.ad_ou)}</span>}
            {!m.enabled && <span className="badge default machine-off-badge">Đã tắt</span>}
          </label>
        ))}
        {loadErr && <span className="error">{loadErr}</span>}
        {!loadErr && machines.length === 0 && <span className="muted">Chưa có máy.</span>}
        {!loadErr && machines.length > 0 && shown.length === 0 && <span className="muted">Không có máy khớp bộ lọc.</span>}
      </div>

      <p className="muted machine-picker-summary">
        {value.length} / {machines.length} máy đã chọn
        {value.length === 0 && <span className="warn-inline"> — chọn ít nhất 1 máy đích</span>}
      </p>
    </div>
  );
}
