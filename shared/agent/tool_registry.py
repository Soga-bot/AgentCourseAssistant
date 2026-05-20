# -*- coding: utf-8 -*-
"""
工具注册中心 - 注册所有可用的Agent工具

将现有业务功能封装为Agent可调用的工具
"""
from typing import Dict, Any, Optional, List
import logging
import sys
import os

# 添加项目路径
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../..')))

from shared.agent.tools import ToolManager
from shared.llm_client import LLMClient, LLMConfig

logger = logging.getLogger(__name__)


def create_tool_manager(
    knowledge_base=None,
    course_generator=None,
    llm_client=None
) -> ToolManager:
    """
    创建并配置工具管理器

    Args:
        knowledge_base: 知识库实例（可选）
        course_generator: 课程生成器实例（可选）
        llm_client: LLM客户端实例（可选）

    Returns:
        配置好的工具管理器
    """
    manager = ToolManager()

    # 如果所有组件都为空，尝试创建知识库
    if knowledge_base is None and course_generator is None and llm_client is None:
        try:
            from teacher.course_pipeline.knowledge_base import KnowledgeBase
            knowledge_base = KnowledgeBase()
            logger.info("[create_tool_manager] 自动创建知识库成功")
        except Exception as e:
            logger.warning(f"[create_tool_manager] 自动创建知识库失败: {e}")

    # ==================== 知识库工具 ====================

    async def query_knowledge_base(
        version: str,
        grade: str,
        chapter_id: str
    ) -> Dict[str, Any]:
        """
        查询教材知识库，获取章节信息

        Args:
            version: 教材版本 (如 "renjiao_v1", "beishi_v1")
            grade: 年级 (如 "七年级上册", "八年级上册")
            chapter_id: 章节ID (如 "c1_youshu", "c2_shizi")

        Returns:
            章节信息字典，包含章节名称、知识点、重难点等
        """
        if not knowledge_base:
            return {
                "success": False,
                "error": "Knowledge base not initialized",
                "message": "知识库未初始化，无法查询"
            }

        try:
            chapter_info = knowledge_base.get_chapter_info(version, grade, chapter_id)

            if not chapter_info:
                return {
                    "success": False,
                    "error": "Chapter not found",
                    "message": f"未找到章节: {version}/{grade}/{chapter_id}"
                }

            return {
                "success": True,
                "chapter_id": chapter_info.chapter_id,
                "chapter_name": chapter_info.chapter_name,
                "order": chapter_info.order,
                "curriculum_requirement": chapter_info.curriculum_requirement,
                "knowledge_points": chapter_info.knowledge_points,
                "key_difficulties": chapter_info.key_difficulties,
                "common_mistakes": chapter_info.common_mistakes,
                "common_question_types": chapter_info.common_question_types,
            }

        except Exception as e:
            logger.error(f"[query_knowledge_base] Error: {e}")
            return {
                "success": False,
                "error": str(e),
                "message": f"查询知识库时出错: {str(e)}"
            }

    manager.register_from_function(
        query_knowledge_base,
        name="query_knowledge_base",
        description="查询教材知识库，获取指定章节的教学要求、知识点、重难点等信息"
    )

    # ==================== 章节列表工具 ====================

    async def list_available_chapters(
        version: str,
        grade: str
    ) -> Dict[str, Any]:
        """
        列出指定教材版本和年级的所有可用章节

        Args:
            version: 教材版本
            grade: 年级

        Returns:
            章节列表
        """
        if not knowledge_base:
            return {
                "success": False,
                "error": "Knowledge base not initialized"
            }

        try:
            chapters = knowledge_base.get_chapters(version, grade)

            # 处理返回的章节（可能是字典或对象）
            chapter_list = []
            for ch in chapters:
                if isinstance(ch, dict):
                    chapter_list.append({
                        "id": ch.get("chapter_id", "N/A"),
                        "name": ch.get("chapter_name", "N/A"),
                        "order": ch.get("order", 0)
                    })
                else:
                    # 假设是ChapterInfo对象
                    chapter_list.append({
                        "id": getattr(ch, "chapter_id", "N/A"),
                        "name": getattr(ch, "chapter_name", "N/A"),
                        "order": getattr(ch, "order", 0)
                    })

            return {
                "success": True,
                "version": version,
                "grade": grade,
                "chapter_count": len(chapter_list),
                "chapters": chapter_list
            }

        except Exception as e:
            logger.error(f"[list_available_chapters] Error: {e}")
            return {
                "success": False,
                "error": str(e)
            }

    manager.register_from_function(
        list_available_chapters,
        name="list_available_chapters",
        description="列出指定教材版本和年级的所有可用章节"
    )

    # ==================== 课程生成工具 ====================

    # 课程生成共享状态：用于在工具外部设置 progress_callback，
    # 工具内部读取并传递给 CourseGenerator.generate()。
    # WHY: progress_callback 是 callable，无法序列化为 JSON 供 LLM 调用，
    #      所以通过共享状态字典传递，与视频工具的 _video_pipeline_state 模式一致。
    _course_gen_state: Dict[str, Any] = {}

    async def generate_course_content(
        version: str,
        grade: str,
        chapter_id: str,
        student_level: str = "中等巩固",
        purpose: str = "学生自学",
        task_id: str = ""
    ) -> Dict[str, Any]:
        """
        生成课程内容

        Args:
            version: 教材版本
            grade: 年级
            chapter_id: 章节ID
            student_level: 学生水平
            purpose: 用途
            task_id: 任务ID（用于进度追踪）

        Returns:
            生成的课程内容（含完整 content_dict 供下游保存和校验）
        """
        if not course_generator:
            return {
                "success": False,
                "error": "Course generator not initialized",
                "message": "课程生成器未初始化"
            }

        try:
            from teacher.course_pipeline.models import CourseGenerateRequest

            request = CourseGenerateRequest(
                version=version,
                grade=grade,
                chapter_id=chapter_id,
                student_level=student_level,
                purpose=purpose
            )

            # 从共享状态中读取 progress_callback，传递给 CourseGenerator
            gen_kwargs = {}
            progress_cb = _course_gen_state.get("progress_callback")
            if progress_cb:
                gen_kwargs["progress_callback"] = progress_cb
            if task_id:
                gen_kwargs["task_id"] = task_id

            # 调用 CourseGenerator.generate()，保持原有生成逻辑不变
            content = await course_generator.generate(request, **gen_kwargs)

            return {
                "success": True,
                "title": content.title,
                "chapter_id": content.chapter_id,
                "grade": content.grade,
                "chapter": content.chapter,
                "sections": list(content.sections.keys()),
                "section_count": len(content.sections),
                "student_level": student_level,
                "generation_time": content.generated_at,
                "content_dict": content.to_dict()
            }

        except Exception as e:
            logger.error(f"[generate_course_content] Error: {e}")
            return {
                "success": False,
                "error": str(e),
                "message": f"生成课程内容时出错: {str(e)}"
            }

    manager.register_from_function(
        generate_course_content,
        name="generate_course_content",
        description="生成指定章节的课程内容，包括知识点详解、例题、练习等"
    )

    # ==================== 内容校验工具 ====================

    async def validate_content(
        content: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        校验生成内容的格式和质量

        Args:
            content: 待校验的内容字典

        Returns:
            校验结果
        """
        if not course_generator or not hasattr(course_generator, 'validator'):
            return {
                "success": False,
                "error": "Validator not available",
                "message": "内容校验器不可用"
            }

        try:
            validator = course_generator.validator

            # 执行基础校验
            validation_result = validator.validate(content)

            return {
                "success": True,
                "is_valid": validation_result.is_valid,
                "errors": validation_result.errors if validation_result.errors else [],
                "warnings": validation_result.warnings if validation_result.warnings else [],
                "error_count": len(validation_result.errors) if validation_result.errors else 0,
                "warning_count": len(validation_result.warnings) if validation_result.warnings else 0,
                "message": "校验完成" if validation_result.is_valid else "校验未通过"
            }

        except Exception as e:
            logger.error(f"[validate_content] Error: {e}")
            return {
                "success": False,
                "error": str(e),
                "message": f"校验内容时出错: {str(e)}"
            }

    manager.register_from_function(
        validate_content,
        name="validate_content",
        description="校验课程内容的格式正确性和质量，检查公式、结构等"
    )

    # ==================== 版本列表工具 ====================

    async def list_available_versions() -> Dict[str, Any]:
        """
        列出所有可用的教材版本

        Returns:
            教材版本列表
        """
        if not knowledge_base:
            return {
                "success": False,
                "error": "Knowledge base not initialized"
            }

        try:
            versions = knowledge_base.get_versions()

            # 处理返回的版本（可能是字典或对象）
            version_list = []
            for v in versions:
                if isinstance(v, dict):
                    version_list.append({
                        "id": v.get("version_id", "N/A"),
                        "name": v.get("version_name", "N/A"),
                        "grades": v.get("grades", [])
                    })
                else:
                    # 假设是VersionInfo对象
                    version_list.append({
                        "id": getattr(v, "version_id", "N/A"),
                        "name": getattr(v, "version_name", "N/A"),
                        "grades": list(getattr(v, "grades", []))
                    })

            return {
                "success": True,
                "version_count": len(version_list),
                "versions": version_list
            }

        except Exception as e:
            logger.error(f"[list_available_versions] Error: {e}")
            return {
                "success": False,
                "error": str(e)
            }

    manager.register_from_function(
        list_available_versions,
        name="list_available_versions",
        description="列出所有可用的教材版本"
    )

    # ==================== 简单问答工具 ====================

    async def simple_question_answer(
        question: str,
        context: str = ""
    ) -> Dict[str, Any]:
        """
        简单问答工具，用于回答常识性问题

        Args:
            question: 问题
            context: 可选的上下文信息

        Returns:
            答案
        """
        if not llm_client:
            return {
                "success": False,
                "error": "LLM client not initialized"
            }

        try:
            system_prompt = """你是一个专业的初中数学学习助手，擅长用通俗易懂的方式解释数学概念。

回答要求：
1. 用简单明了的语言解释
2. 结合实际例子帮助理解
3. 公式使用LaTeX格式：$公式$ 或 $$公式$$
4. 回答简洁有力，通常控制在3-5句话以内
"""

            user_prompt = f"问题：{question}"
            if context:
                user_prompt = f"上下文：{context}\n\n问题：{question}"

            response = await llm_client.generate(
                system_prompt=system_prompt,
                user_prompt=user_prompt
            )

            if response.success:
                return {
                    "success": True,
                    "answer": response.content,
                    "tokens_used": response.tokens_used
                }
            else:
                return {
                    "success": False,
                    "error": response.error
                }

        except Exception as e:
            logger.error(f"[simple_question_answer] Error: {e}")
            return {
                "success": False,
                "error": str(e)
            }

    manager.register_from_function(
        simple_question_answer,
        name="simple_question_answer",
        description="回答简单的数学问题，解释概念"
    )

    # ==================== 视频生成工具 ====================
    # 用于 VideoGenerationAgent 调用

    _video_pipeline_state: Dict[str, Any] = {}

    async def preprocess_frames(
        course_id: str,
        course_json: str
    ) -> Dict[str, Any]:
        """
        预处理课程JSON，转换为规范帧

        Args:
            course_id: 课程ID
            course_json: 课程JSON字符串

        Returns:
            预处理结果
        """
        try:
            import json as _json
            from pathlib import Path as _Path
            from teacher.video_pipeline.modules.frame_preprocessor import FramePreprocessor
            from teacher.video_pipeline.config import VideoGenConfig

            cfg = VideoGenConfig()
            output_dir = _Path(cfg.get_output_dir(course_id))
            output_dir.mkdir(parents=True, exist_ok=True)

            fp = FramePreprocessor()
            course_data = _json.loads(course_json)
            frames = fp.preprocess(course_data)

            # 保存帧数据
            frames_path = output_dir / "frames.json"
            frames_data = fp.frames_to_dict(frames)
            with open(frames_path, 'w', encoding='utf-8') as f:
                _json.dump(frames_data, f, ensure_ascii=False, indent=2)

            # 保存到共享状态
            _video_pipeline_state["frames"] = frames_data
            _video_pipeline_state["output_dir"] = str(output_dir)
            _video_pipeline_state["course_id"] = course_id

            return {
                "success": True,
                "frame_count": len(frames),
                "frames_path": str(frames_path),
                "sections": list(set(
                    fd.get("sectionSource", "")
                    for fd in frames_data
                    if fd.get("sectionSource")
                ))
            }
        except Exception as e:
            logger.error(f"[preprocess_frames] Error: {e}")
            return {"success": False, "error": str(e)}

    async def generate_narration(course_id: str) -> Dict[str, Any]:
        """
        为帧生成口语化讲解内容

        Args:
            course_id: 课程ID

        Returns:
            讲解生成结果
        """
        try:
            import json as _json
            from pathlib import Path as _Path
            frames_data = _video_pipeline_state.get("frames")
            if not frames_data:
                return {"success": False, "error": "未找到帧数据，请先执行预处理"}

            from teacher.video_pipeline.modules.frame_preprocessor import FramePreprocessor
            from teacher.video_pipeline.modules.narration_generator import NarrationGenerator

            fp = FramePreprocessor()
            frames = fp.frames_from_dict(frames_data)

            ng = NarrationGenerator()
            frames = await ng.generate_for_frames(frames, batch_size=3)

            # 更新帧数据
            updated_data = fp.frames_to_dict(frames)
            _video_pipeline_state["frames"] = updated_data

            output_dir = _video_pipeline_state.get("output_dir", "")
            if output_dir:
                frames_path = _Path(output_dir) / "frames.json"
                with open(frames_path, 'w', encoding='utf-8') as f:
                    _json.dump(updated_data, f, ensure_ascii=False, indent=2)

            return {
                "success": True,
                "frame_count": len(frames),
                "message": "讲解生成完成"
            }
        except Exception as e:
            logger.error(f"[generate_narration] Error: {e}")
            return {"success": False, "message": f"讲解生成跳过: {str(e)}"}

    async def generate_latex_pdf(
        course_id: str,
        course_title: str
    ) -> Dict[str, Any]:
        """
        生成LaTeX并编译为PDF

        Args:
            course_id: 课程ID
            course_title: 课程标题

        Returns:
            LaTeX和PDF生成结果
        """
        try:
            import json as _json
            from pathlib import Path as _Path
            from teacher.video_pipeline.modules.frame_preprocessor import FramePreprocessor
            from teacher.video_pipeline.modules.simple_latex_generator import SimpleLaTeXGenerator
            from teacher.video_pipeline.modules.pdf_compiler import PDFCompiler, PDFCompilerConfig
            from teacher.video_pipeline.config import VideoGenConfig

            frames_data = _video_pipeline_state.get("frames")
            if not frames_data:
                return {"success": False, "error": "未找到帧数据"}

            fp = FramePreprocessor()
            frames = fp.frames_from_dict(frames_data)

            # 生成LaTeX
            lg = SimpleLaTeXGenerator()
            latex_result = lg.generate(frames, course_title)

            if not latex_result.success:
                return {"success": False, "error": latex_result.error}

            # 保存LaTeX
            cfg = VideoGenConfig()
            temp_dir = _Path(cfg.get_temp_dir(course_id))
            temp_dir.mkdir(parents=True, exist_ok=True)

            tex_path = temp_dir / "lesson.tex"
            with open(tex_path, 'w', encoding='utf-8') as f:
                f.write(latex_result.tex_content)

            # 编译PDF
            pdf_config = PDFCompilerConfig(latex_compiler="xelatex", max_retries=3, timeout=120)
            pc = PDFCompiler(pdf_config)
            pdf_result = await pc.compile_with_retry(tex_path=tex_path, temp_dir=temp_dir, max_retries=3)

            if not pdf_result.success:
                return {"success": False, "error": f"PDF编译失败: {pdf_result.error}"}

            _video_pipeline_state["pdf_path"] = str(pdf_result.pdf_path)

            # 计算PDF页数
            pdf_page_count = 0
            try:
                from pdf2image import pdfinfo_from_path
                pdf_info = pdfinfo_from_path(str(pdf_result.pdf_path))
                pdf_page_count = pdf_info.get("Pages", 0)
            except Exception:
                # 降级：通过LaTeX帧数估算
                pdf_page_count = latex_result.frame_count

            return {
                "success": True,
                "pdf_path": str(pdf_result.pdf_path),
                "tex_path": str(tex_path),
                "frame_count": latex_result.frame_count,
                "pdf_page_count": pdf_page_count
            }
        except Exception as e:
            logger.error(f"[generate_latex_pdf] Error: {e}")
            return {"success": False, "error": str(e)}

    async def extract_images(course_id: str) -> Dict[str, Any]:
        """
        从PDF提取关键帧图片

        Args:
            course_id: 课程ID

        Returns:
            图片提取结果
        """
        try:
            from pathlib import Path as _Path
            from teacher.video_pipeline.config import VideoGenConfig
            from pdf2image import convert_from_path

            pdf_path = _video_pipeline_state.get("pdf_path")
            if not pdf_path:
                return {"success": False, "error": "未找到PDF，请先生成PDF"}

            cfg = VideoGenConfig()
            output_dir = _Path(cfg.get_output_dir(course_id))
            images_dir = output_dir / "images"
            images_dir.mkdir(exist_ok=True)

            # 转换PDF为图片（使用slide_前缀，与TTSVideoSynthesizer的glob模式一致）
            from pdf2image import convert_from_path as _convert
            raw_images = _convert(
                pdf_path,
                dpi=200,
                fmt="png"
            )

            # 手动保存为 slide_01.png, slide_02.png ... 命名格式
            image_count = 0
            for idx, img in enumerate(raw_images):
                img_path = images_dir / f"slide_{idx + 1:02d}.png"
                img.save(str(img_path), "PNG")
                image_count += 1

            _video_pipeline_state["images_dir"] = str(images_dir)
            _video_pipeline_state["image_count"] = image_count

            return {
                "success": True,
                "image_count": image_count,
                "images_dir": str(images_dir),
                "frames_path": str(output_dir / "frames.json")
            }
        except ImportError:
            return {"success": False, "error": "pdf2image未安装，请安装poppler"}
        except Exception as e:
            logger.error(f"[extract_images] Error: {e}")
            return {"success": False, "error": str(e)}

    async def generate_speech_script(
        course_id: str,
        course_title: str,
        pdf_page_count: int
    ) -> Dict[str, Any]:
        """
        生成语音脚本

        Args:
            course_id: 课程ID
            course_title: 课程标题
            pdf_page_count: PDF页数

        Returns:
            语音脚本生成结果
        """
        try:
            import json as _json
            from pathlib import Path as _Path
            from teacher.video_pipeline.config import VideoGenConfig
            from teacher.video_pipeline.modules.frame_preprocessor import FramePreprocessor, Frame

            frames_data = _video_pipeline_state.get("frames")
            if not frames_data:
                return {"success": False, "error": "未找到帧数据"}

            fp = FramePreprocessor()
            frames = fp.frames_from_dict(frames_data)
            image_count = _video_pipeline_state.get("image_count", pdf_page_count)

            # 封面场景
            cover_text = course_title
            speech_scenes = [{
                "frame_id": "cover",
                "scene_index": 1,
                "text": cover_text,
                "duration": max(3, len(cover_text) / 3),
                "frame_title": "封面",
                "frame_type": "cover",
                "section_source": "封面"
            }]

            # 内容场景
            content_scenes = []
            for i, frame in enumerate(frames):
                text = ""
                if hasattr(frame, 'narration_hint') and frame.narration_hint:
                    text = frame.narration_hint
                else:
                    text = frame.content

                duration = max(2, len(text) / 3)
                content_scenes.append({
                    "frame_id": frame.id,
                    "scene_index": i + 2,
                    "text": text,
                    "duration": duration,
                    "frame_title": frame.title,
                    "frame_type": frame.frame_type,
                    "section_source": frame.section_source
                })

            # 合并场景以匹配PDF页数
            target_content = image_count - 1
            if len(content_scenes) > target_content and target_content > 0:
                ratio = len(content_scenes) / target_content
                merged = []
                for i in range(target_content):
                    start = int(i * ratio)
                    end = int((i + 1) * ratio)
                    batch = content_scenes[start:end]
                    merged.append({
                        "frame_id": batch[0]["frame_id"],
                        "scene_index": i + 2,
                        "text": " ".join(s["text"] for s in batch),
                        "duration": sum(s["duration"] for s in batch),
                        "frame_title": batch[0]["frame_title"],
                        "frame_type": batch[0]["frame_type"],
                        "section_source": batch[0]["section_source"]
                    })
                speech_scenes.extend(merged)
            else:
                speech_scenes.extend(content_scenes)

            for i, scene in enumerate(speech_scenes):
                scene["scene_index"] = i + 1

            speech_script = {
                "total_scenes": len(speech_scenes),
                "total_duration": sum(s["duration"] for s in speech_scenes),
                "scenes": speech_scenes
            }

            # 保存
            cfg = VideoGenConfig()
            output_dir = _Path(cfg.get_output_dir(course_id))
            speech_path = output_dir / "speech.json"
            with open(speech_path, 'w', encoding='utf-8') as f:
                _json.dump(speech_script, f, ensure_ascii=False, indent=2)

            _video_pipeline_state["speech_script"] = speech_script

            return {
                "success": True,
                "scene_count": len(speech_scenes),
                "speech_path": str(speech_path),
                "total_duration": speech_script["total_duration"]
            }
        except Exception as e:
            logger.error(f"[generate_speech_script] Error: {e}")
            return {"success": False, "error": str(e)}

    async def tts_and_synthesize(course_id: str) -> Dict[str, Any]:
        """
        TTS语音合成与视频合成

        Args:
            course_id: 课程ID

        Returns:
            视频生成结果
        """
        try:
            speech_script = _video_pipeline_state.get("speech_script")
            images_dir = _video_pipeline_state.get("images_dir")
            if not speech_script or not images_dir:
                return {"success": False, "error": "缺少语音脚本或图片数据"}

            from pathlib import Path as _Path
            from teacher.video_pipeline.config import VideoGenConfig
            from teacher.video_pipeline.audio_utils import TTSGenerator
            from teacher.video_pipeline.modules.tts_video_synthesizer import TTSVideoSynthesizer, TTSAudioResult

            cfg = VideoGenConfig()
            output_dir = _Path(cfg.get_output_dir(course_id))

            # TTS
            tts = TTSGenerator(
                app_key=cfg.tts.app_key,
                token=cfg.tts.access_token,
                voice=cfg.tts.voice,
                format=cfg.tts.format,
                base_url=cfg.tts.base_url,
                cache_dir=str(output_dir / "audio"),
                max_concurrent=cfg.tts.max_concurrent,
                request_interval=cfg.tts.request_interval
            )

            tts_check = await tts.test_tts_availability()
            if not tts_check["available"]:
                return {"success": False, "error": f"TTS不可用: {tts_check['error']}"}

            # 逐场景生成音频
            audio_results: list = []
            for i, scene in enumerate(speech_script["scenes"]):
                scene_id = scene.get("frame_id", f"s{i+1}")
                narration = scene.get("text", scene.get("narration", ""))
                if not narration:
                    continue
                result = await tts.process_scene_sentences(
                    scene_id=scene_id,
                    narration=narration,
                    audio_index=i + 1
                )
                if result.get("success"):
                    audio_results.append(TTSAudioResult(
                        scene_id=scene_id,
                        audio_path=result["merged_audio_path"],
                        duration=result.get("total_duration", 0),
                        success=True
                    ))

            if not audio_results:
                return {"success": False, "error": "所有场景音频生成失败"}

            # 视频合成
            synthesizer = TTSVideoSynthesizer()

            video_path = output_dir / "video.mp4"
            video_result = await synthesizer.synthesize_video(
                images_dir=images_dir,
                audio_results=audio_results,
                output_path=str(video_path),
                course_id=course_id,
                speech_scenes=speech_script.get("scenes", [])
            )

            if not video_result.success:
                return {
                    "success": False,
                    "error": video_result.error or "视频合成失败"
                }

            return {
                "success": True,
                "video_path": video_result.video_path or str(video_path),
                "duration": video_result.total_duration
            }
        except Exception as e:
            logger.error(f"[tts_and_synthesize] Error: {e}")
            return {"success": False, "error": str(e)}

    manager.register_from_function(
        preprocess_frames,
        name="preprocess_frames",
        description="预处理课程JSON数据，将其转换为规范帧列表"
    )
    manager.register_from_function(
        generate_narration,
        name="generate_narration",
        description="为帧内容生成口语化讲解（LLM调用），可选步骤"
    )
    manager.register_from_function(
        generate_latex_pdf,
        name="generate_latex_pdf",
        description="从帧数据生成LaTeX并编译为PDF"
    )
    manager.register_from_function(
        extract_images,
        name="extract_images",
        description="从PDF提取关键帧图片"
    )
    manager.register_from_function(
        generate_speech_script,
        name="generate_speech_script",
        description="根据帧内容和PDF页数生成语音脚本"
    )
    manager.register_from_function(
        tts_and_synthesize,
        name="tts_and_synthesize",
        description="TTS语音合成与视频合成"
    )

    # 将课程生成共享状态挂载到 manager 上，使 Agent 可在调用工具前设置 progress_callback
    manager._course_gen_state = _course_gen_state

    logger.info(f"[ToolRegistry] 已注册 {len(manager.list_tools())} 个工具")

    return manager


# ==================== 便捷函数 ====================

def create_default_tool_manager(
    require_llm: bool = False,
    require_generator: bool = False
) -> ToolManager:
    """
    创建默认的工具管理器

    自动初始化知识库和可选的课程生成器

    Args:
        require_llm: 是否要求LLM客户端（用于问答工具）
        require_generator: 是否要求课程生成器

    Returns:
        配置好的工具管理器
    """
    kb = None
    cg = None
    llm = None

    # 1. 初始化知识库（必需）
    try:
        from teacher.course_pipeline.knowledge_base import KnowledgeBase
        kb = KnowledgeBase()
        logger.info("[create_default_tool_manager] 知识库初始化成功")
    except Exception as e:
        logger.warning(f"[create_default_tool_manager] 知识库初始化失败: {e}")

    # 2. 初始化LLM客户端（可选）
    if require_llm:
        try:
            llm = LLMClient(LLMConfig())
            logger.info("[create_default_tool_manager] LLM客户端初始化成功")
        except Exception as e:
            logger.warning(f"[create_default_tool_manager] LLM客户端初始化失败: {e}")

    # 3. 初始化课程生成器（可选）
    if require_generator:
        try:
            from teacher.course_pipeline.course_generator import CourseGenerator
            cg = CourseGenerator()
            logger.info("[create_default_tool_manager] 课程生成器初始化成功")
        except Exception as e:
            logger.warning(f"[create_default_tool_manager] 课程生成器初始化失败: {e}")

    # 创建工具管理器
    return create_tool_manager(
        knowledge_base=kb,
        course_generator=cg,
        llm_client=llm
    )


def list_registered_tools(manager: ToolManager) -> str:
    """
    列出已注册的工具

    Args:
        manager: 工具管理器

    Returns:
        格式化的工具列表字符串
    """
    tools = manager.list_tools()

    lines = ["已注册的工具:", ""]

    for tool in tools:
        params = ", ".join(tool.parameters.keys())
        lines.append(f"- {tool.name}({params})")
        lines.append(f"  描述: {tool.description}")
        lines.append("")

    return "\n".join(lines)

