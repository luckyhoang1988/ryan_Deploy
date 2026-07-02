// API client — session auth + CSRF cho Django.

function getCookie(name) {
  const m = document.cookie.match("(^|;)\\s*" + name + "\\s*=\\s*([^;]+)");
  return m ? m.pop() : "";
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
    throw new Error(data.detail || `Lỗi ${res.status}`);
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

  // Auth
  csrf: () => request("GET", "/auth/csrf/"),
  login: (username, password) => request("POST", "/auth/login/", { username, password }),
  logout: () => request("POST", "/auth/logout/"),
  me: () => request("GET", "/auth/me/"),
  stats: () => request("GET", "/stats/"),
};

// Trả về mảng results (hỗ trợ cả paginated lẫn list thô)
export function listOf(data) {
  if (Array.isArray(data)) return data;
  return data?.results ?? [];
}
