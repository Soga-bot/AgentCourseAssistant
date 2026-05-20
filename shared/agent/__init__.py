"""
Agent框架模块

提供智能体(Agent)系统的核心组件，包括：
- Agent基类
- 工具管理器
- 记忆管理器
- ReAct推理循环
- 工具注册中心

使用示例：
    from shared.agent import BaseAgent, ToolManager, MemoryManager
    from shared.agent import create_default_tool_manager

    # 创建带工具的Agent
    tools = create_default_tool_manager()
    agent = MyAgent(tools=tools)
"""

from .base import BaseAgent, AgentMessage, AgentState
from .tools import ToolManager, Tool
from .memory import MemoryManager, MemoryItem
from .react import ReActLoop
from .tool_registry import create_tool_manager, create_default_tool_manager, list_registered_tools

__all__ = [
    "BaseAgent",
    "AgentMessage",
    "AgentState",
    "ToolManager",
    "Tool",
    "MemoryManager",
    "MemoryItem",
    "ReActLoop",
    "create_tool_manager",
    "create_default_tool_manager",
    "list_registered_tools",
]

__version__ = "1.1.0"
