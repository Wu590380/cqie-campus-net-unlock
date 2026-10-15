# 01 · Dr.COM eportal 协议细节（实测记录）

> 实测环境：重庆工程学院校园网，2026-10。门户地址 `10.253.3.84`（自服务 `10.253.3.83:8080`）。
> 所有个人数据（账号/密码/MAC/分配 IP）已脱敏为占位符。

## 1. 门户与静态资源

| 路径 | 说明 |
|---|---|
| `http://10.253.3.84/eportal/index.jsp?<门户下发的参数>` | 认证页，标题「上网认证」，**必须带参数** |
| `http://10.253.3.84:8080/eportal/interface/index_files/pc/login_bch.js` | 登录逻辑（前端在此**双重编码**字段） |
| `http://10.253.3.84:8080/eportal/interface/index_files/js/AuthInterFace.js` | 调接口的封装（`login`/`keepalive`/`getOnlineUserInfo`…） |
| `http://10.253.3.83:8080/selfservice/` | 自助服务（查/下线设备、绑运营商账号） |

未认证时，访问任意 http 站点会被注入这样一段跳转脚本（值都是十六进制编码的字符串，**原样回传即可**）：

```html
<script>
top.self.location.href='http://10.253.3.84/eportal/index.jsp
  ?wlanuserip=<hex>
  &wlanacname=<hex>
  &ssid=<hex>
  &nasip=<hex>
  &mac=<hex>
  &t=wireless-v2
  &url=<hex>';
</script>
```

| 参数 | 含义 |
|---|---|
| `wlanuserip` | 认证客户端（= 路由器 WAN 侧）的 IP |
| `mac` | 认证客户端的 MAC |
| `nasip` / `wlanacname` | 网关/接入设备标识 |
| `ssid` | 无线 SSID 标识 |
| `t` | 终端类型（实测 `wireless-v2`） |
| `url` | 被拦截前的原始目标 |

## 2. 接口清单（`/eportal/InterFace.do?method=<name>`）

| method | 方法 | 关键字段 | 返回 |
|---|---|---|---|
| `getServices` | POST | `queryString` | `defaultService` / `serviceContent`（服务列表 HTML，`selectService('<值>',…)`） |
| `login` | POST | `userId` `password` `service` `queryString` `operatorPwd` `operatorUserId` `validcode` `passwordEncrypt` | `{"result":"success","userIndex":"<hex>","keepaliveInterval":0,…}` |
| `getOnlineUserInfo` | POST | 无 | 会话详情（见下节）；离线时 `result:"fail"` 且 `message:"获取用户信息失败，用户可能已经下线"` |
| `keepalive` | POST | `userIndex` | 保活（本环境 `keepaliveInterval=0`，实测未用到） |
| `logout` | POST | `userIndex` | 主动下线 |

> 会话建立：先 `GET /eportal/index.jsp?<参数>` 拿 `JSESSIONID`，再带着这个 Cookie 调 `InterFace.do` 系列接口。

## 3. `getOnlineUserInfo` 回执（脱敏样例）

```json
{
  "result": "wait",
  "message": "用户信息不完整，请稍后重试",
  "userName": "<账号>",
  "userId": "<账号>",
  "userIp": "<校园网分配给路由器 WAN 的 10.x 地址>",
  "userMac": "<路由器 MAC>",
  "service": "[-1-1]系统默认服务[-1-1]",
  "realServiceName": "[-1-1]系统默认服务[-1-1]",
  "announcement": "<门户公告 HTML，见第 6 节>",
  "welcomeTip": "晚上好"
}
```

要点：

- `userMac` 是**路由器的 MAC**（在路由器 LAN 的 ARP 表里能看到同一个 MAC 对应它的网关地址）→ 认证主体是路由器；
- `userIp` 是校园网分给**路由器 WAN** 的内网地址 → 与终端无关；
- `result` 偶尔回 `"wait"` 而字段已经齐了（门户自身的时序问题），判断在线与否以 `userIp`/`userMac` 是否存在为准更稳。

## 4. `login` 回执与 `userIndex` 解码

```json
{
  "userIndex": "3c...<hex>",
  "result": "success",
  "forwordurl": null,
  "keepaliveInterval": 0,
  "validCodeUrl": ""
}
```

`userIndex` 是**十六进制 ASCII**，解码后形如：

```
<nasip>_<认证后的 WAN 侧 IP>_<账号>
```

（实测：第一段与跳转参数里的 `nasip` 一致，第二段是认证客户端的 WAN 侧地址，第三段是账号。）脚本 `login` 会顺手打印解码结果，方便确认「谁被认证了」。

## 5. 双重编码：这个门户最容易踩的坑

门户前端 `login_bch.js` 里，**每个字段都被编码两次**：

```javascript
var queryString = encodeURIComponent(encodeURIComponent(getQueryString()));
var userId      = encodeURIComponent(encodeURIComponent(username));
var password    = encodeURIComponent(encodeURIComponent(password));
var service     = encodeURIComponent(encodeURIComponent(document.getElementById("net_access_type").value));
```

然后 `AuthInterFace.js` 只是把值拼进 body：

```javascript
var content = "userId=" + userId + "&password=" + password + "&service=" + service
            + "&queryString=" + queryString + "&operatorPwd=" + operatorPwd
            + "&operatorUserId=" + operatorUserId + "&validcode=" + validcode
            + "&passwordEncrypt=" + passwordEncrypt;
```

服务端会解码两次，所以你要是只编一层，`%` 之类的字符就会在第二次解码时被吃掉/变形：

| 做法 | 密码 `Ab%12` 实际发出去的内容 | 服务端解码两次后得到 | 结果 |
|---|---|---|---|
| 只编一层（错） | `Ab%2512` | `Ab%12`→ 再解一次 → 异常/错值 | `密码不匹配,请输入正确的密码!` |
| 双重编码（对） | `Ab%252512` | `Ab%12` → `Ab%12` | `result: success` |

正确的请求体（`dq()` = 双重编码）示例：

```
userId=<dq(账号)>
&password=<dq(密码)>
&service=<dq([-1-1]系统默认服务[-1-1])>
&queryString=<dq(wlanuserip=..&wlanacname=..&ssid=..&nasip=..&mac=..&t=..&url=..)>
&operatorPwd=
&operatorUserId=
&validcode=
&passwordEncrypt=<dq(false)>
```

`passwordEncrypt=false` 表示密码明文提交（本环境前端默认走这个分支；`true` 分支是 RSA 公钥加密，本方案用不到）。

## 6. 门户公告原文（2026-10 抓取）

> 1. 本认证系统使用学校智慧校园平台统一的用户名和密码，忘记密码请点击 http://i.cqie.edu.cn/ 重置密码。
> 2. 如果您已办理中国电信校园网帐号，登录时请选择**中国电信**出口；没有办理中国电信校园网帐号的请选择**校园网**出口。
> 3. 绑定运营商账户时，新用户请先选服务「校园网」连接，再去 自助服务（`10.253.3.83:8080/selfservice/`）进行绑定。
> 4. **每个账户可以同时使用 2 个设备。**
> 5. **访问校内资源不需要认证，请直接访问。**

第 4 条就是本文要处理的那条限制；第 1、3 条解释了「为什么密码不是路由器后台密码」；第 5 条说明校内资源本来就不用认证。

## 7. 用 curl 复刻（不想跑 Python 时）

```bash
# 0) 拿门户参数（未认证时）
curl -s -i http://www.baidu.com/ | grep -o "eportal/index.jsp?[^'\"]*"

# 1) 打开认证页拿 Cookie（把 <QS> 换成上一步拿到的参数串）
curl -s -c cookie.txt "http://10.253.3.84/eportal/index.jsp?<QS>" -o /dev/null

# 2) 登录（注意每个值都要双重编码，这里为可读性写成示意）
curl -s -b cookie.txt -X POST \
  "http://10.253.3.84/eportal/InterFace.do?method=login" \
  --data "userId=<dq>&password=<dq>&service=<dq>&queryString=<dq>&operatorPwd=&operatorUserId=&validcode=&passwordEncrypt=<dq>"
```

双重编码可以直接用 Python 生成：`python -c "import urllib.parse as u;print(u.quote(u.quote('要编码的值',safe=''),safe=''))"`。
