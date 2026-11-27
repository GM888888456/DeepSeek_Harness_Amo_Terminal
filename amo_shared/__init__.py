# -*- coding: utf-8 -*-
"""五个插件共用的最小实现集合（唯一真源）。

为什么集中在这里：

- `chain` / `config_guard` / `config_watch` / `link` 原来在 Image、Finance、Market、
  Medical 里各存一份完全相同的拷贝，改一个 bug 要改五处，漏一处就是「四个面板好使、
  一个面板报错」这种查不出原因的毛病。
- 这些模块都是纯标准库、不 import 任何插件内部代码，所以可以按文件路径加载，不需要
  新造一套包/服务/RPC。

加载方式（各插件里的同名文件只是入口，不是实现）：

    importlib.util.spec_from_file_location(
        "amo_shared_link", "<Terminal>/amo_shared/link.py")

约定：

1. 这里的文件不 import 任何插件代码，只依赖标准库（否则会被插件加载顺序拖住）。
2. 对外接口只增不改：删名字会让某个插件的旧代码在启动时才炸。
3. 改完要把 SHIM_VERSION 加一，入口那边靠它判断「公共实现是不是比我还旧」并降级。
"""

#: 公共实现版本。入口文件（各插件的 chain.py 等）用 NEED 比对它，低于 NEED 就降级。
SHIM_VERSION = 1

__all__ = ["SHIM_VERSION"]
