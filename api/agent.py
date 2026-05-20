# -*- coding: utf-8 -*-
"""
Agent API模块

提供Agent相关的HTTP API端点
"""
from typing import Dict, Any, Optional
from fastapi import HTTPException
from pydantic import BaseModel
import logging
import os
from pathlib import Path
from dotenv import load_dotenv

logger = logging.getLogger(__name__)

# 加载环境变量（从teacher/.env文件）
_dotenv_path = Path(__file__).parent.parent / "teacher" / ".env"
if _dotenv_path.exists():
    load_dotenv(dotenv_path=str(_dotenv_path))
    logger.info(f"[AgentAPI] 已加载环境变量: {_dotenv_path}")


# ==================== 请求模型 ====================

class AgentChatRequest(BaseModel):
    """Agent聊天请求"""
    message: str
    agent_type: str = "learning_tutor"
    session_id: Optional[str] = None
    student_id: Optional[str] = None
    course_id: Optional[str] = None
    chapter_id: Optional[str] = None


class AgentChatResponse(BaseModel):
    """Agent聊天响应"""
    success: bool
    response: str
    agent_id: str
    session_id: str
    metadata: Optional[Dict[str, Any]] = None


class AgentStatusResponse(BaseModel):
    """Agent状态响应"""
    agent_id: str
    agent_name: str
    agent_type: str
    message_count: int
    is_complete: bool
    has_tools: bool
    has_memory: bool
    available_tools: list


# ==================== Agent管理器 ====================

class AgentManager:
    """
    Agent管理器

    负责创建和管理Agent实例
    """

    def __init__(self):
        self._agents: Dict[str, Any] = {}
        self._sessions: Dict[str, str] = {}  # session_id -> agent_id

    async def get_or_create_agent(
        self,
        agent_type: str,
        session_id: Optional[str] = None,
        **kwargs
    ) -> Any:
        """
        获取或创建Agent

        Args:
            agent_type: Agent类型
            session_id: 会话ID
            **kwargs: 额外参数（如student_id）

        Returns:
            Agent实例
        """
        # 如果有会话ID，尝试获取现有Agent
        if session_id and session_id in self._sessions:
            agent_id = self._sessions[session_id]
            if agent_id in self._agents:
                logger.info(f"[AgentManager] 复用现有Agent: {agent_id}")
                return self._agents[agent_id]

        # 创建新Agent
        agent = await self._create_agent(agent_type, **kwargs)

        # 初始化Agent（如果有initialize方法）
        if hasattr(agent, 'initialize'):
            try:
                await agent.initialize()
                logger.info(f"[AgentManager] Agent初始化完成: {agent.agent_id}")
            except Exception as e:
                logger.warning(f"[AgentManager] Agent初始化失败: {e}")

        # 保存Agent
        agent_id = agent.agent_id
        self._agents[agent_id] = agent

        # 关联会话
        if session_id:
            self._sessions[session_id] = agent_id

        logger.info(f"[AgentManager] 创建新Agent: {agent_id} (类型: {agent_type})")
        return agent

    async def _create_agent(self, agent_type: str, **kwargs) -> Any:
        """
        创建指定类型的Agent

        Args:
            agent_type: Agent类型
            **kwargs: 额外参数

        Returns:
            Agent实例
        """
        # 导入Agent工具
        from shared.agent import create_default_tool_manager, MemoryManager
        from shared.llm_client import LLMClient, LLMConfig

        # 创建LLM客户端（所有Agent都可能需要）
        llm_client = None
        try:
            llm_client = LLMClient(LLMConfig())
            logger.info("[AgentManager] LLM客户端初始化成功")
        except Exception as e:
            logger.warning(f"[AgentManager] LLM客户端初始化失败: {e}")

        # 创建工具和记忆（传入llm_client，使工具可用）
        tools = create_default_tool_manager(require_llm=True)
        memory = MemoryManager()

        if agent_type == "learning_tutor":
            from agents import LearningTutorAgent

            agent = LearningTutorAgent(
                tools=tools,
                llm_client=llm_client,
                memory=memory,
                student_id=kwargs.get("student_id"),
                course_id=kwargs.get("course_id"),
                chapter_id=kwargs.get("chapter_id")
            )

        else:
            # 默认Agent
            from shared.agent import BaseAgent

            class DefaultAgent(BaseAgent):
                async def process(self, input_message: str) -> str:
                    return f"收到消息: {input_message}"

            agent = DefaultAgent(
                name="DefaultAgent",
                description="默认Agent",
                tools=tools,
                memory=memory
            )

        return agent

    def get_agent(self, agent_id: str) -> Optional[Any]:
        """获取Agent实例"""
        return self._agents.get(agent_id)

    def remove_agent(self, agent_id: str):
        """移除Agent"""
        if agent_id in self._agents:
            del self._agents[agent_id]

            # 移除会话关联
            sessions_to_remove = [
                session_id for session_id, aid in self._sessions.items()
                if aid == agent_id
            ]
            for session_id in sessions_to_remove:
                del self._sessions[session_id]

            logger.info(f"[AgentManager] 移除Agent: {agent_id}")


# ==================== 全局Agent管理器 ====================

_agent_manager: Optional[AgentManager] = None


def get_agent_manager() -> AgentManager:
    """获取全局Agent管理器"""
    global _agent_manager
    if _agent_manager is None:
        _agent_manager = AgentManager()
    return _agent_manager


# ==================== API处理函数 ====================

async def handle_agent_chat(request: AgentChatRequest) -> AgentChatResponse:
    """
    处理Agent聊天请求

    Args:
        request: 聊天请求

    Returns:
        聊天响应
    """
    manager = get_agent_manager()

    try:
        # 获取或创建Agent
        agent = await manager.get_or_create_agent(
            agent_type=request.agent_type,
            session_id=request.session_id,
            student_id=request.student_id,
            course_id=request.course_id,
            chapter_id=request.chapter_id
        )

        # 处理聊天消息
        response_text = await agent.process(request.message)

        # 获取Agent状态
        state = agent.get_state_info()

        # 构建元数据
        metadata = {
            "message_count": state["message_count"],
            "is_complete": state["is_complete"]
        }

        return AgentChatResponse(
            success=True,
            response=response_text,
            agent_id=agent.agent_id,
            session_id=request.session_id or agent.agent_id,
            metadata=metadata
        )

    except Exception as e:
        logger.error(f"[handle_agent_chat] Error: {e}")
        raise HTTPException(status_code=500, detail=f"处理聊天请求时出错: {str(e)}")


async def handle_agent_status(agent_id: str) -> AgentStatusResponse:
    """
    获取Agent状态

    Args:
        agent_id: Agent ID

    Returns:
        Agent状态
    """
    manager = get_agent_manager()
    agent = manager.get_agent(agent_id)

    if not agent:
        raise HTTPException(status_code=404, detail=f"Agent不存在: {agent_id}")

    try:
        state = agent.get_state_info()

        # 获取可用工具列表
        available_tools = []
        if agent.tools:
            available_tools = [t.name for t in agent.tools.list_tools()]

        return AgentStatusResponse(
            agent_id=agent.agent_id,
            agent_name=agent.name,
            agent_type=state["type"],
            message_count=state["message_count"],
            is_complete=state["is_complete"],
            has_tools=state["has_tools"],
            has_memory=state["has_memory"],
            available_tools=available_tools
        )

    except Exception as e:
        logger.error(f"[handle_agent_status] Error: {e}")
        raise HTTPException(status_code=500, detail=f"获取Agent状态时出错: {str(e)}")


def handle_agent_reset(agent_id: str) -> Dict[str, Any]:
    """
    重置Agent状态

    Args:
        agent_id: Agent ID

    Returns:
        重置结果
    """
    manager = get_agent_manager()
    agent = manager.get_agent(agent_id)

    if not agent:
        raise HTTPException(status_code=404, detail=f"Agent不存在: {agent_id}")

    try:
        agent.reset()

        return {
            "success": True,
            "message": "Agent状态已重置",
            "agent_id": agent_id
        }

    except Exception as e:
        logger.error(f"[handle_agent_reset] Error: {e}")
        raise HTTPException(status_code=500, detail=f"重置Agent状态时出错: {str(e)}")


# ==================== 路由注册函数 ====================

def register_agent_routes(app):
    """
    注册Agent路由到FastAPI应用

    Args:
        app: FastAPI应用实例
    """
    from fastapi import APIRouter

    # 创建路由
    router = APIRouter(prefix="/api/agent", tags=["Agent"])

    @router.post("/chat", response_model=AgentChatResponse)
    async def chat(request: AgentChatRequest):
        """
        Agent聊天接口

        发送消息给Agent并获取响应

        - **message**: 用户消息
        - **agent_type**: Agent类型 (course_generator, learning_tutor)
        - **session_id**: 会话ID（可选，用于保持上下文）
        - **student_id**: 学生ID（可选，用于学习助教）
        """
        return await handle_agent_chat(request)

    @router.get("/status/{agent_id}", response_model=AgentStatusResponse)
    async def get_status(agent_id: str):
        """
        获取Agent状态

        返回指定Agent的当前状态信息

        - **agent_id**: Agent ID
        """
        return await handle_agent_status(agent_id)

    @router.post("/reset/{agent_id}")
    async def reset(agent_id: str):
        """
        重置Agent状态

        重置指定Agent的状态，清空消息历史

        - **agent_id**: Agent ID
        """
        return handle_agent_reset(agent_id)

    @router.get("/tools")
    async def list_tools():
        """
        列出可用的Agent工具

        返回当前可用的所有工具列表
        """
        from shared.agent import create_default_tool_manager

        tools = create_default_tool_manager(require_llm=True)
        tool_list = tools.list_tools()

        return {
            "success": True,
            "tool_count": len(tool_list),
            "tools": [
                {
                    "name": t.name,
                    "description": t.description,
                    "parameters": list(t.parameters.keys())
                }
                for t in tool_list
            ]
        }

    @router.get("/info")
    async def agent_info():
        """
        获取Agent系统信息

        返回Agent系统的基本信息
        """
        manager = get_agent_manager()

        return {
            "success": True,
            "active_agents": len(manager._agents),
            "active_sessions": len(manager._sessions),
            "available_agent_types": [
                "learning_tutor"
            ]
        }

    # 注册路由到应用
    app.include_router(router)

    logger.info("[AgentAPI] 路由已注册到 /api/agent/*")

