"""
视频生成模块 - Agent驱动版本

核心变更：
1. 视频生成通过 VideoGenerationAgent + ReAct 推理框架驱动
2. Agent 通过工具调用完成预处理→讲解→LaTeX→PDF→图片→语音→视频 全流程
"""

import json
import logging
import os
import uuid
from pathlib import Path
from typing import Dict, Optional

from fastapi import HTTPException, BackgroundTasks
from pydantic import BaseModel

from shared.database import course_db, history_db
from shared.session import get_session
from shared.llm_client import LLMClient, LLMConfig
from shared.agent.tool_registry import create_tool_manager
from agents.video_generation import VideoGenerationAgent
from video_pipeline import VideoGenConfig


logger = logging.getLogger(__name__)


# ==================== 数据模型 ====================

class VideoGenerateRequestUnified(BaseModel):
    """统一的视频生成请求模型（API入口）"""
    source_id: str  # 可以是 task_id 或 course_id（自动判断）


# ==================== 全局变量 ====================

_progress_manager = None
_output_dir = None
_base_dir = None


def init_video_generation(progress_manager, output_dir, base_dir):
    """初始化视频生成模块"""
    global _progress_manager, _output_dir, _base_dir
    _progress_manager = progress_manager
    _output_dir = output_dir
    _base_dir = base_dir


# ==================== 统一内容获取 ====================

def _get_course_content_unified(source_id: str) -> tuple:
    """
    统一获取课程内容（自动判断来源）

    优先级：
    1. 从 progress_manager 获取（新任务，内存）
    2. 从数据库获取（已保存的课程）
    3. 尝试读取文件（兼容性回退）

    Args:
        source_id: task_id 或 course_id

    Returns:
        (content_dict, source_type) - 课程内容和来源类型

    Raises:
        HTTPException: 找不到课程内容
    """
    logger.info(f"[统一入口] 尝试获取课程内容: {source_id}")

    # ========== 优先级1: 从 progress_manager 获取（方式2） ==========
    progress = _progress_manager.get_progress(source_id)
    if progress and progress.get("status") == "completed":
        result = progress.get("result")
        if result and isinstance(result, dict) and "sections" in result:
            logger.info(f"[统一入口] ✓ 从 progress_manager 获取到结构化内容")
            logger.info(f"[统一入口]   标题: {result.get('title', '')}")
            logger.info(f"[统一入口]   章节数: {len(result.get('sections', {}))}")
            return result, "progress_manager"

    # ========== 优先级2: 从数据库获取（方式1） ==========
    course = course_db.get_course_by_id(source_id)
    if course:
        # 检查 content 字段
        if course.get("content") and isinstance(course.get("content"), dict):
            content_data = course["content"]
            if "sections" in content_data:
                logger.info(f"[统一入口] ✓ 从数据库获取到结构化内容")
                logger.info(f"[统一入口]   课程: {content_data.get('title', '')}")
                logger.info(f"[统一入口]   章节数: {len(content_data.get('sections', {}))}")
                return content_data, "database"
        # 兼容：直接在 course 顶层有 sections
        elif "sections" in course:
            logger.info(f"[统一入口] ✓ 从数据库获取到结构化内容（旧格式）")
            return course, "database"
        else:
            logger.warning(f"[统一入口] 数据库中的课程没有 sections 字段")

    # ========== 优先级3: 文件回退（兼容性） ==========
    content_file = _output_dir / source_id / "course.json"
    if content_file.exists():
        try:
            with open(content_file, 'r', encoding='utf-8') as f:
                content_data = json.load(f)
            if isinstance(content_data, dict) and "sections" in content_data:
                logger.info(f"[统一入口] ✓ 从文件获取到结构化内容")
                return content_data, "file"
        except Exception as e:
            logger.warning(f"[统一入口] 读取文件失败: {e}")

    # ========== 都找不到 ==========
    raise HTTPException(
        status_code=404,
        detail=f"找不到课程内容: {source_id}（请确认课程ID或任务ID正确）"
    )


# ==================== 统一的视频生成入口 ====================

async def generate_video(request: VideoGenerateRequestUnified, background_tasks: BackgroundTasks, session_id: str = ""):
    """
    统一的视频生成入口

    自动判断 source_id 的类型：
    - 如果是 task_id → 从 progress_manager 获取
    - 如果是 course_id → 从数据库获取
    """
    session = get_session(session_id)
    if not session or session["role"] != "teacher":
        raise HTTPException(status_code=403, detail="需要教师权限")

    source_id = request.source_id

    # 统一获取课程内容
    course_content, source_type = _get_course_content_unified(source_id)

    # 验证权限（仅对数据库课程需要）
    if source_type == "database":
        course = course_db.get_course_by_id(source_id)
        if course and course.get("teacher_id") != session["user_id"]:
            raise HTTPException(status_code=403, detail="无权访问此课程")

    # 创建视频生成任务
    task_id = str(uuid.uuid4())

    # 初始化进度
    _progress_manager.update_progress(task_id, 0, "准备中...", "pending", "video")

    # 根据来源类型选择不同的后台任务
    if source_type == "progress_manager":
        # 从内存任务生成（完成后自动保存）
        background_tasks.add_task(
            _generate_video_and_save_task,
            task_id,
            source_id,  # 原始 task_id
            session,
            source_id,  # original_task_id（同 source_id）
            course_content  # 课程内容
        )
    else:
        # 从数据库课程生成（不需要保存）
        background_tasks.add_task(
            _generate_video_task_unified,
            task_id,
            source_id,  # course_id
            session,
            course_content  # 传递课程内容
        )

    return {"success": True, "task_id": task_id, "source_type": source_type}


# ==================== 后台任务 ====================

def _create_video_agent():
    """
    创建视频生成Agent实例

    通过 Agent + 工具注册中心 驱动视频生成全流程，
    体现"基于智能体的课程助教系统"核心架构。
    """
    llm_client = LLMClient(LLMConfig())
    tool_manager = create_tool_manager(llm_client=llm_client)
    agent = VideoGenerationAgent(tools=tool_manager, llm_client=llm_client)
    return agent


async def _generate_video_and_save_task(
    video_task_id: str,
    source_id: str,  # 原始课件任务ID或课程ID
    session: Dict,
    original_task_id: str,  # 原始课程生成任务ID
    course_content: Dict  # 课程内容（已包含sections和title）
):
    """
    视频生成后台任务 - Agent驱动版（完成后自动保存课程）

    通过 VideoGenerationAgent + ReAct 推理框架驱动视频生成全流程：
    预处理 → 讲解生成 → LaTeX/PDF → 关键帧提取 → 语音脚本 → TTS合成

    Args:
        video_task_id: 视频任务ID
        source_id: 原始课件任务ID或课程ID（用于标识课程）
        session: 用户会话
        original_task_id: 原始课程生成任务ID
        course_content: 课程内容（已包含sections和title）
    """
    try:
        _progress_manager.update_progress(video_task_id, 5, "初始化Agent视频生成器...", "processing", "video")

        # ========== 使用传递的课程内容 ==========
        if course_content and isinstance(course_content, dict) and "sections" in course_content:
            course_json = course_content
            logger.info(f"[Agent视频生成] ✓ 使用内存中的原课程内容")
            logger.info(f"[Agent视频生成]   标题: {course_json.get('title', '')}")
            logger.info(f"[Agent视频生成]   章节数: {len(course_json.get('sections', {}))}")
        else:
            raise Exception(f"课程内容无效或缺少sections字段")

        # ========== 定义进度回调 ==========
        def progress_callback(percent: int, message: str):
            _progress_manager.update_progress(video_task_id, percent, message, "processing", "video")

        # ========== 通过Agent驱动视频生成 ==========
        _progress_manager.update_progress(video_task_id, 8, "Agent正在规划视频生成流程...", "processing", "video")

        agent = _create_video_agent()
        logger.info(f"[Agent视频生成] VideoGenerationAgent 已创建，开始执行工具链")

        result = await agent.generate_video(
            course_id=source_id,
            course_json=course_json,
            progress_callback=progress_callback
        )

        logger.info(f"[Agent视频生成] Agent执行完成，mode={result.get('mode', 'N/A')}")

        if result.get("success"):
            total_frames = result.get("total_frames", 0)
            _progress_manager.update_progress(video_task_id, 95, f"Agent视频生成完成！共{total_frames}帧，正在保存课程...", "completed", "video")

            # 视频生成成功后，自动保存课程到数据库
            if course_json:
                existing_course = course_db.find_course_by_task_id(session["user_id"], original_task_id)

                if existing_course:
                    course_id = existing_course["id"]
                    logger.info(f"[视频完成] 课程已存在 ({course_id})，仅更新视频路径")
                    update_data = {
                        "video_path": result.get("video_path"),
                        "has_video": True
                    }
                    if not existing_course.get("content") or "sections" not in existing_course.get("content", {}):
                        update_data["content"] = course_json
                    course_db.update_course(course_id, update_data)
                else:
                    logger.info(f"[视频完成] 创建新课程 (task_id={original_task_id})")
                    course_json.setdefault("metadata", {})["task_id"] = original_task_id
                    course_id = course_db.create_course(
                        teacher_id=session["user_id"],
                        title=course_json.get("title", "未命名课程"),
                        grade=course_json.get("grade", ""),
                        chapter=course_json.get("chapter", ""),
                        version=course_json.get("version", ""),
                        sections=course_json.get("sections", {}),
                        content=course_json,
                        metadata=course_json.get("metadata", {})
                    )
                    if result.get("video_path"):
                        course_db.update_course(course_id, {
                            "video_path": result.get("video_path"),
                            "has_video": True
                        })

                _progress_manager.update_progress(
                    video_task_id, 100,
                    f"课程已保存！视频共{total_frames}帧（Agent模式）",
                    "completed", "video"
                )

                history_db.add_record(
                    session["user_id"], "generate_video", course_id,
                    details={
                        "title": course_json.get("title", "未命名课程"),
                        "video_path": result.get("video_path"),
                        "duration": result.get("duration"),
                        "total_frames": total_frames,
                        "mode": "agent"
                    }
                )
        else:
            error_msg = result.get('error', '未知错误')
            _progress_manager.update_progress(video_task_id, 0, f"视频生成失败: {error_msg}", "failed", "video")
            logger.error(f"[Agent视频生成] 失败: {error_msg}")

    except Exception as e:
        import traceback
        traceback.print_exc()
        _progress_manager.update_progress(video_task_id, 0, f"视频生成异常: {str(e)}", "failed", "video")


async def _generate_video_task_unified(
    video_task_id: str,
    source_id: str,  # 课程ID
    session: Dict,
    course_content: Dict  # 课程内容（已包含sections和title）
):
    """
    统一的视频生成后台任务（从数据库课程生成）- Agent驱动版

    通过 VideoGenerationAgent + ReAct 推理框架驱动视频生成全流程。

    Args:
        video_task_id: 视频任务ID
        source_id: 课程ID
        session: 用户会话
        course_content: 课程内容（已包含sections和title）
    """
    try:
        _progress_manager.update_progress(video_task_id, 5, "初始化Agent视频生成器...", "processing", "video")

        # ========== 使用传递的课程内容 ==========
        if course_content and isinstance(course_content, dict) and "sections" in course_content:
            course_json = course_content
            logger.info(f"[Agent视频生成-统一] ✓ 使用传递的课程内容")
            logger.info(f"[Agent视频生成-统一]   标题: {course_json.get('title', '')}")
            logger.info(f"[Agent视频生成-统一]   章节数: {len(course_json.get('sections', {}))}")
        else:
            logger.warning(f"[Agent视频生成-统一] ⚠ 未传递课程内容，尝试从数据库获取")
            course = course_db.get_course_by_id(source_id)
            if course and course.get("content") and "sections" in course.get("content", {}):
                course_json = course["content"]
            elif course and "sections" in course:
                course_json = course
            else:
                raise Exception(f"找不到课程内容: {source_id}")

        # ========== 定义进度回调 ==========
        def progress_callback(percent: int, message: str):
            _progress_manager.update_progress(video_task_id, percent, message, "processing", "video")

        # ========== 通过Agent驱动视频生成 ==========
        _progress_manager.update_progress(video_task_id, 8, "Agent正在规划视频生成流程...", "processing", "video")

        agent = _create_video_agent()
        logger.info(f"[Agent视频生成-统一] VideoGenerationAgent 已创建，开始执行工具链")

        result = await agent.generate_video(
            course_id=source_id,
            course_json=course_json,
            progress_callback=progress_callback
        )

        if result.get("success"):
            total_frames = result.get("total_frames", 0)
            _progress_manager.update_progress(video_task_id, 100, f"Agent视频生成完成！共{total_frames}帧", "completed", "video")

            history_db.add_record(
                session["user_id"], "generate_video", source_id,
                details={
                    "title": course_json.get("title", "未命名课程"),
                    "video_path": result.get("video_path"),
                    "duration": result.get("duration"),
                    "total_frames": total_frames,
                    "source_type": "database",
                    "mode": "agent"
                }
            )

            course_db.update_course(source_id, {
                "video_path": result.get("video_path"),
                "has_video": True
            })

        else:
            error_msg = result.get('error', '未知错误')
            _progress_manager.update_progress(video_task_id, 0, f"视频生成失败: {error_msg}", "failed", "video")
            logger.error(f"[Agent视频生成-统一] 失败: {error_msg}")

    except Exception as e:
        import traceback
        traceback.print_exc()
        _progress_manager.update_progress(video_task_id, 0, f"视频生成异常: {str(e)}", "failed", "video")


# ==================== 其他API端点 ====================

async def get_video_progress(task_id: str, session_id: str = ""):
    """获取视频生成进度"""
    session = get_session(session_id)
    if not session:
        raise HTTPException(status_code=401, detail="未授权")

    progress = _progress_manager.get_progress(task_id)
    return {"success": True, "progress": progress}


async def get_course_video(course_id: str, session_id: str = ""):
    """获取课程生成的视频"""
    from shared.utils import get_course_output_dir

    session = get_session(session_id)
    if not session:
        raise HTTPException(status_code=401, detail="未授权")

    # 验证课程访问权限
    course = course_db.get_course_by_id(course_id)
    if not course:
        raise HTTPException(status_code=404, detail="课程不存在")

    # 教师验证所有权
    if session["role"] == "teacher" and course.get("teacher_id") != session["user_id"]:
        raise HTTPException(status_code=403, detail="无权访问此课程")

    # 查找视频文件 - 优先使用数据库中记录的 video_path
    video_file = None

    # 方法1: 使用数据库中的 video_path
    if course.get("video_path"):
        video_path = course["video_path"]
        # 处理Windows路径分隔符
        video_path = video_path.replace("\\", "/")
        # 如果是相对路径，加上项目根目录
        if not video_path.startswith("/"):
            video_file = _base_dir / video_path
        else:
            video_file = Path(video_path)
        logger.info(f"[Video] 使用数据库路径: {video_file}")

    # 方法2: 回退到默认路径（基于 course_id）
    if not video_file or not video_file.exists():
        course_dir = get_course_output_dir(course_id)
        video_file = course_dir / "video" / "course_video.mp4"
        logger.info(f"[Video] 使用默认路径: {video_file}")

    if video_file.exists():
        from fastapi.responses import FileResponse
        return FileResponse(
            path=str(video_file),
            media_type="video/mp4",
            filename=f"{course.get('title', 'course')}.mp4"
        )
    else:
        raise HTTPException(status_code=404, detail="视频文件不存在")


async def get_course_video_status(course_id: str, session_id: str = ""):
    """获取课程视频生成状态"""
    from shared.utils import get_course_output_dir

    session = get_session(session_id)
    if not session:
        raise HTTPException(status_code=401, detail="未授权")

    # 验证课程访问权限
    course = course_db.get_course_by_id(course_id)
    if not course:
        raise HTTPException(status_code=404, detail="课程不存在")

    # 教师验证所有权
    if session["role"] == "teacher" and course.get("teacher_id") != session["user_id"]:
        raise HTTPException(status_code=403, detail="无权访问此课程")

    # 检查视频文件 - 优先使用数据库中记录的 video_path
    video_file = None
    storyboard_file = None

    # 方法1: 使用数据库中的 video_path
    if course.get("video_path"):
        video_path = course["video_path"].replace("\\", "/")
        if not video_path.startswith("/"):
            video_file = _base_dir / video_path
        else:
            video_file = Path(video_path)

    # 方法2: 回退到默认路径（基于 course_id）
    if not video_file or not video_file.exists():
        course_dir = get_course_output_dir(course_id)
        video_file = course_dir / "video" / "course_video.mp4"
        storyboard_file = course_dir / "storyboard.json"

    status = {
        "course_id": course_id,
        "has_video": video_file.exists() if video_file else False,
        "has_storyboard": storyboard_file.exists() if storyboard_file else False,
        "video_path": str(video_file) if video_file and video_file.exists() else None
    }

    # 如果有分镜文件，读取结构信息
    if storyboard_file and storyboard_file.exists():
        try:
            with open(storyboard_file, "r", encoding="utf-8") as f:
                storyboard = json.load(f)
                status["frame_count"] = storyboard.get("totalSlides")
                status["estimated_duration"] = storyboard.get("estimatedDuration")
                status["teaching_flow"] = storyboard.get("teachingFlow", [])
        except Exception:
            pass

    return {"success": True, "status": status}


async def video_diagnostics(session_id: str = ""):
    """视频生成环境诊断"""
    import subprocess

    session = get_session(session_id)
    if not session:
        raise HTTPException(status_code=401, detail="未授权")

    diagnostics = {
        "overall_status": "unknown",
        "checks": {}
    }

    all_passed = True

    # 1. 检查 TTS 配置
    tts_app_key = os.getenv("TTS_APPKEY", "")
    tts_token = os.getenv("TTS_TOKEN", "")
    tts_valid = bool(tts_app_key and tts_token)
    diagnostics["checks"]["tts_config"] = {
        "status": "pass" if tts_valid else "fail",
        "description": "TTS 语音合成配置",
        "details": {
            "app_key_configured": len(tts_app_key) > 0,
            "token_configured": len(tts_token) > 0,
            "app_key_length": len(tts_app_key),
            "token_length": len(tts_token)
        },
        "fix": "请在 teacher/.env 文件中配置 TTS_APPKEY 和 TTS_TOKEN"
    }
    if not tts_valid:
        all_passed = False

    # 2. 检查 FFmpeg
    ffmpeg_status = "fail"
    ffmpeg_path = None
    ffmpeg_version = None
    try:
        result = subprocess.run(
            ["ffmpeg", "-version"],
            capture_output=True,
            timeout=5
        )
        if result.returncode == 0:
            ffmpeg_status = "pass"
            ffmpeg_path = "ffmpeg"
            # 解析版本号
            output = result.stdout.decode("utf-8", errors="ignore")
            for line in output.split("\n")[:5]:
                if "version" in line.lower():
                    ffmpeg_version = line.strip()
                    break
    except Exception:
        pass

    diagnostics["checks"]["ffmpeg"] = {
        "status": ffmpeg_status,
        "description": "FFmpeg 视频处理工具",
        "details": {
            "installed": ffmpeg_status == "pass",
            "path": ffmpeg_path,
            "version": ffmpeg_version
        },
        "fix": "请安装 FFmpeg 或设置 FFMPEG_PATH 环境变量"
    }
    if ffmpeg_status != "pass":
        all_passed = False

    # 3. 检查输出目录写入权限
    output_dir = _output_dir
    dir_writable = output_dir.exists() and os.access(output_dir, os.W_OK)

    diagnostics["checks"]["output_dir"] = {
        "status": "pass" if dir_writable else "fail",
        "description": "输出目录写入权限",
        "details": {
            "path": str(output_dir),
            "writable": dir_writable
        },
        "fix": f"请确保目录 {output_dir} 存在且有写入权限"
    }
    if not dir_writable:
        all_passed = False

    # 4. 检查 LLM 配置
    llm_api_key = (os.getenv("LLM_API_KEY") or
                   os.getenv("COURSE_API_KEY") or
                   os.getenv("VIDEO_API_KEY") or
                   os.getenv("DASHSCOPE_API_KEY", ""))
    llm_base_url = os.getenv("LLM_BASE_URL") or os.getenv("COURSE_BASE_URL") or ""
    llm_valid = bool(llm_api_key)
    diagnostics["checks"]["llm_config"] = {
        "status": "pass" if llm_valid else "fail",
        "description": "LLM API 配置（用于分镜生成）",
        "details": {
            "api_key_configured": len(llm_api_key) > 0,
            "api_key_length": len(llm_api_key),
            "base_url": llm_base_url or "默认"
        },
        "fix": "请在 teacher/.env 文件中配置 LLM_API_KEY"
    }

    # 5. 检查 LaTeX 编译器（可选）
    latex_status = "warning"
    latex_path = None
    try:
        result = subprocess.run(
            ["pdflatex", "--version"],
            capture_output=True,
            timeout=5
        )
        latex_status = "pass"
        latex_path = "pdflatex"
    except Exception:
        pass

    diagnostics["checks"]["latex"] = {
        "status": latex_status,
        "description": "LaTeX 编译器（可选）",
        "details": {
            "installed": latex_status == "pass",
            "path": latex_path
        },
        "fix": "LaTeX 不是必需的，系统使用内置的 Tectonic 编译器"
    }

    # 总体状态
    if all_passed:
        diagnostics["overall_status"] = "ready"
    elif tts_valid and ffmpeg_status == "pass":
        diagnostics["overall_status"] = "mostly_ready"
    else:
        diagnostics["overall_status"] = "not_ready"

    return {"success": True, "diagnostics": diagnostics}


# ==================== 路由注册 ====================

def register_video_routes(app):
    """注册视频生成路由"""

    @app.post("/api/video/generate")
    async def api_generate_video_unified(request: VideoGenerateRequestUnified, background_tasks: BackgroundTasks, session_id: str = ""):
        """
        统一的视频生成入口

        接受 task_id 或 course_id，自动判断来源并生成视频
        """
        return await generate_video(request, background_tasks, session_id)

    @app.get("/api/video/progress/{task_id}")
    async def api_get_video_progress(task_id: str, session_id: str = ""):
        """获取视频生成进度"""
        return await get_video_progress(task_id, session_id)

    @app.get("/api/video/course/{course_id}")
    async def api_get_course_video(course_id: str, session_id: str = ""):
        """获取课程生成的视频"""
        return await get_course_video(course_id, session_id)

    @app.get("/api/video/course/{course_id}/status")
    async def api_get_course_video_status(course_id: str, session_id: str = ""):
        """获取课程视频生成状态"""
        return await get_course_video_status(course_id, session_id)

    @app.get("/api/video/diagnostics")
    async def api_video_diagnostics(session_id: str = ""):
        """视频生成环境诊断"""
        return await video_diagnostics(session_id)
