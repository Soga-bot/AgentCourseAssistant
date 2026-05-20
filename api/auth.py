"""
认证模块

提供用户注册、登录、登出等认证功能
"""

from fastapi import HTTPException
from pydantic import BaseModel

from shared.database import user_db, history_db
from shared.session import create_session, get_session, remove_session


class RegisterRequest(BaseModel):
    """注册请求"""
    username: str
    password: str
    role: str  # "teacher" or "student"
    email: str = ""
    student_id: str = ""
    class_name: str = ""


class LoginRequest(BaseModel):
    """登录请求"""
    username: str
    password: str


async def register(request: RegisterRequest):
    """用户注册"""
    # 验证角色
    if request.role not in ["teacher", "student"]:
        raise HTTPException(status_code=400, detail="角色必须是 teacher 或 student")

    # 验证用户名长度和格式
    if len(request.username) < 2 or len(request.username) > 20:
        raise HTTPException(status_code=400, detail="用户名长度必须在2-20个字符之间")

    # 验证密码长度
    if len(request.password) < 6:
        raise HTTPException(status_code=400, detail="密码长度至少为6位")

    # 验证学生信息
    if request.role == "student":
        if not request.student_id or not request.student_id.strip():
            raise HTTPException(status_code=400, detail="学生需要提供学号")
        if not request.class_name or not request.class_name.strip():
            raise HTTPException(status_code=400, detail="学生需要提供班级")

    # 创建用户
    user = user_db.create_user(
        username=request.username.strip(),
        password=request.password,
        role=request.role,
        email=request.email.strip() if request.email else "",
        student_id=request.student_id.strip() if request.student_id else "",
        class_name=request.class_name.strip() if request.class_name else ""
    )

    if not user:
        raise HTTPException(status_code=400, detail="用户名已存在")

    # 记录注册历史
    history_db.add_record(user["id"], "register", details={"username": user["username"], "role": user["role"]})

    return {
        "success": True,
        "message": "注册成功",
        "user": user
    }


async def login(request: LoginRequest):
    """用户登录"""
    # 查找用户
    user = user_db.get_user_by_username(request.username)
    if not user:
        raise HTTPException(status_code=401, detail="用户名或密码错误")

    # 验证密码
    if not user_db.verify_password(request.password, user["password"]):
        raise HTTPException(status_code=401, detail="用户名或密码错误")

    # 创建会话
    session_id = create_session(user["id"], user["username"], user["role"])

    # 记录登录历史
    history_db.add_record(user["id"], "login", details={"username": user["username"]})

    # 返回用户信息（不含密码）
    user_info = {k: v for k, v in user.items() if k != "password"}

    return {
        "success": True,
        "message": "登录成功",
        "session_id": session_id,
        "user": user_info
    }


async def logout(session_id: str = ""):
    """用户登出"""
    if session_id:
        remove_session(session_id)
    return {"success": True, "message": "登出成功"}


async def get_current_user(session_id: str = ""):
    """获取当前登录用户信息"""
    if not session_id:
        raise HTTPException(status_code=401, detail="未登录")

    session = get_session(session_id)
    if not session:
        raise HTTPException(status_code=401, detail="会话无效或已过期")

    user = user_db.get_user_by_id(session["user_id"])
    if not user:
        raise HTTPException(status_code=404, detail="用户不存在")

    user_info = {k: v for k, v in user.items() if k != "password"}
    return {"success": True, "user": user_info}


def register_auth_routes(app):
    """注册认证相关路由"""

    @app.post("/api/auth/register")
    async def api_register(request: RegisterRequest):
        """用户注册"""
        return await register(request)

    @app.post("/api/auth/login")
    async def api_login(request: LoginRequest):
        """用户登录"""
        return await login(request)

    @app.post("/api/auth/logout")
    async def api_logout(session_id: str = ""):
        """用户登出"""
        return await logout(session_id)

    @app.get("/api/auth/me")
    async def api_get_current_user(session_id: str = ""):
        """获取当前登录用户信息"""
        return await get_current_user(session_id)
