# So sánh CSV theo key (v1.9.0)

1. Thêm hai CSV vào card **Tệp CSV**. Tên file không cần theo mẫu import.
2. Giữ **Ctrl** hoặc **Shift** để chọn đúng hai dòng, rồi nhấn **So sánh 2 CSV**.
3. File ở trên trong danh sách là **bản cũ**, file ở dưới là **bản mới**. Dùng **Đổi cũ ↔ mới** nếu cần.
4. Xem tổng số key mới, đã xóa, thay đổi và không đổi. Chọn bộ lọc **Key mới** để xem từng key và toàn bộ giá trị mới của nó.
5. Bảng ghép cũ/mới theo **key và tên cột**, không theo vị trí dòng/cột. Mỗi dòng kết quả là một ô dữ liệu; số lượng thống kê tính theo key duy nhất. Chọn dòng để xem và sao chép đầy đủ nội dung nhiều dòng ở hai khung bên dưới.

CSV phải dùng UTF-8 (có hoặc không BOM), có hàng header và cột `key`. Hỗ trợ dấu phẩy, chấm phẩy, tab và `|` theo cơ chế nhận diện CSV hiện tại. Tên cột được bỏ khoảng trắng hai đầu và so không phân biệt hoa/thường. Giá trị key được bỏ khoảng trắng hai đầu nhưng **phân biệt hoa/thường**; nội dung các ô còn lại được giữ nguyên, kể cả khoảng trắng và xuống dòng.

Key mới là key chỉ có ở bản mới. Key đã xóa chỉ có ở bản cũ. Key thay đổi có ít nhất một ô khác hoặc thêm/xóa cột; key đổi tên được thể hiện thành một key đã xóa và một key mới. `∅ Không tồn tại` khác với một ô rỗng. CSV có key trùng/rỗng, header trùng/rỗng hoặc dữ liệu sai định dạng sẽ báo lỗi để tránh ghép sai. So sánh chỉ đọc tệp và không cần đăng nhập Google.

**Google Sheet đích** đã chuyển vào **Cài đặt → Google Sheet đích**, gồm link Sheet, kiểu nhập, tên tab và cách xử lý dữ liệu. Các thiết lập được lưu khi đóng cài đặt; bảng Tệp CSV trên màn hình chính có thêm không gian.

Kiểm thử: `py -m pytest -q` và `py validate_ui_forms.py`.

## Điều chỉnh giao diện (v1.9.1)

- Kéo thanh ngăn giữa các card **Tệp CSV / Hành động / Nhật ký** để thay đổi chiều cao. Mỗi card có giới hạn nhỏ nhất theo nội dung để các nút và tiêu đề không chồng lên nhau. Kích thước được lưu khi kéo và khi đóng ứng dụng, rồi khôi phục ở lần mở sau; khi đổi kích thước cửa sổ, các card được điều chỉnh trong giới hạn cho phép.
- **So sánh 2 CSV** nằm cùng hàng với các nút quản lý tệp; bỏ dòng hướng dẫn bên cạnh.
- Popup dùng xanh lá cho key mới, đỏ cho key đã xóa, vàng cho thay đổi và xám cho không đổi. Nhấn tiêu đề **Trạng thái / Key / Cột / Bản cũ / Bản mới** để sắp xếp tăng hoặc giảm. Mặc định nhóm key mới, thay đổi, đã xóa, không đổi; các dòng cùng nhóm được xếp theo key. Bộ lọc và khung chi tiết vẫn theo đúng dữ liệu sau khi sắp xếp.
