# Import Localize v1.3.0

Ứng dụng desktop nhập file CSV vào Google Sheets theo hai chế độ:

- **Nhiều sheet:** mỗi CSV vào một tab riêng theo tên file.
- **Một sheet:** chỉ file nằm trên cùng trong danh sách được nhập vào tab do người dùng nhập.

## Chế độ nhiều sheet

Tên file phải có dạng:

```text
[Tên Google Sheet] - [Tên tab cần import].csv
```

Ví dụ:

```text
DG_Localization - import_vi.csv
DG_Localization - import_pt.csv
DG_Localization - import_en.csv
```

Ứng dụng đối chiếu phần `[Tên Google Sheet]` trong tên file với tên Spreadsheet từ link. Mỗi tab đã có sẽ bị thay thế toàn bộ; tab chưa có được tạo mới.

## Chế độ một sheet

- Nhập tên tab trực tiếp trong card **Google Sheet đích**.
- Chỉ file nằm trên cùng trong card **Tệp CSV** được sử dụng.
- Các file phía dưới hiển thị `Không nhập` và không được upload.
- Tên file không cần theo format của chế độ nhiều sheet.

## Mặc định cố định

- Dòng đầu CSV luôn là tiêu đề.
- Không thêm cột nguồn file.
- Luôn thay thế toàn bộ dữ liệu của tab đích.

## Giao diện v1.3.0

Thứ tự card trên màn hình chính:

1. **Google Sheet đích**
2. **Tệp CSV**
3. **Hành động**
4. **Nhật ký**

Card Google Sheet đích chỉ còn Link Sheet, Kiểu nhập, Tên Sheet khi dùng chế độ một sheet, và cách Google xử lý dữ liệu.

## Cài đặt

```powershell
cd F:\Codes\Import_Localize
py -m venv .venv
.\.venv\Scripts\Activate.ps1
py -m pip install -r requirements.txt
```

## Chạy source

```powershell
cd F:\Codes\Import_Localize\src
py main.py
```

## Kiểm tra SSL của bản EXE

Build tự đóng gói `codex-rejected-cas.pem` nếu Python dùng để build cần file chính sách chứng chỉ này. Bản Python tiêu chuẩn không cần file bổ sung. Mỗi bản EXE phải vượt qua kiểm tra tạo TLS context của urllib3, nạp chứng chỉ certifi và bật xác thực chứng chỉ/hostname, cùng các kiểm tra giao diện trước khi tạo ZIP.

Có thể kiểm tra HTTPS thực tế bằng `Import_Localize.exe --https-self-test <đường-dẫn-report.json>`. Lệnh chỉ GET các endpoint Google công khai, không đọc token, không đăng nhập và không ghi dữ liệu Sheets. Report thành công có `status: "ok"`; endpoint token trả HTTP 404/405 cho GET là bình thường. Kiểm tra này cần mạng; kiểm tra TLS trong bước build chạy offline.

Nếu bản cũ báo thiếu file SSL và không thể kiểm tra cập nhật, tải ZIP bản mới từ GitHub Releases rồi giải nén toàn bộ thư mục để chạy. Không chỉ chép riêng EXE; cấu hình và phiên Google vẫn được lưu riêng trong AppData.

## Google OAuth

Trong **Cài đặt**:

1. Chọn `oauth_client.json` loại Desktop app.
2. Nhấn **Đăng nhập Google**.
3. Tài khoản phải có quyền Editor với bảng tính được dán link.

Token được lưu riêng tại:

```text
%APPDATA%\Import Localize\google_oauth_token.json
```

## Chỉnh giao diện bằng Qt Designer

```powershell
.\open_designer.ps1 -Form main
```

Form chính:

```text
src/import_localize/ui/forms/main_window.ui
```

Sau khi chỉnh:

```powershell
py .\validate_ui_forms.py
```

## Build

```powershell
py .\build_app.py --version 1.3.0
```

Hoặc đóng gói OAuth Client cho bản phát hành nội bộ:

```powershell
py .\build_app.py `
  --version 1.3.0 `
  --oauth-client "F:\Secrets\Import-Localize\oauth_client.json"
```

## Cập nhật tự động

Từ v1.5.0, bản EXE có thể kiểm tra và tự cài bản mới tại **Cài đặt → Cập nhật** thông qua GitHub Releases. Xem [README_V1_5_AUTO_UPDATE.md](README_V1_5_AUTO_UPDATE.md) để cấu hình repository, build và phát hành.

## Tải các tab export_* về máy

Trong card **Hành động**, chọn **Tải các tab export_*** rồi chọn thư mục lưu.
Ứng dụng sẽ quét mọi tab có tên bắt đầu bằng `export_`, tải nguyên byte CSV do
Google Sheets tạo và lưu theo mẫu:

```text
[Tên Google Sheet] - [Tên tab].csv
```

Các file trùng tên trong thư mục đích sẽ được thay thế. Những file đã tải xong
được giữ lại nếu người dùng dừng giữa quá trình.

## So sánh CSV theo key

Chọn hai tệp trong card Tệp CSV → **So sánh 2 CSV** để xem key mới, đã xóa và thay đổi. Link Google Sheet và kiểu nhập nằm trong **Cài đặt → Google Sheet đích**. Xem [hướng dẫn so sánh CSV](README_CSV_COMPARE.md).

## Nhận diện ngôn ngữ CSV offline

Chọn một hoặc nhiều hàng trong card **Tệp CSV** → **Nhận diện ngôn ngữ CSV…**. Không chọn hàng thì kiểm tra toàn bộ danh sách. Cũng có nút này trong cửa sổ Unity Locale để kiểm tra CSV import hoặc CSV export. Trong cửa sổ kết quả có thể chọn các CSV khác và **Kiểm tra lại**.

- Mô hình **Lingua 2.2.0** được đóng gói cùng app, hỗ trợ 75 ngôn ngữ; không cần mạng, tài khoản Google hoặc tải mô hình khi sử dụng. Chạy trên luồng nền, có tiến độ theo số ô đã xử lý và nút **Dừng**. Lần phân tích đầu cần thêm thời gian nạp mô hình.
- Nhận diện nội dung độc lập với tên cột, sau đó đối chiếu với `English`, `Vietnamese`, mã `en`, `vi`, dạng `Portuguese (Brazil) [pt-BR]`… Bỏ qua các cột key/type/desc/metadata. Cột không có tên/mã được hỗ trợ vẫn được nhận diện nhưng báo chưa thể đối chiếu; không suy đoán ngôn ngữ khai báo từ tên file.
- Bảng tổng hợp hiển thị ngôn ngữ nhận diện được, số ô phù hợp, nghi sai và chưa kết luận theo từng file/cột. Bấm một hàng để lọc cột; dùng bộ lọc trạng thái hoặc tìm key/nội dung. Chọn dòng chi tiết để xem nguyên văn, vị trí bản ghi và điểm mô hình. Dòng CSV là dòng vật lý bắt đầu bản ghi; ô nhiều dòng có thể làm số này khác số hàng trong Excel/Sheets.
- Chỉ cảnh báo **Nghi sai ngôn ngữ** khi có đủ nội dung, điểm dự đoán ít nhất 0,80 và chênh lệch với ngôn ngữ kế tiếp ít nhất 0,30. Điểm này không phải tỷ lệ chính xác đã kiểm chứng. Kết quả yếu hoặc quá ngắn được để **Chưa chắc chắn/Chưa đủ nội dung**; không coi là đã đúng. Tên riêng, từ mượn và câu trộn ngôn ngữ có thể gây nhầm; cần xem lại trước khi sửa.
- Thẻ định dạng, placeholder, URL và một số chuỗi kỹ thuật được bỏ qua chỉ trong bản dùng để phân tích. Ô dài hơn 4.000 ký tự lấy 2.000 ký tự đầu và cuối, có ghi chú khi xem chi tiết. Nội dung gốc vẫn hiển thị đầy đủ và không bị sửa.
- Chỉ đối chiếu ngôn ngữ chính, không phân biệt biến thể vùng như `pt-BR`/`pt-PT`, `en-US`/`en-GB`. CSV lỗi được báo riêng, các file hợp lệ khác vẫn có kết quả. Chức năng không tự sửa CSV, thay đổi cặp nguồn–đích hoặc thực hiện import.

Phát triển từ mã nguồn cần **Python 3.12+** và `requirements.txt`; bản EXE đã bao gồm mô hình và thư viện. Lingua dùng giấy phép Apache-2.0; giấy phép được đóng gói trong metadata thư viện. Tham khảo [tài liệu Lingua](https://github.com/pemistahl/lingua-py).

## Unity Locale: Replace Import / Replace Export

Mở **Unity Locale — Replace Import / Export…** trong phần thao tác của ứng dụng.
Tính năng chạy trực tiếp trên file của máy, không cần đăng nhập Google hoặc thêm script vào Unity.

### CSV → Unity

1. Lưu asset trong Unity, thoát Play Mode, chọn **Replace Import** trong Import Localize.
2. Chọn các `locale_*.asset` cần cập nhật, hoặc chọn thư mục `Assets/AssetBundle/Localization`.
3. Chọn các CSV tương ứng, ví dụ `DG_Localization - export_en.csv`, `export_vi.csv`, `export_pt-BR.csv` đã tải từ Google Sheets.
4. Bấm **Xem trước** để kiểm tra file đích, số term thêm/xóa/thay thế và cảnh báo key trùng.
5. Bấm **Thực hiện Replace Import**. Quay lại Unity, dùng **Assets → Refresh / Ctrl+R** nếu chưa thấy dữ liệu mới.

Hai danh sách hiển thị tên file, đường dẫn và số hàng: **Nguồn** bên trái → **Nhận vào** bên phải. Hai file cùng hàng là một cặp chuyển dữ liệu.
Ứng dụng nhớ các file trong card CSV, danh sách asset, CSV import, CSV export và chế độ Unity đang dùng khi đóng cửa sổ/app. Lần sau mở lại sẽ khôi phục đúng thứ tự đã sắp xếp; **Bỏ chọn/Xóa hết** cũng được ghi nhớ. Unity Locale ưu tiên danh sách đã lưu, chỉ lấy CSV từ màn hình chính ở lần mở đầu tiên.
Các đường dẫn bị thiếu trong Unity Locale vẫn giữ nguyên hàng và có nhãn **[Thiếu file]**, tránh làm lệch cặp. CSV đích mới chưa được tạo vẫn được nhớ. CSV không còn đọc được ở màn hình chính được bỏ qua và báo trong nhật ký. Khôi phục danh sách không tự chạy import/export; cần **Xem trước** lại trước khi ghi.
Mỗi file chiếm một dòng: tên bên trái, vị trí bên phải (di chuột để xem đường dẫn đầy đủ). Ctrl/Shift để chọn nhiều file, Ctrl+A để chọn toàn bộ bên đang thao tác.
Kéo thả trong từng bên hoặc dùng thanh nút chung **Lên/Xuống/Bỏ chọn/Xóa hết**. Thanh này tác động lên bên đang chọn, có nhãn chỉ rõ Nguồn hoặc Nhận vào; khi chuyển bên, lựa chọn bên cũ được bỏ. **Xóa hết** chỉ dọn danh sách của bên đó, không xóa file trên máy. Hai bên cuộn cùng nhau để giữ các hàng thẳng nhau.
Mỗi CSV phải chứa đúng bộ ngôn ngữ của asset cùng hàng (`English`, `Vietnamese`, `Portuguese (Brazil) [pt-BR]`…). App báo lỗi đúng hàng nếu không khớp, không tự ghép sang asset khác.
Có thể chọn nhiều asset cùng ngôn ngữ và tự xếp CSV tương ứng. Số file hai bên phải bằng nhau, file đích không được trùng. Đổi thứ tự sẽ hủy kết quả xem trước cũ.
Phần xem trước hiển thị riêng nguồn → file nhận, lượng dữ liệu nguồn, đích trước/sau, và các cột màu **Thêm (xanh), Xóa (đỏ), Sửa (vàng), Giữ (xám)**. Khi nhập, nguồn tính theo dòng CSV và đích tính theo term; khi xuất thì ngược lại. Sửa chỉ tính key có nội dung dịch, loại hoặc mô tả khác trước, không tính mọi key đã tồn tại. Key trùng trong đích được báo riêng; dấu `—` cho biết không thể so sánh nội dung CSV cũ.
CSV chỉ có header, sai ngôn ngữ, trùng cột ngôn ngữ hoặc sai số cột sẽ bị chặn trước khi ghi.

Khi bấm **Thực hiện Replace Import/Export**, popup hiển thị trạng thái và tên file đang kiểm tra, sao lưu, chuẩn bị hoặc ghi. Thanh tiến trình tính theo số bước đã hoàn thành thực tế, không phải thời gian ước lượng; không có trì hoãn hay chạy thanh giả. Nếu tác vụ nhanh, tiến trình hoàn thành ngay. Popup giữ kết quả thành công/lỗi để đọc và có nút mở bản sao lưu. Khi đang ghi, popup không thể đóng; nếu gặp lỗi ghi hàng loạt, trạng thái khôi phục cũng được hiển thị.

### Unity → CSV

1. Chọn **Replace Export** và các asset cần xuất.
2. Bên nhận: **Chọn CSV nhận** để chọn file có sẵn hoặc **Thêm CSV mới** để đặt tên file mới. Có thể chọn thư mục, nhập tên bảng tính (mặc định `DG_Localization`) rồi bấm **Tạo danh sách CSV đích** để tạo nhanh các đường dẫn.
3. Kéo thả đổi thứ tự độc lập ở mỗi bên để ghép asset và CSV theo hàng. Đường dẫn đích đã tạo không tự thay đổi khi di chuyển nguồn; đổi thư mục/tên bảng tính cần bấm **Tạo danh sách CSV đích** lại.
4. Bấm **Xem trước**, sau đó **Thực hiện Replace Export**. Chọn/thêm/tạo danh sách chỉ chuẩn bị đường dẫn; file được ghi khi thực hiện Replace.

Ví dụ file đầu ra: `DG_Localization - upload_en.csv`. Có thể thêm các file này vào luồng upload nhiều sheet sẵn có của ứng dụng.
CSV được ghi UTF-8 có BOM với các cột `Key,Type,Desc,<ngôn ngữ>`. Hỗ trợ dấu phẩy, chấm phẩy và tab;
Import có chế độ tự nhận diện, Export mặc định dùng dấu phẩy. Export ghi đè toàn bộ file đích.

### Kiểm tra và xóa duplicate key trong Unity locale

Trong cửa sổ **Unity Locale**, chọn các asset rồi bấm **Kiểm tra duplicate key…**. Có thể chọn lại nhiều file ngay trong cửa sổ kiểm tra; chức năng này không cần CSV hoặc Google Sheets.
Kiểm tra duplicate cũng nhớ chính xác danh sách file lần trước. Khi chưa chọn asset ở cửa sổ Import/Export, app dùng danh sách duplicate đã lưu; chỉ quét lại toàn bộ thư mục đã lưu nếu chưa có danh sách file trước đó.

Thư mục asset được lưu chung với cài đặt Unity Locale khi chọn file hoặc **Chọn thư mục…**. Lần sau mở kiểm tra duplicate, nếu chưa chọn asset trong danh sách Import/Export, app tự nạp các `locale*.asset` trong thư mục đã lưu và kiểm tra ngay, kể cả sau khi mở lại ứng dụng. Thư mục hiện tại luôn được hiển thị để đối chiếu. Nếu thư mục đã bị chuyển/xóa hoặc không có asset, app thông báo để chọn lại.

- Kiểm tra key giống chính xác, phân biệt hoa/thường, riêng trong từng asset. Key giống nhau ở các file ngôn ngữ khác nhau không bị coi là duplicate.
- Bảng kết quả chỉ rõ file, key, số bản ghi và số bản dư sẽ xóa. Chỉ so sánh **Term (key)** và các chuỗi trong **Languages**; bỏ qua New/Flags, mô tả, loại term, Languages_Touch và các trường phụ. Key nằm ở tiêu đề; mỗi bản hiển thị nội dung theo tên ngôn ngữ, không dùng JSON.
- Nếu key và Languages giống nhau, tự giữ bản đầu (bao gồm metadata nguyên bản của nó), không hỏi từng key dù cờ New khác nhau. Nội dung ngôn ngữ được so sánh chính xác, kể cả khoảng trắng, rich text và xuống dòng; chữ “new” nằm trong bản dịch vẫn là nội dung cần so sánh.
- Luôn hiển thị **toàn bộ nội dung ngôn ngữ**, bao gồm mọi thẻ định dạng giống nhau; chỉ đoạn khác nhau có **nền vàng**, chỗ thiếu so với bản khác có dấu **[không có] trên nền xám**. So sánh với mọi phiên bản trong nhóm, theo từng ngôn ngữ. Khoảng trắng/xuống dòng/tab trong đoạn khác hiện thành `·`/`[xuống dòng]`/`[tab]`. Đây chỉ là cách hiển thị, không sửa nội dung file.
- Nếu khác nội dung, **bấm trực tiếp khung nội dung hoặc tiêu đề** để chọn bản giữ; app tự chuyển đến key tiếp theo chưa chọn, bỏ qua nhóm giống nhau và nhóm đã xử lý. Menu **Giữ lại** cũng tự chuyển sau khi chọn. Khi đã chọn hết, giữ nguyên key cuối và bật **Xóa duplicate**. Có thể bấm lại hàng cũ để xem hoặc đổi lựa chọn; bản đã chọn có viền xanh và nhãn **ĐANG GIỮ BẢN NÀY**. Chưa chọn đủ thì chưa thể xóa.
- Bấm **Xóa duplicate** để sao lưu và thực hiện. Kiểm tra hoặc đóng cửa sổ không làm thay đổi file. Chỉ xóa các đoạn YAML của bản ghi dư, giữ nguyên byte của bản được chọn và phần còn lại, BOM, xuống dòng, `.meta` và GUID.
- Asset thay đổi sau khi kiểm tra sẽ bị chặn; cần **Kiểm tra lại**. Sao lưu và khôi phục khi ghi lỗi dùng chung cơ chế dưới đây. Quay về Unity và Refresh sau khi hoàn tất.

### Quy tắc I2 và sao lưu

- Replace Import tạo lại `mTerms` và `mLanguages`: term không có trong CSV sẽ bị xóa. Các cờ dịch được tạo lại giống I2 Replace.
- Giữ nguyên YAML của các trường có giá trị không đổi (kể cả dấu nháy, xuống dòng và cách ngắt dòng dài); term chuyển vị trí theo CSV cũng giữ định dạng cũ. Chỉ ghi lại trường thay đổi hoặc term mới bằng YAML dạng Unity, tránh diff toàn bộ asset chỉ vì định dạng. Các cờ và mô tả vẫn được thay thế theo quy tắc I2, không giữ dữ liệu cũ nếu CSV yêu cầu thay đổi.
- Đối chiếu import tay phải dùng **cùng một CSV**: `export_*.csv` tải từ Sheets để nhập vào Unity; `upload_*.csv` xuất từ Unity có thể vẫn chứa nội dung cũ. Cách ngắt dòng dài của trường mới có thể khác Unity, nhưng giá trị chuỗi sau đọc YAML được giữ nguyên.
- Key trùng được gộp; ô dịch không rỗng ở dòng sau thắng. Ô rỗng không ghi đè; `-` xóa bản dịch.
- Hỗ trợ các dòng specialization như `[Touch]`, `[Controller]`, tag `[i2s_…]`, rich text, placeholder, dấu ngoặc kép và xuống dòng. Không trim nội dung bản dịch.
- Export theo `Spreadsheet_SortRows` và `Spreadsheet_SpecializationAsRows` trong asset. Giữ key trùng như I2; chuyển ký tự `\n` thành xuống dòng như exporter của Dicegeon.
- Chỉ thay hai trường dữ liệu locale; giữ nguyên phần còn lại của asset, GUID, file `.meta`, tham chiếu và cấu hình Google/BGM.
- Trước khi ghi, kiểm tra lại nội dung file so với lúc xem trước. File đã thay đổi phải được xem trước lại.
- File cũ được lưu ở `%APPDATA%/Import Localize/unity_backups/<thời điểm-id>/`. Nút **Mở bản sao lưu** mở thư mục này. `manifest.json` ghi đường dẫn gốc và file `.bak` tương ứng; để khôi phục, đóng tác vụ đang chỉnh asset rồi chép nội dung `.bak` đè vào đúng đường dẫn gốc. `backup: null` nghĩa là file được tạo mới.
- Nếu ghi hàng loạt thất bại, ứng dụng cố khôi phục các file đã ghi và báo đường dẫn sao lưu. File bị ứng dụng khác sửa tiếp sẽ không bị tự động ghi đè khi khôi phục.

Phạm vi hỗ trợ: `LanguageSourceAsset` dạng Unity YAML text, cấu hình enum I2 của Dicegeon có TextMeshPro.
Không áp dụng cho Unity Localization Package, asset nhị phân hoặc các bảng mã term như `runtime_locale_term.asset`.
Không chạy đồng thời import với thao tác lưu locale trong Unity. Sau khi import vẫn cần quy trình build AssetBundle của dự án để đưa bản dịch vào bản game phát hành.

Mã xử lý: `src/import_localize/services/unity_locale_service.py`; giao diện: `src/import_localize/ui/unity_locale_dialog.py`.
Thư viện bổ sung: `PyYAML` trong `requirements.txt` (được đóng gói tự động khi build bằng `build_app.py`).
