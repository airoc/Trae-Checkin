#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
登录拿 token · trae_gettoken.py
════════════════════════════════════════════════════════════
在装了 Trae 客户端的机器上跑，完成一次浏览器登录，拿到一条独立于
桌面客户端的 refreshToken 会话链，然后输出成**单行 JSON**——直接粘到
金山文档 AirScript 表格「账号」列（A 列）的对应单元格。

零依赖（纯 Python 标准库），单文件，不依赖本项目其它文件。

用法
────────────────────────────────────────────────────────────
  python trae_gettoken.py                          自动读取本机客户端的真实设备号
  python trae_gettoken.py --device-id 3124143766407755   手动指定设备号

输出
────────────────────────────────────────────────────────────
  1. 控制台里打印一行单行 JSON，直接复制；
  2. 同时追加写入同目录的 tokens.txt（每行一个账号，多账号就是多行）。

⚠️ 两个必须记住的限制
  • 设备号必须是客户端**真实注册的**那串数字（自动生成的会被风控拒成 9074）；
  • 一个设备号**一天只能签一个账号**（限额按设备算），多账号请用多台机器的号。
"""

import base64
import json
import os
import re
import secrets
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import webbrowser

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

# ── 常量 ──────────────────────────────────────────────────
CLIENT_ID = "en1oxy7wnw8j9n"
APP_VERSION = os.getenv("TRAE_APP_VERSION", "").strip() or "0.1.43"
UA = "Trae/%s" % APP_VERSION
OAUTH_HOST = "https://api.trae.com.cn"
LOGIN_PAGE = "https://www.trae.cn/authorization"
PLUGIN_VERSION = "2.3.62834"
LOGIN_PORT = 18080
EP_EXCHANGE = OAUTH_HOST + "/cloudide/api/v3/trae/oauth/ExchangeToken"

HERE = os.path.dirname(os.path.abspath(__file__))
OUTPUT_FILE = os.getenv("TRAE_TOKEN_OUTPUT", "").strip() or os.path.join(HERE, "tokens.txt")

DC_PREFIX = "iCubeAuthInfo://icube-dc:"
DEVICE_ID_MIN_LEN = 12
DEVICE_ID_MAX_LEN = 20


def is_valid_device_id(d):
    d = str(d or "").strip()
    return d.isdigit() and DEVICE_ID_MIN_LEN <= len(d) <= DEVICE_ID_MAX_LEN


def device_id_from_key(key, value=None):
    k = str(key or "")
    if k.startswith(DC_PREFIX):
        cand = k[len(DC_PREFIX):].strip()
        return cand if is_valid_device_id(cand) else ""
    if k.rstrip(":") == DC_PREFIX.rstrip(":") and value is not None:
        cand = str(value).strip()
        return cand if is_valid_device_id(cand) else ""
    return ""


def _base_dirs():
    home = os.path.expanduser("~")
    cands = [os.environ.get("APPDATA"), os.environ.get("LOCALAPPDATA"),
             os.path.join(home, "AppData", "Roaming"),
             os.path.join(home, "AppData", "Local")]
    if os.name != "nt":
        cands += [os.path.join(home, "Library", "Application Support"),
                  os.path.join(home, ".config"), home]
    out = []
    for c in cands:
        if c and os.path.isdir(c) and c not in out:
            out.append(c)
    return out


def find_storage_files():
    sub = ("User", "globalStorage", "storage.json")
    known = ("TRAE SOLO CN", "Trae CN", "TRAE SOLO", "Trae", "TraeWork", "TraeWork CN")
    found = []

    def add(p):
        if os.path.isfile(p) and p not in found:
            found.append(p)

    for base in _base_dirs():
        for n in known:
            add(os.path.join(base, n, *sub))
        try:
            for entry in sorted(os.listdir(base)):
                if "trae" in entry.lower():
                    add(os.path.join(base, entry, *sub))
        except OSError:
            pass
    return found


def device_ids_in(path):
    out = []
    try:
        with open(path, "r", encoding="utf-8-sig", errors="replace") as fh:
            storage = json.load(fh)
    except Exception:
        return out
    if not isinstance(storage, dict):
        return out
    for k, v in storage.items():
        d = device_id_from_key(k, v)
        if d and d not in out:
            out.append(d)
    return out


def real_device_ids():
    out = []
    for p in find_storage_files():
        for d in device_ids_in(p):
            if d not in out:
                out.append(d)
    return out


def http_post(url, headers, body="{}", timeout=30):
    data = body.encode("utf-8") if isinstance(body, str) else body
    req = urllib.request.Request(url, data=data, headers=headers, method="POST")
    try:
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        with opener.open(req, timeout=timeout) as resp:
            status, text = resp.status, resp.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        try:
            text = e.read().decode("utf-8", "replace")
        except Exception:
            text = ""
        status = e.code
    except Exception as e:
        return -1, None, str(e)
    try:
        return status, json.loads(text), text
    except Exception:
        return status, None, text


def exchange_token(refresh_token, uid=""):
    body = json.dumps({"ClientID": CLIENT_ID, "RefreshToken": refresh_token,
                       "ClientSecret": "-", "UserID": uid or ""})
    status, d, text = http_post(
        EP_EXCHANGE,
        {"Content-Type": "application/json", "Accept": "application/json", "User-Agent": UA},
        body, 30)
    if status < 0:
        return False, None, "网络错误: %s" % text[:120], False
    if not isinstance(d, dict):
        return False, None, "响应异常 (HTTP %s): %s" % (status, text[:120]), False
    err = ((d.get("ResponseMetadata") or {}).get("Error") or {})
    res = d.get("Result") or d.get("data") or {}
    token = res.get("Token") or res.get("AccessToken") or ""
    if not token:
        return False, None, "服务端拒绝 (HTTP %s) %s %s" % (
            status, err.get("Code", ""), err.get("Message", ""))[:160], True
    exp = res.get("TokenExpireAt") or 0
    try:
        exp = int(exp)
        if exp > 10 ** 12:
            exp //= 1000
    except Exception:
        exp = 0
    if not exp:
        try:
            exp = int(time.time()) + int(res.get("TokenExpireDuration") or 1209600)
        except Exception:
            exp = int(time.time()) + 3600
    return True, {"accessToken": token,
                  "refreshToken": res.get("RefreshToken") or refresh_token,
                  "expiresAt": exp}, "ok", False


def jwt_uid(token):
    if not token or token.count(".") < 1:
        return ""
    try:
        payload = token.split(".")[1]
        payload += "=" * (-len(payload) % 4)
        obj = json.loads(base64.urlsafe_b64decode(payload))
        data = obj.get("data") if isinstance(obj.get("data"), dict) else obj
        for k in ("id", "UserID", "userId", "uid"):
            v = data.get(k) if isinstance(data, dict) else None
            if v:
                return str(v)
    except Exception:
        pass
    return ""


def gen_machine_id():
    return secrets.token_hex(16)


def port_in_use(port=LOGIN_PORT, host="127.0.0.1", timeout=0.6):
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.settimeout(timeout)
    try:
        s.connect((host, port))
        return True
    except Exception:
        return False
    finally:
        try:
            s.close()
        except Exception:
            pass


def port_owner(port=LOGIN_PORT):
    try:
        cmd = ["netstat", "-ano"] if os.name == "nt" else ["ss", "-lptn"]
        r = subprocess.run(cmd, capture_output=True, timeout=8)
        text = (r.stdout + r.stderr).decode("utf-8", "replace")
        for line in text.splitlines():
            if (":%d" % port) not in line:
                continue
            if "LISTEN" not in line.upper():
                continue
            m = re.search(r"pid=(\d+)", line)
            if m:
                return m.group(1)
            parts = line.split()
            if len(parts) > 1 and parts[-1].isdigit():
                return parts[-1]
    except Exception:
        pass
    return ""


def build_login_url(machine_id, device_id, port=LOGIN_PORT):
    params = {
        "login_version": "1",
        "auth_from": "solo",
        "login_channel": "native_ide",
        "plugin_version": PLUGIN_VERSION,
        "auth_type": "local",
        "client_id": CLIENT_ID,
        "redirect": "0",
        "login_trace_id": secrets.token_hex(8),
        "auth_callback_url": "http://127.0.0.1:%d/authorize" % port,
        "machine_id": machine_id,
        "device_id": device_id,
        "x_device_id": device_id,
        "x_machine_id": machine_id,
        "x_device_brand": "PC",
        "x_device_type": "PC",
        "x_os_version": "1.0",
        "x_app_version": APP_VERSION,
        "x_app_type": "stable",
    }
    return LOGIN_PAGE + "?" + urllib.parse.urlencode(params)


def _json_param(raw):
    if not raw:
        return {}
    for val in (raw, urllib.parse.unquote(raw)):
        try:
            o = json.loads(val)
            if isinstance(o, dict):
                return o
        except Exception:
            continue
    return {}


def parse_callback_url(url):
    qs = urllib.parse.parse_qs(urllib.parse.urlparse(url).query)

    def one(k):
        v = qs.get(k) or [""]
        return v[0]

    ui = _json_param(one("userInfo"))
    uj = _json_param(one("userJwt"))
    rt = one("refreshToken") or one("refresh_token") or one("data") \
        or str(uj.get("RefreshToken") or "")
    region = ""
    ur = _json_param(one("userRegion")) or ui.get("userRegion")
    if isinstance(ur, dict):
        region = str(ur.get("region") or "")
    return {"refreshToken": rt,
            "accessToken": str(uj.get("Token") or ""),
            "uid": str(ui.get("UserID") or uj.get("UserID") or ""),
            "nickname": str(ui.get("ScreenName") or ""),
            "region": region}


def get_user_info(access_token):
    try:
        _, d, _ = http_post(
            OAUTH_HOST + "/cloudide/api/v3/trae/GetUserInfo",
            {"Content-Type": "application/json",
             "x-cloudide-token": access_token, "User-Agent": UA},
            json.dumps({"ReqSource": "IDE", "IDEVersion": APP_VERSION}), 15)
        res = (d or {}).get("Result") or d or {}
        return str(res.get("UserID") or ""), str(res.get("ScreenName") or "")
    except Exception:
        return "", ""


def count_lines():
    try:
        with open(OUTPUT_FILE, "r", encoding="utf-8", errors="replace") as fh:
            return sum(1 for ln in fh if ln.strip())
    except Exception:
        return 0


def save_line(line):
    try:
        with open(OUTPUT_FILE, "a", encoding="utf-8") as fh:
            fh.write(line + "\n")
        return True
    except Exception as e:
        print("⚠️ 写入输出文件失败: %s" % e)
        return False


def main(argv):
    low = [a.lower() for a in argv]
    if any(a in ("-h", "--help", "help") for a in low):
        print(__doc__)
        return 0

    # ── 设备号：--device-id 优先，其次自动读本机客户端 ──
    dev_arg = ""
    if "--device-id" in low:
        i = low.index("--device-id")
        if i + 1 < len(argv):
            dev_arg = argv[i + 1].strip()
        else:
            print("❌ --device-id 后面要跟设备号（一串十进制数字）")
            return 1
    if dev_arg and not is_valid_device_id(dev_arg):
        print("❌ --device-id 不像客户端设备号（应为一串十进制数字），收到：%s" % dev_arg)
        return 1

    if dev_arg:
        device_id = dev_arg
        dev_src = "manual"
    else:
        real = real_device_ids()
        if real:
            device_id = real[0]
            dev_src = "auto"
            if len(real) > 1:
                print("⚠️ 本机读到 %d 个设备号，先用第一个 %s。" % (len(real), device_id))
                print("   要换另一个，用 --device-id 指定。")
        else:
            print("❌ 没读到本机客户端的真实设备号，也没用 --device-id 指定。")
            print("   设备号必须用 Trae 客户端真实注册的那个号，自动生成的会被风控拒成 9074。")
            print()
            print("   请先确认这台电脑：")
            print("     1) 装过 Trae 客户端，并且在客户端里登录过一次；")
            print("     2) 满足后重跑本脚本，就能自动读到设备号。")
            print("   如果是在没装客户端的机器上跑，就先去装了客户端的机器上拿真实号，")
            print("   再带过来：")
            print("     python trae_gettoken.py --device-id <设备号>")
            return 1

    if dev_src == "auto":
        dev_label = "当前电脑的设备号为: %s" % device_id
    else:
        dev_label = "当前未获取。该设备号为手动指定: %s" % device_id

    machine_id = gen_machine_id()
    url = build_login_url(machine_id, device_id)

    print()
    print("=" * 66)
    print("  Trae 登录（拿 token，输出单行 JSON）")
    print("=" * 66)
    print()
    print("  " + dev_label)
    print()

    port_busy = port_in_use()
    if port_busy:
        pid = port_owner()
        print("⚠️ 回调端口 %d 已被占用%s" % (LOGIN_PORT, ("（PID %s）" % pid) if pid else ""))
        print("   登录 token 会被那个程序接走，脚本收不到。请先结束它：")
        if pid:
            print("     taskkill /F /PID %s" % pid)
        print()

    print("  登录链接（已尝试用默认浏览器打开，没弹出就手动复制下面这条）：")
    print()
    print(url)
    print()
    if webbrowser.open(url):
        print("  ✅ 已在默认浏览器打开登录页")
    else:
        print("  ⚠️ 自动打开失败，请手动把上面链接复制到浏览器")
    print()
    print("  正常流程：")
    print("    1. 浏览器打开上面的链接 → 手机号 + 验证码登录 → 点「登录并使用 Trae」")
    print("    2. 地址栏变成 http://127.0.0.1:%d/authorize?refreshToken=... 才算成功" % LOGIN_PORT)
    print("       页面「无法访问」是**对的**，看地址栏，别看页面")
    print("    3. 把地址栏那条链接整条复制下来，粘回下面")
    print()
    print("  卡住了一直转圈 → 大多是 %d 端口被占，token 被接走了。" % LOGIN_PORT)
    print("    先 netstat -ano | findstr :%d 查 PID，结束它再 Ctrl+C 重跑。" % LOGIN_PORT)
    print()

    callback = ""
    while not callback:
        sys.stdout.flush()
        try:
            raw = input("  粘贴回调链接（Ctrl+C 取消）: ")
        except (EOFError, KeyboardInterrupt):
            print("\n已取消")
            return 1
        callback = re.sub(r"[^\x20-\x7e]", "", raw).strip()
        if not callback:
            print("  没读到内容，请再粘一次（要取消请按 Ctrl+C）")

    looks_like_url = callback.lower().startswith(("http://", "https://")) or "authorize" in callback
    info = parse_callback_url(callback) if looks_like_url else {}
    if not info.get("refreshToken"):
        info = {"refreshToken": callback, "accessToken": "", "uid": "",
                "nickname": "", "region": ""}

    rt = info["refreshToken"]
    if not rt:
        print("\n❌ 回调里没找到 refreshToken。请确认复制的是浏览器地址栏的完整链接。")
        return 1
    if len(rt) < 12 or re.search(r"\s", rt):
        print("\n❌ 取到的 refreshToken 看起来不对（长度 %d）。" % len(rt))
        return 1

    print("\n  正在用 refreshToken 换取 accessToken ...")
    ok, data, msg, _ = exchange_token(rt, info["uid"])
    if not ok:
        print("❌ 换 token 失败：%s" % msg)
        return 1

    refresh_token = data["refreshToken"]
    uid = info["uid"] or jwt_uid(data["accessToken"])
    gid, gname = get_user_info(data["accessToken"])
    uid = uid or gid
    nickname = info["nickname"] or gname

    record = {"name": nickname or ("账号%d" % (count_lines() + 1)),
              "refreshToken": refresh_token,
              "deviceId": device_id}
    line = json.dumps(record, ensure_ascii=False, separators=(",", ":"))

    print()
    print("=" * 66)
    print("  ✅ 登录成功")
    print("=" * 66)
    print("  账号  : %s" % (nickname or "-"))
    print("  UID   : %s" % (uid or "-"))
    print("  " + dev_label)
    print()
    print("  复制下面这一行，粘到金山表格「账号」列（A 列）对应单元格：")
    print()
    print("  " + line)
    print()
    if save_line(line):
        print("  已追加写入: %s（每行一个账号）" % OUTPUT_FILE)
    else:
        print("  （未写入文件，请手动复制上面的那一行）")
    print("=" * 66)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main(sys.argv[1:]))
    except KeyboardInterrupt:
        print("\n已取消")
        sys.exit(130)