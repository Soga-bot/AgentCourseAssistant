"""
课程生成模块

提供基于教材的课程生成功能
"""

import asyncio
import json
import time
import uuid
from pathlib import Path
from fastapi import HTTPException, BackgroundTasks
from pydantic import BaseModel
from typing import Optional, Dict

from course_pipeline import CourseGenerator, CourseGeneratorConfig, CourseGenerateRequest


class GenerateCourseRequest(BaseModel):
    """生成课程请求"""
    version: str  # 教材版本
    grade: str  # 年级
    chapter: str  # 章节ID (与前端保持一致)
    student_level: Optional[str] = "中等巩固"
    purpose: Optional[str] = "学生自学"
    content_type: Optional[str] = None  # 内容类型: lesson_plan/teaching_script/board_design/review_outline
    generate_video: Optional[bool] = False  # 是否同时生成视频
    custom_topic: Optional[str] = None
    custom_outline: Optional[str] = None  # 自定义大纲内容


# 全局变量（从 main.py 传入）
_progress_manager = None
_output_dir = None


def init_course_generation(progress_manager, output_dir):
    """初始化课程生成模块"""
    global _progress_manager, _output_dir
    _progress_manager = progress_manager
    _output_dir = output_dir


# 全局课程生成器实例
_generator = None


def get_generator():
    """获取课程生成器实例（单例）"""
    global _generator
    if _generator is None:
        config = CourseGeneratorConfig()
        _generator = CourseGenerator(config)
    return _generator


async def _run_course_generation_task(task_id: str, request: CourseGenerateRequest):
    """
    后台运行课程生成任务

    Args:
        task_id: 任务ID
        request: 课程生成请求
    """
    try:
        # 更新任务状态为处理中
        _progress_manager.update_progress(
            task_id,
            percent=5,
            message="正在初始化...",
            status="processing"
        )

        # 获取生成器
        generator = get_generator()

        # 定义进度回调函数
        def progress_callback(percent: int, message: str):
            _progress_manager.update_progress(
                task_id,
                percent=percent,
                message=message,
                status="processing"
            )

        # 生成课程
        content = await generator.generate(request, progress_callback=progress_callback, task_id=task_id)

        # ========== 保存course.json（第一阶段输出） ==========
        if _output_dir:
            course_json_path = Path(_output_dir) / task_id / "course.json"
            course_json_path.parent.mkdir(parents=True, exist_ok=True)

            content_dict = content.to_dict()
            course_json_path.write_text(
                json.dumps(content_dict, ensure_ascii=False, indent=2),
                encoding="utf-8"
            )

            print(f"[课程生成-第一阶段] course.json已保存: {course_json_path}")
            print(f"[课程生成-第一阶段]   - 标题: {content_dict.get('title', 'N/A')}")
            print(f"[课程生成-第一阶段]   - sections数量: {len(content_dict.get('sections', {}))}")
            print(f"[课程生成-第一阶段]   - sections列表: {list(content_dict.get('sections', {}).keys())}")

            # 检测潜在的占位符问题
            placeholder_keywords = ["待补充", "待填充", "待定", "占位", "SceneID:", "内容待补充", "本页内容"]
            found_placeholders = []
            for section_name, section_content in content_dict.get('sections', {}).items():
                for keyword in placeholder_keywords:
                    if keyword in str(section_content):
                        found_placeholders.append(f"{section_name}:{keyword}")

            if found_placeholders:
                print(f"[课程生成-第一阶段] ⚠️ 检测到可能的占位符: {found_placeholders}")
            else:
                print(f"[课程生成-第一阶段] ✓ 未检测到占位符")

        # 任务完成 - 使用 complete() 方法保存结果
        _progress_manager.complete(task_id, content.to_dict())

    except Exception as e:
        # 任务失败
        _progress_manager.update_progress(
            task_id,
            percent=0,
            message=f"生成失败: {str(e)}",
            status="failed"
        )


async def generate_course(request: GenerateCourseRequest, background_tasks: BackgroundTasks):
    """
    生成课程内容（后台任务模式）

    支持两种模式：
    1. 教材章节模式：根据教材版本、年级、章节生成内容
    2. 自定义内容模式：教师提供自定义大纲
    """
    # 调试日志：打印接收到的请求数据
    print(f"[DEBUG] generate_course 收到请求:")
    print(f"  version={request.version}")
    print(f"  grade={request.grade}")
    print(f"  chapter={request.chapter}")
    print(f"  student_level={request.student_level}")
    print(f"  purpose={request.purpose}")
    print(f"  content_type={request.content_type}")
    print(f"  generate_video={request.generate_video}")

    try:
        # 创建任务ID
        task_id = str(uuid.uuid4())

        # 初始化任务
        _progress_manager.tasks[task_id] = {
            "percent": 0,
            "message": "任务已创建",
            "status": "pending",
            "mode": "course",
            "created_at": time.time(),
            "content_type": request.content_type,
            "purpose": request.purpose,
        }

        # 构建课程生成请求（所有章节都是必填的）
        pipeline_request = CourseGenerateRequest(
            version=request.version,
            grade=request.grade,
            chapter_id=request.chapter,
            student_level=request.student_level or "中等巩固",
            purpose=request.purpose or "学生自学",
            content_type=request.content_type,
            custom_topic=request.custom_topic,
            custom_outline=request.custom_outline
        )

        # 启动后台任务
        background_tasks.add_task(_run_course_generation_task, task_id, pipeline_request)

        return {
            "success": True,
            "task_id": task_id,
            "message": "课程生成任务已启动"
        }

    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"课程生成出错: {str(e)}"
        )


async def get_course_progress(task_id: str):
    """获取课程生成进度"""
    progress = _progress_manager.get_progress(task_id)

    if progress is None:
        raise HTTPException(status_code=404, detail="任务不存在")

    return {
        "success": True,
        "task_id": task_id,
        "status": progress["status"],
        "progress": progress["percent"],  # 前端期望 progress 字段
        "percent": progress["percent"],   # 兼容旧代码
        "message": progress.get("message", ""),
        "result": progress.get("result")
    }


async def get_course_preview(task_id: str):
    """获取课程预览"""
    progress = _progress_manager.get_progress(task_id)

    if progress is None:
        raise HTTPException(status_code=404, detail="任务不存在")

    if progress["status"] != "completed":
        raise HTTPException(status_code=400, detail="任务尚未完成")

    result = progress.get("result")
    if not result:
        raise HTTPException(status_code=404, detail="课程内容不存在")

    # 返回前端期望的格式：content 是对象，不是字符串
    # 前端代码: const { content, validation } = response;
    #         content.title, content.sections
    return {
        "content": result,  # 完整的课程对象（包含 title, sections 等）
        "validation": None,  # 验证结果（目前为空）
        "has_video": False,  # 是否有视频
        "task_id": task_id
    }


async def save_course(task_id: str, session_id: str = ""):
    """保存课程到数据库"""
    from shared.session import get_session
    from shared.database import course_db, history_db

    session = get_session(session_id)
    if not session or session["role"] != "teacher":
        raise HTTPException(status_code=403, detail="需要教师权限")

    progress = _progress_manager.get_progress(task_id)

    if progress is None:
        raise HTTPException(status_code=404, detail="任务不存在")

    if progress["status"] != "completed":
        raise HTTPException(status_code=400, detail="任务尚未完成")

    result = progress.get("result")
    if not result:
        raise HTTPException(status_code=404, detail="课程内容不存在")

    # 检查是否已经保存过
    existing = course_db.find_course_by_task_id(session["user_id"], task_id)
    if existing:
        return {
            "success": True,
            "course_id": existing["id"],
            "message": "课程已保存"
        }

    # 保存到数据库
    task_data = _progress_manager.tasks.get(task_id, {})
    course_id = course_db.create_course(
        teacher_id=session["user_id"],
        title=result.get("title", ""),
        grade=result.get("grade", ""),
        chapter=result.get("chapter", ""),
        version=result.get("textbook_version", ""),
        sections=result.get("sections", {}),
        metadata={
            "task_id": task_id,
            "content_source": task_data.get("content_type", ""),
            "purpose": task_data.get("purpose", ""),
            "content_type": task_data.get("content_type", ""),
        },
        content=result
    )

    # 记录历史
    history_db.add_record(
        session["user_id"],
        "save_course",
        course_id,
        details={"task_id": task_id, "title": result.get("title", "")}
    )

    return {
        "success": True,
        "course_id": course_id,
        "message": "课程保存成功"
    }


def register_course_generation_routes(app):
    """注册课程生成相关路由"""

    @app.post("/generate/course")
    async def api_generate_course(request: GenerateCourseRequest, background_tasks: BackgroundTasks):
        """生成课程内容"""
        return await generate_course(request, background_tasks)

    @app.get("/progress/{task_id}")
    async def api_get_course_progress(task_id: str):
        """获取课程生成进度"""
        return await get_course_progress(task_id)

    @app.get("/course/{task_id}/preview")
    async def api_get_course_preview(task_id: str):
        """获取课程预览"""
        return await get_course_preview(task_id)

    @app.post("/course/{task_id}/save")
    async def api_save_course(task_id: str, session_id: str = ""):
        """保存课程到数据库"""
        return await save_course(task_id, session_id)
