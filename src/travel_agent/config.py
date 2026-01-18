"""全局配置"""

# 调试模式开关
DEBUG_MODE = False


def set_debug_mode(enabled: bool):
    """设置调试模式"""
    global DEBUG_MODE
    DEBUG_MODE = enabled


def debug_print(*args, **kwargs):
    """调试模式下打印信息"""
    if DEBUG_MODE:
        print(*args, **kwargs)


def error_print(*args, **kwargs):
    """错误信息打印（始终显示）"""
    print(*args, **kwargs)
