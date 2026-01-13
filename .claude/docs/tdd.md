# 高尔夫旅行智能助手架构开发文档 (Golf Trip Agent TDD)

## 1. 项目概述 (Project Overview)

本项目旨在构建一个基于 LangGraph 的多智能体协作系统（Multi-Agent System），用于处理高尔夫旅行咨询。系统采用 Supervisor-Worker（监督者-工人） 架构模式，后端知识库连接 Notion Database。

核心目标： 提供专家级、有逻辑、上下文关联强的咨询服务，解决跨组件（高尔夫、酒店、物流）的复杂依赖问题。

## 2. 系统架构拓扑 (Architecture Topology)

系统采用 星型（Hub-and-Spoke） 拓扑结构。

### 2.1 核心节点 (Nodes)

Supervisor (大脑): 负责意图识别、任务拆解、依赖规划和路由分发。不直接访问数据库。

Worker Agents (手脚 - 领域专家):

Golf Agent: 负责球场信息、Tee Time、球童规则。

Hotel Agent: 负责酒店设施、房型、餐饮时间。

Logistics Agent: 负责车辆调度、距离计算、接送逻辑。

Itinerary Agent: 负责宏观行程大纲的聚合查询。

Final Responder (嘴巴 - 综合叙事): 负责读取收集到的结构化数据，生成最终面向客户的、有温度的回复。

### 2.2 边与流转 (Edges & Flow)

Main Loop: Supervisor -> Worker -> Supervisor (迭代循环，直到信息收集完毕)。

Termination: Supervisor -> Final Responder -> END。

## 3. 状态管理设计 (State Management)

State 是 Agent 之间协作的共享内存。必须严格区分“对话历史”和“结构化数据”。

### 3.1 Schema 定义 (Python/Pydantic)

```Python

class TripAgentState(TypedDict):
    # 1. 消息流 (Conversation History)
    # 用于 LLM 理解对话上下文
    messages: Annotated[List[BaseMessage], add_messages]

    # 2. 结构化暂存区 (The Knowledge Scratchpad)
    # 核心字段。所有 Worker 查到的数据必须写入此字典，而非仅作为自然语言返回。
    # 示例: {"golf_start": "10:00", "hotel_name": "Ritz", "pickup_time": "09:00"}
    trip_data: Dict[str, Any]

    # 3. 路由控制 (Routing Control)
    next_step: str  # 下一个被调用的 Node 名称
    supervisor_instructions: str  # Supervisor 给 Worker 的具体指令

    # 4. 上下文元数据 (Metadata)
    customer_profile: Dict  # {name: "Mr. Zhang", handicap: 18, preferences: "..."}
    trip_id: str  # Notion Page ID 锚点

```

## 4. Notion 数据库设计 (Database Schema)

为了支持 RAG 和工具调用，Notion 必须构建为关系型数据库。

### 4.1 核心表结构

Master Itinerary (行程总表):

Golf Courses (球场库):

Hotels (酒店库):

Logistics (物流/司机库):

## 5. 节点详细规范 (Node Specifications)

### 5.1 Supervisor Agent (Router)

System Prompt: "你是一个高尔夫行程规划的主管。根据用户的最新问题和 trip_data 中已有的信息，决定下一步行动。如果需要多个步骤（例如先查时间再算车程），请按顺序规划，一次只分发一个最紧急的任务。"

输出格式 (Structured Output):

```JSON

{
  "next_agent": "Golf_Agent" | "Logistics_Agent" | ... | "Final_Responder",
  "reasoning": "用户问接送时间，但我还没查到球局结束时间，需先查 Golf。",
  "instructions": "查询 Notion 中 5月20日 观澜湖球场的开球时间及平均打球时长。"
}

```

### 5.2 Worker Agents (Golf / Hotel / Logistics / Itinerary)

设计模式: Tool-Use Agent (ReAct).

核心逻辑:

接收 supervisor_instructions。

调用对应的 Notion Tool (e.g., notion_search_golf).

关键动作: 将 Tool 返回的原始数据 Update 到 state["trip_data"] 中。

返回一个简短的 ToolMessage 到 messages 供 Supervisor 确认任务完成。

### 5.3 Final Responder (Synthesizer)

输入: 完整的 trip_data 和 messages。

System Prompt: "你是高级旅行顾问。利用 trip_data 中的事实回答用户。不要机械罗列数据，要建立数据之间的联系（如：因为A所以B）。语气要专业、体贴。如果是行程安排，必须使用 Markdown 表格。"

功能:

Contextualization: 解释数据（如“预留了1小时防堵车”）。

Formatting: 自动检测是否需要表格展示。

Call to Action: 引导下一步。

## 6. 开发实施指南 (Implementation Guide)

### 6.1 工具链 (Tools)

你需要封装以下 Python 函数供 Agent 调用：

query_notion_database(database_id, filter_criteria)

get_notion_page_properties(page_id)

calculate_travel_duration(origin, destination) (可对接高德/Google Maps API，也可查静态表)

### 6.2 路由逻辑 (Graph Flow Logic)

```Python

# 伪代码逻辑

def route_step(state):
    # Supervisor 决定下一步
    if state["next_step"] == "Final_Responder":
        return "goto_responder"
    return state["next_step"] # 返回 "golf_node", "hotel_node" 等


# 构建图
graph.add_conditional_edges("supervisor", route_step)
# 所有 Worker 执行完必须回到 Supervisor 汇报
graph.add_edge("golf_expert", "supervisor")
graph.add_edge("logistics_expert", "supervisor")
# ...

```

## 7. 典型测试用例 (Test Scenarios)

开发完成后，请使用以下三个 Case 进行验收测试：

1. 简单查询: "观澜湖球场难打吗？"

预期: Supervisor -> Golf Agent -> Supervisor -> Final Responder。

1. 依赖查询: "周五打完球回酒店，赶得上 18:00 的晚宴吗？"

预期: Supervisor -> Golf Agent (查结束时间) -> Supervisor -> Logistics Agent (查路程耗时) -> Supervisor -> Final Responder (计算并回答)。

1. 信息缺失: "我想订明天的场。" (但没说哪个球场)

预期: Supervisor -> Final Responder (反问用户: "请问您想去哪个球场？")。
