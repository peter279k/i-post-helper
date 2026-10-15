"""
ezpost_pdf_download.py
從 /Mail/MailShipCompleted?mail_Type=IBox 的完成頁下載託運單 PDF。

邏輯：
    1. 權杖：完成頁 <main> 底下 name="__RequestVerificationToken" 的 input 值
    2. 參數：完成頁 a#Id-MailShipCompletedPrint 的 data-funparaval 屬性，
       以逗號分隔，例如：iBox,mail_id,108626079,28sqfRYZVL8witRu6cCZpni++ic=,/OrderGenerator/GetPDF
           前 4 個依序為 string_mail_type、data_type、mail_id、check_code
           最後一個為請求位址（/OrderGenerator/GetPDF）
    3. 組成 string_mail_type、data_type、mail_id、check_code、__RequestVerificationToken
       以 application/x-www-form-urlencoded; charset=UTF-8 POST 到請求位址
    4. 回應為 PDF，以 binary 方式存檔

使用方式（由主程式呼叫）：
    from ezpost_pdf_download import download_shipping_pdf
    pdf_path = download_shipping_pdf(session, completed_html, completed_url, saver=saver)
"""
import os
import re
from urllib.parse import unquote, urljoin, urlencode, urlparse

from bs4 import BeautifulSoup

TOKEN_NAME = "__RequestVerificationToken"
PRINT_LINK_ID = "Id-MailShipCompletedPrint"
PARAM_ATTR = "data-funparaval"
PARAM_NAMES = ["string_mail_type", "data_type", "mail_id", "check_code"]

# 對照成功的 cURL：/OrderGenerator/GetPDF（jQuery $.ajax）
AJAX_HEADERS = {
    "Accept": "*/*",
    "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
    "Sec-Fetch-Dest": "empty",
    "Sec-Fetch-Mode": "cors",
    "Sec-Fetch-Site": "same-origin",
    "X-Requested-With": "XMLHttpRequest",
}


class EzpostPdfError(RuntimeError):
    """託運單 PDF 下載失敗。"""


def parse_completed_page(completed_html, completed_url):
    """
    解析完成頁，回傳 (請求網址, 欄位 list[(name, value)])。
    欄位順序：string_mail_type、data_type、mail_id、check_code、__RequestVerificationToken
    """
    soup = BeautifulSoup(completed_html or "", "html.parser")

    # 1. <main> 底下的 __RequestVerificationToken
    tok = soup.select_one(f'main input[name="{TOKEN_NAME}"]')
    if tok is None or not tok.get("value"):
        raise LookupError(f"完成頁 <main> 底下找不到 {TOKEN_NAME}")

    # 2. a#Id-MailShipCompletedPrint 的 data-funparaval
    link = soup.find("a", id=PRINT_LINK_ID)
    if link is None or not link.get(PARAM_ATTR):
        raise LookupError(f"完成頁找不到 a#{PRINT_LINK_ID} 的 {PARAM_ATTR} 屬性")
    parts = [p.strip() for p in link[PARAM_ATTR].split(",")]
    if len(parts) != len(PARAM_NAMES) + 1:
        raise LookupError(
            f"{PARAM_ATTR} 格式不符，預期 {len(PARAM_NAMES) + 1} 段（逗號分隔），實際：{link[PARAM_ATTR]!r}"
        )

    # 3. 前 4 段為欄位值，最後一段為請求位址
    *values, path = parts
    fields = list(zip(PARAM_NAMES, values)) + [(TOKEN_NAME, tok["value"])]
    return urljoin(completed_url, path), fields


def _filename_from_disposition(disposition):
    """從 Content-Disposition 取檔名（支援 filename*=UTF-8''...）。"""
    if not disposition:
        return None
    m = re.search(r"filename\*\s*=\s*[^']*''([^;]+)", disposition, re.I)
    if m:
        return unquote(m.group(1).strip().strip('"'))
    m = re.search(r'filename\s*=\s*"?([^";]+)"?', disposition, re.I)
    return m.group(1).strip() if m else None


def download_shipping_pdf(session, completed_html, completed_url, saver=None,
                          out_path=None, timeout=30, verbose=True):
    """
    下載託運單 PDF 並以 binary 存檔，回傳 PDF 檔案路徑。

    session        : 沿用整個寄件流程的 requests.Session（Cookie 需一致）
    completed_html : MailShipCompleted 的回應 HTML
    completed_url  : MailShipCompleted 的請求網址（作為 Referer）
    saver          : ezpost_mail_edit.ResponseSaver，給了就存到同一個回應目錄
    out_path       : 另外指定 PDF 存檔路徑（可選）
    """
    log = print if verbose else (lambda *a, **k: None)
    url, fields = parse_completed_page(completed_html, completed_url)
    mail_id = dict(fields).get("mail_id", "")

    log(f"\n=== 下載託運單：POST {url}")
    for k, v in fields:
        log(f"    {k} = {v}")

    u = urlparse(completed_url)
    headers = {**AJAX_HEADERS, "Origin": f"{u.scheme}://{u.netloc}", "Referer": completed_url}
    resp = session.post(url, data=urlencode(fields), headers=headers, timeout=timeout)

    data = resp.content   # binary
    ctype = resp.headers.get("Content-Type", "")
    log(f"    回應：{resp.status_code}  {ctype}  {len(data):,} bytes")

    is_pdf = data[:5] == b"%PDF-"
    if resp.status_code >= 400 or not is_pdf:
        # 不是 PDF：把回應原樣存下來方便檢查，再報錯
        if saver is not None:
            saver.save_bytes(data, f"GetPDF_{mail_id}_error", "html" if b"<" in data[:200] else "txt")
        raise EzpostPdfError(
            f"託運單下載失敗（HTTP {resp.status_code}，Content-Type={ctype}），回應不是 PDF：\n"
            f"{data[:300].decode('utf-8', 'replace')}"
        )

    paths = []
    if saver is not None:
        paths.append(saver.save_bytes(data, f"GetPDF_{mail_id}", "pdf"))
    if out_path:
        os.makedirs(os.path.dirname(os.path.abspath(out_path)), exist_ok=True)
        with open(out_path, "wb") as f:
            f.write(data)
        paths.append(out_path)
        log(f"    已存檔：{out_path}")
    if not paths:
        name = _filename_from_disposition(resp.headers.get("Content-Disposition")) or f"{mail_id or 'shipping'}.pdf"
        name = re.sub(r'[\\/:*?"<>|]+', "_", name)
        with open(name, "wb") as f:
            f.write(data)
        paths.append(name)
        log(f"    已存檔：{name}")
    return paths[0]
