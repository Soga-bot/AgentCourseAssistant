"""
初中数学双模式生成系统 - 主程序入口

支持两种模式：
1. 视频模式：数学题讲解视频生成
2. 课程模式：课程内容生成
"""

import asyncio
import contextlib
import json
import os
import uuid
import time
from pathlib import Path
from typing import Dict, Optional, Any, List, AsyncGenerator
from datetime import datetime, timedelta

from fastapi import FastAPI, HTTPException, BackgroundTasks, UploadFile, File, Form, Request
from fastapi.responses import JSONResponse, FileResponse, HTMLResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.middleware import Middleware
from pydantic import BaseModel
from dotenv import load_dotenv

# 加载环境变量（必须在读取环境变量之前调用）
# 显式指定.env文件路径，因为.env文件在teacher/目录下
_DOTENV_PATH = Path(__file__).parent / "teacher" / ".env"
load_dotenv(dotenv_path=str(_DOTENV_PATH))

# ==================== 配置常量 ====================

# 基础目录（使用绝对路径避免工作目录问题）
_BASE_DIR = Path(__file__).parent

# 输出目录配置（使用绝对路径）
OUTPUT_DIR = _BASE_DIR / "output"
TEMP_DIR = _BASE_DIR / "temp"
STATIC_DIR = _BASE_DIR / "static"

# 任务清理配置
TASK_CLEANUP_ENABLED = os.getenv("TASK_CLEANUP_ENABLED", "true").lower() == "true"
TASK_RETENTION_HOURS = int(os.getenv("TASK_RETENTION_HOURS", "24"))  # 任务保留时间（小时）
CLEANUP_INTERVAL_SECONDS = int(os.getenv("CLEANUP_INTERVAL_SECONDS", "3600"))  # 清理间隔（秒，默认1小时）

# ==================== 早期初始化 ====================
# 在 FastAPI 应用创建前创建必要目录（StaticFiles 需要）
STATIC_DIR.mkdir(parents=True, exist_ok=True)
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
TEMP_DIR.mkdir(parents=True, exist_ok=True)

# 导入视频流水线模块（原有）
import sys
# 添加teacher目录到Python路径，以便导入course_pipeline和video_pipeline
sys.path.insert(0, str(Path(__file__).parent / "teacher"))
# 保留旧路径兼容性

# 导入课程流水线模块
from shared.llm_client import LLMClient, LLMConfig, LLMRequest, LLMResponse
from shared.validators import ContentValidator, ValidationResult
from shared.database import (
    course_db,
    share_db,
    class_db,
    init_all_databases,
)
from course_pipeline import (
    CourseGenerator,
    CourseGeneratorConfig,
    CourseGenerateRequest as PipelineCourseRequest,
    CourseContent
)
from agents.course_generation import CourseGenerationAgent
from shared.agent.tool_registry import create_tool_manager


# ==================== 工具函数 ====================

# 安全打印函数（处理Windows GBK编码问题）
def safe_print(msg: str):
    """安全打印，处理编码问题"""
    try:
        print(msg)
    except UnicodeEncodeError:
        # 移除emoji字符，使用ASCII替代
        msg = msg.encode('ascii', 'ignore').decode('ascii')
        print(msg)


# ==================== 统一响应模型 ====================

# ==================== 统一响应模型 ====================

import logging

logger = logging.getLogger(__name__)


class APIResponse:
    """统一API响应格式"""

    @staticmethod
    def success(
        data: Any = None,
        message: str = "操作成功",
        code: int = 200
    ) -> JSONResponse:
        """成功响应"""
        response_data = {
            "success": True,
            "code": code,
            "message": message,
            "data": data
        }
        # 移除None值
        response_data = {k: v for k, v in response_data.items() if v is not None}
        return JSONResponse(status_code=code, content=response_data)

    @staticmethod
    def error(
        message: str,
        code: int = 400,
        detail: Optional[str] = None,
        errors: Optional[list] = None
    ) -> JSONResponse:
        """错误响应"""
        response_data = {
            "success": False,
            "code": code,
            "message": message
        }
        if detail:
            response_data["detail"] = detail
        if errors:
            response_data["errors"] = errors
        logger.error(f"API Error: {message} - {detail}")
        return JSONResponse(status_code=code, content=response_data)


class AppException(Exception):
    """应用自定义异常基类"""
    def __init__(self, message: str, code: int = 400, detail: Optional[str] = None):
        self.message = message
        self.code = code
        self.detail = detail
        super().__init__(message)


class AuthException(AppException):
    """认证异常"""
    def __init__(self, message: str = "认证失败", detail: Optional[str] = None):
        super().__init__(message=message, code=401, detail=detail)


class NotFoundException(AppException):
    """资源不存在异常"""
    def __init__(self, message: str = "资源不存在", detail: Optional[str] = None):
        super().__init__(message=message, code=404, detail=detail)


class PermissionException(AppException):
    """权限异常"""
    def __init__(self, message: str = "权限不足", detail: Optional[str] = None):
        super().__init__(message=message, code=403, detail=detail)


class ValidationException(AppException):
    """验证异常"""
    def __init__(self, message: str = "参数验证失败", detail: Optional[str] = None):
        super().__init__(message=message, code=400, detail=detail)


# ==================== 辅助函数 ====================


def get_course_output_dir(course_id: str, course_title: str = None) -> Path:
    """
    获取课程的统一输出目录

    目录结构：output/course_{course_id}/
    ├── course.json          # 课程内容
    ├── validation.json      # 验证结果
    ├── course.docx          # Word导出
    ├── course.md            # Markdown导出
    ├── course.tex           # LaTeX导出
    ├── video/
    │   └── course_video.mp4  # 视频文件
    ├── images/              # 视频生成用的图片
    ├── storyboard.json      # 视频分镜数据
    └── speech.json          # 语音数据
    """
    # 使用 course_id 作为主目录名，确保唯一性
    course_dir = OUTPUT_DIR / f"course_{course_id}"
    course_dir.mkdir(parents=True, exist_ok=True)

    # 创建子目录
    (course_dir / "video").mkdir(exist_ok=True)
    (course_dir / "images").mkdir(exist_ok=True)

    return course_dir


def get_course_video_path(course_id: str) -> Path:
    """获取课程视频文件的路径"""
    course_dir = OUTPUT_DIR / f"course_{course_id}"
    return course_dir / "video" / "course_video.mp4"


# ==================== FastAPI应用 ====================

@contextlib.asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """应用生命周期管理（替代废弃的 on_event）"""
    # 启动时执行
    safe_print("\n" + "=" * 60)
    safe_print(">> 系统初始化中...")

    # 运行时调试：检查路径
    safe_print(f"  [DEBUG] __file__: {__file__}")
    safe_print(f"  [DEBUG] _BASE_DIR: {_BASE_DIR}")
    safe_print(f"  [DEBUG] Teacher frontend: {(_BASE_DIR / 'teacher' / 'frontend')} (exists: {(_BASE_DIR / 'teacher' / 'frontend').exists()})")
    safe_print(f"  [DEBUG] Student frontend: {(_BASE_DIR / 'student' / 'frontend')} (exists: {(_BASE_DIR / 'student' / 'frontend').exists()})")

    print("=" * 60)

    # 验证必要目录
    for dir_path, dir_name in [
        (OUTPUT_DIR, "输出目录"),
        (TEMP_DIR, "临时目录"),
        (STATIC_DIR, "静态文件目录")
    ]:
        status = "[OK]" if dir_path.exists() else "[FAIL]"
        safe_print(f"  {status} {dir_name}: {dir_path}")

    # 初始化数据库
    safe_print("  [INIT] 初始化数据库...")
    try:
        init_all_databases()
        safe_print("  [OK] 数据库初始化完成")
        # 显示默认测试账号
        safe_print("  [INFO] 测试账号:")
        safe_print("    - 教师: 张老师 / teacher123")
        safe_print("    - 学生: 李同学 / student123")
        safe_print("    - 管理员: admin / admin123")
    except Exception as e:
        safe_print(f"  [!] 数据库初始化失败: {e}")

    # 启动进度清理任务
    try:
        await progress_manager.start_cleanup_scheduler()
    except Exception as e:
        safe_print(f"  [!] 定时清理启动失败: {e}")

    print("=" * 60 + "\n")

    yield

    # 关闭时执行
    safe_print("\n[INFO] 系统正在关闭...")
    if progress_manager._cleanup_task:
        progress_manager._cleanup_task.cancel()
        try:
            await progress_manager._cleanup_task
        except asyncio.CancelledError:
            pass
    safe_print("[OK] 清理任务已停止")


app = FastAPI(
    title="初中数学双模式生成系统",
    version="2.0.0",
    description="支持视频讲解生成和课程内容生成的双模式系统",
    lifespan=lifespan
)

# 添加CORS中间件
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ==================== 异常处理器 ====================

@app.exception_handler(AppException)
async def app_exception_handler(request: Request, exc: AppException):
    """处理自定义应用异常"""
    return APIResponse.error(
        message=exc.message,
        code=exc.code,
        detail=exc.detail
    )


@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    """处理FastAPI HTTP异常"""
    return APIResponse.error(
        message=str(exc.detail),
        code=exc.status_code
    )


@app.exception_handler(Exception)
async def general_exception_handler(request: Request, exc: Exception):
    """处理所有未捕获的异常"""
    logger.exception(f"Unhandled exception: {exc}")
    return APIResponse.error(
        message="服务器内部错误",
        code=500,
        detail=str(exc) if os.getenv("DEBUG") == "true" else None
    )

# 添加请求日志中间件（用于调试）
@app.middleware("http")
async def log_requests(request: Request, call_next):
    """记录所有请求"""
    import logging
    logger = logging.getLogger("uvicorn")
    logger.info(f"[REQUEST] {request.method} {request.url.path}?{request.url.query}")
    response = await call_next(request)
    logger.info(f"[RESPONSE] {request.method} {request.url.path} -> {response.status_code}")
    return response

# 静态文件服务
app.mount("/static", StaticFiles(directory=str(_BASE_DIR / "static")), name="static")

# 前端文件服务（教师端和学生端分离）
# 使用 resolve() 确保路径是绝对路径
teacher_frontend_dir = (_BASE_DIR / "teacher" / "frontend").resolve()
student_frontend_dir = (_BASE_DIR / "student" / "frontend").resolve()
shared_pages_dir = (_BASE_DIR / "shared" / "pages").resolve()

print(f"[STATIC FILES] Teacher frontend: {teacher_frontend_dir} (exists: {teacher_frontend_dir.exists()})")
print(f"[STATIC FILES] Student frontend: {student_frontend_dir} (exists: {student_frontend_dir.exists()})")
print(f"[STATIC FILES] Shared pages: {shared_pages_dir} (exists: {shared_pages_dir.exists()})")

app.mount("/teacher/frontend", StaticFiles(directory=str(teacher_frontend_dir)), name="teacher_frontend")
app.mount("/student/frontend", StaticFiles(directory=str(student_frontend_dir)), name="student_frontend")
app.mount("/shared/pages", StaticFiles(directory=str(shared_pages_dir)), name="shared_pages")


# ==================== 页面路由 ====================

@app.get("/", response_class=HTMLResponse)
async def root():
    """根路径 - 重定向到登录页面"""
    login_page = shared_pages_dir / "login.html"
    if login_page.exists():
        return FileResponse(str(login_page))
    return FileResponse(str(teacher_frontend_dir / "pages" / "login.html"))

@app.get("/login.html", response_class=HTMLResponse)
async def login_page():
    """统一的登录页面"""
    login_page = shared_pages_dir / "login.html"
    if login_page.exists():
        return FileResponse(str(login_page))
    return FileResponse(str(teacher_frontend_dir / "pages" / "login.html"))


# ==================== 请求模型 ====================

class CourseGenerateRequest(BaseModel):
    """课程生成请求模型"""
    version: str
    grade: str
    chapter_id: str
    student_level: str = "中等巩固"
    purpose: str = "学生自学"
    content_type: Optional[str] = None  # 内容类型: lesson_plan/teaching_script/board_design/review_outline
    generate_video: bool = False  # 是否同时生成视频
    custom_topic: Optional[str] = None
    custom_outline: Optional[str] = None  # 自定义大纲内容


class OutlineGenerateRequest(BaseModel):
    """大纲生成请求模型"""
    grade: str
    topic: str


class VideoGenerateRequest(BaseModel):
    """视频生成请求模型"""
    course_id: str  # 已生成的课程ID
    title: str  # 课程标题
    content: str  # 课程内容（大纲或详细内容）


# ==================== 进度管理 ====================

class ProgressManager:
    """任务进度管理器（支持定时清理过期任务）"""

    def __init__(self):
        self.tasks: Dict[str, Dict] = {}
        self._cleanup_task: Optional[asyncio.Task] = None

    def update_progress(
        self,
        task_id: str,
        percent: int,
        message: str,
        status: str = "processing",
        mode: str = "course"
    ):
        """更新任务进度"""
        self.tasks[task_id] = {
            "percent": percent,
            "message": message,
            "status": status,
            "mode": mode,
            "error": message if status == "failed" else None,  # 添加 error 字段
            "created_at": self.tasks.get(task_id, {}).get("created_at", time.time()),
            "updated_at": time.time()
        }

    def get_progress(self, task_id: str) -> Dict:
        """获取任务进度"""
        return self.tasks.get(task_id, {
            "percent": 0,
            "message": "准备中...",
            "status": "pending",
            "mode": "unknown"
        })

    def complete(self, task_id: str, result: Dict):
        """标记任务完成"""
        self.tasks[task_id] = {
            **self.tasks.get(task_id, {}),
            "percent": 100,
            "message": "完成",
            "status": "completed",
            "result": result,
            "completed_at": time.time()
        }

    def fail(self, task_id: str, error: str):
        """标记任务失败"""
        self.tasks[task_id] = {
            **self.tasks.get(task_id, {}),
            "percent": 0,
            "message": f"失败: {error}",
            "status": "failed",
            "failed_at": time.time()
        }

    def cleanup_old_tasks(self, retention_hours: int = TASK_RETENTION_HOURS) -> Dict[str, int]:
        """
        清理过期的已完成/失败任务

        Args:
            retention_hours: 任务保留时间（小时）

        Returns:
            清理统计信息
        """
        cutoff_time = time.time() - (retention_hours * 3600)
        tasks_to_remove = []

        for task_id, task_data in self.tasks.items():
            # 只清理已完成或失败的任务
            if task_data.get("status") in ["completed", "failed"]:
                # 检查任务是否过期
                completed_at = task_data.get("completed_at", task_data.get("failed_at", 0))
                if completed_at and completed_at < cutoff_time:
                    tasks_to_remove.append(task_id)

        # 删除过期任务
        for task_id in tasks_to_remove:
            del self.tasks[task_id]
            # 同时删除输出文件
            task_output_dir = OUTPUT_DIR / task_id
            if task_output_dir.exists():
                try:
                    import shutil
                    shutil.rmtree(task_output_dir)
                except Exception as e:
                    print(f"  [!] 清理输出目录失败 {task_output_dir}: {e}")

        return {
            "cleaned_count": len(tasks_to_remove),
            "remaining_count": len(self.tasks)
        }

    async def start_cleanup_scheduler(self, interval_seconds: int = CLEANUP_INTERVAL_SECONDS):
        """启动定时清理任务"""
        if not TASK_CLEANUP_ENABLED:
            safe_print("  [INFO] 任务清理功能已禁用")
            return

        async def cleanup_loop():
            """定时清理循环"""
            while True:
                try:
                    await asyncio.sleep(interval_seconds)
                    stats = self.cleanup_old_tasks()
                    if stats["cleaned_count"] > 0:
                        safe_print(f"  [CLEANUP] 清理过期任务: {stats['cleaned_count']}个, "
                              f"剩余: {stats['remaining_count']}个")
                except asyncio.CancelledError:
                    break
                except Exception as e:
                    safe_print(f"  [!] 定时清理错误: {e}")

        self._cleanup_task = asyncio.create_task(cleanup_loop())
        safe_print(f"  [OK] 定时清理已启动（间隔: {interval_seconds}秒, 保留: {TASK_RETENTION_HOURS}小时）")


# 全局进度管理器
progress_manager = ProgressManager()

# 全局课程生成器实例（懒加载）
_course_generator = None


def get_course_generator():
    """获取课程生成器实例（单例）"""
    global _course_generator
    if _course_generator is None:
        config = CourseGeneratorConfig(
            llm_config=LLMConfig(
                api_key=os.getenv("LLM_API_KEY") or os.getenv("COURSE_API_KEY"),
                model=os.getenv("LLM_MODEL", "doubao-seed-2-0-pro-260215"),
                base_url=os.getenv("LLM_BASE_URL", "https://ark.cn-beijing.volces.com/api/v3"),
            )
        )
        _course_generator = CourseGenerator(config)
    return _course_generator


# ==================== 会话管理 ====================

# 简单的会话存储（生产环境应使用Redis）
_active_sessions: Dict[str, Dict] = {}


def create_session(user_id: str, username: str, role: str) -> str:
    """创建会话"""
    session_id = str(uuid.uuid4())
    _active_sessions[session_id] = {
        "user_id": user_id,
        "username": username,
        "role": role,
        "created_at": datetime.now().isoformat()
    }
    return session_id


def get_session(session_id: str) -> Optional[Dict]:
    """获取会话"""
    return _active_sessions.get(session_id)


def remove_session(session_id: str):
    """移除会话"""
    _active_sessions.pop(session_id, None)


# ==================== 请求模型 ====================

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


class ShareRequest(BaseModel):
    """分享课程请求"""
    course_id: str
    student_ids: List[str] = []
    class_id: str = ""


class ClassCreateRequest(BaseModel):
    """创建班级请求"""
    name: str
    grade: str = ""
    description: str = ""


class ClassJoinRequest(BaseModel):
    """加入班级请求"""
    class_id: str


class AIChatRequest(BaseModel):
    """AI聊天请求"""
    question: str  # 用户问题
    context: Optional[List[Dict[str, str]]] = None  # 对话历史上下文
    course_id: Optional[str] = None  # 课程ID（用于获取课程内容作为上下文）
    chapter_id: Optional[str] = None  # 章节ID（用于获取章节内容作为上下文）

# ==================== 路由：知识库查询 ====================
# 已移至 api/textbook.py 模块

# ==================== 路由：课程生成 ====================


async def _generate_course_task(
    task_id: str,
    request: CourseGenerateRequest
):
    """课程生成后台任务（通过 CourseGenerationAgent + ToolManager 调用）"""
    try:
        progress_manager.update_progress(task_id, 1, "初始化Agent...", "course")

        # 获取单例 CourseGenerator（底层生成器保持不变）
        generator = get_course_generator()

        # 构建 ToolManager，将 CourseGenerator 的能力封装为工具
        tool_manager = create_tool_manager(
            knowledge_base=generator.knowledge_base,
            course_generator=generator,
            llm_client=generator.llm_client
        )

        # 创建 CourseGenerationAgent（通过 ToolManager 间接调用 CourseGenerator）
        agent = CourseGenerationAgent(
            tools=tool_manager,
            llm_client=generator.llm_client
        )

        progress_manager.update_progress(task_id, 3, "准备生成课程内容...", "course")

        # 通过 Agent 的策略直调模式生成课程（查知识库 → 生成内容 → 校验）
        result = await agent.generate_with_strategy(
            version=request.version,
            grade=request.grade,
            chapter_id=request.chapter_id,
            student_level=request.student_level,
            purpose=request.purpose,
            task_id=task_id,
            progress_callback=lambda p, m: progress_manager.update_progress(task_id, p, m, "course")
        )

        if not result.get("success"):
            error_msg = result.get("error", "未知错误")
            progress_manager.fail(task_id, error_msg)
            return

        # 获取生成结果
        content_dict = result.get("content_dict", {})
        validation = result.get("validation", {})

        # 保存结果
        progress_manager.update_progress(task_id, 95, "正在保存课程文件...", "course")
        output_dir = OUTPUT_DIR / task_id
        output_dir.mkdir(parents=True, exist_ok=True)

        import json

        # ========== 保存course.json（第一阶段输出） ==========
        content_file = output_dir / "course.json"
        content_file.write_text(json.dumps(content_dict, ensure_ascii=False, indent=2), encoding="utf-8")

        # 记录日志（便于追踪占位符问题）
        logger.info(f"[课程生成-第一阶段] course.json已保存: {content_file}")
        logger.info(f"[课程生成-第一阶段]   - 标题: {content_dict.get('title', 'N/A')}")
        logger.info(f"[课程生成-第一阶段]   - sections数量: {len(content_dict.get('sections', {}))}")
        logger.info(f"[课程生成-第一阶段]   - sections列表: {list(content_dict.get('sections', {}).keys())}")

        # 检测潜在的占位符问题
        placeholder_keywords = ["待补充", "待填充", "待定", "占位", "SceneID:", "内容待补充", "本页内容"]
        found_placeholders = []
        for section_name, section_content in content_dict.get('sections', {}).items():
            for keyword in placeholder_keywords:
                if keyword in str(section_content):
                    found_placeholders.append(f"{section_name}:{keyword}")

        if found_placeholders:
            logger.warning(f"[课程生成-第一阶段] ⚠️ 检测到可能的占位符: {found_placeholders}")
        else:
            logger.info(f"[课程生成-第一阶段] ✓ 未检测到占位符")

        # ========== 保存验证结果 ==========
        progress_manager.update_progress(task_id, 97, "正在保存验证结果...", "course")

        # 使用 Agent 返回的校验结果（由 validate_content 工具完成）
        is_valid = validation.get("is_valid", True) if validation else True
        errors = validation.get("errors", []) if validation else []
        warnings = validation.get("warnings", []) if validation else []

        validation_file = output_dir / "validation.json"
        validation_file.write_text(json.dumps({
            "is_valid": is_valid,
            "errors": errors,
            "warnings": warnings,
            "details": validation.get("details", {}) if validation else {}
        }, ensure_ascii=False, indent=2), encoding="utf-8")

        # 完成（包含验证结果）
        progress_manager.complete(task_id, {
            "title": result.get("title", ""),
            "grade": result.get("grade", ""),
            "chapter": result.get("chapter", ""),
            "sections_count": result.get("section_count", 0),
            "generate_video": request.generate_video,
            "validation": {
                "is_valid": is_valid,
                "errors": errors,
                "warnings": warnings,
                "has_warnings": len(warnings) > 0,
                "has_errors": len(errors) > 0
            },
            "content": content_dict
        })

    except Exception as e:
        progress_manager.fail(task_id, str(e))
        import traceback
        traceback.print_exc()


@app.post("/generate/course/outline")
async def generate_outline(
    request: OutlineGenerateRequest,
    background_tasks: BackgroundTasks
):
    """
    生成自定义专题大纲

    参数：
    - grade: 年级
    - topic: 专题名称
    """
    task_id = str(uuid.uuid4())

    # 初始化任务（记录创建时间）
    progress_manager.tasks[task_id] = {
        "percent": 0,
        "message": "任务已创建",
        "status": "pending",
        "mode": "course",
        "created_at": time.time()
    }

    background_tasks.add_task(
        _generate_outline_task,
        task_id,
        request.grade,
        request.topic
    )

    return {
        "task_id": task_id,
        "message": "大纲生成中...",
        "status": "processing"
    }


async def _generate_outline_task(
    task_id: str,
    grade: str,
    topic: str
):
    """大纲生成后台任务"""
    try:
        progress_manager.update_progress(task_id, 20, "正在生成大纲...", "course")

        generator = get_course_generator()
        outline = await generator.generate_outline(
            grade,
            topic,
            progress_callback=lambda p, m: progress_manager.update_progress(task_id, p, m, "course")
        )

        # 保存结果
        output_dir = OUTPUT_DIR / task_id
        output_dir.mkdir(parents=True, exist_ok=True)

        import json
        outline_file = output_dir / "outline.json"
        outline_file.write_text(json.dumps(outline, ensure_ascii=False, indent=2), encoding="utf-8")

        progress_manager.complete(task_id, {
            "title": outline.get("title", ""),
            "sessions_count": len(outline.get("sessions", []))
        })

    except Exception as e:
        progress_manager.fail(task_id, str(e))
        import traceback
        traceback.print_exc()


@app.post("/course/{task_id}/update")
async def update_course(task_id: str, request: dict, session_id: str = ""):
    """更新课程内容（编辑后保存到内存）"""
    session = get_session(session_id)
    if not session:
        raise HTTPException(status_code=401, detail="未登录")

    # 从 progress_manager 获取原始内容
    progress = progress_manager.get_progress(task_id)
    if not progress:
        raise HTTPException(status_code=404, detail="任务不存在")

    if progress["status"] != "completed":
        raise HTTPException(status_code=400, detail="任务尚未完成")

    original_content = progress.get("result")
    if not original_content:
        raise HTTPException(status_code=404, detail="课程内容不存在")

    # 更新内容（保留grade、chapter、version等元数据）
    updated_content = {
        "title": request.get("title", original_content.get("title", "")),
        "sections": request.get("sections", original_content.get("sections", {})),
        "grade": original_content.get("grade", ""),
        "chapter": original_content.get("chapter", ""),
        "version": original_content.get("version", ""),
        "student_level": original_content.get("student_level", ""),
        "purpose": original_content.get("purpose", ""),
        "diagrams": original_content.get("diagrams", {}),
        "metadata": original_content.get("metadata", {})
    }

    # 更新内存中的内容
    progress_manager.tasks[task_id]["result"] = updated_content

    return {"success": True, "message": "课程内容已更新"}


@app.post("/course/{task_id}/regenerate")
async def regenerate_course(
    task_id: str,
    request: dict = None,
    session_id: str = ""
):
    """重新生成课程"""
    # 暂时简化实现：提示用户返回生成页面
    # 未来可以添加基于反馈的重新生成功能
    _ = task_id, request, session_id  # 避免未使用警告
    raise HTTPException(
        status_code=400,
        detail="请返回生成页面重新生成。如需根据反馈修改，请使用编辑功能。"
    )


@app.get("/course/{course_id}/versions")
async def get_course_versions(course_id: str):
    """获取课程的所有版本"""
    versions = course_db.get_course_versions(course_id)
    return {"success": True, "versions": versions}


@app.get("/course/version/{version_id1}/compare/{version_id2}")
async def compare_course_versions(version_id1: str, version_id2: str):
    """对比两个版本"""
    comparison = course_db.compare_versions(version_id1, version_id2)
    return {"success": True, "comparison": comparison}


@app.get("/export/word/{task_id}")
async def export_word(task_id: str):
    """导出为Word文档"""
    # 从 progress_manager 获取内容
    progress = progress_manager.get_progress(task_id)
    if not progress:
        raise HTTPException(status_code=404, detail="任务不存在")

    if progress["status"] != "completed":
        raise HTTPException(status_code=400, detail="任务尚未完成")

    content = progress.get("result")
    if not content:
        raise HTTPException(status_code=404, detail="课程内容不存在")

    from teacher.course_pipeline.exporters import WordExporter

    exporter = WordExporter()
    output_path = OUTPUT_DIR / task_id / "course.docx"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    await exporter.export(content, str(output_path))

    return FileResponse(
        path=str(output_path),
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        filename="course.docx"
    )


@app.get("/export/pdf/{task_id}")
async def export_pdf(task_id: str):
    """导出为PDF文档"""
    # 从 progress_manager 获取内容
    progress = progress_manager.get_progress(task_id)
    if not progress:
        raise HTTPException(status_code=404, detail="任务不存在")

    if progress["status"] != "completed":
        raise HTTPException(status_code=400, detail="任务尚未完成")

    content = progress.get("result")
    if not content:
        raise HTTPException(status_code=404, detail="课程内容不存在")

    from teacher.course_pipeline.exporters import MarkdownExporter

    # 先导出Markdown
    exporter_md = MarkdownExporter()
    md_path = OUTPUT_DIR / task_id / "course.md"
    md_path.parent.mkdir(parents=True, exist_ok=True)
    await exporter_md.export(content, str(md_path))

    # 返回Markdown文件（PDF转换需要额外的工具）
    return FileResponse(
        path=str(md_path),
        media_type="text/markdown",
        filename="course.md"
    )


@app.get("/export/latex/{task_id}")
async def export_latex(task_id: str):
    """导出为LaTeX文档"""
    # 从 progress_manager 获取内容
    progress = progress_manager.get_progress(task_id)
    if not progress:
        raise HTTPException(status_code=404, detail="任务不存在")

    if progress["status"] != "completed":
        raise HTTPException(status_code=400, detail="任务尚未完成")

    content = progress.get("result")
    if not content:
        raise HTTPException(status_code=404, detail="课程内容不存在")

    from teacher.course_pipeline.exporters import LaTeXExporter

    exporter = LaTeXExporter()
    output_path = OUTPUT_DIR / task_id / "course.tex"
    output_path.parent.mkdir(parents=True, exist_ok=True)

    result_path = await exporter.export(content, str(output_path))

    # 如果成功编译为PDF，返回PDF；否则返回tex文件
    if result_path.endswith(".pdf"):
        return FileResponse(
            path=result_path,
            media_type="application/pdf",
            filename="course.pdf"
        )
    else:
        return FileResponse(
            path=result_path,
            media_type="application/x-tex",
            filename="course.tex"
        )



@app.get("/health")
async def health_check():
    """健康检查"""
    from shared.knowledge_base import knowledge_base

    # 调试：返回路径信息
    teacher_frontend_path = _BASE_DIR / "teacher" / "frontend"
    student_frontend_path = _BASE_DIR / "student" / "frontend"

    return {
        "status": "ok",
        "service": "初中数学双模式生成系统",
        "version": "2.0.0",
        "modes": ["video", "course"],
        "debug": {
            "_BASE_DIR": str(_BASE_DIR),
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


# ==================== 注册模块化路由 ====================
# 从独立模块导入并注册路由，避免代码重复
try:
    from api.routes import register_all_routes
    register_all_routes(app, progress_manager, OUTPUT_DIR, TEMP_DIR, STATIC_DIR, _BASE_DIR)
    print("[系统] 模块化路由已注册")
except ImportError as e:
    print(f"[警告] 模块化路由注册失败: {e}")
    print("[系统] 使用内置路由...")


# ==================== 启动服务 ====================

if __name__ == "__main__":
    import uvicorn
    import webbrowser
    import threading

    # 自动打开浏览器
    def open_browser():
        time.sleep(2)
        webbrowser.open("http://localhost:8000/")

    threading.Thread(target=open_browser, daemon=True).start()

    print("\n" + "=" * 60)
    print(">> 启动初中数学双模式生成系统...")
    print("=" * 60)
    print(">> 首页地址: http://localhost:8000/")
    print(">> API 文档: http://localhost:8000/docs")
    print(">> 健康检查: http://localhost:8000/health")
    print(">> 管理接口: http://localhost:8000/admin/stats")
    print("=" * 60 + "\n")

    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=8000,
        reload=False,  # 暂时禁用自动重载来测试
        log_level="info"
    )
