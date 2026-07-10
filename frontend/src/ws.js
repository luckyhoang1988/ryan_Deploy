// WebSocket client — kết nối 1 lần duy nhất tới /ws/updates/ (singleton module-level,
// nhiều component subscribe cùng 1 socket thay vì mỗi component tự mở 1 kết nối riêng),
// tự reconnect với backoff khi rớt mạng. Session cookie tự gửi kèm handshake (same-origin),
// không cần token riêng — giống cách api.js dựa vào credentials: "include".
//
// Dùng: const unsubscribe = subscribe("deployment.update", (data) => {...}); // patch state
//       unsubscribe(); // lúc unmount

const listeners = {
  "deployment.update": new Set(),
  "job.update": new Set(),
};

let socket = null;
let retryMs = 1000;
const MAX_RETRY_MS = 15000;

function wsUrl() {
  const scheme = location.protocol === "https:" ? "wss:" : "ws:";
  return `${scheme}//${location.host}/ws/updates/`;
}

function connect() {
  if (socket && (socket.readyState === WebSocket.OPEN || socket.readyState === WebSocket.CONNECTING)) return;

  socket = new WebSocket(wsUrl());

  socket.onopen = () => {
    retryMs = 1000; // reset backoff sau khi kết nối lại thành công
  };

  socket.onmessage = (ev) => {
    let msg;
    try {
      msg = JSON.parse(ev.data);
    } catch {
      return;
    }
    listeners[msg.type]?.forEach((fn) => fn(msg.data));
  };

  socket.onclose = () => {
    socket = null;
    setTimeout(connect, retryMs);
    retryMs = Math.min(retryMs * 2, MAX_RETRY_MS);
  };

  socket.onerror = () => socket?.close();
}

// Đăng ký nhận message theo type ("deployment.update"/"job.update"); trả về hàm hủy đăng ký.
// Tự kết nối (nếu chưa) ngay khi có subscriber đầu tiên.
export function subscribe(type, handler) {
  listeners[type].add(handler);
  connect();
  return () => listeners[type].delete(handler);
}
