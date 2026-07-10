import { useEffect, useMemo, useState } from "react";
import { fetchAll } from "../api";
import Icon from "./Icon";

// Picker máy đích dùng chung cho Wizard tạo deployment và form lịch lặp.
// Controlled: value = mảng id máy đã chọn, onChange(newValue) cập nhật state form cha.
export default function MachinePicker({ value, onChange, maxHeight = 300 }) {
  const [machines, setMachines] = useState([]);
  const [groups, setGroups] = useState([]);
  const [search, setSearch] = useState("");
  const [groupFilter, setGroupFilter] = useState("");
  const [loadErr, setLoadErr] = useState("");
  const [collapsedPaths, setCollapsedPaths] = useState(() => new Set());

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

  // Reset thu gọn mỗi khi bộ lọc đổi, để kết quả lọc luôn hiện đầy đủ thay vì
  // bị giấu trong 1 node đang collapsed từ trước.
  useEffect(() => {
    setCollapsedPaths(new Set());
  }, [q, groupFilter]);

  const toggleCollapse = (path) =>
    setCollapsedPaths((prev) => {
      const next = new Set(prev);
      if (next.has(path)) next.delete(path);
      else next.add(path);
      return next;
    });

  // Dựng cây OU từ danh sách đang hiển thị (đã áp search/group filter).
  // ad_ou lưu dạng "OU=Laptops,OU=IT" — thứ tự lá trước, cần đảo ngược để có
  // thứ tự gốc-trước (root-first) khi dựng cây cha/con.
  const ouTree = useMemo(() => buildOuTree(shown), [shown]);

  const toggle = (id) =>
    onChange(value.includes(id) ? value.filter((x) => x !== id) : [...value, id]);

  // Chỉ chọn hết máy CÒN BẬT — máy enabled=false bị targeting bỏ qua lúc chạy nên
  // đưa vào "chọn hết" sẽ tạo ảo tưởng đã chọn nhưng thực chất không chạy.
  const selectableShown = shown.filter((m) => m.enabled);
  const onlineShown = selectableShown.filter((m) => m.is_online);
  const selectAllShown = () =>
    onChange([...new Set([...value, ...selectableShown.map((m) => m.id)])]);
  const selectOnlineShown = () =>
    onChange([...new Set([...value, ...onlineShown.map((m) => m.id)])]);
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
        <button type="button" className="btn ghost" style={{ padding: "6px 10px" }} onClick={selectOnlineShown} disabled={onlineShown.length === 0}>
          🟢 Chọn máy online ({onlineShown.length})
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
        {ouTree.children.map((node) => (
          <OuTreeNode
            key={node.path}
            node={node}
            depth={0}
            collapsedPaths={collapsedPaths}
            toggleCollapse={toggleCollapse}
            value={value}
            onChange={onChange}
            toggleMachine={toggle}
          />
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

const UNASSIGNED_OU = "(Chưa phân loại OU)";

// "OU=Laptops,OU=IT" -> ["IT", "Laptops"] — đảo về thứ tự gốc-trước (root-first)
// để dựng cây cha/con, vì AD DN lưu OU lá trước.
function parseOuPath(dn) {
  if (!dn) return [];
  return dn
    .split(",")
    .map((p) => p.trim().match(/OU=([^,]+)/i))
    .filter(Boolean)
    .map((m) => m[1])
    .reverse();
}

// Dựng cây OU từ danh sách máy đang hiển thị. Máy không có ad_ou được gom vào
// 1 node ảo để không bị mất khỏi danh sách.
function buildOuTree(machinesList) {
  const root = { name: "", path: "", childMap: new Map(), machines: [] };
  for (const m of machinesList) {
    const segments = parseOuPath(m.ad_ou);
    const path = segments.length > 0 ? segments : [UNASSIGNED_OU];
    let node = root;
    let pathSoFar = "";
    for (const seg of path) {
      pathSoFar = pathSoFar ? `${pathSoFar}/${seg}` : seg;
      if (!node.childMap.has(seg)) {
        node.childMap.set(seg, { name: seg, path: pathSoFar, childMap: new Map(), machines: [] });
      }
      node = node.childMap.get(seg);
    }
    node.machines.push(m);
  }
  return finalizeOuNode(root);
}

// Chuyển childMap -> mảng con đã sắp xếp, và gộp đệ quy danh sách id máy
// enabled trong subtree (dùng cho checkbox tri-state ở mỗi node).
function finalizeOuNode(node) {
  const children = [...node.childMap.values()]
    .map(finalizeOuNode)
    .sort((a, b) => a.name.localeCompare(b.name, "vi"));
  const machines = [...node.machines].sort((a, b) => a.hostname.localeCompare(b.hostname, "vi"));
  const enabledIds = [
    ...machines.filter((m) => m.enabled).map((m) => m.id),
    ...children.flatMap((c) => c.enabledIds),
  ];
  const totalCount = machines.length + children.reduce((sum, c) => sum + c.totalCount, 0);
  return { name: node.name, path: node.path, children, machines, enabledIds, totalCount };
}

function OuTreeNode({ node, depth, collapsedPaths, toggleCollapse, value, onChange, toggleMachine }) {
  const hasContent = node.children.length > 0 || node.machines.length > 0;
  const isOpen = !collapsedPaths.has(node.path);
  const checkedCount = node.enabledIds.filter((id) => value.includes(id)).length;
  const allChecked = node.enabledIds.length > 0 && checkedCount === node.enabledIds.length;
  const someChecked = checkedCount > 0 && !allChecked;

  // Check/uncheck cả subtree — chỉ tác động máy enabled, giữ nguyên các máy
  // khác ngoài subtree đang có trong value (khớp ngữ nghĩa nút "Chọn hết").
  const toggleNode = () => {
    if (node.enabledIds.length === 0) return;
    if (allChecked) {
      const remove = new Set(node.enabledIds);
      onChange(value.filter((id) => !remove.has(id)));
    } else {
      onChange([...new Set([...value, ...node.enabledIds])]);
    }
  };

  return (
    <div>
      <div className="tree-node" style={{ paddingLeft: depth * 16 }}>
        {hasContent ? (
          <button type="button" className="tree-toggle" onClick={() => toggleCollapse(node.path)}>
            <Icon name={isOpen ? "chevronDown" : "chevronRight"} size={13} />
          </button>
        ) : (
          <span className="tree-toggle-spacer" />
        )}
        <input
          type="checkbox"
          checked={allChecked}
          disabled={node.enabledIds.length === 0}
          ref={(el) => {
            if (el) el.indeterminate = someChecked;
          }}
          onChange={toggleNode}
        />
        <span className="tree-label" onClick={() => toggleCollapse(node.path)}>
          <Icon name={isOpen ? "folderOpen" : "folder"} size={15} /> {node.name}
          <span className="muted ou-tree-count"> ({node.totalCount})</span>
        </span>
      </div>
      {isOpen && (
        <>
          {node.children.map((child) => (
            <OuTreeNode
              key={child.path}
              node={child}
              depth={depth + 1}
              collapsedPaths={collapsedPaths}
              toggleCollapse={toggleCollapse}
              value={value}
              onChange={onChange}
              toggleMachine={toggleMachine}
            />
          ))}
          {node.machines.map((m) => (
            <MachineRow
              key={m.id}
              m={m}
              depth={depth + 1}
              checked={value.includes(m.id)}
              onToggle={() => toggleMachine(m.id)}
            />
          ))}
        </>
      )}
    </div>
  );
}

function MachineRow({ m, depth, checked, onToggle }) {
  return (
    <label className={`machine-row${m.enabled ? "" : " is-disabled"}`} style={{ paddingLeft: depth * 16 + 17 }}>
      <input type="checkbox" checked={checked} onChange={onToggle} />
      <span
        className={`status-dot ${m.enabled ? (m.is_online ? "online" : "offline") : "disabled"}`}
        title={m.enabled ? (m.is_online ? "Online" : "Offline") : "Đã tắt — sẽ không chạy"}
      />
      <span className="machine-name">{m.hostname}</span>
      {m.connection_mode === "agent" && <span className="badge info machine-off-badge">Agent</span>}
      {!m.enabled && <span className="badge default machine-off-badge">Đã tắt</span>}
    </label>
  );
}
