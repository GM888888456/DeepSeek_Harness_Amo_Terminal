#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""五个面板的一致性体检（只读，不改文件）。

查的都是「会让人看得见」的问题，不评判配色审美、不重设主题：

1. `terminal-base.css` 五份是否一致（终端那份是源，另外四个插件各存一份副本，
   因为 AstrBot 每个插件自己托管自己的静态文件，跨插件引用拿不到）。
2. 每个页面 `<link>` 的 `?v=` 是否统一——版本号不一致，改一次皮肤就有面板还在用旧缓存。
3. 每个页面有没有 viewport（手机上不设会整体缩放错位）。
4. JS 里 `getElementById("x")` 绑的 id，页面上是否真的存在（删控件最容易留下这种悬空引用，
   一点就报错，整个面板脚本都可能停）。
5. 页面引用的本地 css/js 是否存在。

用法：

    python3 tools/panel_audit.py            # 打印问题清单
    python3 tools/panel_audit.py --json     # 机器可读
退出码：0 = 干净，1 = 有问题。
"""

from __future__ import annotations

import hashlib
import io
import json
import os
import re
import sys

PLUGINS = ["DeepSeek_Harness_Amo_Terminal", "DeepSeek_Harness_Amo_Image",
           "DeepSeek_Harness_Amo_Finance", "DeepSeek_Harness_Amo_Market",
           "DeepSeek_Harness_Amo_Medical"]
SOURCE_PLUGIN = "DeepSeek_Harness_Amo_Terminal"
BASE_CSS = "terminal-base.css"

#: 已知且有意容忍的悬空 id（代码里有 null 判断，缺了也不会报错），写清原因免得以后当成 bug。
TOLERATED = {
    # 8.0.0 精简面板时删掉了页脚 #counts，JS 那边专门判过空
    "DeepSeek_Harness_Amo_Terminal": {"counts"},
}


def _root():
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _page_path(root, plugin):
    return os.path.join(root, "..", plugin, "views", "dashboard", "index.html")


def _digest(path):
    with open(path, "rb") as handle:
        return hashlib.md5(handle.read()).hexdigest()


def audit(root=None):
    root = root or _root()
    findings = []
    pages = {}
    css_digest = {}

    for plugin in PLUGINS:
        page = _page_path(root, plugin)
        if not os.path.isfile(page):
            findings.append({"level": "error", "plugin": plugin,
                             "what": "没有 views/dashboard/index.html"})
            continue
        pages[plugin] = io.open(page, encoding="utf-8").read()
        css = os.path.join(os.path.dirname(page), BASE_CSS)
        if os.path.isfile(css):
            css_digest[plugin] = _digest(css)
        elif plugin != SOURCE_PLUGIN:
            findings.append({"level": "error", "plugin": plugin, "what": "缺少 " + BASE_CSS})

    if css_digest:
        baseline = css_digest.get(SOURCE_PLUGIN) or list(css_digest.values())[0]
        for plugin, digest in css_digest.items():
            if digest != baseline:
                findings.append({"level": "error", "plugin": plugin,
                                 "what": "%s 与其他副本不一致（%s ≠ %s）"
                                         % (BASE_CSS, digest[:8], baseline[:8])})

    versions = {}
    for plugin, html in pages.items():
        match = re.search(r"terminal-base\.css\?v=([0-9]+)", html)
        if match:
            versions[plugin] = match.group(1)
    if len(set(versions.values())) > 1:
        findings.append({"level": "error", "plugin": "all",
                         "what": "terminal-base.css 的 ?v= 不一致：%s" % versions})

    for plugin, html in pages.items():
        if "width=device-width" not in html:
            findings.append({"level": "error", "plugin": plugin, "what": "缺 viewport meta"})

        # 元素 id：静态写在 HTML 里的，加上 JS 运行时创建的（el.id = "x" /
        # setAttribute("id", "x") / innerHTML 里拼的 id="x"），都算「存在」。
        ids = set(re.findall(r'\bid="([^"]+)"', html))
        ids |= set(re.findall(r'\.id\s*=\s*"([^"]+)"', html))
        ids |= set(re.findall(r"setAttribute\(\s*[\"']id[\"']\s*,\s*[\"']([^\"']+)", html))
        bound = set(re.findall(r'getElementById\("([^"]+)"\)', html))
        bound |= set(re.findall(r"getElementById\('([^']+)'\)", html))
        tolerated = TOLERATED.get(plugin, set())
        for name in sorted(n for n in bound if n not in ids and n not in tolerated):
            findings.append({"level": "error", "plugin": plugin,
                             "what": "JS 绑定了不存在的元素 id：%s" % name})

        folder = os.path.dirname(_page_path(root, plugin))
        for ref in re.findall(r'(?:href|src)="\./([^"?]+)', html):
            if not os.path.isfile(os.path.join(folder, ref)):
                findings.append({"level": "error", "plugin": plugin,
                                 "what": "引用了不存在的文件：%s" % ref})

    return findings


def main(argv):
    findings = audit()
    if "--json" in argv:
        print(json.dumps(findings, ensure_ascii=False, indent=2))
    elif not findings:
        print("面板一致性：干净（五个面板同一份 css、版本号一致、无悬空 id / 缺文件）")
    else:
        for item in findings:
            print("[%s] %-32s %s" % (item["level"], item["plugin"], item["what"]))
    return 1 if findings else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
