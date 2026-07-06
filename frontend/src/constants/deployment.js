// Action cần chọn package version; các action khác chạy không gắn package.
export const ACTIONS = [
  { value: "install", label: "Cài đặt" },
  { value: "uninstall", label: "Gỡ cài đặt" },
  { value: "reboot", label: "Khởi động lại" },
  { value: "shutdown", label: "Tắt máy" },
  { value: "inventory", label: "Quét phần mềm (inventory)" },
];
export const PACKAGE_ACTIONS = ["install", "uninstall"];
// Khớp ADMIN_ONLY_ACTIONS ở backend/apps/deployments/models.py — chỉ admin được trigger.
export const ADMIN_ONLY_ACTIONS = ["reboot", "shutdown"];
