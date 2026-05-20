"""
教师端模块

提供教师课程管理、分享、历史记录、教案管理等功能
"""

from fastapi import HTTPException
from pydantic import BaseModel
from typing import List, Dict
from pathlib import Path
import shutil

from shared.database import (
    course_db, share_db, history_db, user_db,
    class_db
)
from shared.session import get_session
from shared.utils import get_course_output_dir


class ShareRequest(BaseModel):
    """分享课程请求"""
    course_id: str
    student_ids: List[str] = []
    class_id: str = ""


async def get_teacher_courses(session_id: str = ""):
    """获取教师的课程列表（仅学生课程，排除教师自定义教案）"""
    session = get_session(session_id)
    if not session or session["role"] != "teacher":
        raise HTTPException(status_code=403, detail="需要教师权限")

    courses = course_db.get_courses_by_teacher(session["user_id"])
    # 排除教师自定义教案（有 content_type 标记的），只显示学生课程
    _TEACHER_CONTENT_TYPES = {"lesson_plan", "teaching_script", "board_design", "review_outline"}
    courses = [c for c in courses
               if (c.get("metadata") or {}).get("content_type", "") not in _TEACHER_CONTENT_TYPES]
    return {"success": True, "courses": courses}


async def get_teacher_course_detail(course_id: str, session_id: str = ""):
    """获取教师课程详情"""
    session = get_session(session_id)
    if not session or session["role"] != "teacher":
        raise HTTPException(status_code=403, detail="需要教师权限")

    course = course_db.get_course_by_id(course_id)
    if not course:
        raise HTTPException(status_code=404, detail="课程不存在")

    # 验证课程所有权
    if course.get("teacher_id") != session["user_id"]:
        raise HTTPException(status_code=403, detail="无权访问此课程")

    return {"success": True, "course": course}


async def delete_teacher_course(course_id: str, session_id: str = ""):
    """删除教师课程"""
    session = get_session(session_id)
    if not session or session["role"] != "teacher":
        raise HTTPException(status_code=403, detail="需要教师权限")

    # 验证课程所有权
    course = course_db.get_course_by_id(course_id)
    if not course:
        raise HTTPException(status_code=404, detail="课程不存在")

    if course.get("teacher_id") != session["user_id"]:
        raise HTTPException(status_code=403, detail="无权删除此课程")

    # 删除课程文件
    course_dir = get_course_output_dir(course_id)
    if course_dir.exists():
        shutil.rmtree(course_dir, ignore_errors=True)

    # 删除数据库记录
    success = course_db.delete_course(course_id)
    if not success:
        raise HTTPException(status_code=500, detail="删除课程失败")

    return {"success": True, "message": "课程已删除"}


async def share_course(request: ShareRequest, session_id: str = ""):
    """分享课程到班级或学生"""
    session = get_session(session_id)
    if not session or session["role"] != "teacher":
        raise HTTPException(status_code=403, detail="需要教师权限")

    # 验证课程所有权
    course = course_db.get_course_by_id(request.course_id)
    if not course or course.get("teacher_id") != session["user_id"]:
        raise HTTPException(status_code=403, detail="无权分享此课程")

    share_id = None

    # 分享到班级
    if request.class_id:
        # 验证班级所有权
        cls = class_db.get_class_by_id(request.class_id)
        if not cls or cls.get("teacher_id") != session["user_id"]:
            raise HTTPException(status_code=403, detail="无权分享到此班级")

        share_id = share_db.share_course_to_class(session["user_id"], request.course_id, request.class_id)

        # 记录历史
        history_db.add_record(
            session["user_id"],
            "share_course_to_class",
            request.course_id,
            details={"class_id": request.class_id, "class_name": cls.get("name", "")}
        )

        return {"success": True, "share_id": share_id, "message": f"已分享到 {cls.get('name', '')}"}

    # 分享给单个学生（兼容旧方式）
    elif request.student_ids:
        share_id = share_db.share_course(session["user_id"], request.course_id, request.student_ids)

        # 记录历史
        history_db.add_record(
            session["user_id"],
            "share_course",
            request.course_id,
            details={"student_count": len(request.student_ids)}
        )

        return {"success": True, "share_id": share_id, "message": f"已分享给 {len(request.student_ids)} 位学生"}

    else:
        raise HTTPException(status_code=400, detail="请选择要分享的班级或学生")


async def get_teacher_history(session_id: str = "", limit: int = 50):
    """获取教师历史记录"""
    session = get_session(session_id)
    if not session or session["role"] != "teacher":
        raise HTTPException(status_code=403, detail="需要教师权限")

    history = history_db.get_user_history(session["user_id"], limit)
    return {"success": True, "history": history}


async def get_class_students(class_name: str = "", session_id: str = ""):
    """获取班级学生列表"""
    session = get_session(session_id)
    if not session or session["role"] != "teacher":
        raise HTTPException(status_code=403, detail="需要教师权限")

    if not class_name:
        raise HTTPException(status_code=400, detail="需要提供班级名称")

    students = user_db.get_students_by_class(class_name)
    return {"success": True, "students": students}


# ==================== 教案管理 ====================

# 教材版本ID到中文名的映射
_VERSION_NAMES = {
    "renjiao_v1": "人教版",
    "beishi_v1": "北师大版",
    "suke_v1": "苏科版",
    "huke_v1": "沪科版",
}


def _get_version_display(version: str) -> str:
    """获取教材版本的显示名称"""
    return _VERSION_NAMES.get(version, version or "自定义教案")


async def get_teacher_lesson_plans(session_id: str = ""):
    """获取教师的教案列表（包含学生课程和教师自定义教案）"""
    session = get_session(session_id)
    if not session or session["role"] != "teacher":
        raise HTTPException(status_code=403, detail="需要教师权限")

    # 获取教师的课程列表作为教案
    courses = course_db.get_courses_by_teacher(session["user_id"])

    # 转换为教案格式
    lesson_plans = []
    for course in courses:
        lesson_plans.append({
            "id": course["id"],
            "title": course.get("title", f"{course.get('grade', '')} {course.get('chapter', '')}"),
            "grade": course.get("grade", ""),
            "chapter": course.get("chapter", ""),
            "lesson_type": _get_version_display(course.get("version", "")),
            "created_at": course.get("created_at", ""),
            "sections": course.get("sections", {}),
            "content": course.get("content", {})
        })

    return {"success": True, "lesson_plans": lesson_plans}


async def get_lesson_plan_detail(plan_id: str, session_id: str = ""):
    """获取教案详情"""
    session = get_session(session_id)
    if not session or session["role"] != "teacher":
        raise HTTPException(status_code=403, detail="需要教师权限")

    course = course_db.get_course_by_id(plan_id)
    if not course:
        raise HTTPException(status_code=404, detail="教案不存在")

    # 验证权限
    if course.get("teacher_id") != session["user_id"]:
        raise HTTPException(status_code=403, detail="无权访问此教案")

    lesson_plan = {
        "id": course["id"],
        "title": course.get("title", f"{course.get('grade', '')} {course.get('chapter', '')}"),
        "grade": course.get("grade", ""),
        "chapter": course.get("chapter", ""),
        "lesson_type": _get_version_display(course.get("version", "")),
        "created_at": course.get("created_at", ""),
        "sections": course.get("sections", {}),
        "content": course.get("content", {}),
        "content_source": (course.get("metadata") or {}).get("content_source", ""),
        "metadata": course.get("metadata", {})
    }

    return {"success": True, "lesson_plan": lesson_plan}


async def delete_lesson_plan(plan_id: str, session_id: str = ""):
    """删除教案"""
    session = get_session(session_id)
    if not session or session["role"] != "teacher":
        raise HTTPException(status_code=403, detail="需要教师权限")

    # 验证教案所有权
    course = course_db.get_course_by_id(plan_id)
    if not course:
        raise HTTPException(status_code=404, detail="教案不存在")

    if course.get("teacher_id") != session["user_id"]:
        raise HTTPException(status_code=403, detail="无权删除此教案")

    # 删除教案（其实就是删除课程）
    success = course_db.delete_course(plan_id)
    if not success:
        raise HTTPException(status_code=500, detail="删除失败")

    # 记录历史
    history_db.add_record(
        session["user_id"],
        "delete_lesson_plan",
        plan_id,
        details={"title": course.get("title", "")}
    )

    return {"success": True, "message": "教案已删除"}


async def download_lesson_plan(plan_id: str, session_id: str = ""):
    """下载教案（返回教案内容供前端生成文件）"""
    session = get_session(session_id)
    if not session or session["role"] != "teacher":
        raise HTTPException(status_code=403, detail="需要教师权限")

    course = course_db.get_course_by_id(plan_id)
    if not course:
        raise HTTPException(status_code=404, detail="教案不存在")

    # 验证权限
    if course.get("teacher_id") != session["user_id"]:
        raise HTTPException(status_code=403, detail="无权访问此教案")

    # 构建教案内容
    lesson_plan = {
        "id": course["id"],
        "title": course.get("title", f"{course.get('grade', '')} {course.get('chapter', '')}"),
        "grade": course.get("grade", ""),
        "chapter": course.get("chapter", ""),
        "lesson_type": _get_version_display(course.get("version", "")),
        "created_at": course.get("created_at", ""),
        "sections": course.get("sections", {}),
        "content": course.get("content", {}),
        "metadata": course.get("metadata", {})
    }

    return {"success": True, "lesson_plan": lesson_plan}


def register_teacher_routes(app):
    """注册教师端相关路由"""

    @app.get("/api/teacher/courses")
    async def api_get_teacher_courses(session_id: str = ""):
        """获取教师的课程列表"""
        return await get_teacher_courses(session_id)

    @app.get("/api/teacher/course/{course_id}")
    async def api_get_teacher_course_detail(course_id: str, session_id: str = ""):
        """获取教师课程详情"""
        return await get_teacher_course_detail(course_id, session_id)

    @app.delete("/api/teacher/course/{course_id}")
    async def api_delete_teacher_course(course_id: str, session_id: str = ""):
        """删除教师课程"""
        return await delete_teacher_course(course_id, session_id)

    @app.post("/api/teacher/course/{course_id}/delete")
    async def api_delete_teacher_course_post(course_id: str, session_id: str = ""):
        """删除教师课程（POST备用接口）"""
        return await delete_teacher_course(course_id, session_id)

    @app.post("/api/teacher/share")
    async def api_share_course(request: ShareRequest, session_id: str = ""):
        """分享课程到班级或学生"""
        return await share_course(request, session_id)

    @app.get("/api/teacher/history")
    async def api_get_teacher_history(session_id: str = "", limit: int = 50):
        """获取教师历史记录"""
        return await get_teacher_history(session_id, limit)

    @app.get("/api/teacher/students")
    async def api_get_class_students(class_name: str = "", session_id: str = ""):
        """获取班级学生列表"""
        return await get_class_students(class_name, session_id)

    # 教案管理路由
    @app.get("/api/teacher/lesson-plans")
    async def api_get_teacher_lesson_plans(session_id: str = ""):
        """获取教师的教案列表"""
        return await get_teacher_lesson_plans(session_id)

    @app.get("/api/teacher/lesson-plans/{plan_id}")
    async def api_get_lesson_plan_detail(plan_id: str, session_id: str = ""):
        """获取教案详情"""
        return await get_lesson_plan_detail(plan_id, session_id)

    @app.get("/api/teacher/lesson-plans/{plan_id}/download")
    async def api_download_lesson_plan(plan_id: str, session_id: str = ""):
        """下载教案"""
        return await download_lesson_plan(plan_id, session_id)

    @app.delete("/api/teacher/lesson-plans/{plan_id}")
    async def api_delete_lesson_plan(plan_id: str, session_id: str = ""):
        """删除教案"""
        return await delete_lesson_plan(plan_id, session_id)
