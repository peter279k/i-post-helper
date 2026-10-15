"""
ezpost_form_submit.py  主程式

1. GET /Mail/SingleShipRule，解析 form 並送出（同意條款 → 進入建立託運單頁）
2. 呼叫 ezpost_mail_edit 模組：依序呼叫 CheckMailSender / CheckMailReceiver /
   CheckMailContents（Base64Data + __RequestVerificationToken），送出確認明細，
   最後 POST /Mail/MailShipCompleted?mail_Type=IBox
3. 呼叫 ezpost_pdf_download 模組，從完成頁下載託運單 PDF（/OrderGenerator/GetPDF）
4. 輸出完成頁 HTML；每個步驟的回應都存到 responses/<時間>/（可用 --out-dir 指定）

需求套件：pip install requests beautifulsoup4

用法：
    python ezpost_form_submit.py                  # 使用程式內的 DEFAULT_* 資料
    python ezpost_form_submit.py --data mail.json # 從 JSON 讀取 {"sender":{}, "receiver":{}, "content":{}}
    python ezpost_form_submit.py --out-dir out    # 回應存檔目錄
    python ezpost_form_submit.py --pdf-out a.pdf  # 託運單 PDF 另存路徑
    python ezpost_form_submit.py --no-pdf         # 不下載託運單
"""
import argparse
import json
from urllib.parse import urljoin, urlencode

import requests
from bs4 import BeautifulSoup

from ezpost_mail_edit import EzpostMailEditor, EzpostSubmitError, ResponseSaver
from ezpost_pdf_download import EzpostPdfError, download_shipping_pdf

RULE_URL = "https://ezpost.post.gov.tw/Mail/SingleShipRule"

# 所有請求共用的瀏覽器標頭（對照成功的 cURL）
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/155.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "zh-TW,zh;q=0.9,en-US;q=0.8,en;q=0.7,ja;q=0.6",
    "Connection": "keep-alive",
    "sec-ch-ua": '"Google Chrome";v="155", "Chromium";v="155", "Not(A:Brand";v="24"',
    "sec-ch-ua-mobile": "?0",
    "sec-ch-ua-platform": '"Windows"',
}

# ---------------------------------------------------------------------------
# 要填入表單的資料（key 用欄位 name，也接受 id）— 以下為範例，請改成實際資料
# ---------------------------------------------------------------------------
DEFAULT_SENDER = {
    "MAIL_SNAME": "王小明",
    "MAIL_SPHONE": "0912345678",
    "MAIL_SADD_TYPE": "001",          # 001 = 一般地址
    "MAIL_SADD_CITY": "臺北市",
    "MAIL_SADD_AREA": "中正區",
    "MAIL_SADD_ZIP": "100",
    "MAIL_SADD_ROAD": "忠孝西路一段",
    "MAIL_SADD_OTHER": "1號",
    "MAIL_SEMAIL": "sender@example.com",
}

DEFAULT_RECEIVER = {
    "MAIL_RNAME": "陳小華",
    "MAIL_RPHONE": "0987654321",
    "MAIL_RADD_TYPE": "001",          # 001 一般地址 / 002 i郵箱 / 003 郵政信箱 / 004 特種郵政信箱 / 005 存局候領
    "MAIL_RADD_CITY": "新北市",
    "MAIL_RADD_AREA": "板橋區",
    "MAIL_RADD_ZIP": "220",
    "MAIL_RADD_ROAD": "中山路一段",
    "MAIL_RADD_OTHER": "161號",
}

DEFAULT_CONTENT = {
    "MAIL_CONTENTS_NO": "6",          # 物品種類：1 空白文件 2 食品 … 6 書籍 … B 其他
    "MAIL_CONTENTS": "",              # 物品種類選 B(其他) 時必填
    "MAIL_PACKAGE_SIZE": "00G",       # 包材：00F 大 / 00G 中 / 00H 小
    "MAIL_COMMENT": "書籍兩本",
    "MAIL_UNDELIVER_OPTNO": "001",    # 無法投遞：001 退回寄件人 / 002 拋棄
    "MAIL_RETURN_TYPE": "001",        # 退件地址：001 寄件人地址 / 004 原寄件i郵箱 / 003 其他地址
}


def open_mail_edit_page(session, saver):
    """送出注意事項頁的 form，回傳 /Mail/IBoxMailEdit 的回應。"""
    resp = session.get(RULE_URL, timeout=15)
    resp.encoding = "utf-8"
    saver.save(resp, "SingleShipRule")
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "html.parser")

    # 1. 找 form，擷取 action 與 method
    form = soup.find("form", id="form-Upload") or soup.find("form")
    if form is None:
        raise SystemExit("頁面中找不到 <form>")
    action = urljoin(RULE_URL, form.get("action", ""))
    method = form.get("method", "get").strip().upper()
    print(f"[條款頁] {method} {action}")

    # 2. input 欄位：id 優先，其次 name
    fields = {}
    for inp in form.find_all("input"):
        key = inp.get("id") or inp.get("name")
        if key:
            fields[key] = inp.get("value", "")
    for k, v in fields.items():
        print(f"    {k} = {v!r}")

    # 3. 組 payload  4. 送出
    payload = urlencode(fields)
    headers = {"Content-Type": "application/x-www-form-urlencoded", "Referer": RULE_URL}
    if method == "POST":
        result = session.post(action, data=payload, headers=headers, timeout=15)
    else:
        result = session.get(action, params=fields, headers={"Referer": RULE_URL}, timeout=15)
    result.encoding = result.apparent_encoding or "utf-8"
    print(f"    回應：{result.status_code}  {result.url}")
    saver.save(result, "IBoxMailEdit")
    result.raise_for_status()
    return result


def main(sender_data, receiver_data, content_data, out_dir=None, download_pdf=True, pdf_out=None):
    session = requests.Session()
    session.headers.update(HEADERS)
    saver = ResponseSaver(out_dir)
    print(f"回應存檔目錄：{saver.out_dir}")

    edit_page = open_mail_edit_page(session, saver)

    editor = EzpostMailEditor(
        session=session,
        page_html=edit_page.text,
        page_url=edit_page.url,
        saver=saver,
    )
    try:
        final_html = editor.run(sender_data, receiver_data, content_data)
    except (EzpostSubmitError, LookupError) as e:
        print("\n已存檔的回應：", *saver.saved, sep="\n  ")
        raise SystemExit(f"\n[失敗] {e}")

    print("\n" + "=" * 60 + "\n完成頁 HTML（/Mail/MailShipCompleted）：\n" + "=" * 60)
    print(final_html)

    pdf_path = None
    if download_pdf:
        try:
            pdf_path = download_shipping_pdf(
                session, final_html, editor.completed_url, saver=saver, out_path=pdf_out,
            )
        except (EzpostPdfError, LookupError) as e:
            print("\n已存檔的回應：", *saver.saved, sep="\n  ")
            raise SystemExit(f"\n[託運單下載失敗] {e}")
        print(f"\n託運單 PDF：{pdf_path}")

    print("\n已存檔的回應：", *saver.saved, sep="\n  ")
    return final_html


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="EZPost i 郵箱寄件表單送出")
    parser.add_argument("--data", help='JSON 檔，格式 {"sender":{...}, "receiver":{...}, "content":{...}}')
    parser.add_argument("--out-dir", help="回應存檔目錄（預設 responses/<時間>）")
    parser.add_argument("--pdf-out", help="託運單 PDF 另存路徑（預設只存在回應目錄）")
    parser.add_argument("--no-pdf", action="store_true", help="不下載託運單 PDF")
    args = parser.parse_args()

    sender, receiver, content = DEFAULT_SENDER, DEFAULT_RECEIVER, DEFAULT_CONTENT
    if args.data:
        with open(args.data, encoding="utf-8") as f:
            cfg = json.load(f)
        sender = cfg.get("sender", sender)
        receiver = cfg.get("receiver", receiver)
        content = cfg.get("content", content)

    main(sender, receiver, content, out_dir=args.out_dir,
         download_pdf=not args.no_pdf, pdf_out=args.pdf_out)
