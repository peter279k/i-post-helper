# mail.json 欄位說明

執行：`python ezpost_form_submit.py --data mail.json`

- 檔案分成 `sender`（寄件人）、`receiver`（收件人）、`content`（內裝物品）三段，每段的 key 是表單欄位的 name，值一律用字串。
- 沒寫的欄位會用頁面上的預設值。隱藏欄位（`MAIL_TYPE`、`MailId`、`DATA_SOURCE`、`MAIL_WIDTH` 等）由程式從頁面帶入，不需要寫。
- 寫了表單裡沒有的 key，程式會印警告並忽略。
- `--data` 讀到的段落會**整段取代**程式內建的 `DEFAULT_*`；缺少的段落才用內建範例資料。三段都要寫，避免混用到範例資料。

欄位內容參考自 `02_IBoxMailEdit.html` 的實際表單。「必填」欄位的條件會依地址類型等選項而定。

## sender（寄件人）

| 欄位 | 說明 | 必填 | 允許值／限制 |
|---|---|---|---|
| `MAIL_SNAME` | 寄件人姓名 | 是 | 最多 15 字 |
| `MAIL_SPHONE` | 聯絡電話 | 是 | 最多 18 字；可用 `+`、數字、空白、`-`、`()`、`p`、`x` |
| `MAIL_SADD_TYPE` | 地址類型 | — | 只有 `001` 一般地址 |
| `MAIL_SADD_CITY` | 縣市 | 是 | 例：`臺北市`（用「臺」不是「台」） |
| `MAIL_SADD_AREA` | 鄉鎮市區 | 是 | 例：`中正區`。網頁用 JS 動態載入，需和縣市相符 |
| `MAIL_SADD_ZIP` | 郵遞區號 | 建議 | 網頁依區自動帶入，程式不會自動算，請自己填（例：`100`） |
| `MAIL_SADD_ROAD` | 路名、鄉道村里 | 建議 | 例：`忠孝西路一段` |
| `MAIL_SADD_OTHER` | 巷弄、號碼、樓層 | 是 | 例：`1號`、`23號12樓` |
| `MAIL_SEMAIL` | 電子信箱 | 否 | 最多 50 字 |

## receiver（收件人）

| 欄位 | 說明 | 必填 | 允許值／限制 |
|---|---|---|---|
| `MAIL_RNAME` | 收件人姓名 | 是 | 最多 15 字 |
| `MAIL_RPHONE` | 聯絡電話 | 是 | 最多 18 字；**i 郵箱收件須填手機** |
| `MAIL_RADD_TYPE` | 地址類型 | 是 | `001` 一般地址、`002` i郵箱、`003` 郵政信箱、`004` 特種郵政信箱、`005` 存局候領 |
| `MAIL_RADD_CITY` | 縣市 | 類型 001/003/004/005 時 | 同寄件人 |
| `MAIL_RADD_AREA` | 鄉鎮市區 | 類型 001/003/004/005 時 | 同寄件人 |
| `MAIL_RADD_ZIP` | 郵遞區號 | 建議 | 請自己填 |
| `MAIL_RADD_ROAD` | 路名、鄉道村里 | 建議 | |
| `MAIL_RADD_OTHER` | 巷弄、號碼、樓層 | 類型 001/003/004/005 時 | 最多 50 字，不可全為數字 |
| `MAIL_RADD_OTHER002` | i 郵箱地址 | 類型 002 時 | 網頁是從 i 郵箱清單選取，見下方說明 |
| `MAIL_RADD_OTHER003` | 郵政信箱 | 類型 003 時 | 例：`臺北北門郵局第10號信箱` |
| `MAIL_RADD_OTHER004` | 特種郵政信箱 | 類型 004 時 | 例：`郵政90277號信箱` |
| `MAIL_RADD_OTHER005` | 存局候領 | 類型 005 時 | 例：`臺北北門郵局存局候領` |

## content（內裝物品）

| 欄位 | 說明 | 必填 | 允許值／限制 |
|---|---|---|---|
| `MAIL_CONTENTS_NO` | 物品種類 | 是 | `1` 空白文件、`2` 食品、`3` 零件、`4` 貨樣、`5` 禮品、`6` 書籍、`7` 衣物、`8` 藥品、`A` 日用品、`B` 其他 |
| `MAIL_CONTENTS` | 物品描述 | 種類為 `B` 時 | 簡述內裝物品 |
| `MAIL_PACKAGE_SIZE` | 包材尺寸 | 是 | `00F` 大（34×24×45 cm）、`00G` 中（34×17×45 cm）、`00H` 小（14×17×45 cm） |
| `MAIL_COMMENT` | 郵件備註 | 否 | 最多 50 字 |
| `MAIL_UNDELIVER_OPTNO` | 無法投遞處理方式 | 是 | `001` 退回寄件人（另付退回費）、`002` 拋棄 |
| `MAIL_RETURN_TYPE` | 退件地址 | `001` 退回時 | `001` 寄件人地址、`004` 原寄件 i 郵箱、`003` 其他地址 |
| `MAIL_RETURN_CITY` | 退件縣市 | 退件地址 `003` 時 | |
| `MAIL_RETURN_AREA` | 退件鄉鎮市區 | 退件地址 `003` 時 | |
| `MAIL_RETURN_ZIP` | 退件郵遞區號 | 退件地址 `003` 時 | 最多 6 字 |
| `MAIL_RETURN_ROAD` | 退件路名 | 退件地址 `003` 時 | 最多 20 字 |
| `MAIL_RETURN_OTHER` | 退件巷弄、號碼、樓層 | 退件地址 `003` 時 | 最多 50 字 |

## 變化範例

只列出要改的段落，其餘同 `mail.json`。

**退件寄到其他地址**（content 段）：

```json
"MAIL_UNDELIVER_OPTNO": "001",
"MAIL_RETURN_TYPE": "003",
"MAIL_RETURN_CITY": "臺中市",
"MAIL_RETURN_AREA": "西屯區",
"MAIL_RETURN_ZIP": "407",
"MAIL_RETURN_ROAD": "臺灣大道三段",
"MAIL_RETURN_OTHER": "99號"
```

**收件人為郵政信箱**（receiver 段）：

```json
"MAIL_RADD_TYPE": "003",
"MAIL_RADD_CITY": "臺北市",
"MAIL_RADD_AREA": "中正區",
"MAIL_RADD_ZIP": "100",
"MAIL_RADD_OTHER003": "臺北北門郵局第10號信箱"
```

**物品種類為其他**（content 段）：

```json
"MAIL_CONTENTS_NO": "B",
"MAIL_CONTENTS": "手工皂"
```

## 收件人為 i 郵箱（`MAIL_RADD_TYPE` = `002`）

網頁上 i 郵箱地址是從清單選取的，選取後會同時填入三個欄位：

- `MAIL_RADD_IBOX_ADMID`：i 郵箱代號
- `MAIL_RADD_IBOX_ADMZip`：i 郵箱郵遞區號
- `MAIL_RADD_OTHER002`：i 郵箱地址文字

這三個值的實際格式還沒有看過成功的範例，程式也還沒做查詢 i 郵箱清單的功能。要寄到 i 郵箱，請先在瀏覽器用開發者工具看一次 `CheckMailReceiver` 送出的內容，再把這三個值照抄進 receiver 段。

`mail.json` 刻意沒有寫 `MAIL_RADD_IBOX_ADMZip`：頁面上它的預設值是 `{ class = form-control }`，瀏覽器也照樣送出，寫成空字串反而會不一致。
