"""
任务管理模块

提供任务进度查询、任务列表、手动清理等功能
"""

# 全局变量（从 main.py 传入）
_progress_manager = None


def init_task_management(progress_manager):
    """初始化任务管理模块"""
    global _progress_manager
    _progress_manager = progress_manager


async def get_progress(task_id: str):
    """查询任务进度"""
    return _progress_manager.get_progress(task_id)


async def list_tasks():
    """列出所有任务"""
    return {
        "total": len(_progress_manager.tasks),
        "tasks": list(_progress_manager.tasks.keys())
    }


async def manual_cleanup():
    """手动触发任务清理（管理接口）"""
    stats = _progress_manager.cleanup_old_tasks(retention_hours=0)  # 立即清理所有已完成/失败任务
    return {
        "message": "清理完成",
        "cleaned_count": stats["cleaned_count"],
        "remaining_count": stats["remaining_count"]
    }


def register_task_routes(app):
    """注册任务管理路由"""

    @app.get("/progress/{task_id}")
    async def api_get_progress(task_id: str):
        """查询任务进度"""
        return await get_progress(task_id)

    @app.get("/tasks")
    async def api_list_tasks():
        """列出所有任务"""
        return await list_tasks()

    @app.post("/admin/cleanup")
    async def api_manual_cleanup():
        """手动触发任务清理（管理接口）"""
        return await manual_cleanup()
