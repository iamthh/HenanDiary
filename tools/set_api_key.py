"""一次性工具：把明文 API Key 用 DPAPI 加密后写进 settings.json。

用法：python tools/set_api_key.py <你的Key>
（M4 首次引导做完后此脚本退役）
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # 让脚本能 import 项目模块

import config
from ai.client import encrypt_key


def main() -> int:
    if len(sys.argv) != 2:
        print("用法: python tools/set_api_key.py <API_KEY>")
        return 1
    config.ensure_dirs()
    config.update_settings({"ai": {"api_key_encrypted": encrypt_key(sys.argv[1])}})
    print("已加密写入", config.get_config_path())
    return 0


if __name__ == "__main__":
    sys.exit(main())
