// Thanh phân trang dùng chung (Machines, DeploymentDetail, ...): tối đa 7 nút số
// trang + dấu "…" khi quá nhiều, cộng nút ‹/› và dòng "Hiển thị x–y / tổng".

function pageNumbers(page, totalPages) {
  const pages = [];
  if (totalPages <= 7) {
    for (let i = 1; i <= totalPages; i++) pages.push(i);
  } else {
    pages.push(1);
    if (page > 3) pages.push("…l");
    const start = Math.max(2, page - 1);
    const end = Math.min(totalPages - 1, page + 1);
    for (let i = start; i <= end; i++) pages.push(i);
    if (page < totalPages - 2) pages.push("…r");
    pages.push(totalPages);
  }
  return pages;
}

export default function Pagination({ page, totalCount, pageSize, onPageChange, itemLabel = "mục" }) {
  const totalPages = Math.max(1, Math.ceil(totalCount / pageSize));
  if (totalPages <= 1) return null;

  const goToPage = (p) => {
    if (p >= 1 && p <= totalPages) onPageChange(p);
  };

  return (
    <div className="pagination">
      <span className="pagination-info">
        Hiển thị {(page - 1) * pageSize + 1}–{Math.min(page * pageSize, totalCount)} / {totalCount} {itemLabel}
      </span>
      <div className="pagination-controls">
        <button
          className="pagination-btn"
          onClick={() => goToPage(page - 1)}
          disabled={page <= 1}
          title="Trang trước"
        >
          ‹
        </button>
        {pageNumbers(page, totalPages).map((p) =>
          typeof p === "string" ? (
            <span key={p} className="pagination-ellipsis">…</span>
          ) : (
            <button
              key={p}
              className={`pagination-btn${p === page ? " active" : ""}`}
              onClick={() => goToPage(p)}
            >
              {p}
            </button>
          )
        )}
        <button
          className="pagination-btn"
          onClick={() => goToPage(page + 1)}
          disabled={page >= totalPages}
          title="Trang sau"
        >
          ›
        </button>
      </div>
    </div>
  );
}
