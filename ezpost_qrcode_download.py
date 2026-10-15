"""
ezpost_qrcode_download.py
從 /Mail/MailShipCompleted?mail_Type=IBox 的完成頁取出寄件 QR Code 圖片並存檔。

邏輯：
    1. 找完成頁的 img#QRcodeImg；沒有 id 時，改找 src 以「data:image/」開頭的 img
    2. src 為 data URI，例如「data:image/jpg;base64,iVBORw0KGgo...」，取逗號後的 Base64 解碼
    3. 依解碼後的檔頭判斷實際格式（PNG / JPEG / GIF / WebP）決定副檔名
       （網站宣告為 image/jpg，但實際內容是 PNG）
    4. 以 binary 方式存檔；不需要另外發送請求

使用方式（由主程式呼叫）：
    from ezpost_qrcode_download import save_qrcode
    qr_path = save_qrcode(completed_html, saver=saver)
"""
import base64
import binascii
import os
import re
from urllib.parse import unquote

from bs4 import BeautifulSoup

QR_IMG_ID = "QRcodeImg"
DATA_URI_RE = re.compile(r"^data:(?P<mime>[\w/+.-]*)(?P<params>(?:;[^,]*)?),(?P<data>.*)$", re.S | re.I)

# 檔頭 → (副檔名, MIME)
SIGNATURES = [
    (b"\x89PNG\r\n\x1a\n", ("png", "image/png")),
    (b"\xff\xd8\xff", ("jpg", "image/jpeg")),
    (b"GIF87a", ("gif", "image/gif")),
    (b"GIF89a", ("gif", "image/gif")),
]


class EzpostQrError(RuntimeError):
    """寄件 QR Code 取出或解碼失敗。"""


def detect_image_type(data):
    """依檔頭判斷圖片格式，回傳 (副檔名, MIME)；無法辨識回傳 (None, None)。"""
    for sig, info in SIGNATURES:
        if data.startswith(sig):
            return info
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "webp", "image/webp"
    return None, None


def decode_data_uri(src):
    """解碼 data URI，回傳 (bytes, 宣告的 MIME)。"""
    m = DATA_URI_RE.match((src or "").strip())
    if not m:
        raise EzpostQrError(f"src 不是 data URI：{(src or '')[:60]!r}")
    declared = m.group("mime") or "text/plain"
    payload = m.group("data")
    if ";base64" in m.group("params").lower():
        b64 = re.sub(r"\s+", "", unquote(payload))
        b64 += "=" * (-len(b64) % 4)          # 補齊 padding
        try:
            data = base64.b64decode(b64, validate=True)
        except (binascii.Error, ValueError) as e:
            raise EzpostQrError(f"QR Code 的 Base64 內容無法解碼：{e}")
    else:
        data = unquote(payload).encode("latin-1")
    return data, declared


def find_qrcode_img(completed_html):
    """找完成頁的 QR Code img 標籤。"""
    soup = BeautifulSoup(completed_html or "", "html.parser")
    img = soup.find("img", id=QR_IMG_ID)
    if img is None or not (img.get("src") or "").lower().startswith("data:image/"):
        img = soup.find("img", src=lambda s: bool(s) and s.strip().lower().startswith("data:image/"))
    if img is None:
        raise LookupError(f"完成頁找不到 img#{QR_IMG_ID}（src 以 data:image/ 開頭）")
    return img, soup


def mail_number(soup):
    """取完成頁表格中的「郵件編號」，找不到回傳空字串。"""
    th = soup.find("th", string=lambda s: s and "郵件編號" in s)
    td = th.find_next("td") if th else None
    return td.get_text(strip=True) if td else ""


def save_qrcode(completed_html, saver=None, out_path=None, verbose=True):
    """
    取出完成頁的寄件 QR Code 並以 binary 存檔，回傳圖片檔案路徑。

    completed_html : MailShipCompleted 的回應 HTML
    saver          : ezpost_mail_edit.ResponseSaver，給了就存到同一個回應目錄
    out_path       : 另外指定圖片存檔路徑（可選）；副檔名若和實際格式不符會印出提醒
    """
    log = print if verbose else (lambda *a, **k: None)
    img, soup = find_qrcode_img(completed_html)
    data, declared = decode_data_uri(img["src"])

    ext, mime = detect_image_type(data)
    if ext is None:
        raise EzpostQrError(f"QR Code 解碼後不是可辨識的圖片格式（宣告為 {declared}，檔頭 {data[:8]!r}）")

    number = mail_number(soup)
    log("\n=== 寄件 QR Code")
    log(f"    郵件編號：{number or '（未找到）'}")
    declared_norm = {"image/jpg": "image/jpeg"}.get(declared.lower(), declared.lower())
    note = "" if declared_norm == mime else f"（網頁宣告為 {declared}，實際為 {mime}）"
    log(f"    格式：{mime}，{len(data):,} bytes {note}")

    name = f"QRCode_{number}" if number else "QRCode"
    paths = []
    if saver is not None:
        paths.append(saver.save_bytes(data, name, ext))
    if out_path:
        out_ext = os.path.splitext(out_path)[1].lower().lstrip(".")
        if {"jpeg": "jpg"}.get(out_ext, out_ext) != ext:
            log(f"    [提醒] {out_path} 的副檔名與實際格式 .{ext} 不符")
        os.makedirs(os.path.dirname(os.path.abspath(out_path)), exist_ok=True)
        with open(out_path, "wb") as f:
            f.write(data)
        paths.append(out_path)
        log(f"    已存檔：{out_path}")
    if not paths:
        path = re.sub(r'[\\/:*?"<>|]+', "_", f"{name}.{ext}")
        with open(path, "wb") as f:
            f.write(data)
        paths.append(path)
        log(f"    已存檔：{path}")
    return paths[0]
