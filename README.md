# EZPost i-Box Shipping Automation

Using Python (`requests` + `BeautifulSoup`) to execute the "i-Box shipping" (i 郵箱寄件) flow on Chunghwa Post's EZPost website automatically: fill in the sender, recipient and contents, create the shipping order, save the shipping QR Code image, and download the shipping label PDF.

> ⚠️ A successful run **actually creates a shipping order**. Always pass real data with `--data`. Without it, the program uses its built-in sample data (王小明 / 陳小華).

## Files

| File | Purpose |
|---|---|
| `ezpost_form_submit.py` | Main program (command-line entry point); runs the whole flow |
| `ezpost_mail_edit.py` | Module: sender / recipient / contents checks, confirm details, complete shipment |
| `ezpost_pdf_download.py` | Module: downloads the shipping label PDF from the completion page |
| `ezpost_qrcode_download.py` | Module: extracts the shipping QR Code image from the completion page |
| `mail.json` | Example shipping data |
| `mail_json_field.md` | Description and allowed values for every `mail.json` field (in Traditional Chinese) |

The four `.py` files must be in the same folder.

## Requirements

We suggest using the Python 3.10+.

## Installation

```bash
python3 -m venv venv
source venv/bin/activate
pip install requests beautifulsoup4
```

## Usage

```bash
# Ship using the data in mail.json, save the QR Code and download the label PDF (recommended)
python ezpost_form_submit.py --data mail.json

# Choose the response output folder (default: responses/<date_time>/)
python ezpost_form_submit.py --data mail.json --out-dir out

# Also save the label PDF to a specific path
python ezpost_form_submit.py --data mail.json --pdf-out label.pdf

# Also save the QR Code image to a specific path
python ezpost_form_submit.py --data mail.json --qr-out qrcode.png

# Create the shipping order only, without downloading the PDF
python ezpost_form_submit.py --data mail.json --no-pdf

# Create the shipping order only, without saving the QR Code
python ezpost_form_submit.py --data mail.json --no-qr

# Without --data: uses the built-in DEFAULT_* sample data (testing only)
python ezpost_form_submit.py
```

### Command-line options

| Option | Description |
|---|---|
| `--data <file>` | JSON file in the form `{"sender":{...}, "receiver":{...}, "content":{...}}` |
| `--out-dir <folder>` | Response output folder; default `responses/<date_time>/` |
| `--pdf-out <file>` | Extra path to save the label PDF to (by default it is saved only in the response folder) |
| `--no-pdf` | Do not download the label PDF |
| `--qr-out <file>` | Extra path to save the QR Code image to (by default it is saved only in the response folder). The image is PNG, so use a `.png` extension |
| `--no-qr` | Do not save the QR Code image |

Progress messages and errors are printed in Chinese.

### Flows

| Step | Request Action | Page Name | Comment |
|---|---|---|---|
| 1 | `GET /Mail/SingleShipRule` | Terms page | — |
| 2 | `POST /Mail/IBoxMailEdit` | Accept the terms and open the create-order page | `form#form-Upload` on the terms page |
| 3 | `POST /Mail/CheckMailSender` | Sender check (AJAX) | First token on the create-order page |
| 4 | `POST /Mail/CheckMailReceiver` | Recipient check (AJAX) | Same as above |
| 5 | `POST /Mail/CheckMailContents` | Contents check (AJAX) | Same as above |
| 6 | `POST /Mail/MailInfoDetailsCheck` | Confirm-details page | `form#form-DetailsCheck` on the create-order page |
| 7 | `POST /Mail/CheckSendMailInfo` | Shipping data check (AJAX) | Form with `action=/Mail/MailInfoDetailsCheck` (looked up on the confirm-details page first, then the create-order page) |
| 8 | `POST /Mail/MailShipCompleted?mail_Type=IBox` | Complete the shipment | Form with `action=/Mail/MailShipCompleted?mail_Type=IBox` on the confirm-details page |
| 9 | (no request) | Save the QR Code image | Decoded from `img#QRcodeImg` on the completion page |
| 10 | `POST /OrderGenerator/GetPDF` | Download the label PDF (AJAX) | First token under `<main>` on the completion page |

- One `requests.Session` is used throughout, so the `__RequestVerificationToken` and `ASP.NET_SessionId` cookies are sent automatically. Tokens must match the cookies, so never reuse old tokens or take them from saved pages.
- The body of steps 3–5 is `Base64Data` plus `__RequestVerificationToken`. `Base64Data` is `base64(UTF-8(JSON.stringify(MailObj)))`, the same as the page's JS `btoa(unescape(encodeURIComponent(...)))`. `MailObj` contains `MailId`, `DATA_SOURCE`, `MAIL_STATUS`, `Status`, and every field of the three forms; forms not yet filled in use their defaults.
- Steps 3–5 and 7 return JSON. If `success` is `false`, the program stops and shows the server's message.
- Step 9 sends no request: the QR Code is the `src` of `img#QRcodeImg` on the completion page, a `data:image/...;base64,` data URI that is decoded locally. The page declares it as `image/jpg`, but the content is actually PNG, so the file extension is chosen from the decoded bytes. The QR Code encodes the mail number (without dashes) and the verification code, e.g. `62618190010870220001;5678`.
- The parameters for step 10 come from the `data-funparaval` attribute of `a#Id-MailShipCompletedPrint` on the completion page (comma-separated: `string_mail_type, data_type, mail_id, check_code, request URL`).
- AJAX requests send `X-Requested-With: XMLHttpRequest` and `Sec-Fetch-Mode: cors`. Page-navigation requests (steps 6 and 8) send `Sec-Fetch-Mode: navigate` and related browser headers. All headers match the cURL commands captured from a real browser.

## Shipping data (mail.json)

The file has three sections. Keys are the form field `name` (the field `id` is also accepted), and all values are strings:

```json
{
  "sender":   { "MAIL_SNAME": "王小明", "MAIL_SPHONE": "0912345678", "MAIL_SADD_CITY": "臺北市", "...": "..." },
  "receiver": { "MAIL_RNAME": "陳小華", "MAIL_RPHONE": "0987654321", "MAIL_RADD_TYPE": "001", "...": "..." },
  "content":  { "MAIL_CONTENTS_NO": "6", "MAIL_PACKAGE_SIZE": "00G", "MAIL_UNDELIVER_OPTNO": "001", "...": "..." }
}
```

- A section you provide **replaces the built-in sample section entirely**; only missing sections fall back to the sample data. Always provide all three.
- Fields you leave out use the page's default value. Hidden fields (`MAIL_TYPE`, `MailId`, `DATA_SOURCE`, etc.) are filled in from the page automatically.
- Keys that don't exist in the form are ignored with a warning.
- Postal codes (`*_ZIP`) are filled in automatically by the website but not by this program, so set them yourself. City names must use 臺 rather than 台 (e.g. `臺北市`).
- See `mail.json` for a complete example, and `mail_json_field.md` for each field's required conditions and allowed values.

### Common field values

| Field | Values |
|---|---|
| `MAIL_RADD_TYPE` (recipient address type) | `001` regular address, `002` i-Box, `003` P.O. box, `004` special P.O. box, `005` poste restante |
| `MAIL_CONTENTS_NO` (item type) | `1` blank documents, `2` food, `3` parts, `4` samples, `5` gifts, `6` books, `7` clothing, `8` medicine, `A` daily goods, `B` other (also set `MAIL_CONTENTS`) |
| `MAIL_PACKAGE_SIZE` (package size) | `00F` large (34×24×45 cm), `00G` medium (34×17×45 cm), `00H` small (14×17×45 cm) |
| `MAIL_UNDELIVER_OPTNO` (if undeliverable) | `001` return to sender (return postage charged), `002` discard |
| `MAIL_RETURN_TYPE` (return address) | `001` sender's address, `004` original sending i-Box, `003` other address (also set the `MAIL_RETURN_*` fields) |

## Output

Each run saves every step's response, in order, to the response folder.

The sample folder structure is as follows:

```
responses/20261015_154304/
├── 01_SingleShipRule.html
├── 02_IBoxMailEdit.html
├── 03_CheckMailSender.json
├── 04_CheckMailReceiver.json
├── 05_CheckMailContents.json
├── 06_MailInfoDetailsCheck.html
├── 07_CheckSendMailInfo.json
├── 08_MailShipCompleted.html
├── 09_QRCode_<mail number>.png    ← shipping QR Code (saved as binary)
└── 10_GetPDF_<mail_id>.pdf        ← shipping label (saved as binary)
```

- The file extension is chosen from the `Content-Type`; JSON is pretty-printed. When an HTML page is saved, the program shows how many `__RequestVerificationToken` fields it contains.
- If a step fails, its response is saved before the program stops, and the list of saved files is printed.
- The QR Code is saved before the PDF is downloaded, so it is kept even if the PDF download fails. If the QR Code can't be saved, the program prints a warning and continues.
- If the PDF download returns something other than a PDF (the file doesn't start with `%PDF-`), the raw response is saved as `10_GetPDF_<mail_id>_error.html` and an error is raised.
- The program prints the completion page HTML and the paths of the QR Code image and label PDF.

## Using the modules in your own code

```python
import requests
from ezpost_pdf_download import EzpostPdfError, download_shipping_pdf
from ezpost_qrcode_download import EzpostQrError, save_qrcode
from ezpost_mail_edit import EzpostMailEditor, EzpostSubmitError, ResponseSaver


session = requests.Session()            # First GET the terms page and submit it to obtain the create-order page
saver = ResponseSaver("responses/run1") # Response output folder

editor = EzpostMailEditor(session, edit_page_html, edit_page_url, saver=saver)
completed_html = editor.run(sender_data, receiver_data, content_data)

qr_path = save_qrcode(
  completed_html,
  saver=saver, out_path="qrcode.png"
)

pdf_path = download_shipping_pdf(
  session, completed_html, editor.completed_url,
  saver=saver, out_path="label.pdf"
)
```

### ezpost_mail_edit

| Name | Description |
|---|---|
| `EzpostMailEditor(session, page_html, page_url, timeout=15, verbose=True, saver=None)` | `session`: the Session used to open the create-order page; `page_html` / `page_url`: HTML and URL of `/Mail/IBoxMailEdit`; if `saver` is omitted, `responses/<time>/` is created automatically |
| `.run(sender_data, receiver_data, content_data)` | Runs steps 3–8 in order and returns the completion page HTML |
| `.check_sender(data)` / `.check_receiver(data)` / `.check_content(data)` | Runs step 3 / 4 / 5 on its own and returns the server's JSON result |
| `.submit_details_check()` | Step 6; returns the confirm-details page HTML |
| `.check_send_mail_info(details_html)` | Step 7 |
| `.submit_ship_completed(details_html)` | Step 8; returns the completion page HTML |
| `.build_mail_obj(step)` | Builds the `MailObj` for a step (`"sender"` / `"receiver"` / `"content"`), useful for inspecting what will be sent |
| `.completed_url` | Request URL of step 8 (used as the Referer when downloading the PDF) |
| `collect_fields(form, data)` | Mimics jQuery `serializeObject`: collects form fields keyed by `name` |
| `encode_mail_obj(mail_obj)` | Encodes a `MailObj` into `Base64Data` |
| `ResponseSaver(out_dir=None, verbose=True)` | Saves responses; `.save(resp, name)` saves text, `.save_bytes(data, name, ext)` saves binary, `.saved` lists the saved files |
| `EzpostSubmitError` | HTTP error, or the server returned `success: false` |

### ezpost_pdf_download

| Name | Description |
|---|---|
| `download_shipping_pdf(session, completed_html, completed_url, saver=None, out_path=None, timeout=30, verbose=True)` | Downloads the label PDF, saves it as binary, and returns its path. With `saver`, it is saved in the same response folder; `out_path` saves an extra copy; with neither, it is saved in the current folder |
| `parse_completed_page(completed_html, completed_url)` | Parses the completion page and returns `(request URL, [(field, value), ...])` |
| `EzpostPdfError` | The download failed or the response is not a PDF |

### ezpost_qrcode_download

| Name | Description |
|---|---|
| `save_qrcode(completed_html, saver=None, out_path=None, verbose=True)` | Extracts the QR Code from the completion page, saves it as binary, and returns its path. No request is sent. With `saver`, it is saved in the same response folder; `out_path` saves an extra copy (a warning is printed if its extension doesn't match the real format); with neither, it is saved in the current folder |
| `find_qrcode_img(completed_html)` | Finds `img#QRcodeImg` (falls back to any `img` whose `src` starts with `data:image/`) |
| `decode_data_uri(src)` | Decodes a data URI and returns `(bytes, declared MIME type)` |
| `detect_image_type(data)` | Detects PNG / JPEG / GIF / WebP from the file signature and returns `(extension, MIME type)` |
| `EzpostQrError` | The QR Code could not be decoded or is not a recognizable image |

## Limitations

- When the recipient address type is i-Box (`MAIL_RADD_TYPE` = `002`), `MAIL_RADD_IBOX_ADMID`, `MAIL_RADD_IBOX_ADMZip` and `MAIL_RADD_OTHER002` come from the website's i-Box picker. The program can't look these up yet, so get them from your browser's developer tools and fill them in yourself.
- The sender address supports only regular addresses (`001`).
- If the website changes (field names, form actions, JS logic), the program may need updating. Compare the saved responses in the response folder to find what changed.
