// Thanh % tiến trình deploy: xanh = thành công, đỏ = lỗi, sọc vàng = đang chạy.
// % hoàn tất = (thành công + lỗi) / tổng số máy. Dùng chung cho DeploymentDetail và
// panel "Đang chạy" toàn cục (Layout.jsx).
export default function DeployProgress({ dep, compact = false }) {
  const total = dep.total_count || 0;
  const success = dep.success_count || 0;
  const failed = dep.failed_count || 0;
  const skipped = dep.skipped_count || 0;
  const pending = dep.pending_count || 0;
  // skipped (đã tồn tại, bỏ qua cài) tính vào "đã xong" cùng success/failed.
  const done = success + failed + skipped;
  // Máy đang chạy = tổng trừ đã xong trừ chờ (kẹp về 0 nếu số liệu lệch nhất thời).
  const running = Math.max(total - done - pending, 0);
  const pct = total > 0 ? Math.round((done / total) * 100) : 0;
  const w = (n) => (total > 0 ? `${(n / total) * 100}%` : "0%");

  return (
    <div className={`progress-wrap${compact ? " compact" : ""}`}>
      <div className="progress-head">
        <span className="progress-pct">{pct}%</span>
        {!compact && (
          <span className="progress-sub">
            {done}/{total} máy đã xong
            {running > 0 && ` · ${running} đang chạy`}
            {pending > 0 && ` · ${pending} chờ`}
            {skipped > 0 && ` · ${skipped} đã tồn tại`}
          </span>
        )}
      </div>
      <div className="progress-track" role="progressbar"
        aria-valuenow={pct} aria-valuemin={0} aria-valuemax={100}>
        <div className="progress-seg success" style={{ width: w(success) }} />
        <div className="progress-seg skipped" style={{ width: w(skipped) }} />
        <div className="progress-seg failed" style={{ width: w(failed) }} />
        <div className="progress-seg running" style={{ width: w(running) }} />
      </div>
    </div>
  );
}
