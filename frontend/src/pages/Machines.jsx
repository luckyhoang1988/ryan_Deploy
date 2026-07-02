import { useEffect, useState } from "react";
import { api, listOf } from "../api";
import { StatusBadge } from "../components/Layout";

export default function Machines() {
  const [machines, setMachines] = useState([]);
  const [msg, setMsg] = useState("");
  const [err, setErr] = useState("");
  const [busy, setBusy] = useState("");

  const load = () =>
    api.get("/machines/").then((d) => setMachines(listOf(d))).catch((e) => setErr(e.message));

  useEffect(() => {
    load();
  }, []);

  const syncAd = async () => {
    setBusy("ad"); setErr(""); setMsg("");
    try {
      const r = await api.post("/machines/sync_ad/", {});
      setMsg(`AD sync: +${r.created} mới, ${r.updated} cập nhật`);
      load();
    } catch (e) { setErr(e.message); } finally { setBusy(""); }
  };

  const checkOnline = async () => {
    setBusy("online"); setErr(""); setMsg("");
    try {
      const r = await api.post("/machines/check_online/", {});
      setMsg(`Online check: ${r.online}/${r.checked} máy online`);
      load();
    } catch (e) { setErr(e.message); } finally { setBusy(""); }
  };

  return (
    <div>
      <div className="topbar">
        <h2>Máy trạm</h2>
        <div className="row">
          <button className="btn ghost" onClick={syncAd} disabled={busy}>
            {busy === "ad" ? "Đang sync…" : "Sync AD"}
          </button>
          <button className="btn ghost" onClick={checkOnline} disabled={busy}>
            {busy === "online" ? "Đang kiểm tra…" : "Kiểm tra online"}
          </button>
        </div>
      </div>
      {msg && <p className="muted">{msg}</p>}
      {err && <p className="error">{err}</p>}
      <table>
        <thead>
          <tr><th>Hostname</th><th>FQDN</th><th>OS</th><th>OU</th><th>Trạng thái</th></tr>
        </thead>
        <tbody>
          {machines.map((m) => (
            <tr key={m.id}>
              <td>{m.hostname}</td>
              <td className="muted">{m.fqdn || "—"}</td>
              <td>{m.os_name || "—"}</td>
              <td className="muted">{m.ad_ou || "—"}</td>
              <td><StatusBadge status={m.is_online ? "success" : "failed"} /></td>
            </tr>
          ))}
          {machines.length === 0 && <tr><td colSpan="5" className="muted">Chưa có máy. Bấm “Sync AD”.</td></tr>}
        </tbody>
      </table>
    </div>
  );
}
