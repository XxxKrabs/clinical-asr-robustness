"""跨 Python 小版本兼容工具。"""

from __future__ import annotations

from enum import Enum

try:  # Python 3.11+
    from enum import StrEnum as StrEnum
except ImportError:  # pragma: no cover - 只在 Python 3.10 路径触发

    class StrEnum(str, Enum):
        """Python 3.10 的轻量 StrEnum 兼容实现。"""

        def __str__(self) -> str:
            return str(self.value)
