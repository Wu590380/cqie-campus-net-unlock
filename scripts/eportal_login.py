#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
cqie-campus-net-unlock — Dr.COM eportal 校园网自动认证（实测环境：重庆工程学院 CQIE）

只用 Python 标准库，Windows / Linux 都能跑（路由器上建议直接用 curl 复刻）。

用法:
    python eportal_login.py login   --config config.local.json
    python eportal_login.py check   --config config.local.json
    python eportal_login.py watch   --config config.local.json --interval 60

务必注意（血泪坑）:
    这个门户要求**所有字段双重 encodeURIComponent**，见 docs/01-portal-protocol.md。
    只编一层，服务端会回 "密码不匹配" —— 不是密码错，是编码错。

安全说明:
    本脚本**不修改任何系统路由 / 网卡设置**。`--source-ip` 只是让 socket 绑定源地址：
    当电脑同时接了「手机共享」和「路由器」两条线时，用它可以强制认证流量走路由器那条路，
    默认路由（也就是你正在上网的那条）完全不动，所以不会断网。
"""
from __future__ import annotations

import argparse
import http.client
import json
import os
import re
import sys
import time
import urllib.parse

DEFAULT_PORTAL = "10.253.3.84"          # 实测门户地址（校园网内网，未认证时被劫持到这里）
DEFAULT_SERVICE = "[-1-1]系统默认服务[-1-1]"

# 未认证时随便访问一个 http 站点，会被劫持并下发带参数的 eportal 跳转
PROBES = (
    ("connect.rom.miui.com", "/generate_204"),
    ("www.msftconnecttest.com", "/connecttest.txt"),
    ("www.baidu.com", "/"),
)

ENTRY_RE = re.compile(r"eportal/index\.jsp\?([^\"'\s;]+)")


def dq(value: str) -> str:
    """复刻浏览器行为：encodeURIComponent(encodeURIComponent(x))，即双重编码。"""
    return urllib.parse.quote(urllib.parse.quote(value, safe=""), safe="")


def hex_to_ascii(hexstr: str) -> str:
    """认证回执 userIndex 是十六进制 ASCII，解码后 = <nasip>_<WAN侧IP>_<账号>。"""
    try:
        return bytes.fromhex(hexstr).decode("ascii", "replace")
    except Exception:
        return hexstr


class Portal:
    def __init__(self, host: str = DEFAULT_PORTAL, port: int = 80,
                 source_ip: str | None = None, timeout: float = 10.0):
        self.host = host
        self.port = port
        self.source_ip = source_ip
        self.timeout = timeout
        self.cookie = None

    # ---------- 底层 ----------
    def _conn(self, host=None, port=None):
        src = (self.source_ip, 0) if self.source_ip else None
        return http.client.HTTPConnection(host or self.host, port or self.port,
                                          timeout=self.timeout, source_address=src)

    def _do(self, method, path, body=None, host=None, port=None, keep_cookie=False):
        conn = self._conn(host, port)
        headers = {"User-Agent": "Mozilla/5.0", "Accept": "*/*",
                   "X-Requested-With": "XMLHttpRequest"}
        if self.cookie:
            headers["Cookie"] = self.cookie
        if body is not None:
            headers["Content-Type"] = "application/x-www-form-urlencoded; charset=UTF-8"
        try:
            conn.request(method, path, body=body, headers=headers)
            resp = conn.getresponse()
            raw = resp.read()
            status, location = resp.status, resp.getheader("Location")
            set_cookie = [v.split(";")[0] for k, v in resp.getheaders()
                          if k.lower() == "set-cookie"]
        finally:
            conn.close()

        text = ""
        for enc in ("gbk", "utf-8"):          # 门户页面是 GBK
            try:
                text = raw.decode(enc)
                break
            except UnicodeDecodeError:
                continue

        if keep_cookie and set_cookie:
            self.cookie = "; ".join(set_cookie)
        return status, location, text, set_cookie

    # ---------- 门户流程 ----------
    def discover_query(self):
        """探测未认证状态，返回门户下发的参数串（wlanuserip=..&wlanacname=..&...）。"""
        for host, path in PROBES:
            try:
                _, location, text, _ = self._do("GET", path, host=host, port=80)
            except Exception:
                continue
            for blob in (location or "", text[:4000]):
                m = ENTRY_RE.search(blob)
                if m:
                    return urllib.parse.unquote(m.group(1))
        return None

    def open_index(self, query: str):
        """打开认证页拿 JSESSIONID。少了参数会误报「设备未注册,请联系管理员」。"""
        self._do("GET", "/eportal/index.jsp?" + query, keep_cookie=True)
        return self.cookie

    def services(self, query: str):
        _, _, text, _ = self._do("POST", "/eportal/InterFace.do?method=getServices",
                                 body="queryString=" + dq(query))
        try:
            return json.loads(text)
        except Exception:
            return {}

    def pick_service(self, query: str, fallback: str | None = None) -> str:
        info = self.services(query)
        m = re.findall(r"selectService\('([^']*)'", info.get("serviceContent", "") or "")
        if m:
            return m[0]
        m = re.findall(r"value='([^']*)'", info.get("defaultService", "") or "")
        if m and m[0]:
            return m[0]
        return fallback or DEFAULT_SERVICE

    def login(self, query: str, account: str, password: str, service: str | None = None):
        self.open_index(query)
        if service is None:
            service = self.pick_service(query)
        body = "&".join([
            "userId=" + dq(account),
            "password=" + dq(password),
            "service=" + dq(service),
            "queryString=" + dq(query),
            "operatorPwd=",
            "operatorUserId=",
            "validcode=",
            "passwordEncrypt=" + dq("false"),
        ])
        _, _, text, _ = self._do("POST", "/eportal/InterFace.do?method=login", body=body)
        try:
            return json.loads(text)
        except Exception:
            return {"result": "fail", "message": text[:300]}

    def online_user_info(self):
        _, _, text, _ = self._do("POST", "/eportal/InterFace.do?method=getOnlineUserInfo",
                                 body="")
        try:
            return json.loads(text)
        except Exception:
            return {"result": "fail", "message": text[:300]}


# ---------- CLI ----------
def load_config(path):
    cfg = {"portal": DEFAULT_PORTAL, "port": 80, "service": None, "source_ip": None}
    if path:
        with open(path, encoding="utf-8") as fh:
            cfg.update(json.load(fh))
    for key in ("account", "password"):
        env = os.environ.get("EPORTAL_" + key.upper())
        if env:
            cfg[key] = env
    return cfg


def build_portal(cfg) -> Portal:
    return Portal(host=cfg.get("portal") or DEFAULT_PORTAL,
                  port=int(cfg.get("port") or 80),
                  source_ip=cfg.get("source_ip") or None,
                  timeout=float(cfg.get("timeout") or 10))


def cmd_check(cfg):
    info = build_portal(cfg).online_user_info()
    ok = info.get("result") == "success"
    print(json.dumps(info, ensure_ascii=False, indent=1))
    print("\n[在线]" if ok else "\n[未在线 / 信息不完整]")
    return 0 if ok else 1


def cmd_login(cfg):
    portal = build_portal(cfg)
    query = portal.discover_query()
    if not query:
        sys.exit("拿不到门户跳转参数：确认已插到未认证的校园网 WAN 路径上"
                 "（多线路时用 --source-ip 绑定路由器那条线的本地地址）")
    result = portal.login(query, cfg["account"], cfg["password"], cfg.get("service"))
    print(json.dumps(result, ensure_ascii=False, indent=1))
    if result.get("result") == "success":
        print("userIndex 解码:", hex_to_ascii(result.get("userIndex") or ""))
        print("认证成功：校园网现在把这台路由器当成 1 台设备。")
        return 0
    print("认证失败。若提示『密码不匹配』，先确认双重编码（见 docs/01-portal-protocol.md）。")
    return 1


def cmd_watch(cfg):
    interval = int(cfg.get("interval") or 60)
    portal = build_portal(cfg)
    while True:
        info = portal.online_user_info()
        if info.get("result") != "success":
            print("[%s] 掉线，重新认证…" % time.strftime("%H:%M:%S"))
            query = portal.discover_query()
            if query:
                print(json.dumps(portal.login(query, cfg["account"], cfg["password"],
                                              cfg.get("service")), ensure_ascii=False))
        else:
            print("[%s] 在线: %s" % (time.strftime("%H:%M:%S"), info.get("userIp")))
        time.sleep(interval)


def main(argv=None):
    parser = argparse.ArgumentParser(description="Dr.COM eportal 校园网自动认证")
    parser.add_argument("action", choices=["login", "check", "watch"])
    parser.add_argument("--config", help="配置文件（见 config.example.json）")
    parser.add_argument("--interval", type=int, default=60, help="watch 模式的轮询秒数")
    parser.add_argument("--source-ip", help="绑定源地址，多线路时强制走校园网那条")
    args = parser.parse_args(argv)

    cfg = load_config(args.config)
    if args.source_ip:
        cfg["source_ip"] = args.source_ip
    if args.interval and args.action == "watch":
        cfg["interval"] = args.interval
    if args.action in ("login", "watch") and not (cfg.get("account") and cfg.get("password")):
        sys.exit("缺少账号密码：请在配置文件里填 account/password，"
                 "或用环境变量 EPORTAL_ACCOUNT / EPORTAL_PASSWORD")

    return {"check": cmd_check, "login": cmd_login, "watch": cmd_watch}[args.action](cfg)


if __name__ == "__main__":
    raise SystemExit(main())
