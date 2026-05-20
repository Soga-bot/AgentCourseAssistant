"""
Agent基类 - 所有Agent的父类

提供Agent的核心功能：
- 消息管理
- 状态管理
- 工具调用
- 记忆管理

架构总览（继承关系）：
    BaseAgent（本文件，抽象基类）
      └── ReActLoop（推理-行动循环，实现 process 的通用框架）
            ├── ToolAgent       —— 专注于工具调用的Agent
            ├── PlannerAgent    —— 负责任务规划的Agent
            ├── CoderAgent      —— 代码生成/调试Agent
            └── ...             —— 其他具体业务Agent

    数据流概览：
        用户输入 → BaseAgent.process()（子类实现）
                 → ReActLoop.run_step() 逐步执行
                    → BaseAgent.call_tool() → ToolManager → 实际工具函数
                    → BaseAgent.remember()  → MemoryManager（短期/长期存储）
                    → BaseAgent.recall()    → MemoryManager（检索历史记忆）
                 → 返回最终响应

    外部依赖：
        - ToolManager：统一管理工具的注册、查找与执行
        - MemoryManager：提供按 agent_id 隔离的键值存储，区分短期/长期记忆
"""
from abc import ABC, abstractmethod
from typing import Dict, List, Any, Optional, Callable
from dataclasses import dataclass, field
import logging
import uuid
from datetime import datetime

# WHY: 使用 dataclass 而非手写 __init__，是为了自动生成 __eq__、__repr__ 等方法，
#      方便在单元测试中对比消息/状态对象，也减少样板代码

logger = logging.getLogger(__name__)


@dataclass
class AgentMessage:
    """Agent消息

    用于记录Agent与用户/系统之间的所有交互消息
    """
    role: str  # user, assistant, system, tool
    content: str
    # tool_calls 与 tool_outputs 成对使用，支撑 ReAct 循环中的工具调用场景：
    #   1. Agent 决定调用工具时，生成 role="assistant" 的消息，tool_calls 记录待执行的工具列表
    #      例如: [{"id": "call_001", "name": "search", "arguments": {"query": "..."}}]
    #   2. 工具执行完毕后，生成 role="tool" 的消息，tool_outputs 记录每个工具的返回结果
    #      例如: {"call_001": {"status": "ok", "data": "..."}}
    # → 数据流: LLM响应(tool_calls) → ToolManager执行 → 结果写入(tool_outputs)
    tool_calls: Optional[List[Dict]] = None
    tool_outputs: Optional[Dict[str, Any]] = None
    metadata: Dict[str, Any] = field(default_factory=dict)  # 扩展字段，可携带 token 用量、模型名等附加信息
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())  # ISO 8601 格式，便于日志排序和调试


@dataclass
class AgentState:
    """Agent状态

    跟踪Agent的运行状态和执行历史

    状态机转换逻辑：
        initial（初始）
          │  调用 process() 开始执行
          ▼
        running（运行中，current_step 递增）
          │
          ├── 正常完成 → complete（is_complete=True, result 有值）
          ├── 达到 max_steps → complete（强制结束，防止无限循环）
          └── 发生异常 → error（error 记录异常信息）
    """
    agent_id: str       # 所属 Agent 的唯一标识，与 BaseAgent.agent_id 一致
    agent_type: str     # Agent 类名（如 "ToolAgent"），用于日志和调试时区分类
    messages: List[AgentMessage] = field(default_factory=list)  # 完整的对话历史，用于构建 LLM 上下文
    current_step: int = 0    # 当前已执行的 ReAct 步数，每轮 Thought+Action+Observation 计为一步
    max_steps: int = 10      # 最大允许步数，防止 Agent 陷入死循环
    is_complete: bool = False  # 标记任务是否已完成（成功或失败均可标记）
    result: Optional[Any] = None   # 任务成功时的最终返回值
    error: Optional[str] = None    # 任务失败时的错误描述
    metadata: Dict[str, Any] = field(default_factory=dict)  # 扩展状态字段，可存放自定义运行时数据

    def add_message(self, message: AgentMessage):
        """添加消息到历史"""
        self.messages.append(message)
        # → 数据流: AgentMessage 追加到 messages 列表，后续 get_message_history() 会读取

    def increment_step(self):
        """递增步数"""
        self.current_step += 1
        # WHY: ReAct 循环每执行一轮（Thought→Action→Observation）调用一次，
        #      与 max_steps 配合实现安全终止

    def is_max_steps_reached(self) -> bool:
        """检查是否达到最大步数"""
        return self.current_step >= self.max_steps
        # WHY: 返回 bool 而非抛异常，让调用方自行决定是强制结束还是继续


class BaseAgent(ABC):
    """
    Agent基类

    提供通用功能：
    - 消息管理：记录所有交互历史
    - 状态管理：跟踪Agent执行状态
    - 工具调用：通过ToolManager调用工具
    - 记忆管理：通过MemoryManager存储/检索记忆

    所有具体Agent都应该继承此类并实现process方法

    设计说明：
        BaseAgent 定义了 Agent 的"骨架"（消息、状态、工具、记忆四大能力），
        子类通过实现 process() 方法来填充具体的推理/执行策略。
        典型子类 ReActLoop 在此基础上实现了 Thought→Action→Observation 循环。
    """

    def __init__(
        self,
        name: str,
        description: str,
        tools: Optional['ToolManager'] = None,
        memory: Optional['MemoryManager'] = None,
        max_steps: int = 10
    ):
        """
        初始化Agent

        Args:
            name: Agent名称
            description: Agent描述
            tools: 工具管理器实例
            memory: 记忆管理器实例
            max_steps: 最大执行步数
        """
        self.name = name
        self.description = description
        # agent_id 生成规则: "{name}_{8位hex}"，例如 "coder_a3f1b2c4"
        # WHY: 使用 uuid4 的前8位十六进制，在保证唯一性的同时保持 ID 可读性；
        #      名前缀方便在日志中快速识别 Agent 类型
        self.agent_id = f"{name}_{uuid.uuid4().hex[:8]}"
        # tools 和 memory 通过构造函数注入（依赖注入模式），
        # 而非在 Agent 内部创建，便于：
        #   1. 多个 Agent 共享同一个 ToolManager / MemoryManager 实例
        #   2. 单元测试时注入 mock 对象
        self.tools = tools    # → ToolManager 实例，控制工具的注册与执行
        self.memory = memory  # → MemoryManager 实例，管理短期/长期记忆存储
        self.max_steps = max_steps

        # 初始化状态
        self.state = AgentState(
            agent_id=self.agent_id,
            agent_type=self.__class__.__name__,  # 记录实际子类名，而非固定的 "BaseAgent"
            max_steps=max_steps
        )

        logger.info(f"[Agent] {self.name} initialized (ID: {self.agent_id})")
        if tools:
            logger.info(f"[Agent] {self.name} has {len(tools.list_tools())} tools available")
        if memory:
            logger.info(f"[Agent] {self.name} has memory manager attached")
        # WHY: 在初始化时打印工具/记忆的可用状态，方便排查"Agent 无法调用工具"类的配置问题

    @abstractmethod
    async def process(self, input_message: str) -> str:
        """
        处理用户输入

        这是一个抽象方法，子类必须实现它。
        它定义了Agent如何处理用户的输入并返回响应。

        Args:
            input_message: 用户输入的消息

        Returns:
            Agent的响应消息
        """
        pass

    def add_message(self, role: str, content: str, **metadata):
        """
        添加消息到历史

        Args:
            role: 消息角色 (user/assistant/system/tool)
            content: 消息内容
            **metadata: 额外的元数据
        """
        message = AgentMessage(
            role=role,
            content=content,
            metadata=metadata
        )
        self.state.add_message(message)
        logger.debug(f"[Agent:{self.name}] Message added: {role} - {content[:50]}...")
        # → 数据流: role+content → AgentMessage → AgentState.messages 列表

    def get_message_history(self, last_n: Optional[int] = None) -> List[Dict]:
        """
        获取消息历史

        Args:
            last_n: 只返回最近N条消息，None表示返回全部

        Returns:
            消息历史列表
        """
        messages = [
            {"role": m.role, "content": m.content}
            for m in self.state.messages
        ]
        # → 数据流: AgentState.messages → 简化的 role/content 字典列表，供 LLM API 消费
        # WHY: 只提取 role 和 content，过滤掉 tool_calls/metadata 等内部字段，
        #      避免将非必要信息发送给 LLM
        if last_n:
            messages = messages[-last_n:]
        return messages

    async def call_tool(self, tool_name: str, **kwargs) -> Any:
        """
        调用工具

        通过ToolManager执行指定的工具

        Args:
            tool_name: 工具名称
            **kwargs: 工具参数

        Returns:
            工具执行结果

        Raises:
            ValueError: 如果工具未配置或工具不存在
        """
        if not self.tools:
            raise ValueError(f"Agent {self.name} has no tools configured")

        # 执行链: BaseAgent.call_tool() → ToolManager.call() → 实际工具函数
        # WHY: Agent 不直接调用工具函数，而是通过 ToolManager 中转，
        #      这样 ToolManager 可以统一处理：参数校验、超时控制、结果缓存、错误恢复等横切关注点
        logger.info(f"[Agent:{self.name}] Calling tool: {tool_name}")
        result = await self.tools.call(tool_name, **kwargs)
        logger.info(f"[Agent:{self.name}] Tool {tool_name} completed")
        return result

    def remember(self, key: str, value: Any):
        """
        存储到记忆

        Args:
            key: 记忆键
            value: 记忆值
        """
        if self.memory:
            # → 数据流: (agent_id, key, value) → MemoryManager.store()
            # MemoryManager 内部按 agent_id 命名空间隔离存储，
            # 并区分短期记忆（当次会话，会话结束即清除）和长期记忆（跨会话持久化）
            self.memory.store(self.agent_id, key, value)
            logger.debug(f"[Agent:{self.name}] Remembered: {key}")
        else:
            logger.warning(f"[Agent:{self.name}] No memory manager, cannot remember: {key}")

    def recall(self, key: str) -> Optional[Any]:
        """
        从记忆中读取

        Args:
            key: 记忆键

        Returns:
            记忆值，如果不存在则返回None
        """
        if self.memory:
            # → 数据流: MemoryManager.retrieve(agent_id, key) → 返回 value 或 None
            # 优先检索短期记忆（当前会话的上下文），若未命中则查找长期记忆（历史积累）
            value = self.memory.retrieve(self.agent_id, key)
            logger.debug(f"[Agent:{self.name}] Recalled: {key} = {value is not None}")
            return value
        else:
            logger.warning(f"[Agent:{self.name}] No memory manager, cannot recall: {key}")
            return None

    def get_context_memory(self, max_items: int = 10) -> List[Dict[str, Any]]:
        """
        获取上下文记忆

        返回最近的N条记忆，用于构建提示词

        Args:
            max_items: 最大记忆数量

        Returns:
            记忆列表
        """
        if self.memory:
            # 用途: 在构建 LLM prompt 时调用，将最近的相关记忆注入到系统提示或用户消息中，
            #       使 Agent 在本轮对话中能够"回想起"之前的经验
            # → 数据流: MemoryManager.get_context(agent_id, max_items) → List[Dict] → 注入到 prompt
            return self.memory.get_context(self.agent_id, max_items)
        return []

    def reset(self):
        """重置Agent状态

        清空消息历史，重置执行状态，但保留记忆
        """
        # 重置范围说明：
        #   ✅ 清空: messages（对话历史）、current_step（步数计数器）、
        #            is_complete、result、error、metadata
        #   ❌ 保留: memory（记忆管理器中的数据不受影响），
        #            tools（工具管理器引用）、agent_id（身份标识不变）
        # WHY: reset 用于"开始新对话"的场景，需要干净的对话状态，
        #      但跨对话的记忆（如用户偏好、学到的知识）应保留
        self.state = AgentState(
            agent_id=self.agent_id,
            agent_type=self.__class__.__name__,
            max_steps=self.max_steps
        )
        logger.info(f"[Agent] {self.name} state reset")

    def get_state_info(self) -> Dict:
        """
        获取状态信息

        Returns:
            包含Agent当前状态的字典
        """
        return {
            "agent_id": self.agent_id,
            "name": self.name,
            "type": self.state.agent_type,
            "description": self.description,
            "step": self.state.current_step,
            "max_steps": self.state.max_steps,
            "is_complete": self.state.is_complete,
            "error": self.state.error,
            "message_count": len(self.state.messages),
            "has_tools": self.tools is not None,
            "has_memory": self.memory is not None,
        }

    def __repr__(self) -> str:
        return f"<{self.__class__.__name__} name={self.name} id={self.agent_id}>"
