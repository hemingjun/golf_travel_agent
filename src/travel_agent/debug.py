"""Debug 模块 - 统一的调试输出组件

提供 ANSI 颜色支持和结构化的调试输出组件，让 terminal 展示更易于阅读。
"""

from typing import Any

# ==================== 全局配置 ====================

DEBUG_MODE = False


def set_debug_mode(enabled: bool):
    """设置调试模式"""
    global DEBUG_MODE
    DEBUG_MODE = enabled


# ==================== ANSI 颜色 ====================


class Colors:
    """ANSI 颜色代码"""

    RESET = "\033[0m"
    BOLD = "\033[1m"
    DIM = "\033[2m"

    # 前景色
    RED = "\033[31m"
    GREEN = "\033[32m"
    YELLOW = "\033[33m"
    BLUE = "\033[34m"
    MAGENTA = "\033[35m"
    CYAN = "\033[36m"
    WHITE = "\033[37m"
    GRAY = "\033[90m"


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


# ==================== 基础函数 ====================


def debug_print(*args, **kwargs):
    """调试模式下打印信息"""
    if DEBUG_MODE:
        print(*args, **kwargs)


def error_print(*args, **kwargs):
    """错误信息打印（始终显示）"""
    print(*args, **kwargs)


# ==================== 基础组件 ====================


# 节点图标映射
NODE_ICONS = {
    "planner": "🎯",
    "supervisor": "🔄",
    "analyst": "📊",
    "responder": "💬",
    "hotel_agent": "🏨",
    "golf_agent": "⛳",
    "search_agent": "🔍",
    "weather_agent": "🌤️",
    "customer_agent": "👤",
    "logistics_agent": "🚗",
    "itinerary_agent": "📅",
}


def print_node_enter(node_name: str, **meta):
    """打印节点入口标识

    Args:
        node_name: 节点名称
        **meta: 额外元信息，如 iteration=1
    """
    if not DEBUG_MODE:
        return

    icon = NODE_ICONS.get(node_name, "📦")

    # 构建标题
    title = f"{icon} {node_name.upper()}"
    if "iteration" in meta:
        title += f" (迭代 {meta['iteration']})"

    # 打印盒子
    width = 60
    print()
    print(_c("╭" + "─" * (width - 2) + "╮", Colors.CYAN))
    # 计算标题实际显示宽度（emoji 占 2 字符宽度）
    title_display_len = len(title) + 1  # emoji 额外占 1 宽度
    padding = " " * (width - title_display_len - 4)
    print(_c("│", Colors.CYAN) + f"  {_c(title, Colors.BOLD, Colors.CYAN)}{padding}" + _c("│", Colors.CYAN))
    print(_c("╰" + "─" * (width - 2) + "╯", Colors.CYAN))


def print_section(title: str, icon: str = ""):
    """打印小节标题

    Args:
        title: 标题文本
        icon: 可选图标
    """
    if not DEBUG_MODE:
        return
    prefix = f"{icon} " if icon else ""
    print(f"\n{prefix}{_c(title, Colors.BOLD)}")


def print_kv(key: str, value: Any, indent: int = 2, color: str = None):
    """打印键值对

    Args:
        key: 键名
        value: 值
        indent: 缩进空格数
        color: 可选颜色
    """
    if not DEBUG_MODE:
        return
    prefix = " " * indent
    value_str = str(value)
    if color:
        print(f"{prefix}{key}: {_c(value_str, color)}")
    else:
        print(f"{prefix}{key}: {value_str}")


# ==================== 业务组件 ====================


def print_thought_trace(trace: str, max_lines: int = 15):
    """格式化展示思维链

    Args:
        trace: 思维链文本
        max_lines: 最大显示行数
    """
    if not DEBUG_MODE or not trace:
        return

    print()
    print(_c("┌─ 思维链 " + "─" * 50, Colors.MAGENTA))

    lines = trace.strip().split("\n")
    for i, line in enumerate(lines[:max_lines]):
        line = line.strip()
        if line:
            # 高亮数字编号
            if line[0].isdigit() and "." in line[:3]:
                print(_c("│ ", Colors.MAGENTA) + _c(line, Colors.BOLD))
            else:
                print(_c("│ ", Colors.MAGENTA) + line)

    if len(lines) > max_lines:
        omitted = len(lines) - max_lines
        print(_c("│ ", Colors.MAGENTA) + _c(f"... ({omitted} more lines)", Colors.DIM))

    print(_c("└" + "─" * 60, Colors.MAGENTA))


def print_worker_result(slot_id: str, status: str, value: str = None):
    """打印 Worker 执行结果

    Args:
        slot_id: Slot ID
        status: 状态 (FILLED/FAILED)
        value: 值（可选）
    """
    if not DEBUG_MODE:
        return

    if status == "FILLED":
        icon, color = "✅", Colors.GREEN
    elif status == "FAILED":
        icon, color = "❌", Colors.RED
    else:
        icon, color = "⏳", Colors.YELLOW

    print(f"  {icon} {slot_id}: {_c(status, color)}")
    if value:
        value_display = str(value)[:60] + "..." if len(str(value)) > 60 else str(value)
        print(f"     Value: {_c(value_display, Colors.DIM)}")


def print_dispatch(target: str, slot: dict, instruction: str):
    """打印调度信息

    Args:
        target: 目标 Agent
        slot: Slot 信息
        instruction: 指令内容
    """
    if not DEBUG_MODE:
        return

    print_section("调度", "📤")
    print_kv("Target", target, color=Colors.CYAN)
    print_kv("Slot", f"{slot.get('id', '?')} ({slot.get('field_name', '?')})")

    # 指令可能较长，截断显示
    instr_display = instruction[:80] + "..." if len(instruction) > 80 else instruction
    print_kv("指令", instr_display)


def print_routing(from_node: str, to_node: str, reason: str = ""):
    """打印路由决策

    Args:
        from_node: 源节点
        to_node: 目标节点
        reason: 路由原因（可选）
    """
    if not DEBUG_MODE:
        return

    arrow = _c("→", Colors.BOLD)
    print()
    print(f"{arrow} 路由: {from_node} {arrow} {_c(to_node, Colors.CYAN)}")
    if reason:
        print(f"  原因: {_c(reason, Colors.DIM)}")
    print(_c("═" * 60, Colors.DIM))


def print_trip_data_update(key: str, data: Any):
    """打印 trip_data 更新

    Args:
        key: 更新的键名
        data: 更新的数据
    """
    if not DEBUG_MODE:
        return

    print_section("trip_data 更新", "📊")
    print(f"  + {_c(key, Colors.BLUE)}")

    if isinstance(data, list) and data:
        print(f"    └─ {len(data)} 项")
        # 展示第一项的关键字段
        first = data[0] if data else {}
        for k, v in list(first.items())[:3]:
            v_str = str(v)[:40] + "..." if len(str(v)) > 40 else str(v)
            print(f"       {k}: {v_str}")
    elif isinstance(data, dict):
        for k, v in list(data.items())[:3]:
            v_str = str(v)[:40] + "..." if len(str(v)) > 40 else str(v)
            print(f"    {k}: {v_str}")
    elif data:
        data_str = str(data)[:60] + "..." if len(str(data)) > 60 else str(data)
        print(f"    {data_str}")


def print_recipe_status(
    procurement_plan: list[dict],
    title: str = "Recipe Status",
    show_summary: bool = False,
):
    """统一的食谱状态展示函数 - 增强版

    Args:
        procurement_plan: 采购计划列表
        title: 展示标题
        show_summary: 是否显示统计摘要
    """
    if not DEBUG_MODE:
        return

    STATUS_STYLES = {
        "PENDING": ("⏳", Colors.YELLOW),
        "DISPATCHED": ("🚀", Colors.YELLOW),
        "FILLED": ("✅", Colors.GREEN),
        "FAILED": ("❌", Colors.RED),
    }

    print(f"\n📋 {_c(title, Colors.BOLD)}")

    if not procurement_plan:
        print("  (空)")
        return

    # 表格头
    print(_c("┌" + "─" * 18 + "┬" + "─" * 14 + "┬" + "─" * 14 + "┬" + "─" * 14 + "┐", Colors.DIM))
    header = (
        _c("│", Colors.DIM) + f" {'Slot ID':<16} " +
        _c("│", Colors.DIM) + f" {'Field':<12} " +
        _c("│", Colors.DIM) + f" {'Agent':<12} " +
        _c("│", Colors.DIM) + f" {'Status':<12} " +
        _c("│", Colors.DIM)
    )
    print(header)
    print(_c("├" + "─" * 18 + "┼" + "─" * 14 + "┼" + "─" * 14 + "┼" + "─" * 14 + "┤", Colors.DIM))

    # 表格内容
    deps_info = []
    for slot in procurement_plan:
        status = slot.get("status", "?")
        icon, color = STATUS_STYLES.get(status, ("❓", Colors.WHITE))

        slot_id = slot.get("id", "?")[:16]
        field = slot.get("field_name", "?")[:12]
        agent = slot.get("source_agent", "?")[:12]
        status_str = f"{icon} {status}"

        row = (
            _c("│", Colors.DIM) + f" {slot_id:<16} " +
            _c("│", Colors.DIM) + f" {field:<12} " +
            _c("│", Colors.DIM) + f" {agent:<12} " +
            _c("│", Colors.DIM) + f" {_c(status_str, color):<12} " +
            _c("│", Colors.DIM)
        )
        print(row)

        # 收集依赖信息
        deps = slot.get("dependencies", [])
        if deps:
            deps_info.append(f"{slot.get('id')} ← {deps}")

    print(_c("└" + "─" * 18 + "┴" + "─" * 14 + "┴" + "─" * 14 + "┴" + "─" * 14 + "┘", Colors.DIM))

    # 依赖关系
    if deps_info:
        print(f"  Dependencies: {_c(', '.join(deps_info), Colors.DIM)}")

    # 统计摘要
    if show_summary:
        statuses = [s.get("status", "?") for s in procurement_plan]
        filled = statuses.count("FILLED")
        failed = statuses.count("FAILED")
        pending = statuses.count("PENDING")
        print(
            f"  Summary: {_c(f'✅ {filled}', Colors.GREEN)} | "
            f"{_c(f'❌ {failed}', Colors.RED)} | "
            f"{_c(f'⏳ {pending}', Colors.YELLOW)}"
        )


def print_data_sync(slot_id: str, field_name: str, source_key: str):
    """打印数据同步信息

    Args:
        slot_id: Slot ID
        field_name: 字段名
        source_key: 数据来源键
    """
    if not DEBUG_MODE:
        return
    print(f"  {_c('↳', Colors.GREEN)} {slot_id}: {field_name} from trip_data.{source_key}")


def print_completion(reason: str, is_success: bool = True):
    """打印完成状态

    Args:
        reason: 完成原因
        is_success: 是否成功
    """
    if not DEBUG_MODE:
        return

    if is_success:
        print(f"\n{_c('✓', Colors.GREEN, Colors.BOLD)} {_c('完成', Colors.GREEN)}: {reason}")
    else:
        print(f"\n{_c('⚠', Colors.YELLOW, Colors.BOLD)} {_c('终止', Colors.YELLOW)}: {reason}")


def print_error_msg(message: str, detail: str = None):
    """打印错误信息

    Args:
        message: 错误消息
        detail: 详细信息（可选）
    """
    if not DEBUG_MODE:
        return

    print(f"\n{_c('✗', Colors.RED, Colors.BOLD)} {_c('错误', Colors.RED)}: {message}")
    if detail:
        print(f"  {_c(detail, Colors.DIM)}")
