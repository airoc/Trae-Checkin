# Trae 每日自动签到（金山云文档版）

基于金山文档 AirScript 的 Trae 免费积分每日自动签到，不用服务器、不用本地常驻，网页 / 手机都能跑。

## 特性

- 多账号，表格逐行管理
- refresh_token 轮换后自动写回表格，长期无人值守也不失效
- 三种推送：Server酱 / PushPlus / 企业微信，填哪个推哪个，可多填
- 随机延迟错峰（单次签到 ≤10 秒、多账号间隔 30~50 秒），避免多账号挤在同一秒触发风控

## 目录结构

```
├── trae_gettoken.py                 # 本地跑一次，登录拿 token
├── Trae签到-金山文档AirScript.js       # 签到脚本（粘进金山文档）
├── Trae签到-金山文档空表格.xlsx        # 表格模板
├── tokens.txt                         # 运行后自动生成，存拿到的 token（勿提交）
└── LICENSE
```

## 快速开始

### 1. 拿 token

在一台装过 Trae 客户端、并且登录过的 Windows 电脑上：

```bash
python trae_gettoken.py
```

脚本会自动读本机真实设备号 + 打开浏览器登录，成功后打印一行 JSON，同时追加写入 `tokens.txt`：

```
{"name":"xxx","refreshToken":"xxxxxx","deviceId":"3124143766407755"}
```

手动指定设备号（比如在没装客户端的机器上跑）：

```bash
python trae_gettoken.py --device-id 3124143766407755
```

### 2. 建表格

把 `Trae签到-金山文档空表格.xlsx` 导入金山文档，或照着下面这个列布局自己建：

| 列 | 内容 | 说明 |
|---|---|---|
| A | 账号 JSON | `{"refreshToken":"...","deviceId":"..."}`，一行一账号 |
| B | 是否签到 | 填「是」才签 |
| C | Server酱 token | 留空不推 |
| D | PushPlus token | 留空不推 |
| E | 企业微信 key | 群机器人 webhook 的 key 或完整地址，留空不推 |
| F | 签到结果 | 自动写回，不用管 |

### 3. 部署 AirScript

金山文档 → 效率 → 高级开发 → AirScript 脚本编辑器：

1. 新建脚本，把 `Trae签到-金山文档AirScript.js` 整段粘贴进去（账号行数会自动识别，不用改）；
2. 保存，新建一个「定时任务」每天跑一次（避开整点）。

## 两条前提（重要）

1. 设备号必须是客户端真实注册的那串数字，自己编的会被服务端风控拒成 9074；
2. 一个设备号一天只能签一个账号，所以多账号要用多台机器、各取各的设备号。

## 常见问题

- **9074 风控拦截**：设备号不对。用 `trae_gettoken.py` 在装过客户端的机器上重新登录。
- **1001/1002 鉴权失败**：refresh_token 失效了，重新跑 `trae_gettoken.py`，把新 JSON 填回 A 列。
- **某天没签上**：脚本自带随机延迟错峰，当天没跑上/被风控没签成，等下次定时任务再跑一次即可。

## 致谢

签到接口逻辑来自 [trae-checkin](https://github.com/wallechfox/Trae-Checkin) 项目，表格脚本结构参照阿里云盘每日签到 AirScript 模版改造。

## License

[MIT](./LICENSE)

## 免责声明

本脚本仅用于个人学习与自动化签到，请遵守 Trae 相关服务条款，使用产生的一切后果由使用者自行承担。