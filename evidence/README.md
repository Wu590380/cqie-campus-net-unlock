# evidence · 实测回执样例（全部已脱敏）

这里放的是**真实回执的结构**，用来支撑 README / docs 里的结论。

## 脱敏规则

| 原始数据 | 处理 |
|---|---|
| 学号/账号 | → `<账号>` |
| 密码 | 从不记录 |
| 路由器 MAC | → `<路由器MAC>` |
| 校园网分配给 WAN 的 IP | → `<10.x.x.x>` |
| 公网出口 IP | → `183.69.x.x` / `123.147.x.x`（只留网段前缀） |
| 门户下发的 `wlanuserip/mac/nasip` 等十六进制参数 | → `<hex>` 占位（这些值每次跳转都会变） |

## 采集方法

```bash
# 认证回执（脚本会打印）
python eportal_login.py login --config config.local.json

# 在线会话
python eportal_login.py check --config config.local.json
```

## 文件

- `sample-login-success.json` —— `InterFace.do?method=login` 成功后返回的字段结构，以及 `userIndex` 的解码格式。
- `sample-online-user-info.json` —— `InterFace.do?method=getOnlineUserInfo` 返回的会话详情（含门户公告原文），这是「认证主体是路由器」的直接证据。

> 说明：回执里的 `result` 偶尔返回 `"wait"`（门户自身的时序/提示），此时字段其实已经齐了；判断是否在线以 `userIp` / `userMac` 是否存在为准更稳。
