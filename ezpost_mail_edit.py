"""
ezpost_mail_edit.py
EZPost「i 郵箱寄件 - 建立託運單」(/Mail/IBoxMailEdit) 的送出模組。

實際流程（對照頁面上的 MailEdit.js）：
    1. 寄件人 → POST /Mail/CheckMailSender
    2. 收件人 → POST /Mail/CheckMailReceiver
    3. 內裝物品 → POST /Mail/CheckMailContents
    4. 檢查都通過後送出 form#form-DetailsCheck (/Mail/MailInfoDetailsCheck)
    5. POST /Mail/CheckSendMailInfo（AJAX，網址固定，頁面上沒有對應表單），只帶
       action=/Mail/MailInfoDetailsCheck 表單內的 __RequestVerificationToken
       （先找確認明細頁，沒有則用建立託運單頁的 form#form-DetailsCheck）
    6. POST /Mail/MailShipCompleted?mail_Type=IBox，只帶確認明細頁中
       action=/Mail/MailShipCompleted?mail_Type=IBox 表單內的 __RequestVerificationToken，取得完成頁 HTML

步驟 1~3 的請求格式（Content-Type: application/x-www-form-urlencoded）：
    Base64Data                 = base64( UTF-8( JSON.stringify(MailObj) ) )
    __RequestVerificationToken = 頁面上的防偽權杖

MailObj 由 MailId / DATA_SOURCE / MAIL_STATUS / Status，加上三張表單
(form-sender / form-receiver / form-content) 的所有欄位組成，key 用欄位的 name
（等同 jQuery serializeObject）。尚未填寫的表單會帶預設值。

使用方式（由主程式呼叫）：
    from ezpost_mail_edit import EzpostMailEditor
    editor = EzpostMailEditor(session, page_html, page_url)
    html = editor.run(sender_data, receiver_data, content_data)

欄位資料以 dict 傳入，key 可用欄位的 name 或 id，例如 {"MAIL_SNAME": "王小明", ...}

每個步驟的回應都會由 ResponseSaver 存成檔案（預設 responses/<時間>/），例如：
    03_CheckMailSender.json、06_MailInfoDetailsCheck.html、07_MailShipCompleted.html
"""
import base64
import datetime
import json
import os
import re
from urllib.parse import urljoin, urlencode, urlparse

from bs4 import BeautifulSoup

TOKEN_NAME = "__RequestVerificationToken"
SHIP_COMPLETED_PATH = "/Mail/MailShipCompleted?mail_Type=IBox"
CHECK_SEND_PATH = "/Mail/CheckSendMailInfo"
DETAILS_CHECK_PATH = "/Mail/MailInfoDetailsCheck"
REQUIRED_COOKIES = (TOKEN_NAME, "ASP.NET_SessionId")

# 瀏覽器「送出表單、換頁」時的標頭（對照成功的 cURL：MailShipCompleted）
NAVIGATION_HEADERS = {
    "Accept": (
        "text/html,application/xhtml+xml,application/xml;q=0.9,image/jxl,image/avif,"
        "image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7"
    ),
    "Cache-Control": "max-age=0",
    "Content-Type": "application/x-www-form-urlencoded",
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "same-origin",
    "Sec-Fetch-User": "?1",
    "Upgrade-Insecure-Requests": "1",
}

# jQuery $.ajax 呼叫時的標頭（對照成功的 cURL：CheckSendMailInfo）
AJAX_HEADERS = {
    "Accept": "*/*",
    "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
    "Sec-Fetch-Dest": "empty",
    "Sec-Fetch-Mode": "cors",
    "Sec-Fetch-Site": "same-origin",
    "X-Requested-With": "XMLHttpRequest",
}
SKIP_INPUT_TYPES = {"submit", "button", "image", "reset", "file"}

FORM_IDS = {"sender": "form-sender", "receiver": "form-receiver", "content": "form-content"}

# 各步驟：端點來源（#data-mail-edit 的屬性與預設值）、MailObj 開頭欄位、表單合併順序
STEPS = {
    "sender": {
        "label": "寄件人",
        "url_attr": "data-mail-url-check-sender",
        "default_url": "/Mail/CheckMailSender",
        "lead": ["MailId", "DATA_SOURCE", "MAIL_STATUS", "Status"],
        "order": ["sender", "receiver", "content"],
    },
    "receiver": {
        "label": "收件人",
        "url_attr": "data-mail-url-check-receiver",
        "default_url": "/Mail/CheckMailReceiver",
        "lead": ["MailId", "MAIL_STATUS", "Status"],
        "order": ["receiver", "sender", "content"],
    },
    "content": {
        "label": "內裝物品",
        "url_attr": "data-mail-url-check-contents",
        "default_url": "/Mail/CheckMailContents",
        "lead": ["MailId", "MAIL_STATUS", "Status"],
        "order": ["content", "receiver", "sender"],
    },
}


class EzpostSubmitError(RuntimeError):
    """送出失敗：HTTP 錯誤，或伺服器回傳 success = false。"""


# ---------------------------------------------------------------------------
# 欄位擷取與填值
# ---------------------------------------------------------------------------
def _lookup(data, el):
    """從使用者資料中找此欄位的值：先用 name，再用 id。"""
    for k in (el.get("name"), el.get("id")):
        if k and k in data:
            return True, data[k]
    return False, None


def collect_fields(form, data=None, warn=print):
    """
    模擬 jQuery serializeObject：走訪 form 底下的 input / select / textarea，
    以 name 為 key（沒有 name 才用 id），填入 data 中的值後回傳 dict。
    radio / checkbox 只收選中的；disabled 欄位略過。
    """
    data = data or {}
    result = {}

    for el in form.find_all(["input", "select", "textarea"]):
        if el.has_attr("disabled"):
            continue
        key = el.get("name") or el.get("id")
        if not key:
            continue
        found, user_val = _lookup(data, el)

        if el.name == "input":
            itype = (el.get("type") or "text").lower()
            if itype in SKIP_INPUT_TYPES:
                continue
            if itype in ("radio", "checkbox"):
                if found:
                    checked = user_val is True or str(user_val) == el.get("value", "on")
                else:
                    checked = el.has_attr("checked")
                if checked:
                    result[key] = el.get("value", "on")
                continue
            if found:
                result[key] = "" if user_val is None else str(user_val)
            else:
                result[key] = el.get("value", "")

        elif el.name == "select":
            options = [o.get("value", o.get_text(strip=True)) for o in el.find_all("option")]
            if found:
                value = "" if user_val is None else str(user_val)
                # 只檢查有完整靜態選項的下拉選單（鄉鎮市區等由 JS 動態載入的不檢查）
                if value and any(options) and value not in options:
                    warn(f"    [警告] {key} 的值 {value!r} 不在選項中：{options}")
            else:
                selected = el.find("option", selected=True) or el.find("option")
                value = selected.get("value", selected.get_text(strip=True)) if selected else ""
            result[key] = value

        elif el.name == "textarea":
            result[key] = str(user_val) if found and user_val is not None else el.get_text().strip()

    # 提醒：使用者給了但表單裡沒有的欄位
    form_keys = {k for el in form.find_all(["input", "select", "textarea"])
                 for k in (el.get("id"), el.get("name")) if k}
    unknown = [k for k in data if k not in form_keys]
    if unknown:
        warn(f"    [警告] 下列欄位不在 #{form.get('id')} 中，已忽略：{unknown}")
    return result


def encode_mail_obj(mail_obj):
    """等同 JS：btoa(unescape(encodeURIComponent(JSON.stringify(obj))))"""
    json_str = json.dumps(mail_obj, ensure_ascii=False, separators=(",", ":"))
    return base64.b64encode(json_str.encode("utf-8")).decode("ascii")


# ---------------------------------------------------------------------------
# 回應存檔
# ---------------------------------------------------------------------------
class ResponseSaver:
    """把每個步驟的回應依序存檔：NN_<端點名稱>.<html|json|txt>"""

    def __init__(self, out_dir=None, verbose=True):
        if out_dir is None:
            stamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
            out_dir = os.path.join("responses", stamp)
        self.out_dir = out_dir
        self.verbose = verbose
        self.count = 0
        self.saved = []
        os.makedirs(out_dir, exist_ok=True)

    def save(self, resp, name=None):
        self.count += 1
        if not name:
            name = urlparse(resp.url).path.rstrip("/").rsplit("/", 1)[-1] or "index"
        name = re.sub(r"[^\w.-]+", "_", name)

        ctype = (resp.headers.get("Content-Type", "") if getattr(resp, "headers", None) else "").lower()
        text = resp.text
        if "json" in ctype or text.lstrip()[:1] in ("{", "["):
            ext = "json"
            try:  # 排版成易讀格式
                text = json.dumps(json.loads(text), ensure_ascii=False, indent=2)
            except ValueError:
                pass
        elif "html" in ctype or "<html" in text[:500].lower() or "<!doctype" in text[:500].lower():
            ext = "html"
        else:
            ext = "txt"

        path = os.path.join(self.out_dir, f"{self.count:02d}_{name}.{ext}")
        with open(path, "w", encoding="utf-8") as f:
            f.write(text)
        self.saved.append(path)

        if self.verbose:
            extra = ""
            if ext == "html":
                n = len(BeautifulSoup(text, "html.parser").find_all("input", attrs={"name": TOKEN_NAME}))
                extra = f"（含 {TOKEN_NAME} {n} 個）"
            print(f"    已存檔：{path} {extra}")
        return path

    def save_bytes(self, data, name, ext):
        """以 binary 方式存檔（例如 PDF），回傳路徑。"""
        self.count += 1
        name = re.sub(r"[^\w.-]+", "_", name)
        path = os.path.join(self.out_dir, f"{self.count:02d}_{name}.{ext}")
        with open(path, "wb") as f:
            f.write(data)
        self.saved.append(path)
        if self.verbose:
            print(f"    已存檔：{path}（{len(data):,} bytes）")
        return path


# ---------------------------------------------------------------------------
# 主要類別
# ---------------------------------------------------------------------------
class EzpostMailEditor:
    def __init__(self, session, page_html, page_url, timeout=15, verbose=True, saver=None):
        """
        session   : 沿用進入此頁時的 requests.Session（防偽權杖要配對 Cookie）
        page_html : /Mail/IBoxMailEdit 的 HTML
        page_url  : 該頁網址（解析相對網址、當 Referer）
        saver     : ResponseSaver；不給則自動建立 responses/<時間>/
        """
        self.saver = saver or ResponseSaver(verbose=verbose)
        self.session = session
        self.page_url = page_url
        self.timeout = timeout
        self.verbose = verbose
        self.soup = BeautifulSoup(page_html, "html.parser")
        self.user_data = {"sender": {}, "receiver": {}, "content": {}}

        self.forms = {}
        for part, form_id in FORM_IDS.items():
            form = self.soup.find("form", id=form_id)
            if form is None:
                raise LookupError(f"找不到表單 #{form_id}")
            self.forms[part] = form

        tok = self.soup.find("input", attrs={"name": TOKEN_NAME})
        if tok is None:
            raise LookupError(f"頁面中找不到 {TOKEN_NAME}")
        self.token = tok.get("value", "")

        self.urls_div = self.soup.find(id="data-mail-edit")

    # ----- 工具 -----
    def _log(self, *args):
        if self.verbose:
            print(*args)

    def _origin(self):
        u = urlparse(self.page_url)
        return f"{u.scheme}://{u.netloc}"

    def _nav_headers(self, referer):
        """換頁型 POST 的標頭：NAVIGATION_HEADERS + Origin + Referer。"""
        return {**NAVIGATION_HEADERS, "Origin": self._origin(), "Referer": referer}

    def _ajax_headers(self, referer):
        """AJAX 型 POST 的標頭：AJAX_HEADERS + Origin + Referer。"""
        return {**AJAX_HEADERS, "Origin": self._origin(), "Referer": referer}

    def _check_cookies(self, step_label):
        """確認 Session 中已有伺服器發的 __RequestVerificationToken 與 ASP.NET_SessionId Cookie。"""
        names = {c.name for c in getattr(self.session, "cookies", [])}
        missing = [n for n in REQUIRED_COOKIES if n not in names]
        if missing:
            self._log(f"    [警告] {step_label}前 Session 缺少 Cookie：{missing}，伺服器可能拒絕請求")
        else:
            self._log(f"    Cookie：{', '.join(REQUIRED_COOKIES)} 皆已存在")

    def _hidden(self, field_id):
        el = self.soup.find("input", id=field_id)
        return el.get("value", "") if el else ""

    def _endpoint(self, step):
        cfg = STEPS[step]
        path = self.urls_div.get(cfg["url_attr"]) if self.urls_div else None
        return urljoin(self.page_url, path or cfg["default_url"])

    def build_mail_obj(self, step):
        """組出該步驟要送的 MailObj（未填的表單帶預設值）。"""
        cfg = STEPS[step]
        lead_values = {
            "MailId": self._hidden("MailId"),
            "DATA_SOURCE": self._hidden("DATA_SOURCE"),
            "MAIL_STATUS": self._hidden("MAIL_STATUS"),
            "Status": None,   # 只有「暫存」時才會帶步驟編號
        }
        obj = {k: lead_values[k] for k in cfg["lead"]}
        for part in cfg["order"]:
            fields = collect_fields(self.forms[part], self.user_data[part],
                                    warn=self._log if part == step else (lambda *a: None))
            for k, v in fields.items():
                obj.setdefault(k, v)   # 同 JS 物件展開：key 只出現一次
        return obj

    # ----- 單一步驟 -----
    def check_step(self, step, data):
        self.user_data[step] = dict(data or {})
        url = self._endpoint(step)
        self._log(f"\n=== {STEPS[step]['label']}：POST {url}")

        mail_obj = self.build_mail_obj(step)
        self._log("    MailObj:", json.dumps(mail_obj, ensure_ascii=False))

        payload = urlencode({"Base64Data": encode_mail_obj(mail_obj), TOKEN_NAME: self.token})
        resp = self.session.post(url, data=payload, headers=self._ajax_headers(self.page_url),
                                 timeout=self.timeout)
        resp.encoding = resp.encoding or "utf-8"
        self._log(f"    回應：{resp.status_code}")
        self.saver.save(resp)
        if resp.status_code >= 400:
            raise EzpostSubmitError(f"{STEPS[step]['label']}檢查失敗（HTTP {resp.status_code}）\n{resp.text[:500]}")

        try:
            body = resp.json()
        except ValueError:
            raise EzpostSubmitError(f"{STEPS[step]['label']}檢查回應不是 JSON：\n{resp.text[:500]}")
        result = body.get("response", body) if isinstance(body, dict) else body
        self._log("    結果：", json.dumps(result, ensure_ascii=False)[:500])
        if not (isinstance(result, dict) and result.get("success")):
            msg = result.get("message") if isinstance(result, dict) else result
            raise EzpostSubmitError(f"{STEPS[step]['label']}檢查未通過：{msg}")
        return result

    def submit_details_check(self):
        """三個檢查都通過後，送出 form#form-DetailsCheck，回傳回應 HTML。"""
        form = self.soup.find("form", id="form-DetailsCheck")
        if form is None:
            raise LookupError("找不到表單 #form-DetailsCheck")
        url = urljoin(self.page_url, form.get("action") or "")
        fields = collect_fields(form, warn=self._log)
        self._log(f"\n=== 確認明細：POST {url}")

        resp = self.session.post(
            url, data=urlencode(fields), timeout=self.timeout,
            headers=self._nav_headers(self.page_url),
        )
        resp.encoding = resp.apparent_encoding or "utf-8"
        self._log(f"    回應：{resp.status_code}  {resp.url}")
        self.saver.save(resp, "MailInfoDetailsCheck")
        self.details_post_url = url   # 下一步的 Referer（瀏覽器網址列上的頁面）
        if resp.status_code >= 400:
            raise EzpostSubmitError(f"確認明細送出失敗（HTTP {resp.status_code}）\n{resp.text[:500]}")
        self.details_url = resp.url
        return resp.text

    @staticmethod
    def _find_form_by_action(soup, base, path):
        target = urljoin(base, path).lower()
        return soup.find(
            "form", action=lambda a: bool(a) and urljoin(base, a.strip()).lower() == target
        )

    def _form_token(self, details_html, path):
        """
        從確認明細頁（MailInfoDetailsCheck 回應）找 action 為 path 的 form，
        取其中的 __RequestVerificationToken。回傳 (請求網址, 權杖)。
        """
        base = getattr(self, "details_url", None) or self.page_url
        dsoup = BeautifulSoup(details_html or "", "html.parser")
        form = self._find_form_by_action(dsoup, base, path)
        if form is None:
            raise LookupError(f"確認明細頁中找不到 action={path} 的表單")
        tok = form.find("input", attrs={"name": TOKEN_NAME})
        if tok is None or not tok.get("value"):
            raise LookupError(f"action={path} 的表單內找不到 {TOKEN_NAME}")
        return urljoin(base, form.get("action").strip()), tok.get("value")

    def _details_referer(self):
        return getattr(self, "details_post_url", None) or urljoin(self.page_url, "/Mail/MailInfoDetailsCheck")

    def _details_check_form_token(self, details_html):
        """
        取 action=/Mail/MailInfoDetailsCheck 表單內的 __RequestVerificationToken。
        先找確認明細頁（MailInfoDetailsCheck 回應），沒有再用建立託運單頁的 form#form-DetailsCheck。
        回傳 (權杖, 來源說明)。
        """
        sources = [
            ("確認明細頁", BeautifulSoup(details_html or "", "html.parser"),
             getattr(self, "details_url", None) or self.page_url),
            ("建立託運單頁", self.soup, self.page_url),
        ]
        for label, soup, base in sources:
            form = self._find_form_by_action(soup, base, DETAILS_CHECK_PATH)
            tok = form.find("input", attrs={"name": TOKEN_NAME}) if form else None
            if tok is not None and tok.get("value"):
                return tok.get("value"), f"{label} action={DETAILS_CHECK_PATH} 的表單"
        raise LookupError(f"找不到 action={DETAILS_CHECK_PATH} 表單內的 {TOKEN_NAME}")

    def check_send_mail_info(self, details_html):
        """
        完成寄件前的檢查：POST /Mail/CheckSendMailInfo（AJAX）
        CheckSendMailInfo 沒有對應表單，只帶 action=/Mail/MailInfoDetailsCheck 表單內的
        __RequestVerificationToken。回應若為 JSON 且 success 為 false，視為失敗。
        """
        url = urljoin(self.page_url, CHECK_SEND_PATH)
        token, source = self._details_check_form_token(details_html)
        self._log(f"\n=== 寄件資料檢查：POST {url}（權杖取自{source}：{token[:12]}…）")
        self._check_cookies("寄件資料檢查")
        resp = self.session.post(
            url, data=urlencode({TOKEN_NAME: token}), timeout=self.timeout,
            headers=self._ajax_headers(self._details_referer()),
        )
        resp.encoding = resp.encoding or "utf-8"
        self._log(f"    回應：{resp.status_code}")
        self.saver.save(resp, "CheckSendMailInfo")
        if resp.status_code >= 400:
            raise EzpostSubmitError(f"寄件資料檢查失敗（HTTP {resp.status_code}）\n{resp.text[:500]}")
        try:
            body = resp.json()
        except ValueError:
            self._log("    [注意] 回應不是 JSON，已存檔，繼續下一步")
            return resp.text
        result = body.get("response", body) if isinstance(body, dict) else body
        self._log("    結果：", json.dumps(result, ensure_ascii=False)[:500])
        if isinstance(result, dict) and result.get("success") is False:
            raise EzpostSubmitError(f"寄件資料檢查未通過：{result.get('message')}")
        return result

    def submit_ship_completed(self, details_html):
        """
        最後一步：POST /Mail/MailShipCompleted?mail_Type=IBox
        只帶確認明細頁中 action=/Mail/MailShipCompleted?mail_Type=IBox 表單內的
        __RequestVerificationToken，回傳完成頁 HTML。
        """
        url, token = self._form_token(details_html, SHIP_COMPLETED_PATH)
        self._log(f"\n=== 完成寄件：POST {url}（權杖取自 action={SHIP_COMPLETED_PATH} 的表單：{token[:12]}…）")

        # 對照成功的 cURL：Referer 為 /Mail/MailInfoDetailsCheck、帶 Origin 與換頁標頭，
        # Cookie（__RequestVerificationToken、ASP.NET_SessionId）由同一個 Session 自動帶上，
        # 內容只有表單內的 __RequestVerificationToken。
        referer = self._details_referer()
        self._check_cookies("完成寄件")
        resp = self.session.post(
            url, data=urlencode({TOKEN_NAME: token}), timeout=self.timeout,
            headers=self._nav_headers(referer),
        )
        resp.encoding = resp.apparent_encoding or "utf-8"
        self._log(f"    回應：{resp.status_code}  {resp.url}")
        self.saver.save(resp, "MailShipCompleted")
        self.completed_url = url   # 下載託運單時的 Referer
        if resp.status_code >= 400:
            raise EzpostSubmitError(f"完成寄件送出失敗（HTTP {resp.status_code}）\n{resp.text[:500]}")
        return resp.text

    # ----- 整體流程 -----
    def check_sender(self, data):
        return self.check_step("sender", data)

    def check_receiver(self, data):
        return self.check_step("receiver", data)

    def check_content(self, data):
        return self.check_step("content", data)

    def run(self, sender_data, receiver_data, content_data):
        """寄件人 → 收件人 → 內裝物品 → 確認明細 → 寄件資料檢查 → 完成寄件，回傳完成頁 HTML。"""
        self.check_sender(sender_data)
        self.check_receiver(receiver_data)
        self.check_content(content_data)
        details_html = self.submit_details_check()
        self.check_send_mail_info(details_html)
        return self.submit_ship_completed(details_html)
