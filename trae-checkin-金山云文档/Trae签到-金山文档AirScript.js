// ============================================================================
//  Trae 每日自动签到 · 金山文档 AirScript 版
//  参照「阿里云签到模版」改造，签到接口与 trae-checkin 项目对齐
// ============================================================================
//
// 【表格列布局】（第 1 行是表头，账号从第 2 行开始，每行一个账号）
//   A  账号 JSON       一行一个账号，格式：{"refreshToken":"...","deviceId":"..."}
//                      直接复制 trae_gettoken.py 输出的那一行 JSON 即可
//   B  是否签到        填「是」才签，其它/空 跳过
//   C  Server酱 token  填了就推，留空不推
//   D  PushPlus token  填了就推，留空不推
//   E  企业微信 key    填了就推，留空不推（群机器人 webhook 的 key，或完整地址都行）
//   F  签到结果        脚本自动写回，平时不用管
//
// 【必须记住的两条前提】（很重要）
//   1. 每个账号要有「自己的」真实设备号，自动编的号会被服务端风控拒成 9074。
//   2. 一个设备号一天只能签一个账号（限额按设备算）。所以多账号 = 多设备号，
//      每个号都得单独在装过客户端的机器上取。
//
// 【怎么运行】
//   金山文档 → 效率 → 高级开发 → AirScript 脚本编辑器，把本文件整个粘贴进去，
//   再建一个「定时任务」每天跑一次（避开整点，建议 08:00~10:00 随机一点）。
//   账号行数、签到前等待（≤10 秒）、多账号间隔（30~50 秒）都已内置，不用改。

var date = new Date().getFullYear() + "-" + (new Date().getMonth() + 1).toString().padStart(2, '0') + "-" + new Date().getDate().toString().padStart(2, '0')

// ── 延迟参数（已内置，一般不用改）──────────────────────
// 签到前随机等待 0~10 秒；多账号之间额外随机间隔 30~50 秒

// ── Trae 接口常量（不用改）─────────────────────────────
var CLIENT_ID = "en1oxy7wnw8j9n";
var APP_VERSION = "0.1.43";
var UA = "Trae/" + APP_VERSION;
var EP_EXCHANGE = "https://api.trae.com.cn/cloudide/api/v3/trae/oauth/ExchangeToken";
var EP_STATUS = "https://api.trae.cn/trae/api/v2/ug/checkin_credits/status";
var EP_CLAIM = "https://api.trae.cn/trae/api/v2/ug/checkin_credits/claim";
var EP_USAGE = "https://api.trae.cn/trae/api/v2/pay/ide_user_ent_usage";              // 查真实积分余额
var EP_ENTITLE = "https://api.trae.cn/trae/api/v2/pay/user_current_entitlement_list"; // 备选
var REQ_BODY = JSON.stringify({ "req_source": 2 });   // SOLO 谱系契约，改成 1 或空会被判 9074

// ── 列号变量 ───────────────────────────────────────────
var tokenColumn = "A";       // 账号 JSON（含 refreshToken + deviceId）
var qiandaoColumn = "B";     // 是否签到
var serverchanColumn = "C";  // Server酱 token
var pushplusColumn = "D";    // PushPlus token
var qywxColumn = "E";        // 企业微信群机器人 key（或完整 webhook）
var signinresult = "F";      // 签到结果

function sleep(d) {
    for (var t = Date.now(); Date.now() - t <= d;);
}

function ugHeaders(token, deviceId) {
    var h = {
        "Authorization": "Cloud-IDE-JWT " + token,
        "X-User-Region": "CN",
        "Content-Type": "application/json",
        "Accept": "application/json",
        "User-Agent": UA
    };
    if (deviceId) h["x-device-id"] = deviceId;
    return h;
}

// 用 refresh_token 换 access_token，返回 {access_token, refresh_token, error}
function exchangeToken(refresh_token) {
    try {
        var resp = HTTP.post(EP_EXCHANGE,
            JSON.stringify({ "ClientID": CLIENT_ID, "RefreshToken": refresh_token, "ClientSecret": "-", "UserID": "" }),
            { headers: { "Content-Type": "application/json", "Accept": "application/json", "User-Agent": UA }, timeout: 30000 });
        var data = resp.json();
    } catch (e) {
        return { error: "刷新 token 请求失败：" + e.message };
    }
    var err = (data.ResponseMetadata && data.ResponseMetadata.Error) || {};
    var res = data.Result || data.data || {};
    var access_token = res.Token || res.AccessToken || "";
    if (!access_token) {
        return { error: "服务端拒绝：" + (err.Code || "") + " " + (err.Message || "") };
    }
    return { access_token: access_token, refresh_token: res.RefreshToken || refresh_token };
}

// 查签到状态，返回 {checked, enable, credits, code}
function queryStatus(token, deviceId) {
    var data = HTTP.post(EP_STATUS, REQ_BODY, { headers: ugHeaders(token, deviceId), timeout: 30000 }).json();
    var root = (data && data.data) || data || {};
    return {
        checked: !!(root.checked_in || root.checkedIn),
        enable: root.enable !== false,
        credits: root.credits,
        code: data ? data.code : -1
    };
}

// 签到，返回 {success, code, msg, gained}
function doClaim(token, deviceId) {
    var data = HTTP.post(EP_CLAIM, REQ_BODY, { headers: ugHeaders(token, deviceId), timeout: 30000 }).json();
    var root = (data && data.data) || data || {};
    var gained = root.points || root.credits;
    return {
        success: (data && data.code === 0),
        code: (data && data.code != null) ? data.code : -1,
        msg: (data && data.message) || "",
        gained: gained
    };
}

// 查真实积分余额：先 ide_user_ent_usage，不行再 user_current_entitlement_list，返回数字或 null
function queryUsage(token, deviceId) {
    var urls = [EP_USAGE, EP_ENTITLE];
    var bodies = ["{}", JSON.stringify({ "require_usage": true })];
    for (var i = 0; i < urls.length; i++) {
        try {
            var data = HTTP.post(urls[i], bodies[i], { headers: ugHeaders(token, deviceId), timeout: 30000 }).json();
            var root = (data && data.data) || data || {};
            var packs = root.user_entitlement_pack_list || root.userEntitlementPackList;
            if (packs && packs.length) {
                var total = 0;
                for (var j = 0; j < packs.length; j++) {
                    var p = packs[j] || {};
                    var quota = p.entitlement_base_info || p;
                    var limit = (quota.credits_limit != null ? quota.credits_limit : quota.creditsLimit) || 0;
                    var usage = p.usage || {};
                    var used = (usage.credits_amount != null ? usage.credits_amount : usage.creditsAmount) || 0;
                    total += Math.max(parseFloat(limit) - parseFloat(used), 0);
                }
                if (total > 0) return total;
            }
            var us = root.usage_summary || root.usageSummary;
            if (us) {
                var t = parseFloat(us.total_amount || 0);
                var u = parseFloat(us.consumed_amount || 0);
                if (t > 0) return t - u;
            }
        } catch (e) {
            // 忽略，试下一个接口
        }
    }
    return null;
}

// 格式化余额：千分位 + 去尾 0（对齐 Python 版 _fmt）
function fmtBalance(v) {
    try {
        var n = parseFloat(v);
        if (isNaN(n)) return String(v);
        var neg = n < 0; n = Math.abs(n);
        var s = n.toFixed(2);
        s = s.replace(/0+$/, "").replace(/\.$/, "");
        var parts = s.split(".");
        parts[0] = parts[0].replace(/\B(?=(\d{3})+(?!\d))/g, ",");
        s = parts.join(".");
        return (neg ? "-" : "") + (s || "0");
    } catch (e) {
        return String(v);
    }
}

// 统计账号行：从第 2 行往下，到第一个空行或非 JSON 内容为止
function countAccounts() {
    var r = 2;
    while (r <= 500) {
        var t = (Application.Range("A" + r).Text || "").trim();
        if (t == "" || t.charAt(0) != "{") break;
        r++;
    }
    return r - 1;
}

// 当前北京时间字符串（用于通知）
function nowBJ() {
    var t = new Date();
    return t.getFullYear() + "-" + (t.getMonth() + 1).toString().padStart(2, '0') + "-" + t.getDate().toString().padStart(2, '0')
        + " " + t.getHours().toString().padStart(2, '0') + ":" + t.getMinutes().toString().padStart(2, '0') + ":" + t.getSeconds().toString().padStart(2, '0');
}

// 单账号推送：签完一个立即发一个（用该行自己的 C/D/E 通道）
function sendNotify(sc, pp, wx, text) {
    var title = "🤖 Trae 每日签到";
    if (sc != "") {
        HTTP.post("https://sctapi.ftqq.com/" + sc + ".send",
            { title: title, desp: text },
            { headers: { "Content-Type": "application/json" }, timeout: 60000 });
    }
    if (pp != "") {
        HTTP.post("https://www.pushplus.plus/send",
            { token: pp, title: title, content: text.replace(/\n/g, "<br>"), channel: "wechat", template: "html" },
            { headers: { "Content-Type": "application/json" }, timeout: 60000 });
    }
    if (wx != "") {
        var key = wx.split("key=").pop();
        HTTP.post("https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=" + key,
            JSON.stringify({ "msgtype": "text", "text": { "content": text } }),
            { headers: { "Content-Type": "application/json" }, timeout: 60000 });
    }
}

// ── 主循环 ─────────────────────────────────────────────
var lastRow = countAccounts();
console.log("共识别到 " + (lastRow - 1) + " 个账号（从第 2 行起）");
if (lastRow < 2) {
    console.log("没有在 A 列第 2 行起读到账号 JSON，请确认 A 列已填入 token、且不在「使用说明」区域内");
}
for (let row = 2; row <= lastRow; row++) {
    // 多账号之间随机间隔 30~50 秒（第一个账号不等待）
    if (row > 2) {
        Time.sleep(30000 + Math.floor(Math.random() * 20000));
    }
    var acc = {};
    var refresh_token = "";
    var deviceId = "";
    var accRaw = Application.Range(tokenColumn + row).Text;
    try {
        acc = JSON.parse(accRaw);
        refresh_token = acc.refreshToken || acc.refresh_token || "";
        deviceId = acc.deviceId || acc.device_id || "";
    } catch (e) {
        refresh_token = accRaw;   // 不是 JSON，就当纯 refreshToken（此时没有 deviceId）
    }
    var qiandao = Application.Range(qiandaoColumn + row).Text;
    var servertoken = Application.Range(serverchanColumn + row).Text;
    var pushtoken = Application.Range(pushplusColumn + row).Text;
    var qywxtoken = Application.Range(qywxColumn + row).Text;
    if (refresh_token == "") {
        continue;   // 该行没填 token，跳过
    }

    var name = acc.name || ("账号" + (row - 1));

    if (deviceId == "") {
        console.log(name + " 账号 JSON 里缺 deviceId，跳过（用 trae_gettoken.py 重新登录拿完整 JSON）");
        continue;
    }

    if (qiandao != "是") {
        console.log(name + " 签到开关未打开，跳过");
        continue;
    }

    if (Application.Range(signinresult + row).Text == date + "已签到") {
        console.log(name + " " + date + " 已签到");
        var oneText = "🤖 Trae 每日签到\n🕒 北京时间：" + nowBJ() + "\n☑️ " + name + "(" + (acc.uid || "-") + ")：已签到 | 今日已签到";
        sendNotify(servertoken, pushtoken, qywxtoken, oneText);
        console.log(name + " 已推送通知");
        continue;
    }

    // 签到前随机等待 0~10 秒（轻微错峰，不耽误时间）
    Time.sleep(Math.floor(Math.random() * 10000));

    // 1) refresh_token 换 access_token
    var ex = exchangeToken(refresh_token);
    if (ex.error) {
        console.log("单元格【" + tokenColumn + row + "】" + ex.error + "（需重新用 trae_gettoken.py 登录拿 refresh_token）");
        continue;
    }
    var access_token = ex.access_token;

    // 刷新后若 refresh_token 轮换了，更新 JSON 里的 refreshToken 再写回（保住 deviceId，别把整格改成纯 token）
    if (ex.refresh_token && ex.refresh_token != refresh_token) {
        acc.refreshToken = ex.refresh_token;
        delete acc.refresh_token;   // 兼容下划线命名，避免新旧并存
        Application.Range(tokenColumn + row).Value2 = JSON.stringify(acc);
        console.log(name + " refresh_token 已刷新并写回");
    }

    var uid = acc.uid || "-";
    var r = { icon: "❌", name: name, uid: uid, status: "失败", credits: "-", detail: "" };
    try {
        var st = queryStatus(access_token, deviceId);

        if (st.code == 1001 || st.code == 1002) {
            r.icon = "🔑"; r.status = "鉴权失败";
            r.detail = "token 失效，需重新用 trae_gettoken.py 登录拿 refresh_token 填回 A 列";
            console.log(name + " 鉴权失败");
        } else if (st.checked) {
            var pts = queryUsage(access_token, deviceId);
            r.icon = "☑️"; r.status = "已签到";
            r.credits = pts != null ? fmtBalance(pts) : "-";
            r.detail = "今日已签到，积分余额 " + (pts != null ? fmtBalance(pts) : (st.credits != null ? fmtBalance(st.credits) : "-"));
            Application.Range(signinresult + row).Value2 = date + "已签到";
            console.log(name + " 已签到，" + r.detail);
        } else if (st.enable === false) {
            r.icon = "🚫"; r.status = "未开放";
            r.detail = "该账号未开放签到(enable=false)";
            console.log(name + " 未开放签到");
        } else {
            var cl = doClaim(access_token, deviceId);
            if (cl.success) {
                var pts2 = queryUsage(access_token, deviceId);
                r.icon = "✅"; r.status = "签到成功";
                r.credits = pts2 != null ? fmtBalance(pts2) : (cl.gained != null ? fmtBalance(cl.gained) : "-");
                var tail = cl.gained != null ? "，本次 +" + fmtBalance(cl.gained) : "";
                r.detail = "签到成功" + tail + "，当前余额 " + (pts2 != null ? fmtBalance(pts2) : "-");
                Application.Range(signinresult + row).Value2 = date + "已签到";
                console.log(name + " " + r.detail);
            } else if (cl.code == 9095) {
                var pts3 = queryUsage(access_token, deviceId);
                r.icon = "☑️"; r.status = "已签到";
                r.credits = pts3 != null ? fmtBalance(pts3) : "-";
                r.detail = "今日已签到(" + (cl.msg || "9095") + ")";
                Application.Range(signinresult + row).Value2 = date + "已签到";
                console.log(name + " 已签到");
            } else if (cl.code == 9074) {
                r.icon = "⏳"; r.status = "待重试";
                r.detail = "设备号不对，需在装过客户端的机器上用 trae_gettoken.py 重新登录（当前：" + deviceId + "）";
                console.log(name + " 风控拦截(9074)");
            } else {
                r.icon = "❌"; r.status = "失败";
                r.detail = "code=" + cl.code + " " + (cl.msg || "");
                console.log(name + " 签到失败，" + r.detail);
            }
        }
    } catch (e) {
        r.icon = "❌"; r.status = "异常";
        r.detail = e.message;
        console.log("单元格【" + tokenColumn + row + "】签到出错：" + e.message);
    }
    var oneText = "🤖 Trae 每日签到\n🕒 北京时间：" + nowBJ() + "\n" + r.icon + " " + r.name + "(" + uid + ")：" + r.status + " | " + r.detail;
    sendNotify(servertoken, pushtoken, qywxtoken, oneText);
    console.log(name + " 已推送通知");
}

console.log("全部处理完成");