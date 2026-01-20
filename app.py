"""Chainlit Web 适配器 - 高尔夫旅行智能助手

UI Adapter 模式：仅负责事件到 UI 组件的映射，不包含业务逻辑。
包含登录认证流程：通过姓名+生日验证客户身份。
"""

import os
import sys
import uuid
import json
from datetime import datetime

import chainlit as cl
from dotenv import load_dotenv
from langchain_core.messages import HumanMessage
from langgraph.checkpoint.memory import MemorySaver

load_dotenv()
sys.path.insert(0, "src")

from travel_agent import create_graph
from travel_agent.tools.customer import authenticate_customer


# ==================== 环境变量配置 ====================

_trip_id = os.getenv("TRIP_ID")
if not _trip_id:
    raise ValueError(
        "TRIP_ID 环境变量未设置。启动命令示例:\n"
        "  TRIP_ID=<行程ID> uv run chainlit run app.py -w"
    )
TRIP_ID: str = _trip_id


# ==================== 常量定义 ====================

# 登录状态
LOGIN_STATE_WAITING = "waiting"
LOGIN_STATE_AUTHENTICATED = "authenticated"

# 状态 Emoji
STATUS_EMOJI = {
    "PENDING": "⏳",
    "DISPATCHED": "🚀",
    "FILLED": "✅",
    "FAILED": "❌",
}

# 节点图标
NODE_ICONS = {
    "planner": "🧠",
    "supervisor": "👀",
    "analyst": "📊",
    "final_responder": "💬",
    "hotel_agent": "🏨",
    "golf_agent": "⛳",
    "search_agent": "🔍",
    "weather_agent": "🌤️",
    "customer_agent": "👤",
    "logistics_agent": "🚗",
    "itinerary_agent": "📅",
}


# ==================== 工具函数 ====================


def _render_recipe_markdown(plan: list[dict]) -> str:
    """将 procurement_plan 渲染为 Markdown 表格"""
    if not plan:
        return "_无采购计划_"

    lines = [
        "| ID | 字段 | Agent | 状态 | 当前值 |",
        "|:---|:-----|:------|:----:|:-------|",
    ]
    for slot in plan:
        slot_id = slot.get("id", "?")[:16]
        field = slot.get("field_name", "?")[:12]
        agent = slot.get("source_agent", "?").replace("_agent", "")[:10]
        status = slot.get("status", "?")
        emoji = STATUS_EMOJI.get(status, "❓")

        value = slot.get("value")
        if value is None:
            value_str = ""
        elif isinstance(value, str):
            value_str = value[:30] + "..." if len(value) > 30 else value
        else:
            value_str = str(value)[:30]

        lines.append(f"| {slot_id} | {field} | {agent} | {emoji} | {value_str} |")

    return "\n".join(lines)


def _parse_refined_plan(plan_str: str) -> dict:
    """解析 refined_plan JSON 字符串"""
    if not plan_str:
        return {}
    try:
        return json.loads(plan_str)
    except (json.JSONDecodeError, TypeError):
        return {}


def _format_thought_trace(trace: str, max_len: int = 300) -> str:
    """格式化思维链，截断过长内容"""
    if not trace:
        return ""
    if len(trace) > max_len:
        return trace[:max_len] + "\n\n... (已截断)"
    return trace


def _format_debug_info(debug_info: dict) -> str:
    """格式化调试信息为可复制的完整文本（不截断）"""
    parts = ["# AI 思考链调试信息\n"]

    # 1. Planner 思维链（完整）
    if debug_info.get("planner_trace"):
        parts.append("## 1. Planner 思维链")
        parts.append(debug_info["planner_trace"])
        parts.append("")

    # 2. 理解的意图
    if debug_info.get("understood_intent"):
        parts.append("## 2. 理解的意图")
        parts.append(debug_info["understood_intent"])
        parts.append("")

    # 3. 采购计划（完整表格，不截断）
    if debug_info.get("procurement_plan"):
        parts.append("## 3. 采购计划")
        plan = debug_info["procurement_plan"]
        lines = [
            "| ID | 字段 | Agent | 依赖 | 状态 | 值摘要 |",
            "|:---|:-----|:------|:-----|:----:|:-------|",
        ]
        for slot in plan:
            slot_id = slot.get("id", "?")
            field = slot.get("field_name", "?")
            agent = slot.get("source_agent", "?")
            deps = ", ".join(slot.get("dependencies", [])) or "-"
            status = slot.get("status", "?")
            value = slot.get("value")
            if value is None:
                value_str = ""
            elif isinstance(value, str):
                value_str = value[:80] + "..." if len(value) > 80 else value
            else:
                value_str = str(value)[:80]
            lines.append(f"| {slot_id} | {field} | {agent} | {deps} | {status} | {value_str} |")
        parts.append("\n".join(lines))
        parts.append("")

    # 4. Analyst 思维链（完整）
    if debug_info.get("analyst_trace"):
        parts.append("## 4. Analyst 思维链")
        parts.append(debug_info["analyst_trace"])
        parts.append("")

    # 5. 最终报告（完整）
    if debug_info.get("analysis_report"):
        parts.append("## 5. 最终分析报告")
        parts.append(debug_info["analysis_report"])
        parts.append("")

    parts.append(f"---\n生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

    return "\n".join(parts)


# ==================== Action 回调 ====================


@cl.action_callback("show_thought_chain")
async def on_show_thought_chain(action: cl.Action):
    """展示完整思维链"""
    content = action.payload.get("content", "")
    await cl.Message(content=content).send()


# ==================== 登录流程 ====================


async def _start_login_flow():
    """登录表单流程 - 简化为2步"""

    # 1. 输入全名拼音
    res = await cl.AskUserMessage(
        content="请输入您的 **全名拼音** (格式: Last Name, First Name，例如 Wang, XiaoMing):",
        timeout=300,
    ).send()
    if not res:
        await cl.Message(content="⏰ 输入超时，请刷新页面重试。").send()
        return
    full_name = str(res.get("output", "")).strip()

    # 2. 输入生日
    res = await cl.AskUserMessage(
        content="请输入您的 **生日** (格式: YYYY-MM-DD，例如 1990-01-15):",
        timeout=300,
    ).send()
    if not res:
        await cl.Message(content="⏰ 输入超时，请刷新页面重试。").send()
        return
    birthday = str(res.get("output", "")).strip()

    # 3. 验证
    trip_id = cl.user_session.get("trip_id") or TRIP_ID
    await cl.Message(content="🔄 正在验证身份...").send()

    customer = authenticate_customer(full_name, birthday, str(trip_id))

    if customer:
        await _login_success(customer)
    else:
        await _login_failed()


async def _login_success(customer: dict):
    """登录成功 - 初始化图并显示欢迎消息"""
    cl.user_session.set("login_state", LOGIN_STATE_AUTHENTICATED)
    cl.user_session.set("customer_data", customer)
    cl.user_session.set("customer_id", customer.get("id", ""))

    # 初始化图
    checkpointer = MemorySaver()
    graph = create_graph(checkpointer=checkpointer)
    thread_id = str(uuid.uuid4())
    current_date = datetime.now().strftime("%Y年%m月%d日")

    # 初始状态
    trip_id = cl.user_session.get("trip_id")
    initial_state = {
        "messages": [],
        "trip_id": trip_id,
        "customer_id": customer.get("id", ""),
        "current_date": current_date,
        "trip_data": {"customer": customer},
        "next_step": "supervisor",
        "supervisor_instructions": "",
        "iteration_count": 0,
    }

    cl.user_session.set("graph", graph)
    cl.user_session.set("thread_id", thread_id)
    cl.user_session.set("initial_state", initial_state)
    cl.user_session.set("first_call", True)

    # 发送欢迎消息
    customer_name = customer.get("name", "客户")
    await cl.Message(content=f"""## ✅ 欢迎，{customer_name}！

您的行程助手已就绪。请问有什么可以帮您？

**示例问题**:
- "明天几点出发打球？"
- "我住的酒店怎么样？"
- "后天的天气如何？"
""").send()


async def _login_failed():
    """登录失败 - 显示错误并重试"""
    await cl.Message(
        content="❌ **验证失败**: 未找到匹配的客户信息，或您没有权限访问该行程。\n\n请检查输入后重试。"
    ).send()
    # 重新开始登录
    await _start_login_flow()


# ==================== Chainlit 生命周期 ====================


@cl.on_chat_start
async def on_chat_start():
    """会话开始 - 显示欢迎页并启动登录流程"""

    # 初始化会话状态
    cl.user_session.set("login_state", LOGIN_STATE_WAITING)
    cl.user_session.set("trip_id", TRIP_ID)

    # 显示欢迎消息
    await cl.Message(content=f"""## 🏌️ 高尔夫旅行智能助手

**行程**: `{TRIP_ID[:8]}...`

请完成身份验证以继续。
""").send()

    # 启动登录流程
    await _start_login_flow()


@cl.on_message
async def on_message(message: cl.Message):
    """处理用户消息"""

    # 检查登录状态
    if cl.user_session.get("login_state") != LOGIN_STATE_AUTHENTICATED:
        await cl.Message(content="⚠️ 请先完成身份验证。").send()
        return

    # 获取会话状态
    graph = cl.user_session.get("graph")
    thread_id = cl.user_session.get("thread_id")
    initial_state = cl.user_session.get("initial_state")
    first_call = cl.user_session.get("first_call")

    if not graph:
        await cl.Message(content="❌ 会话已过期，请刷新页面重试。").send()
        return

    # 构建配置
    config = {"configurable": {"thread_id": thread_id}}

    # 构建输入状态
    if first_call and initial_state:
        input_state = dict(initial_state)
        input_state["messages"] = [HumanMessage(content=message.content)]
        cl.user_session.set("first_call", False)
    else:
        input_state = {
            "messages": [HumanMessage(content=message.content)],
            "iteration_count": 0,
        }

    # 创建最终回复消息容器
    final_msg = cl.Message(content="")
    await final_msg.send()

    # 初始化调试信息收集器
    debug_info = {
        "planner_trace": "",
        "understood_intent": "",
        "procurement_plan": [],
        "analyst_trace": "",
        "analysis_report": "",
    }

    try:
        # 使用 stream 模式执行图
        result = None
        for mode, chunk in graph.stream(
            input_state, config, stream_mode=["updates", "values"]
        ):
            if mode == "updates":
                for node_name, output in chunk.items():
                    await _handle_node_output(node_name, output, final_msg, debug_info)
            elif mode == "values":
                result = chunk

        # 确保最终消息有内容
        if result and result.get("messages"):
            last_msg = result["messages"][-1]
            if hasattr(last_msg, "content") and last_msg.content:
                final_msg.content = last_msg.content
                await final_msg.update()

        # 添加展示思维链按钮（如果有思维链数据）
        thought_chain = _format_debug_info(debug_info)
        if thought_chain.strip() and thought_chain != "# AI 思考链调试信息\n":
            await cl.Message(
                content="",
                actions=[
                    cl.Action(
                        name="show_thought_chain",
                        label="🔍 查看完整思维链",
                        payload={"content": thought_chain},
                    )
                ],
            ).send()

    except Exception as e:
        final_msg.content = f"❌ 执行出错: {str(e)}"
        await final_msg.update()


async def _handle_node_output(
    node_name: str, output: dict, final_msg: cl.Message, debug_info: dict
):
    """处理节点输出 - 映射到 Chainlit UI 组件，同时收集调试信息"""

    # Final Responder: 直接更新最终消息
    if node_name == "final_responder":
        if output.get("messages"):
            for msg in output["messages"]:
                if hasattr(msg, "content") and msg.content:
                    final_msg.content = msg.content
                    await final_msg.update()
        return

    # 其他节点: 使用 Step 组件展示
    icon = NODE_ICONS.get(node_name, "📦")
    step_name = f"{icon} {node_name}"

    async with cl.Step(name=step_name) as step:
        if node_name == "planner":
            await _render_planner_step(step, output, debug_info)

        elif node_name == "supervisor":
            await _render_supervisor_step(step, output, debug_info)

        elif node_name == "analyst":
            await _render_analyst_step(step, output, debug_info)

        else:
            # Workers (golf_agent, hotel_agent, etc.)
            await _render_worker_step(step, node_name, output)


async def _render_planner_step(step: cl.Step, output: dict, debug_info: dict):
    """渲染 Planner 节点输出，同时收集调试信息"""
    plan_str = output.get("refined_plan", "")
    plan = _parse_refined_plan(plan_str)

    parts = []

    # 数据源判定
    data_source = plan.get("data_source", "UNKNOWN")
    source_emoji = {"PRIVATE_DB": "🔒", "PUBLIC_WEB": "🌐", "MIXED": "🔀"}.get(
        data_source, "❓"
    )
    parts.append(f"**数据源**: {source_emoji} {data_source}")

    # 理解的意图
    intent = plan.get("understood_intent", "")
    if intent:
        parts.append(f"**意图**: {intent}")
        # 收集到调试信息
        debug_info["understood_intent"] = intent

    # 思维链（折叠展示，但完整收集到 debug_info）
    trace = plan.get("thought_trace", "")
    # 始终收集完整思维链（即使为空）
    debug_info["planner_trace"] = trace
    if trace:
        formatted = _format_thought_trace(trace)
        parts.append(f"\n<details>\n<summary>📝 思维链</summary>\n\n{formatted}\n</details>")

    # 采购计划表格
    procurement_plan = output.get("procurement_plan", [])
    # 始终收集采购计划
    debug_info["procurement_plan"] = procurement_plan
    if procurement_plan:
        parts.append(f"\n**📋 采购计划**:\n{_render_recipe_markdown(procurement_plan)}")

    step.output = "\n\n".join(parts) if parts else "_规划完成_"


async def _render_supervisor_step(step: cl.Step, output: dict, debug_info: dict):
    """渲染 Supervisor 节点输出，更新采购计划状态"""
    parts = []

    # 路由决策
    next_step = output.get("next_step", "?")
    parts.append(f"**下一步**: → `{next_step}`")

    # 调度指令
    instruction = output.get("supervisor_instructions", "")
    if instruction:
        if len(instruction) > 100:
            instruction = instruction[:97] + "..."
        parts.append(f"**指令**: {instruction}")

    # 采购计划状态（更新到调试信息）
    procurement_plan = output.get("procurement_plan", [])
    if procurement_plan:
        parts.append(f"\n**状态**:\n{_render_recipe_markdown(procurement_plan)}")
        # 更新采购计划（包含最新状态和值）
        debug_info["procurement_plan"] = procurement_plan

    step.output = "\n\n".join(parts) if parts else "_调度中_"


async def _render_analyst_step(step: cl.Step, output: dict, debug_info: dict):
    """渲染 Analyst 节点输出，收集完整思维链和报告"""
    report = output.get("analysis_report", "")
    analyst_trace = output.get("analyst_thought_trace", "")

    # 始终收集完整的分析报告和思维链（即使为空）
    debug_info["analysis_report"] = report
    debug_info["analyst_trace"] = analyst_trace

    # 显示截断版本
    if report:
        display_report = report
        if len(display_report) > 800:
            display_report = display_report[:800] + "\n\n... (已截断)"
        step.output = display_report
    else:
        step.output = "_分析完成_"


async def _render_worker_step(step: cl.Step, node_name: str, output: dict):
    """渲染 Worker 节点输出"""
    parts = []

    # 显示消息
    messages = output.get("messages", [])
    for msg in messages:
        if hasattr(msg, "content") and msg.content:
            parts.append(msg.content)

    # 显示数据摘要
    trip_data = output.get("trip_data", {})
    if trip_data:
        data_summary = []
        for key, value in trip_data.items():
            if isinstance(value, list):
                data_summary.append(f"- **{key}**: {len(value)} 条记录")
            elif isinstance(value, dict):
                data_summary.append(f"- **{key}**: {len(value)} 个字段")
            elif value is not None:
                data_summary.append(f"- **{key}**: {str(value)[:50]}")
        if data_summary:
            parts.append("\n**数据更新**:\n" + "\n".join(data_summary))

    step.output = "\n\n".join(parts) if parts else f"_{node_name} 执行完成_"
