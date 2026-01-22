"""精简调试工具

提供基础的调试输出功能和 ANSI 颜色支持。
"""

DEBUG_MODE = False


def set_debug_mode(enabled: bool):
    """设置调试模式"""
    global DEBUG_MODE
    DEBUG_MODE = enabled


class Colors:
    """ANSI 颜色代码"""

    RESET = "\033[0m"
    BOLD = "\033[1m"
    DIM = "\033[2m"
    RED = "\033[31m"
    GREEN = "\033[32m"
    YELLOW = "\033[33m"
    BLUE = "\033[34m"
    MAGENTA = "\033[35m"
    CYAN = "\033[36m"


def _c(text: str, *colors: str) -> str:
    """包装颜色

    Args:
        text: 要着色的文本
        colors: 颜色代码列表

    Returns:
        带颜色的文本（DEBUG_MODE 关闭时返回原文本）
    """
    if not DEBUG_MODE or not colors:
        return text
    return "".join(colors) + str(text) + Colors.RESET


def debug_print(*args, **kwargs):
    """调试模式下打印信息"""
    if DEBUG_MODE:
        print(*args, **kwargs)


def error_print(*args, **kwargs):
    """错误信息打印（始终显示）"""
    print(*args, **kwargs)
