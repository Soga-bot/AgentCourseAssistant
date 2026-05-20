"""
ReAct推理循环 - 实现思考-行动-观察循环

ReAct (Reasoning + Acting) 是一种让AI通过推理和行动交替进行来解决问题的范式。

循环流程图：

    用户输入
       │
       ▼
    ┌──────────────────────────────────────┐
    │  Thought (思考)                       │
    │  分析当前状态，决定下一步做什么          │
    └──────────────┬───────────────────────┘
                   │
                   ▼
    ┌──────────────────────────────────────┐
    │  Action (选工具)                      │
    │  选择工具 + 构造参数，调用执行           │
    └──────────────┬───────────────────────┘
                   │
                   ▼
    ┌──────────────────────────────────────┐
    │  Observation (观察结果)                │
    │  获取工具返回值，作为下一轮上下文         │
    └──────────────┬───────────────────────┘
                   │
                   ▼
            ┌─────────────┐
            │ 信息足够？    │
            └──┬───────┬──┘
         否(循环)│       │是(终止)
               ▼       ▼
         回到Thought   Answer: 最终答案

循环过程：
1. Thought：思考当前状态
2. Action：选择并执行工具
3. Observation：观察工具执行结果
4. 重复直到完成

论文参考: ReAct: Synergizing Reasoning and Acting in Language Models
"""
from typing import Dict, List, Optional, Any
import logging
import json
from .base import BaseAgent, AgentMessage

logger = logging.getLogger(__name__)


class ReActLoop:
    """
    ReAct推理循环

    实现经典的ReAct模式：
    1. Thought：思考当前状态
    2. Action：选择并执行工具
    3. Observation：观察工具执行结果
    4. 重复直到完成

    使用示例：
        agent = MyAgent(tools=tool_manager)
        react = ReActLoop(agent, llm_client)

        response = await react.run("帮我生成七年级有理数的课程")
    """

    def __init__(
        self,
        agent: BaseAgent,
        llm_client,
        max_iterations: int = 10
    ):
        """
        初始化ReAct循环

        Args:
            agent: Agent实例
            llm_client: LLM客户端
            max_iterations: 最大迭代次数
        """
        self.agent = agent
        self.llm_client = llm_client
        self.max_iterations = max_iterations

        logger.info(
            f"[ReAct] Initialized for agent {agent.name} "
            f"with max_iterations={max_iterations}"
        )

    async def run(self, user_input: str, extra_context: dict = None) -> str:
        """
        运行ReAct循环

        Args:
            user_input: 用户输入
            extra_context: Agent层传入的附加上下文（如问题分类等），会注入system prompt

        Returns:
            最终答案
        """
        self._extra_context = extra_context or {}
        logger.info(f"[ReAct] Starting loop for input: {user_input[:100]}...")

        # → 记录用户输入到 Agent 的消息历史，供后续追溯和记忆存储使用
        self.agent.add_message("user", user_input)

        # --- 消息构建逻辑 ---
        # messages 是发送给 LLM 的完整对话列表，结构为：
        #   [0] system prompt（含工具描述、附加上下文、记忆上下文）
        #   [1] user message（用户原始输入）
        # 后续每轮迭代会追加 assistant (Thought+Action) 和 user (Observation) 消息
        # → system prompt 每次构建时都会读取最新的工具列表和记忆数据
        messages = [
            {"role": "system", "content": self._build_system_prompt()},
            {"role": "user", "content": user_input}
        ]

        # --- ReAct 主循环 ---
        # 循环条件：最多执行 max_iterations 轮，防止无限循环消耗资源
        for iteration in range(self.max_iterations):
            logger.info(f"[ReAct] Iteration {iteration + 1}/{self.max_iterations}")

            # 1. 调用LLM获取下一步动作
            # → messages 随循环不断增长，LLM 可看到全部历史 Thought/Action/Observation
            try:
                response = await self._call_llm(messages)

                if not response.success:
                    error_msg = f"LLM调用失败: {response.error}"
                    logger.error(f"[ReAct] {error_msg}")
                    return f"抱歉，处理过程中出现错误：{error_msg}"

                thought_process = response.content
                logger.debug(f"[ReAct] LLM response: {thought_process[:200]}...")

            except Exception as e:
                logger.error(f"[ReAct] LLM call exception: {e}")
                return f"抱歉，处理过程中出现错误：{str(e)}"

            # 2. 解析LLM输出 → 判定本轮是执行工具还是给出最终答案
            parsed = self._parse_react_output(thought_process)

            # --- 终止条件1：得到 Answer ---
            # LLM 判断信息已足够，直接以 "Answer:" 格式返回最终答案
            if parsed.get("type") == "answer":
                self.agent.add_message("assistant", parsed["content"])
                logger.info(f"[ReAct] Agent给出最终答案")
                return parsed["content"]

            # --- 继续循环：执行 Action ---
            # LLM 输出了 Thought + Action + Action Input，需要调用工具
            elif parsed.get("type") == "action":
                tool_name = parsed["tool_name"]
                tool_params = parsed.get("tool_params", {})

                logger.info(f"[ReAct] 执行工具: {tool_name}")

                try:
                    # → 调用 Agent 的工具执行方法，获取工具返回结果
                    result = await self.agent.call_tool(tool_name, **tool_params)

                    # 格式化结果 → 截断过长内容，避免 prompt 膨胀
                    observation = self._format_observation(result)

                    # → 同步记录到 Agent 内部消息历史（用于记忆/日志）
                    thought = parsed.get('thought', '')
                    self.agent.add_message(
                        "assistant",
                        f"Thought: {thought}\nAction: {tool_name}"
                    )
                    self.agent.add_message("user", f"Observation: {observation}")

                    # → 追加到 LLM 的 messages 列表，下一轮 LLM 可看到本轮结果
                    messages.append({"role": "assistant", "content": thought_process})
                    messages.append({"role": "user", "content": observation})

                    logger.info(f"[ReAct] 工具执行成功，结果长度: {len(observation)}")

                except Exception as e:
                    error_msg = f"工具执行出错: {str(e)}"
                    logger.error(f"[ReAct] {error_msg}")
                    # WHY: 即使工具执行失败也将错误信息注入 messages，让 LLM 自行判断是否重试
                    messages.append({"role": "assistant", "content": thought_process})
                    messages.append({"role": "user", "content": error_msg})

            # --- 终止条件2：无法解析 ---
            # LLM 输出不符合 Thought/Action/Answer 任何一种格式，视为兜底退出
            else:
                logger.warning(f"[ReAct] 无法解析LLM输出，直接返回")
                self.agent.add_message("assistant", thought_process)
                return thought_process

        # --- 终止条件3：达到最大迭代次数 ---
        # WHY: 防止 LLM 在复杂问题上陷入无限工具调用循环
        logger.warning(f"[ReAct] 达到最大迭代次数 {self.max_iterations}")
        return "抱歉，我需要更多步骤来解决这个问题，但已达到最大尝试次数。"

    def _build_system_prompt(self) -> str:
        """
        构建系统提示词

        包含：Agent身份、可用工具、Agent层传入的附加上下文、记忆上下文

        Returns:
            系统提示词字符串
        """
        # --- 第1部分：工具信息 ---
        # → 调用 _format_tools_for_prompt() 获取所有注册工具的名称、参数和描述
        # WHY: LLM 需要知道有哪些工具可用以及如何调用，才能在 Action 阶段正确选择
        tools_info = self._format_tools_for_prompt()

        # --- 第2部分：附加上下文（extra_context） ---
        # WHY: Agent 层在调用 run() 时会传入问题分类、工具使用建议等上下文，
        #       帮助 LLM 更精准地选择工具和调整回答策略
        context_sections = []

        extra = getattr(self, '_extra_context', {})
        if extra:
            parts = []
            if "question_type" in extra:
                # → 将问题类型（如"课程生成"、"作业答疑"等）注入 prompt
                parts.append(f"问题类型：{extra['question_type']}")
            if parts:
                context_sections.append(
                    "**当前问题分析：**\n"
                    + "\n".join(f"- {p}" for p in parts)
                    + "\n请根据问题类型调整回答策略。\n"
                )
            if "tool_guidance" in extra:
                # → 工具使用建议：由上层 Agent 根据问题类型给出推荐工具及用法
                context_sections.append(
                    "**工具使用建议：**\n" + extra["tool_guidance"] + "\n"
                )

        # --- 第3部分：记忆上下文（MemoryManager） ---
        # WHY: 从 MemoryManager 获取学生的历史学习数据（如薄弱知识点、学习偏好等），
        #       用于生成个性化回答，而非千篇一律的通用回复
        if self.agent.memory:
            # → 获取最多 10 条记忆条目，避免 prompt 过长
            memories = self.agent.get_context_memory(max_items=10)
            if memories:
                memory_lines = []
                for m in memories:
                    key = m.get("key", "")
                    value = m.get("value", "")
                    if isinstance(value, dict):
                        # WHY: 字典类型只取前3个键值对做精简展示，防止记忆内容撑爆 prompt
                        summary = ", ".join(f"{k}={v}" for k, v in list(value.items())[:3])
                        memory_lines.append(f"- {key}: {summary}")
                    else:
                        memory_lines.append(f"- {key}: {value}")
                context_sections.append(
                    "**学生上下文信息：**\n"
                    + "\n".join(memory_lines) + "\n"
                )

        # --- 拼接所有上下文区块 ---
        # → context_block 最终包含：问题分析 + 工具建议 + 学生上下文，可为空
        context_block = "\n".join(context_sections)

        # --- 最终 prompt 模板 ---
        # 结构：Agent身份 → 工具列表 → 附加上下文 → ReAct格式要求 → 行为约束
        return f"""你是{self.agent.name}，{self.agent.description}

{tools_info}

{context_block}
请按照以下格式回复：

**思考阶段：**
Thought: [你的思考过程，分析当前情况和下一步该做什么]

**执行阶段：**
Action: [工具名称]
Action Input: [工具参数，JSON格式]

**或者如果你已经有了答案：**
Answer: [最终答案]

重要提示：
1. 每次只执行一个工具
2. 仔细观察工具的返回结果
3. 根据观察结果决定下一步
4. 如果信息不足，继续调用工具
5. 如果已经有足够信息给出答案，使用Answer格式
6. 工具参数必须是有效的JSON格式
"""

    def _format_tools_for_prompt(self) -> str:
        """
        格式化工具信息为提示词

        Returns:
            工具信息字符串
        """
        if not self.agent.tools:
            return "当前没有可用工具。"

        tools = self.agent.tools.list_tools()

        if not tools:
            return "当前没有可用工具。"

        tool_descriptions = []
        for tool in tools:
            params = ", ".join(tool.parameters.keys())
            tool_descriptions.append(
                f"- {tool.name}({params}): {tool.description}"
            )

        return "**可用工具：**\n" + "\n".join(tool_descriptions)

    def _parse_react_output(self, output: str) -> Dict[str, Any]:
        """
        解析ReAct输出

        支持的格式：
        1. Thought/Action 格式
        2. Answer 格式
        3. 无法解析的情况

        Args:
            output: LLM输出

        Returns:
            解析结果字典，包含type字段
        """
        output = output.strip()

        # --- 判定1：Answer（直接以 "Answer:" 开头） ---
        # WHY: LLM 判断已有足够信息，跳过工具调用直接给出最终答案
        # → 触发 run() 中的终止条件1，直接返回给用户
        if output.startswith("Answer:"):
            return {
                "type": "answer",
                "content": output[7:].strip()
            }

        # --- 判定2：Action（包含 "Thought:" + "Action:" + "Action Input:"） ---
        # WHY: LLM 决定需要调用工具获取更多信息，逐行提取三个关键字段
        lines = output.split("\n")
        thought = ""
        action = ""
        action_input = ""

        for line in lines:
            line = line.strip()
            if line.startswith("Thought:"):
                thought = line[8:].strip()
            elif line.startswith("Action:"):
                action = line[7:].strip()
            elif line.startswith("Action Input:"):
                action_input = line[13:].strip()

        # 只要存在 Action 字段就认为是工具调用意图
        if action:
            # → 将 Action Input 的 JSON 字符串解析为字典，传给工具执行
            try:
                if action_input:
                    tool_params = json.loads(action_input)
                else:
                    tool_params = {}

                return {
                    "type": "action",
                    "thought": thought,
                    "tool_name": action,
                    "tool_params": tool_params
                }
            except json.JSONDecodeError:
                # WHY: JSON 解析失败说明 LLM 输出了非法参数格式，记录警告后降级为 unknown
                logger.warning(f"[ReAct] 无法解析工具参数JSON: {action_input}")

        # --- 判定3：unknown（无法匹配以上任何格式） ---
        # WHY: 兜底处理，LLM 输出可能不符合预期的 ReAct 格式（如自由文本回复）
        # → 触发 run() 中的终止条件2，直接返回原始文本
        return {"type": "unknown", "content": output}

    def _format_observation(self, result: Any) -> str:
        """
        格式化工具执行结果

        Args:
            result: 工具执行结果

        Returns:
            格式化后的字符串
        """
        if isinstance(result, dict):
            # → 优先检查错误状态，让 LLM 知道工具调用失败以便决定是否重试
            if "error" in result:
                return f"错误: {result['error']}"
            if "success" in result and not result["success"]:
                return f"失败: {result.get('message', '未知错误')}"

            # WHY: 限制1000字符避免prompt过长导致API超限
            # → 每轮迭代都会将 observation 追加到 messages，过长会导致后续 LLM 调用 token 激增
            result_str = json.dumps(result, ensure_ascii=False)
            if len(result_str) > 1000:
                return result_str[:1000] + "... (内容过长，已截断)"
            return result_str

        elif isinstance(result, list):
            # WHY: 列表类型直接序列化，不做截断（通常为工具返回的简短结果列表）
            return json.dumps(result, ensure_ascii=False)

        elif isinstance(result, str):
            # → 字符串类型原样返回，假设工具已自行控制输出长度
            return result

        else:
            # WHY: 其他类型（如数值、自定义对象）转为字符串并截断至500字符
            return str(result)[:500]

    async def _call_llm(self, messages: List[Dict]):
        """
        调用LLM

        Args:
            messages: 消息列表

        Returns:
            LLM响应对象
        """
        # 尝试调用LLM客户端
        try:
            # 检查LLM客户端的接口
            if hasattr(self.llm_client, 'call'):
                # 使用LLMClient.call()方法，传入LLMRequest对象
                from shared.llm_client import LLMRequest
                request = LLMRequest(
                    messages=messages,
                    temperature=0.1,
                    max_tokens=1000
                )
                return await self.llm_client.call(request)
            elif hasattr(self.llm_client, 'generate'):
                return await self.llm_client.generate(
                    system_prompt=messages[0]["content"],
                    user_prompt=messages[-1]["content"]
                )
            else:
                raise ValueError("不支持的LLM客户端接口")

        except Exception as e:
            logger.error(f"[ReAct] LLM调用异常: {e}")
            # 返回一个模拟的错误响应
            class ErrorResponse:
                success = False
                error = str(e)
                content = ""

            return ErrorResponse()

    def __repr__(self) -> str:
        return f"<ReActLoop agent={self.agent.name} max_iter={self.max_iterations}>"


# ==================== 便捷函数 ====================

def create_react_loop(
    agent: BaseAgent,
    llm_client,
    max_iterations: int = 10
) -> ReActLoop:
    """
    创建ReAct循环

    Args:
        agent: Agent实例
        llm_client: LLM客户端
        max_iterations: 最大迭代次数

    Returns:
        ReActLoop实例
    """
    return ReActLoop(agent, llm_client, max_iterations)
