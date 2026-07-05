// API client — session auth + CSRF cho Django.

function getCookie(name) {
  const m = document.cookie.match("(^|;)\\s*" + name + "\\s*=\\s*([^;]+)");
  return m ? m.pop() : "";
}

// Trích thông điệp lỗi dễ đọc từ body lỗi DRF. DRF trả nhiều dạng:
//   {detail: "..."}                       → lỗi quyền/404/throttle
//   {field: ["msg"], other: ["msg"]}      → lỗi validation (400) — trước đây bị nuốt
//   {non_field_errors: ["..."]}           → lỗi mức form
//   ["msg", ...]                          → list lỗi thô
function extractError(data, status) {
  if (data == null) return `Lỗi ${status}`;
  if (typeof data === "string") return data;
  if (data.detail) return data.detail;
  if (Array.isArray(data)) return data.join(" ");
  if (typeof data === "object") {
    const parts = [];
    for (const [field, val] of Object.entries(data)) {
      const msg = Array.isArray(val) ? val.join(" ") : String(val);
      // non_field_errors: bỏ tiền tố field cho gọn; còn lại ghi rõ tên field.
      parts.push(field === "non_field_errors" ? msg : `${field}: ${msg}`);
    }
    if (parts.length) return parts.join(" · ");
  }
  return `Lỗi ${status}`;
}

async function request(method, path, body, isForm = false) {
  const headers = {};
  if (!isForm) headers["Content-Type"] = "application/json";
  if (method !== "GET") headers["X-CSRFToken"] = getCookie("csrftoken");

  const res = await fetch(`/api${path}`, {
    method,
    headers,
    credentials: "include",
    body: body ? (isForm ? body : JSON.stringify(body)) : undefined,
  });

  if (res.status === 204) return null;
  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    throw new Error(extractError(data, res.status));
  }
  return data;
}

export const api = {
  get: (p) => request("GET", p),
  post: (p, b) => request("POST", p, b),
  put: (p, b) => request("PUT", p, b),
  patch: (p, b) => request("PATCH", p, b),
  del: (p) => request("DELETE", p),
  postForm: (p, formData) => request("POST", p, formData, true),
  patchForm: (p, formData) => request("PATCH", p, formData, true),

  // Auth
  csrf: () => request("GET", "/auth/csrf/"),
  login: (username, password) => request("POST", "/auth/login/", { username, password }),
  logout: () => request("POST", "/auth/logout/"),
  me: () => request("GET", "/auth/me/"),
  stats: () => request("GET", "/stats/"),
  report: () => request("GET", "/report/"),
  serverStats: () => request("GET", "/server-stats/"),
};

// Trả về mảng results (hỗ trợ cả paginated lẫn list thô)
export function listOf(data) {
  if (Array.isArray(data)) return data;
  return data?.results ?? [];
}

// Lấy TOÀN BỘ bản ghi qua mọi trang phân trang (dùng cho picker cần đủ danh sách,
// vd chọn máy đích — API mặc định chỉ trả 25/trang).
const FETCH_ALL_MAX_PAGES = 20000; // an toàn chống vòng lặp vô hạn, không phải trần thực tế

export async function fetchAll(path) {
  let out = [];
  let next = path;
  let i = 0;
  for (; i < FETCH_ALL_MAX_PAGES && next; i++) {
    const data = await api.get(next);
    if (Array.isArray(data)) return data; // endpoint không phân trang
    out = out.concat(data.results ?? []);
    if (!data.next) break;
    // data.next là URL tuyệt đối; lấy path+query sau tiền tố /api để gọi tiếp.
    const u = new URL(data.next);
    next = u.pathname.replace(/^\/api/, "") + u.search;
  }
  if (i >= FETCH_ALL_MAX_PAGES && next) {
    // Chạm trần an toàn mà vẫn còn trang tiếp theo → dữ liệu BỊ CẮT, phải biết ngay
    // thay vì im lặng thiếu (vd wizard chọn máy đích thiếu máy mà không báo).
    console.warn(`fetchAll(${path}): dừng ở ${FETCH_ALL_MAX_PAGES} trang, còn dữ liệu — kết quả bị cắt.`);
  }
  return out;
}

// Poll một Celery task (tác vụ nền) tới khi xong; trả về payload cuối (có .result / .error).
export async function waitForTask(taskId, { interval = 1500, timeout = 120000 } = {}) {
  const start = Date.now();
  while (Date.now() - start < timeout) {
    const t = await api.get(`/tasks/${taskId}/`);
    if (t.ready) return t;
    await new Promise((r) => setTimeout(r, interval));
  }
  throw new Error("Tác vụ nền quá thời gian chờ.");
}
