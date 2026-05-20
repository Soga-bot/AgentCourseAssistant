"""
系统管理模块

提供健康检查、系统统计、个人资料等功能
"""

import os
from pathlib import Path

from fastapi import HTTPException

from shared.database import user_db
from shared.session import get_session
from shared.knowledge_base import knowledge_base


# 全局变量（从 main.py 传入）
_progress_manager = None
_output_dir = None
_temp_dir = None
_static_dir = None
_base_dir = None


def init_admin(progress_manager, output_dir, temp_dir, static_dir, base_dir):
    """初始化管理模块"""
    global _progress_manager, _output_dir, _temp_dir, _static_dir, _base_dir
    _progress_manager = progress_manager
    _output_dir = output_dir
    _temp_dir = temp_dir
    _static_dir = static_dir
    _base_dir = base_dir


async def health_check():
    """健康检查"""
    teacher_frontend_path = _base_dir / "teacher" / "frontend"
    student_frontend_path = _base_dir / "student" / "frontend"

    return {
        "status": "ok",
        "service": "初中数学双模式生成系统",
        "version": "2.0.0",
        "modes": ["video", "course"],
        "debug": {
            "_BASE_DIR": str(_base_dir),
            "teacher_frontend_path": str(teacher_frontend_path),
            "teacher_frontend_exists": teacher_frontend_path.exists(),
            "student_frontend_path": str(student_frontend_path),
            "student_frontend_exists": student_frontend_path.exists()
        },
        "knowledge_base": {
            "textbook_versions": len(knowledge_base.get_versions()),
            "formulas": len(knowledge_base._formulas),
            "forbidden_keywords": len(knowledge_base._forbidden_keywords)
        }
    }


async def get_admin_stats():
    """获取系统统计信息（管理接口）"""
    active_count = sum(1 for t in _progress_manager.tasks.values() if t.get("status") == "processing")
    completed_count = sum(1 for t in _progress_manager.tasks.values() if t.get("status") == "completed")
    failed_count = sum(1 for t in _progress_manager.tasks.values() if t.get("status") == "failed")

    # 检查输出目录
    output_exists = _output_dir.exists()
    temp_exists = _temp_dir.exists()
    static_exists = _static_dir.exists()

    # 计算输出目录大小
    output_size = 0
    if output_exists:
        for f in _output_dir.rglob("*"):
            if f.is_file():
                output_size += f.stat().st_size

    return {
        "tasks": {
            "total": len(_progress_manager.tasks),
            "active": active_count,
            "completed": completed_count,
            "failed": failed_count
        },
        "directories": {
            "output_exists": output_exists,
            "temp_exists": temp_exists,
            "static_exists": static_exists,
            "output_size_mb": round(output_size / 1024 / 1024, 2)
        },
        "cleanup_config": {
            "enabled": os.getenv("TASK_CLEANUP_ENABLED", "true").lower() == "true",
            "retention_hours": int(os.getenv("TASK_RETENTION_HOURS", "24")),
            "cleanup_interval_seconds": int(os.getenv("CLEANUP_INTERVAL_SECONDS", "3600"))
        }
    }


async def get_profile(session_id: str = ""):
    """获取个人资料"""
    session = get_session(session_id)
    if not session:
        raise HTTPException(status_code=401, detail="未登录")

    user = user_db.get_user_by_id(session["user_id"])
    if not user:
        raise HTTPException(status_code=404, detail="用户不存在")

    user_info = {k: v for k, v in user.items() if k != "password"}
    return {"success": True, "user": user_info}


def register_admin_routes(app):
    """注册系统管理路由"""

    @app.get("/health")
    async def api_health_check():
        """健康检查"""
        return await health_check()

    @app.get("/admin/stats")
    async def api_get_admin_stats():
        """获取系统统计信息（管理接口）"""
        return await get_admin_stats()

    @app.get("/api/common/profile")
    async def api_get_profile(session_id: str = ""):
        """获取个人资料"""
        return await get_profile(session_id)
