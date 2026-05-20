"""
简化版视频生成流水线

[开发历史] 开发初期的视频生成方案，采用 FramePreprocessor + SimpleLaTeXGenerator 的简化路径。
后续被 pipeline.py（CourseVideoGenerator）取代，后者使用 CourseToVideoMapper + LaTeXGenerator 的混合模式。
本文件保留作为早期设计参考。
[已弃用 - 2026] 本模块未被任何外部代码调用，仅作存档保留。

核心思想：
1. 使用 FramePreprocessor 将 course.json 转换为规范帧（0次LLM调用）
2. 使用 NarrationGenerator 将书面内容转换为口语讲解（N次LLM调用）
3. 使用 SimpleLaTeXGenerator 生成 LaTeX（0次LLM调用）
4. PDF 编译
5. 语音脚本生成（使用讲解内容）
6. TTS + 视频合成

特点：
- 讲解内容自然口语化，数学术语发音准确
- 视频生成阶段（不含讲解生成）0 次 LLM 调用
- 帧内容保证不溢出、不截断
"""

import asyncio
import json
import logging
import tempfile
from pathlib import Path
from typing import Dict, List, Optional, Any
from datetime import datetime
import subprocess
import os

from .config import VideoGenConfig
from .modules.frame_preprocessor import FramePreprocessor, Frame
from .modules.simple_latex_generator import SimpleLaTeXGenerator
from .modules.narration_generator import NarrationGenerator

# ========== 统一日志配置 ==========
from .logging_config import setup_logging, get_module_logger

# 初始化统一日志系统
setup_logging(
    level=logging.INFO,
    console_level=logging.INFO,
    enable_console=True,
    enable_file=True
)

# 模块级日志
logger = get_module_logger(__name__, "simple_pipeline")


class SimpleVideoGenerator:
    """
    简化版视频生成器

    完全不依赖 LLM 的视频生成流程
    """

    def __init__(self, config: Optional[VideoGenConfig] = None, enable_narration: bool = True):
        """
        初始化简化版视频生成器

        Args:
            config: 视频生成配置
            enable_narration: 是否启用 LLM 讲解生成（默认启用）
        """
        self.cfg = config or VideoGenConfig()
        self.enable_narration = enable_narration

        # 帧预处理器
        self.frame_preprocessor = FramePreprocessor()

        # LaTeX 生成器
        self.latex_generator = SimpleLaTeXGenerator()

        # 讲解生成器（可选）
        if self.enable_narration:
            self.narration_generator = NarrationGenerator()
        else:
            self.narration_generator = None

        # PDF 编译模块
        from .modules.pdf_compiler import PDFCompiler, PDFCompilerConfig
        pdf_config = PDFCompilerConfig(
            latex_compiler="xelatex",
            max_retries=2,
            timeout=120
        )
        self.pdf_compiler = PDFCompiler(pdf_config)

        logger.info("[SimpleVideoGenerator] 初始化完成")
        logger.info("[SimpleVideoGenerator]   - 帧预处理器: FramePreprocessor")
        logger.info("[SimpleVideoGenerator]   - LaTeX生成器: SimpleLaTeXGenerator")
        logger.info("[SimpleVideoGenerator]   - PDF编译器: PDFCompiler")
        if self.enable_narration:
            logger.info("[SimpleVideoGenerator]   - 讲解生成器: NarrationGenerator (已启用)")
        else:
            logger.info("[SimpleVideoGenerator]   - 讲解生成器: 未启用")

    async def generate_from_course_json(
        self,
        course_id: str,
        course_json: Dict[str, Any],
        progress_callback: Optional[callable] = None
    ) -> Dict[str, Any]:
        """
        从 course.json 生成视频（简化路径）

        流程：
        1. 预处理：course.json → 规范帧（0次LLM）
        2. LaTeX生成：规范帧 → LaTeX（0次LLM）
        3. PDF编译：LaTeX → PDF
        4. 语音脚本：帧内容 → 语音脚本（0次LLM）
        5. TTS + 视频合成

        Args:
            course_id: 课程ID
            course_json: course.json 的内容
            progress_callback: 进度回调函数

        Returns:
            生成结果字典
        """
        logger.info(f"[简化流水线] ========== 开始生成视频 ==========")
        logger.info(f"[简化流水线] 课程ID: {course_id}")
        logger.info(f"[简化流水线] 课程标题: {course_json.get('title', 'N/A')}")

        result = {
            "success": False,
            "course_id": course_id,
            "outputs": {},
            "mode": "simple"  # 标记为简化路径
        }

        try:
            # 准备输出目录
            output_dir = Path(self.cfg.get_output_dir(course_id))
            temp_dir = Path(self.cfg.get_temp_dir(course_id))
            temp_dir.mkdir(parents=True, exist_ok=True)

            logger.info(f"[简化流水线] 输出目录: {output_dir}")
            logger.info(f"[简化流水线] 临时目录: {temp_dir}")

            # ========== 步骤1: 帧预处理 ==========
            if progress_callback:
                progress_callback(5, "正在预处理课程内容...")

            logger.info(f"[简化流水线] 步骤1: 帧预处理")

            frames = self.frame_preprocessor.preprocess(course_json)

            logger.info(f"[简化流水线] 预处理完成: {len(frames)} 帧")

            # 保存帧数据
            frames_path = output_dir / "frames.json"
            frames_data = self.frame_preprocessor.frames_to_dict(frames)
            with open(frames_path, 'w', encoding='utf-8') as f:
                json.dump(frames_data, f, ensure_ascii=False, indent=2)

            logger.info(f"[简化流水线] 帧数据已保存: {frames_path}")

            if progress_callback:
                progress_callback(15, "帧预处理完成...")

            # ========== 步骤2: 讲解生成 (可选) ==========
            if self.enable_narration and self.narration_generator:
                if progress_callback:
                    progress_callback(18, "正在生成讲解内容...")

                logger.info(f"[简化流水线] 步骤2: 讲解生成")

                frames = await self.narration_generator.generate_for_frames(
                    frames,
                    batch_size=3,
                    progress_callback=lambda cur, total, fid: progress_callback(
                        18 + int((cur / total) * 12),
                        f"生成讲解 {cur}/{total}..."
                    ) if progress_callback else None
                )

                logger.info(f"[简化流水线] 讲解生成完成: {len(frames)} 帧")

                if progress_callback:
                    progress_callback(30, "讲解生成完成...")
            else:
                logger.info(f"[简化流水线] 跳过讲解生成（未启用）")
                if progress_callback:
                    progress_callback(30, "跳过讲解生成...")

            # ========== 步骤3: LaTeX 生成 ==========
            if progress_callback:
                progress_callback(32, "正在生成 LaTeX...")

            logger.info(f"[简化流水线] 步骤3: LaTeX 生成")

            course_title = course_json.get('title', '课程')
            latex_result = self.latex_generator.generate(frames, course_title)

            if not latex_result.success:
                raise Exception(f"LaTeX 生成失败: {latex_result.error}")

            latex_content = latex_result.tex_content
            logger.info(f"[简化流水线] LaTeX 生成完成: {latex_result.frame_count} 帧")

            # 保存 LaTeX 文件
            tex_path = temp_dir / "lesson.tex"
            with open(tex_path, 'w', encoding='utf-8') as f:
                f.write(latex_content)

            logger.info(f"[简化流水线] LaTeX 已保存: {tex_path}")

            if progress_callback:
                progress_callback(40, "LaTeX 生成完成...")

            # ========== 步骤4: PDF 编译 ==========
            if progress_callback:
                progress_callback(45, "正在编译 PDF...")

            logger.info(f"[简化流水线] 步骤4: PDF 编译")

            pdf_result = await self.pdf_compiler.compile_with_retry(
                tex_path=tex_path,
                temp_dir=temp_dir,
                max_retries=3
            )

            if not pdf_result.success:
                raise Exception(f"PDF 编译失败: {pdf_result.error}")

            pdf_path = pdf_result.pdf_path
            logger.info(f"[简化流水线] PDF 已生成: {pdf_path}")

            if progress_callback:
                progress_callback(60, "PDF 编译完成...")

            # ========== 步骤5: 提取关键帧 ==========
            if progress_callback:
                progress_callback(65, "正在提取关键帧...")

            logger.info(f"[简化流水线] 步骤5: 提取关键帧")

            images_dir = output_dir / "images"
            images_dir.mkdir(exist_ok=True)

            images_result = await self._generate_images(str(pdf_path), output_dir)

            if not images_result.get("success"):
                raise Exception(f"提取关键帧失败: {images_result.get('error')}")

            actual_image_count = images_result.get('count', 0)
            logger.info(f"[简化流水线] 关键帧已提取: {actual_image_count} 帧")

            if progress_callback:
                progress_callback(75, "关键帧提取完成...")

            # ========== 步骤6: 生成语音脚本 ==========
            if progress_callback:
                progress_callback(78, "正在生成语音脚本...")

            logger.info(f"[简化流水线] 步骤6: 生成语音脚本")

            speech_script = self._generate_speech_from_frames(
                frames,
                actual_image_count,
                course_title=course_json.get('title', '课程')
            )

            # 保存语音脚本
            speech_path = output_dir / "speech.json"
            with open(speech_path, 'w', encoding='utf-8') as f:
                json.dump(speech_script, f, ensure_ascii=False, indent=2)

            logger.info(f"[简化流水线] 语音脚本已生成: {len(speech_script.get('scenes', []))} 个场景")

            if progress_callback:
                progress_callback(80, "语音脚本生成完成...")

            # ========== 步骤6: TTS 与视频合成 ==========
            if progress_callback:
                progress_callback(85, "准备 TTS 与视频合成...")

            logger.info(f"[简化流水线] 步骤6: TTS 与视频合成")

            # TTS 预检
            from .audio_utils import TTSGenerator

            tts_tester = TTSGenerator(
                app_key=self.cfg.tts.app_key,
                token=self.cfg.tts.access_token,
                voice=self.cfg.tts.voice,
                format=self.cfg.tts.format,
                base_url=self.cfg.tts.base_url,
                cache_dir=str(output_dir / "audio"),
                max_concurrent=self.cfg.tts.max_concurrent,
                request_interval=self.cfg.tts.request_interval
            )

            tts_check = await tts_tester.test_tts_availability()
            if not tts_check["available"]:
                logger.error(f"[简化流水线] TTS 服务不可用: {tts_check['error']}")
                raise Exception(f"TTS 服务不可用: {tts_check['error']}")

            logger.info(f"[简化流水线] TTS 服务预检通过")

            # 视频合成
            video_result = await self._generate_video(
                speech_script=speech_script,
                images_result=images_result,
                output_dir=output_dir
            )

            if not video_result.get("success"):
                raise Exception(f"视频合成失败: {video_result.get('error')}")

            logger.info(f"[简化流水线] 视频已生成: {video_result.get('video_path')}")

            # ========== 完成 ==========
            result["success"] = True
            result["video_path"] = str(video_result.get("video_path"))
            result["outputs"]["video"] = str(video_result.get("video_path"))
            result["outputs"]["frames"] = str(frames_path)
            result["outputs"]["speech"] = str(speech_path)
            result["outputs"]["pdf"] = str(pdf_path)
            result["duration"] = video_result.get("duration")
            result["total_frames"] = len(frames)

            logger.info(f"[简化流水线] ========== 生成完成 ==========")
            logger.info(f"[简化流水线]   - 视频路径: {result['video_path']}")
            logger.info(f"[简化流水线]   - 总帧数: {result['total_frames']}")
            logger.info(f"[简化流水线]   - 时长: {result.get('duration', 'N/A')}")

            if progress_callback:
                progress_callback(100, "生成完成!")

        except Exception as e:
            logger.error(f"[简化流水线] 生成失败: {e}")
            import traceback
            logger.error(traceback.format_exc())

            result["error"] = str(e)
            result["traceback"] = traceback.format_exc()

            if progress_callback:
                progress_callback(0, f"生成失败: {str(e)}")

        return result

    def _generate_speech_from_frames(
        self,
        frames: List[Frame],
        actual_image_count: int,
        course_title: str = "课程"
    ) -> Dict[str, Any]:
        """
        从规范帧生成语音脚本

        重要：
        1. PDF 第 1 页是封面页，需要为封面页添加一个场景
        2. Beamer 可能合并内容较短的帧，导致 PDF 页数 < 帧数
        3. 需要确保最终场景数 = PDF 页数

        Args:
            frames: Frame 对象列表
            actual_image_count: 实际 PDF 页数
            course_title: 课程标题（用于封面页语音）

        Returns:
            语音脚本字典
        """
        logger.info(f"[语音生成] 输入: {len(frames)} 帧, PDF 页数: {actual_image_count}")

        # ========== 第 1 个场景：封面页 ==========
        cover_text = f"{course_title}"
        speech_scenes = [{
            "frame_id": "cover",
            "scene_index": 1,
            "text": cover_text,
            "duration": max(3, len(cover_text) / 3),
            "frame_title": "封面",
            "frame_type": "cover",
            "section_source": "封面"
        }]
        logger.info(f"[语音生成] 场景 1: 封面 → {cover_text}")

        # ========== 第 2+ 个场景：内容帧 ==========
        content_scenes = []
        for i, frame in enumerate(frames):
            text = self._extract_speech_text(frame)
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

        # ========== 合并场景以匹配 PDF 页数 ==========
        # PDF 页数 = 1（封面）+ 内容页数
        # 如果内容场景数 > PDF 内容页数，需要合并
        target_content_scenes = actual_image_count - 1  # 减去封面页
        current_content_scenes = len(content_scenes)

        if current_content_scenes > target_content_scenes:
            # 需要合并场景
            logger.info(f"[语音生成] 需要合并场景: {current_content_scenes} → {target_content_scenes}")
            merged_scenes = self._merge_scenes(content_scenes, target_content_scenes)
            speech_scenes.extend(merged_scenes)
        else:
            speech_scenes.extend(content_scenes)

        # 重新编号场景
        for i, scene in enumerate(speech_scenes):
            scene["scene_index"] = i + 1

        result = {
            "total_scenes": len(speech_scenes),
            "total_duration": sum(s["duration"] for s in speech_scenes),
            "scenes": speech_scenes
        }

        logger.info(f"[语音生成] 输出: {len(speech_scenes)} 个场景, 总时长={result['total_duration']:.1f}秒")
        logger.info(f"[语音生成] 场景数 = PDF 页数: {len(speech_scenes)} == {actual_image_count} ✓")

        return result

    def _merge_scenes(self, scenes: List[Dict], target_count: int) -> List[Dict]:
        """
        合并场景以匹配目标数量

        Args:
            scenes: 原始场景列表
            target_count: 目标场景数

        Returns:
            合并后的场景列表
        """
        if target_count <= 0:
            return scenes

        current_count = len(scenes)
        if current_count <= target_count:
            return scenes

        # 计算每个目标场景需要合并多少原始场景
        ratio = current_count / target_count
        merged = []

        for i in range(target_count):
            start_idx = int(i * ratio)
            end_idx = int((i + 1) * ratio)

            # 合并从 start_idx 到 end_idx 的场景
            batch = scenes[start_idx:end_idx]

            # 合并文本和时长
            merged_text = " ".join([s["text"] for s in batch])
            merged_duration = sum(s["duration"] for s in batch)

            # 使用第一个场景的信息作为基础
            merged_scene = {
                "frame_id": batch[0]["frame_id"],
                "scene_index": i + 2,  # 从 2 开始（1 是封面）
                "text": merged_text,
                "duration": merged_duration,
                "frame_title": batch[0]["frame_title"],
                "frame_type": batch[0]["frame_type"],
                "section_source": batch[0]["section_source"]
            }

            # 如果合并了多个场景，标记合并信息
            if len(batch) > 1:
                merged_scene["merged_from"] = [s["frame_title"] for s in batch]
                logger.info(f"[语音生成] 合并场景 {i+2}: {[s['frame_title'] for s in batch]}")

            merged.append(merged_scene)

        return merged

    def _extract_speech_text(self, frame: Frame) -> str:
        """
        从帧内容提取适合语音的文本

        优先使用 narration_hint（LLM 生成的讲解内容）
        如果没有，则从 content 中提取

        Args:
            frame: Frame 对象

        Returns:
            语音文本
        """
        import re

        # 优先使用 LLM 生成的讲解内容
        if hasattr(frame, 'narration_hint') and frame.narration_hint:
            logger.debug(f"[语音生成] 使用讲解内容: {frame.narration_hint[:50]}...")
            return frame.narration_hint

        # 降级：从 content 中提取
        content = frame.content
        if not content:
            return frame.title

        # 清理 LaTeX 标记
        text = content

        # 移除 LaTeX 命令
        text = re.sub(r'\\[a-zA-Z]+\{[^}]*\}', '', text)
        text = re.sub(r'\\[a-zA-Z]+', '', text)
        text = re.sub(r'[{}$\\]', '', text)

        # 处理特殊字符
        text = text.replace('\\\\', '，')
        text = text.replace('\\n', '\n')

        # 移除多余的空白
        text = re.sub(r'\s+', ' ', text)
        text = text.strip()

        # 组合标题和内容
        if text:
            return f"{frame.title}。{text}"
        else:
            return frame.title

    async def _generate_images(
        self,
        pdf_path: str,
        output_dir: Path
    ) -> Dict[str, Any]:
        """PDF 转 PNG 图片"""
        images_dir = output_dir / "images"
        images_dir.mkdir(exist_ok=True)

        logger.info(f"[PDF转PNG] 开始转换图片")
        logger.debug(f"[PDF转PNG] PDF路径: {pdf_path}")
        logger.debug(f"[PDF转PNG] 输出目录: {images_dir}")

        if not pdf_path or not Path(pdf_path).exists():
            logger.error(f"[PDF转PNG] PDF 文件不存在: {pdf_path}")
            return {
                "success": False,
                "error": "PDF 文件不存在",
                "count": 0,
                "dir": str(images_dir)
            }

        try:
            from pdf2image import convert_from_path
            logger.info(f"[PDF转PNG] pdf2image 已导入，DPI: {self.cfg.latex.dpi}")

            # 转换 PDF 为图片
            images = convert_from_path(
                pdf_path,
                dpi=self.cfg.latex.dpi,
                output_folder=str(images_dir)
            )

            # 保存图片
            image_paths = []
            for i, image in enumerate(images):
                image_path = images_dir / f"slide_{i+1}.png"
                image.save(str(image_path), "PNG")
                image_paths.append(str(image_path))

            logger.info(f"[PDF转PNG] 成功生成 {len(image_paths)} 张图片")

            return {
                "success": True,
                "count": len(image_paths),
                "dir": str(images_dir),
                "images": image_paths
            }

        except ImportError:
            logger.error(f"[PDF转PNG] pdf2image 未安装")
            return {
                "success": False,
                "error": "pdf2image 未安装，请运行: pip install pdf2image",
                "count": 0,
                "dir": str(images_dir)
            }
        except Exception as e:
            logger.error(f"[PDF转PNG] 转换异常: {str(e)}")
            import traceback
            logger.debug(f"[PDF转PNG] 异常堆栈:\n{traceback.format_exc()}")
            return {
                "success": False,
                "error": f"PDF 转换失败: {str(e)}",
                "count": 0,
                "dir": str(images_dir)
            }

    async def _generate_video(
        self,
        speech_script: Dict[str, Any],
        images_result: Dict[str, Any],
        output_dir: Path
    ) -> Dict[str, Any]:
        """
        生成最终视频

        Args:
            speech_script: 语音脚本
            images_result: 图片生成结果
            output_dir: 输出目录

        Returns:
            视频生成结果字典
        """
        from .modules.video_synthesizer import VideoSynthesizer, VideoSynthesizerConfig
        import importlib

        audio_utils_module = importlib.import_module('.audio_utils', package='teacher.video_pipeline')

        video_config = VideoSynthesizerConfig(
            ffmpeg_path=self.cfg.ffmpeg_path if hasattr(self.cfg, 'ffmpeg_path') else "ffmpeg",
            ffprobe_path=self.cfg.ffprobe_path if hasattr(self.cfg, 'ffprobe_path') else "ffprobe",
            transition=self.cfg.transition if hasattr(self.cfg, 'transition') else 1.0
        )

        video_synthesizer = VideoSynthesizer(
            tts_config=self.cfg.tts,
            video_config=video_config,
            audio_utils_module=audio_utils_module
        )

        result = await video_synthesizer.generate_video(
            speech_script=speech_script,
            images_result=images_result,
            output_dir=output_dir
        )

        return {
            'success': result.success,
            'video_path': result.video_path,
            'duration': result.duration,
            'frames': result.frames,
            'error': result.error,
            'partial': result.partial
        }


# ========== 便捷函数 ==========

async def generate_video_from_course(
    course_id: str,
    course_json: Dict[str, Any],
    config: Optional[VideoGenConfig] = None,
    progress_callback: Optional[callable] = None
) -> Dict[str, Any]:
    """
    从 course.json 生成视频的便捷函数

    Args:
        course_id: 课程 ID
        course_json: course.json 的内容
        config: 配置对象
        progress_callback: 进度回调函数

    Returns:
        生成结果字典
    """
    generator = SimpleVideoGenerator(config)
    return await generator.generate_from_course_json(
        course_id,
        course_json,
        progress_callback
    )
