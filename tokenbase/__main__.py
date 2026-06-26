"""
tokenbase.__main__ — 支持 `python -m tokenbase ...` 调用 CLI。

stdio 编码重配置在 cli.main() 内完成,此处仅做入口分发。

SPDX-License-Identifier: GPL-3.0-or-later
Copyright (c) KiteFlyerX
"""
import sys
from .cli import main

if __name__ == "__main__":
    sys.exit(main())
