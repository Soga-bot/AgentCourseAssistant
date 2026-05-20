"""
班级管理模块

提供班级创建、管理、加入、退出等功能
"""

from fastapi import HTTPException
from pydantic import BaseModel

from shared.database import (
    class_db, user_db, history_db
)
from shared.session import get_session


class ClassCreateRequest(BaseModel):
    """创建班级请求"""
    name: str
    grade: str = ""
    description: str = ""


class ClassJoinRequest(BaseModel):
    """加入班级请求"""
    class_id: str


async def create_class(request: ClassCreateRequest, session_id: str = ""):
    """教师创建班级"""
    session = get_session(session_id)
    if not session or session["role"] != "teacher":
        raise HTTPException(status_code=403, detail="需要教师权限")

    class_id = class_db.create_class(
        teacher_id=session["user_id"],
        name=request.name,
        grade=request.grade,
        description=request.description
    )

    if not class_id:
        raise HTTPException(status_code=400, detail="班级名称已存在")

    history_db.add_record(
        session["user_id"],
        "create_class",
        details={"class_id": class_id, "name": request.name}
    )

    return {"success": True, "class_id": class_id, "message": "班级创建成功"}


async def get_teacher_classes(session_id: str = ""):
    """获取教师创建的所有班级"""
    session = get_session(session_id)
    if not session or session["role"] != "teacher":
        raise HTTPException(status_code=403, detail="需要教师权限")

    classes = class_db.get_classes_by_teacher(session["user_id"])

    # 添加学生人数统计
    result = []
    for cls in classes:
        cls_info = cls.copy()
        cls_info["student_count"] = len(cls.get("student_ids", []))
        result.append(cls_info)

    return {"success": True, "classes": result}


async def get_class_students(class_id: str, session_id: str = ""):
    """获取班级学生列表"""
    session = get_session(session_id)
    if not session:
        raise HTTPException(status_code=401, detail="需要登录")

    cls = class_db.get_class_by_id(class_id)
    if not cls:
        raise HTTPException(status_code=404, detail="班级不存在")

    # 只有班级创建者可以查看
    if session["role"] == "teacher" and cls.get("teacher_id") != session["user_id"]:
        raise HTTPException(status_code=403, detail="无权查看此班级")

    students = class_db.get_class_students(class_id)
    return {"success": True, "students": students, "class_name": cls["name"]}


async def delete_class(class_id: str, session_id: str = ""):
    """删除班级"""
    session = get_session(session_id)
    if not session or session["role"] != "teacher":
        raise HTTPException(status_code=403, detail="需要教师权限")

    success = class_db.delete_class(class_id, session["user_id"])
    if not success:
        raise HTTPException(status_code=404, detail="班级不存在或无权删除")

    return {"success": True, "message": "班级已删除"}


async def search_classes(keyword: str = "", session_id: str = ""):
    """搜索所有班级（学生用）"""
    session = get_session(session_id)
    if not session or session["role"] != "student":
        raise HTTPException(status_code=403, detail="需要学生权限")

    if keyword:
        classes = class_db.search_classes(keyword)
    else:
        classes = class_db.get_all_classes()

    # 过滤掉已加入的班级
    user = user_db.get_user_by_id(session["user_id"])
    user_class_name = user.get("class", "")

    result = []
    for cls in classes:
        cls_info = cls.copy()
        # 标记是否已加入
        cls_info["joined"] = (session["user_id"] in cls.get("student_ids", []) or
                             cls["name"] == user_class_name)
        # 添加学生人数
        cls_info["student_count"] = len(cls.get("student_ids", []))
        result.append(cls_info)

    return {"success": True, "classes": result}


async def join_class(request: ClassJoinRequest, session_id: str = ""):
    """学生加入班级"""
    session = get_session(session_id)
    if not session or session["role"] != "student":
        raise HTTPException(status_code=403, detail="需要学生权限")

    cls = class_db.get_class_by_id(request.class_id)
    if not cls:
        raise HTTPException(status_code=404, detail="班级不存在")

    # 检查是否已加入
    if session["user_id"] in cls.get("student_ids", []):
        raise HTTPException(status_code=400, detail="已加入此班级")

    success = class_db.join_class(request.class_id, session["user_id"])
    if not success:
        raise HTTPException(status_code=400, detail="加入失败")

    history_db.add_record(
        session["user_id"],
        "join_class",
        details={"class_id": request.class_id, "class_name": cls["name"]}
    )

    return {"success": True, "message": f"已加入 {cls['name']}"}


async def leave_class(request: ClassJoinRequest, session_id: str = ""):
    """学生退出班级"""
    session = get_session(session_id)
    if not session or session["role"] != "student":
        raise HTTPException(status_code=403, detail="需要学生权限")

    success = class_db.leave_class(request.class_id, session["user_id"])
    if not success:
        raise HTTPException(status_code=400, detail="退出失败")

    # 清除用户的班级信息
    user_db.update_user(session["user_id"], {"class": ""})

    return {"success": True, "message": "已退出班级"}


def register_class_routes(app):
    """注册班级管理相关路由"""

    @app.post("/api/teacher/class")
    async def api_create_class(request: ClassCreateRequest, session_id: str = ""):
        """教师创建班级"""
        return await create_class(request, session_id)

    @app.get("/api/teacher/classes")
    async def api_get_teacher_classes(session_id: str = ""):
        """获取教师创建的所有班级"""
        return await get_teacher_classes(session_id)

    @app.get("/api/class/{class_id}/students")
    async def api_get_class_students(class_id: str, session_id: str = ""):
        """获取班级学生列表"""
        return await get_class_students(class_id, session_id)

    @app.delete("/api/teacher/class/{class_id}")
    async def api_delete_class(class_id: str, session_id: str = ""):
        """删除班级"""
        return await delete_class(class_id, session_id)

    @app.get("/api/classes")
    async def api_search_classes(keyword: str = "", session_id: str = ""):
        """搜索所有班级（学生用）"""
        return await search_classes(keyword, session_id)

    @app.post("/api/student/class/join")
    async def api_join_class(request: ClassJoinRequest, session_id: str = ""):
        """学生加入班级"""
        return await join_class(request, session_id)

    @app.post("/api/student/class/leave")
    async def api_leave_class(request: ClassJoinRequest, session_id: str = ""):
        """学生退出班级"""
        return await leave_class(request, session_id)
