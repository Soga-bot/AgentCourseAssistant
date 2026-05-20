"""
学生端模块

提供学生课程访问等功能
"""

from fastapi import HTTPException

from shared.database import course_db, user_db, history_db
from shared.session import get_session


async def get_student_courses(session_id: str = ""):
    """获取学生可访问的课程"""
    session = get_session(session_id)
    if not session or session["role"] != "student":
        raise HTTPException(status_code=403, detail="需要学生权限")

    # 获取用户的班级信息
    user = user_db.get_user_by_id(session["user_id"])
    user_class_name = user.get("class", "")

    courses = course_db.get_accessible_courses(
        session["user_id"],
        session["role"],
        user_class_name
    )

    return {"success": True, "courses": courses}


async def get_student_course_detail(course_id: str, session_id: str = ""):
    """获取学生课程详情"""
    session = get_session(session_id)
    if not session or session["role"] != "student":
        raise HTTPException(status_code=403, detail="需要学生权限")

    course = course_db.get_course_by_id(course_id)
    if not course:
        raise HTTPException(status_code=404, detail="课程不存在")

    # 验证访问权限
    user = user_db.get_user_by_id(session["user_id"])
    user_class_name = user.get("class", "")

    accessible_courses = course_db.get_accessible_courses(
        session["user_id"],
        session["role"],
        user_class_name
    )

    accessible_ids = [c["id"] for c in accessible_courses]
    if course_id not in accessible_ids:
        raise HTTPException(status_code=403, detail="无权访问此课程")

    return {"success": True, "course": course}


def register_student_routes(app):
    """注册学生端相关路由"""

    @app.get("/api/student/courses")
    async def api_get_student_courses(session_id: str = ""):
        """获取学生可访问的课程"""
        return await get_student_courses(session_id)

    @app.get("/api/student/course/{course_id}")
    async def api_get_student_course_detail(course_id: str, session_id: str = ""):
        """获取学生课程详情"""
        return await get_student_course_detail(course_id, session_id)
