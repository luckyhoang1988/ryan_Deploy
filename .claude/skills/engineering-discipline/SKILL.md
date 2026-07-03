---
name: engineering-discipline
description: >-
  Quy tắc kỷ luật kỹ thuật BẮT BUỘC đọc TRƯỚC khi viết/sửa code, chạy test, hay
  thay đổi bất kỳ file nào của dự án — và đọc lại SAU khi xong để rút kinh nghiệm.
  Kích hoạt khi: tạo/sửa/xóa code, thêm tính năng, fix bug, refactor, viết test,
  đổi cấu hình, hoặc bất kỳ thao tác nào chạm vào mã nguồn. Dùng như checklist
  cho từng thay đổi.
---

# Engineering Discipline — Kỷ luật kỹ thuật

7 nguyên tắc làm việc. Áp dụng cho **mọi** thay đổi mã nguồn, không có ngoại lệ.
Đọc `LESSONS.md` (cùng thư mục) trước khi bắt đầu; ghi thêm vào đó sau khi xong.

---

## 1. Không đoán khi không biết
- Nếu không chắc về API, hành vi, hay cấu trúc → **kiểm chứng bằng cách đọc code/tài liệu**, đừng suy diễn.
- Không bịa tên hàm, flag, tham số, phiên bản. Nếu không tìm thấy, nói rõ "chưa xác định" thay vì đoán.
- Khi có nhiều cách hiểu → hỏi lại hoặc verify, không chọn bừa.

## 2. Code dựa trên test thật
- Mọi thay đổi có mặt runtime phải được **chạy thật** để quan sát hành vi — không chỉ dựa vào "trông có vẻ đúng".
- Ưu tiên: chạy đúng luồng bị ảnh hưởng (end-to-end), rồi mới đến unit test.
- Không tuyên bố "đã xong/đã fix" nếu chưa thấy nó chạy đúng. Nếu test fail, báo cáo trung thực kèm output.
- Với dự án này: `manage.py check`, `pytest` (dùng `DJANGO_SETTINGS_MODULE=ryandeploy.settings.test` cho sqlite), `npm run build`.

## 3. Đọc kỹ tài liệu chuyên môn để cập nhật skill
- Trước khi dùng thư viện/công nghệ mới, đọc tài liệu chính thức — không dựa vào trí nhớ.
- Khi phát hiện kiến thức mới đáng giá (hành vi thư viện, gotcha, best practice) → cập nhật `LESSONS.md` hoặc skill liên quan.
- Với câu hỏi về Claude/Anthropic API, thư viện LLM → dùng skill `claude-api`, không trả lời từ trí nhớ.

## 4. Luôn đọc skill trước khi thay đổi
- **Trước** khi sửa/tạo file: đọc skill này + `LESSONS.md` + skill chuyên biệt nếu có (vd `claude-api`, `dataviz`, skill của dự án).
- Đọc file mục tiêu và mã xung quanh trước khi sửa — code mới phải khớp phong cách, cách đặt tên, độ dày comment của code hiện có.
- Nếu điều đọc được mâu thuẫn với yêu cầu → nêu ra, đừng cứ thế làm.

## 5. Luôn code như một chuyên gia thực thụ
- Ưu tiên: đúng đắn → an toàn → đơn giản → hiệu năng. Không đánh đổi tính đúng lấy sự tiện.
- Xử lý lỗi, edge case, bảo mật (không log/echo secret, không hardcode credential).
- Tái sử dụng pattern có sẵn thay vì phát minh lại. Giữ thay đổi tối thiểu và có mục đích.
- Không để lại code chết, comment thừa, hay TODO mơ hồ.

## 6. Rút kinh nghiệm sau mỗi lần thực hiện
- Sau khi hoàn tất một thay đổi, tự hỏi: *điều gì đã sai/mất thời gian? điều gì không hiển nhiên?*
- Ghi bài học vào `LESSONS.md` (định dạng ở cuối file đó) để lần sau không lặp lại.
- Chỉ ghi điều **không suy ra được** từ code/git — bài học thật sự, không phải nhật ký công việc.

## 7. Luôn mở rộng tư duy trước khi code
- Trước khi gõ dòng code đầu tiên: hiểu rõ yêu cầu, khảo sát các file liên quan, cân nhắc 2–3 hướng và chọn có lý do.
- Nghĩ về ảnh hưởng lan tỏa: migration, API contract, frontend, test, bảo mật, tương thích ngược.
- Với việc phức tạp: phác thảo kế hoạch (dùng TodoWrite nếu nhiều bước) trước khi thực thi.

---

## Checklist nhanh cho mỗi thay đổi

```
TRƯỚC:
□ (7) Đã hiểu yêu cầu và cân nhắc các hướng?
□ (4) Đã đọc skill này + LESSONS.md + file mục tiêu + mã xung quanh?
□ (1) Có chỗ nào đang đoán không? Nếu có → verify trước.
□ (3) Công nghệ mới? → đọc tài liệu chính thức.

TRONG KHI:
□ (5) Code khớp phong cách hiện có, xử lý lỗi/edge case/bảo mật.

SAU:
□ (2) Đã CHẠY THẬT và quan sát kết quả? Test pass?
□ (6) Có bài học nào mới? → ghi vào LESSONS.md.
□ Báo cáo trung thực: nếu test fail hay bước bị bỏ qua, nói rõ.
```

> Nguyên tắc vàng: **Đọc → Nghĩ → Verify → Code → Test thật → Rút kinh nghiệm.**
