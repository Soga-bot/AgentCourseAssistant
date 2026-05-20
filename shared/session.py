"""
会话管理模块

提供用户会话的创建、获取和删除功能
"""

from typing import Dict, Optional

# 全局会话存储（生产环境应使用Redis）
_active_sessions: Dict[str, Dict] = {}


def create_session(user_id: str, username: str, role: str) -> str:
    """创建新会话"""
    import uuid
    session_id = uuid.uuid4().hex
    _active_sessions[session_id] = {
        "user_id": user_id,
        "username": username,
        "role": role
    }
    return session_id


def get_session(session_id: str) -> Optional[Dict]:
    """获取会话"""
    return _active_sessions.get(session_id)


def remove_session(session_id: str):
    """移除会话"""
    _active_sessions.pop(session_id, None)


def get_all_sessions() -> Dict[str, Dict]:
    """获取所有活动会话（用于调试）"""
    return _active_sessions.copy()
