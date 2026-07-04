// Biểu đồ báo cáo bằng SVG nội tuyến (không thêm thư viện).
// Màu truyền theo entity/trạng thái (dùng biến CSS của theme), luôn kèm nhãn ở chú giải.

// Donut: data = [{ key, label, value, color }]. Bỏ qua slice value=0.
export function Donut({ data, size = 168, thickness = 22 }) {
  const items = data.filter((d) => d.value > 0);
  const total = items.reduce((s, d) => s + d.value, 0);
  const r = (size - thickness) / 2;
  const cx = size / 2;
  const gap = total > 0 && items.length > 1 ? 1.2 : 0; // khoảng hở giữa các slice (đơn vị %)

  let acc = 0;
  return (
    <div className="chart">
      <svg width={size} height={size} viewBox={`0 0 ${size} ${size}`} role="img">
        {/* vòng nền */}
        <circle
          cx={cx}
          cy={cx}
          r={r}
          fill="none"
          strokeWidth={thickness}
          style={{ stroke: "var(--panel2)" }}
        />
        {total > 0 &&
          items.map((d) => {
            const pct = (d.value / total) * 100;
            const dash = Math.max(pct - gap, 0.5);
            const seg = (
              <circle
                key={d.key}
                cx={cx}
                cy={cx}
                r={r}
                fill="none"
                strokeWidth={thickness}
                strokeLinecap="butt"
                pathLength={100}
                strokeDasharray={`${dash} ${100 - dash}`}
                strokeDashoffset={-acc}
                style={{ stroke: d.color }}
                transform={`rotate(-90 ${cx} ${cx})`}
              >
                <title>{`${d.label}: ${d.value} (${pct.toFixed(0)}%)`}</title>
              </circle>
            );
            acc += pct;
            return seg;
          })}
        <text x={cx} y={cx - 4} textAnchor="middle" className="donut-total">
          {total}
        </text>
        <text x={cx} y={cx + 16} textAnchor="middle" className="donut-sub">
          tổng
        </text>
      </svg>
      <ul className="legend">
        {data.map((d) => (
          <li key={d.key}>
            <span className="swatch" style={{ background: d.color }} />
            <span className="legend-label">{d.label}</span>
            <span className="legend-value">{d.value}</span>
          </li>
        ))}
      </ul>
    </div>
  );
}

// Cột chồng theo ngày: data = [{ date, success, failed }] (14 phần tử).
export function TimelineBars({ data, height = 160 }) {
  const step = 34;
  const barW = 20;
  const padTop = 10;
  const padBottom = 22;
  const plot = height - padTop - padBottom;
  const width = data.length * step;
  const max = Math.max(1, ...data.map((d) => d.success + d.failed));

  return (
    <div className="chart-wide">
      <svg
        viewBox={`0 0 ${width} ${height}`}
        preserveAspectRatio="xMinYMid meet"
        className="timeline-svg"
        role="img"
      >
        {data.map((d, i) => {
          const x = i * step + (step - barW) / 2;
          const total = d.success + d.failed;
          const hFail = (d.failed / max) * plot;
          const hOk = (d.success / max) * plot;
          const dd = d.date.slice(8, 10); // DD
          const baseY = padTop + plot;
          const okY = baseY - hOk;
          const failY = okY - hFail;
          return (
            <g key={d.date}>
              {d.success > 0 && (
                <rect
                  x={x}
                  y={okY}
                  width={barW}
                  height={hOk}
                  rx={total === d.success ? 4 : 0}
                  style={{ fill: "var(--green)" }}
                >
                  <title>{`${d.date}: ${d.success} thành công`}</title>
                </rect>
              )}
              {d.failed > 0 && (
                <rect x={x} y={failY} width={barW} height={hFail} rx={4} style={{ fill: "var(--red)" }}>
                  <title>{`${d.date}: ${d.failed} thất bại`}</title>
                </rect>
              )}
              <text x={x + barW / 2} y={height - 7} textAnchor="middle" className="bar-label">
                {dd}
              </text>
            </g>
          );
        })}
      </svg>
      <ul className="legend legend-row">
        <li>
          <span className="swatch" style={{ background: "var(--green)" }} />
          <span className="legend-label">Thành công</span>
        </li>
        <li>
          <span className="swatch" style={{ background: "var(--red)" }} />
          <span className="legend-label">Thất bại</span>
        </li>
      </ul>
    </div>
  );
}
