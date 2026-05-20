"""
课程视频生成流水线
混合模式：Tectonic LaTeX + matplotlib 图示嵌入 + TikZ 几何补充
"""
import asyncio
import json
import re
import logging
import tempfile
from pathlib import Path
from typing import Dict, List, Optional, Any
from datetime import datetime
import subprocess
import os

from shared.llm_client import LLMClient, LLMConfig, LLMRequest
from .config import VideoGenConfig
from .modules.content_processor import ContentProcessor

# ========== 统一日志配置 ==========
from .logging_config import setup_logging, get_module_logger

# 初始化统一日志系统
setup_logging(
    level=logging.INFO,
    console_level=logging.INFO,
    enable_console=True,
    enable_file=True
)

# ========== 新增：使用独立模块 ==========
from .modules.latex_generator import LaTeXGenerator, LaTeXGenerationResult
from .modules.speech_generator import SpeechGenerator, SpeechGenerationResult
from .modules.content_converter import ContentConverter
from .modules.video_synthesizer import VideoSynthesizer, VideoSynthesisResult, VideoSynthesizerConfig

# ========== 简化路径所需模块 ==========
from .modules.speech_script_generator import SpeechScriptGenerator, SpeechScriptResult
from .modules.tts_video_synthesizer import TTSVideoSynthesizer, VideoSynthesisResult
from .modules.storyboard_preprocessor import StoryboardPreprocessor, PreprocessResult
from .modules.course_to_video_mapper import CourseToVideoMapper, map_course_to_storyboard
from .modules.narration_generator import NarrationGenerator

# 模块级日志（使用统一配置）
logger = get_module_logger(__name__, "pipeline")


def natural_sort_key(text: str) -> List:
    """
    自然排序键函数
    用于正确排序文件名：slide_1.png, slide_2.png, ..., slide_10.png, slide_11.png
    而不是错误地排序为：slide_1.png, slide_10.png, slide_11.png, ..., slide_2.png

    例如：
    - "slide_1.png" → [0, "slide_", 1, ".png"]
    - "slide_10.png" → [0, "slide_", 10, ".png"]
    - "slide_2.png" → [0, "slide_", 2, ".png"]
    """
    return [int(c) if c.isdigit() else c.lower() for c in re.split(r'(\d+)', text)]


class QualityChecker:
    """内容质量检查器

    在生成LaTeX之前检查course_json的质量，减少返工
    """

    @staticmethod
    def check_course_json(course_json: Dict) -> Dict[str, Any]:
        """
        检查course.json的质量

        Returns:
            {"passed": bool, "issues": list, "score": int}
        """
        issues = []
        score = 100

        # 1. 完整性检查（要求8个章节）
        sections = course_json.get("sections", {})
        if not sections:
            issues.append("sections为空")
            score -= 30
        elif len(sections) < 8:
            issues.append(f"sections数量不足：{len(sections)}个，要求8个")
            score -= 30

        # 核心章节检查（必须有，否则直接不通过）
        core_sections = ["知识点详解", "典例精讲"]
        missing_core = [s for s in core_sections if s not in sections]
        if missing_core:
            issues.append(f"缺少核心章节: {', '.join(missing_core)}")
            score -= 50  # 扣足够分数确保不通过

        # 预期的section类型（其余章节）
        expected_sections = ["导入", "学习目标", "易错点", "随堂小测", "知识框架", "课后拓展"]
        for expected in expected_sections:
            if expected not in sections:
                # 检查相似名称
                found = False
                for actual in sections.keys():
                    if expected in actual or actual in expected:
                        found = True
                        break
                if not found:
                    issues.append(f"缺少section: {expected}")
                    score -= 5

        # 2. 内容长度检查
        for name, content in sections.items():
            if not content or len(content.strip()) < 20:
                issues.append(f"{name}内容过短（<20字）")
                score -= 10
            elif len(content) > 1000:
                issues.append(f"{name}内容过长（>1000字，建议拆分）")
                score -= 5

        # 3. 标题检查
        title = course_json.get("title", "")
        if not title or len(title) < 5:
            issues.append("标题过短或为空")
            score -= 10

        # 4. 结构检查
        if course_json.get("grade") == "" or course_json.get("chapter") == "":
            issues.append("缺少年级或章节信息")
            score -= 5

        # 判断是否通过
        passed = score >= 70 and len([i for i in issues if "内容过短" in i or "为空" in i]) == 0

        return {
            "passed": passed,
            "issues": issues,
            "score": score
        }


class CourseVideoGenerator:
    """
    课程视频生成器
    混合模式：Tectonic LaTeX + matplotlib 图示

    ⚠️ 并发使用说明：
    此类不支持并发调用。如需并发生成多个课程，请为每个任务创建新实例。
    原因：内部使用实例属性(self._last_latex_result)在步骤间传递数据，并发会导致数据覆盖。
    """


    def __init__(self, config: Optional[VideoGenConfig] = None):
        """初始化视频生成器（简化路径）"""
        self.cfg = config or VideoGenConfig()

        # 创建LLM客户端
        llm_cfg = LLMConfig(
            model=self.cfg.video.model,
            api_key=self.cfg.video.api_key,
            base_url=self.cfg.video.base_url,
            temperature=self.cfg.video.temperature,
            max_tokens=8000,
            timeout=self.cfg.video.timeout
        )
        self.llm = LLMClient(llm_cfg)

        # ========== 简化路径所需模块 ==========
        # 轻量分镜映射器（规则映射 + LLM优化）
        self.course_mapper = CourseToVideoMapper(llm_client=self.llm)

        # 语音脚本生成专家
        self.speech_generator = SpeechScriptGenerator(
            llm_client=self.llm,
            max_tokens=4000
        )

        # TTS与视频合成专家
        self.synthesizer = TTSVideoSynthesizer(
            config={
                'ffmpeg_path': self.cfg.ffmpeg_path if hasattr(self.cfg, 'ffmpeg_path') else 'ffmpeg'
            },
            output_dir=self.cfg.output_dir if hasattr(self.cfg, 'output_dir') else 'output'
        )

        # 预处理器
        self._preprocessor = None

        # 讲解文本生成器
        self.narration_generator = NarrationGenerator(llm_config=llm_cfg)

        logger.info("[CourseVideoGenerator] 初始化完成（简化路径）")
        logger.info("[CourseVideoGenerator]   - 分镜映射: CourseToVideoMapper")
        logger.info("[CourseVideoGenerator]   - 讲解生成: NarrationGenerator")
        logger.info("[CourseVideoGenerator]   - 语音生成: SpeechScriptGenerator")
        logger.info("[CourseVideoGenerator]   - 视频合成: TTSVideoSynthesizer")
        logger.info("[CourseVideoGenerator]   - 预处理: StoryboardPreprocessor")

        # ========== 内容转换模块（兼容性保留）==========
        self.content_converter = ContentConverter()

        # ========== PDF编译模块 ==========
        from .modules.pdf_compiler import PDFCompiler, PDFCompilerConfig
        pdf_config = PDFCompilerConfig(
            latex_compiler=self.cfg.latex.latex_compiler if hasattr(self.cfg, 'latex') else "xelatex",
            max_retries=2,
            timeout=120
        )
        self.pdf_compiler = PDFCompiler(pdf_config)

        # ========== 视频合成模块 ==========
        import importlib
        audio_utils_module = importlib.import_module('.audio_utils', package='teacher.video_pipeline')
        video_config = VideoSynthesizerConfig(
            ffmpeg_path=self.cfg.ffmpeg_path if hasattr(self.cfg, 'ffmpeg_path') else "ffmpeg",
            ffprobe_path=self.cfg.ffprobe_path if hasattr(self.cfg, 'ffprobe_path') else "ffprobe",
            transition=self.cfg.transition if hasattr(self.cfg, 'transition') else 1.0
        )
        self.video_synthesizer = VideoSynthesizer(
            tts_config=self.cfg.tts,
            video_config=video_config,
            audio_utils_module=audio_utils_module
        )

        # ========== LaTeX生成结果缓存（用于语音生成阶段的页数同步） ==========
        self._last_latex_result = None

        logger.info("[CourseVideoGenerator] 五阶段专家初始化完成")
        logger.info("[CourseVideoGenerator]   - 阶段0: IntelligentDifficultyJudge")
        logger.info("[CourseVideoGenerator]   - 阶段1: ContentUnderstandingExpert")
        logger.info("[CourseVideoGenerator]   - 阶段2A: StoryboardDesigner")
        logger.info("[CourseVideoGenerator]   - 阶段2B: FormatConverter")
        logger.info("[CourseVideoGenerator]   - 阶段3: SpeechScriptGenerator")
        logger.info("[CourseVideoGenerator]   - 阶段4: TTSVideoSynthesizer")
        logger.info("[CourseVideoGenerator]   - 轻量分镜映射器: CourseToVideoMapper (简化路径)")
        logger.info("[CourseVideoGenerator] 只保留简化路径：从 course.json 生成视频")

    async def generate_from_course_json(
        self,
        course_id: str,
        course_json: Dict[str, Any],
        progress_callback: Optional[callable] = None,
        existing_diagrams: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        简化路径: 从 course.json 直接生成视频（无图示模式）

        流程: 轻量分镜映射 → LaTeX → PDF → TTS → 合成

        Args:
            course_id: 课程ID
            course_json: course.json 的内容
            progress_callback: 进度回调函数
            existing_diagrams: 已保留（兼容性，实际不使用）

        Returns:
            生成结果字典
        """
        logger.info(f"[简化路径] ========== 从 course.json 生成视频 ==========")
        logger.info(f"[简化路径] 课程ID: {course_id}")
        logger.info(f"[简化路径] 课程标题: {course_json.get('title', 'N/A')}")

        result = {
            "success": False,
            "course_id": course_id,
            "outputs": {},
            "mode": "lightweight"  # 标记为简化路径
        }

        try:
            # 准备输出目录
            output_dir = Path(self.cfg.get_output_dir(course_id))
            temp_dir = Path(self.cfg.get_temp_dir(course_id))
            temp_dir.mkdir(parents=True, exist_ok=True)

            logger.info(f"[简化路径] 输出目录: {output_dir}")
            logger.info(f"[简化路径] 临时目录: {temp_dir}")

            # ========== 前置质量检查 ==========
            logger.info(f"[质量检查] 开始检查course.json质量...")
            quality_check = QualityChecker.check_course_json(course_json)

            if not quality_check["passed"]:
                logger.warning(f"[质量检查] 质量检查未通过: {quality_check['issues']}")
                logger.warning(f"[质量检查] 质量分数: {quality_check['score']}/100")
                # 仍然继续，但记录警告
            else:
                logger.info(f"[质量检查] ✓ 质量检查通过，分数: {quality_check['score']}/100")

            # ========== 步骤1: 分镜生成（混合模式） ==========
            if progress_callback:
                progress_callback(10, "正在生成分镜...")

            logger.info(f"[简化路径] 步骤1: 分镜生成（混合模式：规则映射 + LLM优化）")

            # 使用混合模式生成（内部自动选择最佳方式）
            storyboard = await self.course_mapper.map_to_storyboard(
                course_json=course_json,
                progress_callback=lambda p, m: progress_callback(10 + int(p * 0.15), m)  # 10-25%
            )

            # 保存分镜
            storyboard_path = output_dir / "storyboard.json"
            with open(storyboard_path, 'w', encoding='utf-8') as f:
                json.dump(storyboard, f, ensure_ascii=False, indent=2)

            logger.info(f"[简化路径] 分镜已保存: {storyboard_path}")
            logger.info(f"[简化路径]   - 总帧数: {storyboard['totalSlides']}")
            logger.info(f"[简化路径]   - 预计时长: {storyboard['estimatedDuration']}")

            if progress_callback:
                progress_callback(25, "分镜生成完成...")

            # ========== 步骤1.5: 预处理分镜数据（减轻LLM压力） ==========
            if progress_callback:
                progress_callback(30, "预处理分镜数据...")

            logger.info(f"[简化路径] 步骤1.5: 预处理分镜数据")

            if not hasattr(self, '_preprocessor') or self._preprocessor is None:
                self._preprocessor = StoryboardPreprocessor()

            preprocess_result = await self._preprocessor.preprocess(
                storyboard,
                target_batch_size=2  # 建议批次大小为2
            )

            if not preprocess_result.success:
                logger.warning(f"[预处理] 预处理失败，将使用原始分镜数据: {preprocess_result.warnings}")
            else:
                logger.info(f"[预处理] 完成: 处理{len(preprocess_result.preprocessed_scenes)}个场景")
                logger.info(f"[预处理] 建议批次大小: {preprocess_result.batch_suggestion}")
                # 将预处理结果附加到storyboard，供LaTeX生成器使用
                storyboard['_preprocessed'] = {
                    'scenes': [
                        {
                            'sceneID': s.scene_id,
                            'frameTitle': s.frame_title,  # 清理后的标题（不含分页标记）
                            'contentBlocks': s.content_blocks,
                            'suggestedEnvironments': s.suggested_environments,
                            'estimatedHeight': s.estimated_height,
                            'needsMathMode': s.needs_math_mode,
                        }
                        for s in preprocess_result.preprocessed_scenes
                    ],
                    'batchSuggestion': preprocess_result.batch_suggestion,
                    'hints': self._preprocessor.get_latex_generation_hints()
                }

            if progress_callback:
                progress_callback(35, "预处理完成...")

            # ========== 步骤2: 讲解文本生成 ==========
            if progress_callback:
                progress_callback(37, "正在生成讲解文本...")

            logger.info(f"[简化路径] 步骤2: 讲解文本生成（口语化转换）")

            scenes = storyboard.get("scenes", [])
            narration_success_count = 0
            narration_fail_count = 0

            # 过滤出需要处理的场景（narration非空且长度>=5）
            scenes_to_process = []
            for idx, scene in enumerate(scenes):
                narration = scene.get("narration", "")
                if narration and len(narration.strip()) >= 5:
                    scenes_to_process.append((idx, scene))
                else:
                    scene_id = scene.get("sceneID", f"s{idx+1}")
                    logger.debug(f"[讲解生成] 场景 {scene_id}: narration为空或过短，跳过")

            # 批量处理，batch_size=5
            batch_size = 5
            for i in range(0, len(scenes_to_process), batch_size):
                batch = scenes_to_process[i:i + batch_size]

                tasks = [
                    self.narration_generator.generate_narration(
                        frame_id=scene.get("sceneID", f"s{idx+1}"),
                        title=scene.get("frameTitle", ""),
                        content=scene.get("narration", ""),
                        frame_type=scene.get("slideType", "concept")
                    )
                    for idx, scene in batch
                ]

                try:
                    batch_results = await asyncio.gather(*tasks, return_exceptions=True)

                    for (idx, scene), result in zip(batch, batch_results):
                        scene_id = scene.get("sceneID", f"s{idx+1}")

                        if isinstance(result, Exception):
                            narration_fail_count += 1
                            logger.warning(f"[讲解生成] 场景 {scene_id}: 异常 {result}，保留原始narration")
                        elif result.success and result.narration:
                            scene["narration"] = result.narration
                            narration_success_count += 1
                            logger.debug(f"[讲解生成] 场景 {scene_id}: 口语化成功")
                        else:
                            narration_fail_count += 1
                            logger.warning(f"[讲解生成] 场景 {scene_id}: 生成失败，保留原始narration")

                except Exception as e:
                    for idx, scene in batch:
                        narration_fail_count += 1
                    logger.warning(f"[讲解生成] 批次异常 {e}，保留原始narration")

                # 批次间延迟，避免API限流
                if i + batch_size < len(scenes_to_process):
                    await asyncio.sleep(1.0)

            logger.info(f"[讲解生成] 完成: 成功{narration_success_count}个, 失败{narration_fail_count}个(已降级)")

            if progress_callback:
                progress_callback(40, "讲解文本生成完成...")

            # ========== 步骤3: LaTeX生成（无图示） ==========
            if progress_callback:
                progress_callback(45, "正在生成LaTeX...")

            logger.info(f"[简化路径] 步骤3: LaTeX生成（无图示模式）")
            # 使用LLM直通方法
            latex_content = await self._generate_latex_with_llm(storyboard, None)

            # 保存LaTeX文件
            tex_path = temp_dir / "lesson.tex"
            with open(tex_path, 'w', encoding='utf-8') as f:
                f.write(latex_content)

            logger.info(f"[简化路径] LaTeX已保存: {tex_path}")

            if progress_callback:
                progress_callback(55, "LaTeX生成完成...")

            # ========== 步骤4: PDF渲染 ==========
            if progress_callback:
                progress_callback(60, "正在渲染PDF...")

            logger.info(f"[简化路径] 步骤4: PDF渲染")

            # 编译LaTeX为PDF（使用智能重试）
            pdf_result = await self._compile_latex_with_retry(tex_path, temp_dir, max_retries=3)

            if not pdf_result.get("success"):
                raise Exception(f"PDF编译失败: {pdf_result.get('error')}")

            pdf_path = pdf_result["pdf_path"]

            # 验证PDF是否真的从当前tex生成（通过检查文件时间）
            import os
            tex_mtime = os.path.getmtime(tex_path)
            pdf_mtime = os.path.getmtime(pdf_path)

            if pdf_mtime < tex_mtime:
                logger.warning(f"[PDF验证] PDF文件({pdf_mtime})早于tex文件({tex_mtime})，可能使用了错误的源文件")
                # 重新生成PDF（使用智能重试）
                pdf_result = await self._compile_latex_with_retry(tex_path, temp_dir, max_retries=2)
                pdf_path = pdf_result["pdf_path"]
            logger.info(f"[简化路径] PDF已生成: {pdf_path}")

            # 提取关键帧
            images_dir = output_dir / "images"
            images_dir.mkdir(exist_ok=True)

            images_result = await self._generate_images(str(pdf_path), output_dir)

            if not images_result.get("success"):
                raise Exception(f"提取关键帧失败: {images_result.get('error')}")

            logger.info(f"[简化路径] 关键帧已提取: {images_result.get('count', 0)}帧")

            # ========== 检测页数不匹配 ==========
            actual_image_count = images_result.get('count', 0)
            storyboard_scene_count = storyboard.get('totalSlides', 0)

            logger.info(f"[页数检测] Storyboard场景: {storyboard_scene_count}, PDF实际页数: {actual_image_count}")

            if actual_image_count > storyboard_scene_count:
                logger.warning(f"[页数检测] PDF页数({actual_image_count}) > Storyboard场景数({storyboard_scene_count})")
                logger.warning(f"[页数检测] 需要扩展语音脚本以匹配实际页数")

            if progress_callback:
                progress_callback(75, "PDF渲染完成...")

            # ========== 步骤5: 语音脚本生成 ==========
            if progress_callback:
                progress_callback(80, "正在生成语音脚本...")

            logger.info(f"[简化路径] 步骤5: 语音脚本生成")

            # ========== 新策略：优先使用frame_mappings ==========
            frame_mappings = None
            if hasattr(self, '_last_latex_result') and self._last_latex_result:
                frame_mappings = self._last_latex_result.frame_mappings

            if frame_mappings and len(frame_mappings) > 0:
                logger.info(f"[语音生成] 使用frame_mappings生成语音: {len(frame_mappings)}个frame")
                speech_script = self._generate_speech_from_frame_mappings(frame_mappings)

                # 验证语音数量与PDF页数是否匹配
                speech_count = len(speech_script.get('scenes', []))
                if speech_count == actual_image_count:
                    logger.info(f"[语音生成] ✓ 语音数量与PDF页数完全匹配: {speech_count}帧")
                else:
                    logger.warning(f"[语音生成] ⚠ 语音数量({speech_count})与PDF页数({actual_image_count})不匹配，需要调整")
                    # 这里可以添加扩展逻辑，但理想情况下应该是匹配的
            else:
                logger.info(f"[语音生成] 未找到frame_mappings，使用storyboard生成语音")
                # 回退到原来的方式
                speech_script = self._generate_speech_from_storyboard(storyboard)

                # ========== 扩展语音脚本以匹配实际PDF页数 ==========
                speech_script = self._expand_speech_to_match_images(
                    speech_script,
                    storyboard,
                    actual_image_count
                )

            logger.info(f"[语音生成] 语音脚本已生成: {len(speech_script.get('scenes', []))}个场景")

            # 保存语音脚本
            speech_path = output_dir / "speech.json"
            with open(speech_path, 'w', encoding='utf-8') as f:
                json.dump(speech_script, f, ensure_ascii=False, indent=2)

            logger.info(f"[简化路径] 语音脚本已保存: {speech_path}")

            # ========== 步骤6: TTS与视频合成 ==========
            if progress_callback:
                progress_callback(90, "准备TTS与视频合成...")

            logger.info(f"[简化路径] 步骤6: TTS与视频合成")

            # 5.1 TTS预检（新增）
            logger.info(f"[简化路径] 步骤6.1: TTS服务预检")
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
                logger.error(f"[简化路径] TTS服务不可用: {tts_check['error']}")
                raise Exception(f"TTS服务不可用: {tts_check['error']}")

            print(f"[简化路径] ✓ TTS 服务预检通过")

            video_result = await self._generate_video(
                speech_script=speech_script,
                images_result=images_result,
                output_dir=output_dir
            )

            if not video_result.get("success"):
                raise Exception(f"视频合成失败: {video_result.get('error')}")

            logger.info(f"[简化路径] 视频已生成: {video_result.get('video_path')}")

            # ========== 完成 ==========
            result["success"] = True
            result["video_path"] = str(video_result.get("video_path"))
            result["outputs"]["video"] = str(video_result.get("video_path"))
            result["outputs"]["storyboard"] = str(storyboard_path)
            result["outputs"]["speech"] = str(speech_path)
            result["outputs"]["pdf"] = str(pdf_path)
            result["duration"] = video_result.get("duration")
            result["total_frames"] = storyboard["totalSlides"]

            logger.info(f"[简化路径] ========== 生成完成 ==========")
            logger.info(f"[简化路径]   - 视频路径: {result['video_path']}")
            logger.info(f"[简化路径]   - 总帧数: {result['total_frames']}")
            logger.info(f"[简化路径]   - 时长: {result.get('duration', 'N/A')}")

            if progress_callback:
                progress_callback(100, "生成完成!")

        except Exception as e:
            logger.error(f"[简化路径] 生成失败: {e}")
            import traceback
            logger.error(traceback.format_exc())

            result["error"] = str(e)
            result["traceback"] = traceback.format_exc()

            if progress_callback:
                progress_callback(0, f"生成失败: {str(e)}")

        return result

    def _generate_speech_from_storyboard(self, storyboard: Dict) -> Dict:
        """
        从分镜生成语音脚本（简化模式）

        直接使用分镜中的 narration，无需LLM处理
        """
        scenes = storyboard.get("scenes", [])
        speech_scenes = []

        logger.info(f"[SpeechGen] 输入: {len(scenes)}个场景")
        print(f"[SpeechGen] 输入: {len(scenes)}个场景")

        for i, scene in enumerate(scenes, 1):
            narration = scene.get("narration", "")
            frame_id = scene.get("sceneID", f"s{i}")

            # 调试输出：显示从storyboard提取的旁白内容
            logger.info(f"[SpeechGen] 场景 {frame_id}: narration长度={len(narration)}, 内容={narration[:50] if narration else '(空)'}")
            print(f"[SpeechGen] 场景 {frame_id}: narration长度={len(narration)}, 内容={narration[:50] if narration else '(空)'}")

            # 估算时长 (按180字/分钟计算)
            duration = max(2, len(narration) / 3)  # 至少2秒

            speech_scenes.append({
                "frame_id": frame_id,
                "scene_index": i,
                "text": narration,
                "duration": duration
            })

        result = {
            "total_scenes": len(speech_scenes),
            "total_duration": sum(s["duration"] for s in speech_scenes),
            "scenes": speech_scenes
        }

        logger.info(f"[SpeechGen] 输出: {len(speech_scenes)}个场景, 总时长={result['total_duration']:.1f}秒")
        print(f"[SpeechGen] 输出: {len(speech_scenes)}个场景, 总时长={result['total_duration']:.1f}秒")

        return result

    def _generate_speech_from_frame_mappings(self, frame_mappings: List) -> Dict:
        """
        从frame_mappings生成语音脚本（新方法）

        使用专门分页模块生成的frame_mappings，确保每个分页后的frame都有对应的语音。

        Args:
            frame_mappings: FrameMapping对象列表，包含每个frame的完整信息

        Returns:
            语音脚本字典，格式与_generate_speech_from_storyboard相同
        """
        from .modules.pagination_types import FrameMapping

        speech_scenes = []

        logger.info(f"[SpeechGen-FrameMapping] 输入: {len(frame_mappings)}个frame映射")
        print(f"[SpeechGen-FrameMapping] 输入: {len(frame_mappings)}个frame映射")

        for i, mapping in enumerate(frame_mappings):
            # 优先使用content_summary，如果太短则从full_content提取
            summary = mapping.content_summary
            original_title = mapping.original_title

            # 如果摘要信息不足（少于50字），从full_content提取更详细内容
            if len(summary) < 50:
                # 从LaTeX内容中提取纯文本
                extracted_text = self._extract_text_from_latex(mapping.full_content)
                if extracted_text:
                    text = f"{original_title}。{extracted_text}"
                else:
                    text = f"{original_title}。{summary}"
            else:
                text = f"{original_title}。{summary}"

            # 构建frame_id：使用original_scene_id和frame_num
            frame_id = f"{mapping.original_scene_id}_f{mapping.frame_num}"

            # 估算时长
            duration = max(2, len(text) / 3)  # 至少2秒

            speech_scenes.append({
                "frame_id": frame_id,
                "scene_index": i,
                "text": text,
                "duration": duration,
                "frame_title": mapping.frame_title,
                "original_scene_id": mapping.original_scene_id,
                "frame_num": mapping.frame_num,
                "total_frames": mapping.total_frames
            })

            logger.info(f"[SpeechGen-FrameMapping] Frame {i+1}: {mapping.frame_title}")
            logger.info(f"[SpeechGen-FrameMapping]   → 语音: {text[:50]}...")
            print(f"[SpeechGen-FrameMapping] Frame {i+1}: {mapping.frame_title} → {text[:50]}...")

        result = {
            "total_scenes": len(speech_scenes),
            "total_duration": sum(s["duration"] for s in speech_scenes),
            "scenes": speech_scenes,
            "source": "frame_mappings"  # 标记来源
        }

        logger.info(f"[SpeechGen-FrameMapping] 输出: {len(speech_scenes)}个场景, 总时长={result['total_duration']:.1f}秒")
        print(f"[SpeechGen-FrameMapping] 输出: {len(speech_scenes)}个场景, 总时长={result['total_duration']:.1f}秒")

        return result

    def _extract_text_from_latex(self, latex_content: str) -> str:
        """
        从LaTeX内容中提取纯文本，用于语音生成

        Args:
            latex_content: LaTeX代码字符串

        Returns:
            提取的纯文本
        """
        import re

        if not latex_content:
            return ""

        # 移除LaTeX命令和结构
        text = latex_content

        # 移除frame结构
        text = re.sub(r'\\begin\{frame\}(\[[^\]]*\])?\{[^\}]*\}', '', text)
        text = re.sub(r'\\end\{frame\}', '', text)
        text = re.sub(r'\\frametitle\{[^\}]*\}', '', text)
        text = re.sub(r'\\framesubtitle\{[^\}]*\}', '', text)

        # 移除itemize/enumerate环境标记，保留内容
        text = re.sub(r'\\begin\{itemize\}', '', text)
        text = re.sub(r'\\end\{itemize\}', '', text)
        text = re.sub(r'\\begin\{enumerate\}', '', text)
        text = re.sub(r'\\end\{enumerate\}', '', text)

        # 移除嵌套itemize/enumerate
        text = re.sub(r'\\begin\{itemize\}', '', text)
        text = re.sub(r'\\end\{itemize\}', '', text)

        # 处理\item - 移除命令但保留分隔
        text = re.sub(r'\\item\s*', '。', text)

        # 移除文本格式命令（但保留内容）
        text = re.sub(r'\\textbf\{([^}]*)\}', r'\1', text)
        text = re.sub(r'\\textit\{([^}]*)\}', r'\1', text)
        text = re.sub(r'\\emph\{([^}]*)\}', r'\1', text)
        text = re.sub(r'\\underline\{([^}]*)\}', r'\1', text)

        # 移除数学模式中的命令，保留简单内容
        # 处理 $...$ 中的简单内容
        def simplify_math(match):
            math_content = match.group(1)
            # 移除常见的LaTeX数学命令
            math_content = re.sub(r'\\[a-zA-Z]+', '', math_content)
            # 只保留数字、基本运算符和简单分数
            if re.match(r'^[\d\s+\-*/().<>=,]+$', math_content):
                return math_content.strip()
            return ''  # 复杂数学表达式不读

        text = re.sub(r'\$([^$]+)\$', simplify_math, text)

        # 移除剩余的LaTeX命令
        text = re.sub(r'\\[a-zA-Z]+', '', text)

        # 移除花括号（用于命令分组）
        text = re.sub(r'\{|\}', '', text)

        # 处理特殊字符
        text = text.replace('\\$', '元')
        text = text.replace('\\%', '百分之')
        text = text.replace('&', '、')

        # 移除过多的空白
        text = re.sub(r'\s+', ' ', text)

        # 移除LaTeX注释
        text = re.sub(r'%.*$', '', text, flags=re.MULTILINE)

        # 清理首尾
        text = text.strip()
        # 移除开头的句号
        if text.startswith('。'):
            text = text[1:].strip()

        # 限制长度（避免语音过长）
        if len(text) > 200:
            text = text[:200].rsplit('。', 1)[0] + '。'

        return text

    def _expand_speech_to_match_images(
        self,
        speech_script: Dict,
        storyboard: Dict,
        actual_image_count: int
    ) -> Dict:
        """
        扩展语音脚本以匹配实际PDF页数

        当LaTeX自动分页导致PDF页数多于storyboard场景数时，
        需要为额外的页面生成对应的语音脚本。

        策略：将长场景的narration拆分到多个子页面
        """
        storyboard_scenes = storyboard.get("scenes", [])
        speech_scenes = speech_script.get("scenes", [])
        current_scene_count = len(speech_scenes)

        if actual_image_count <= current_scene_count:
            logger.info(f"[页数同步] 页数匹配，无需扩展")
            return speech_script

        logger.info(f"[页数同步] 开始扩展语音脚本: {current_scene_count} → {actual_image_count}")
        logger.warning(f"[页数同步] 注意：额外页面将复用原场景的narration")

        # 计算需要扩展的页数
        extra_pages_needed = actual_image_count - current_scene_count

        # 分析哪些场景可能被分页（内容长度超过一定阈值）
        long_scenes = []
        for scene in storyboard_scenes:
            scene_id = scene.get("sceneID", "")
            content = scene.get("mainContent", "")
            narration = scene.get("narration", "")

            content_length = len(content)
            # 长内容场景：concept类型超过500字，或practice类型超过800字
            is_long = (
                (scene.get("slideType") == "concept" and content_length > 500) or
                (scene.get("slideType") == "practice" and content_length > 800) or
                (scene.get("slideType") == "example" and content_length > 600)
            )

            if is_long:
                long_scenes.append({
                    "scene_id": scene_id,
                    "content_length": content_length,
                    "narration": narration,
                    "slide_type": scene.get("slideType", "")
                })

        logger.info(f"[页数同步] 检测到 {len(long_scenes)} 个长场景可能需要分页")

        # 扩展speech_scenes
        expanded_scenes = list(speech_scenes)
        scene_index = current_scene_count

        for long_scene in long_scenes:
            # 根据内容长度估算需要拆分成几页
            content_length = long_scene["content_length"]
            if long_scene["slide_type"] == "concept":
                # concept类型：每500字一页
                pages_from_this_scene = min(
                    content_length // 500,
                    extra_pages_needed - (scene_index - current_scene_count)
                )
            elif long_scene["slide_type"] == "practice":
                # practice类型：每3道题一页（约800字）
                pages_from_this_scene = min(
                    content_length // 800,
                    extra_pages_needed - (scene_index - current_scene_count)
                )
            else:
                # 其他类型：每600字一页
                pages_from_this_scene = min(
                    content_length // 600,
                    extra_pages_needed - (scene_index - current_scene_count)
                )

            pages_from_this_scene = max(1, pages_from_this_scene)

            # 为这个长场景创建子页面
            base_scene_id = long_scene["scene_id"]
            base_narration = long_scene["narration"]

            for i in range(1, pages_from_this_scene + 1):
                if scene_index >= actual_image_count:
                    break

                # 创建子场景ID（如s4a, s4b, s4c）
                if len(base_scene_id) == 2:
                    sub_id = chr(96 + i)  # a, b, c...
                    new_scene_id = f"{base_scene_id}{sub_id}"
                else:
                    new_scene_id = f"{base_scene_id}_{i}"

                # 使用原narration（可以添加"续"提示）
                if i == 1:
                    narration_text = base_narration
                else:
                    narration_text = f"{base_narration}（续）"

                # 估算时长
                duration = max(2, len(narration_text) / 3)

                expanded_scenes.append({
                    "frame_id": new_scene_id,
                    "scene_index": scene_index + 1,
                    "text": narration_text,
                    "duration": duration
                })

                logger.info(f"[页数同步] 新增场景: {new_scene_id} (基于{base_scene_id})")
                scene_index += 1

        # 如果还不够，用最后一个场景的narration填充
        while scene_index < actual_image_count:
            last_scene = speech_scenes[-1] if speech_scenes else expanded_scenes[-1]
            new_scene_id = f"{last_scene['frame_id']}_续"

            expanded_scenes.append({
                "frame_id": new_scene_id,
                "scene_index": scene_index + 1,
                "text": last_scene["text"],
                "duration": last_scene["duration"]
            })

            logger.info(f"[页数同步] 填充场景: {new_scene_id}")
            scene_index += 1

        # 更新结果
        result = {
            "total_scenes": len(expanded_scenes),
            "total_duration": sum(s["duration"] for s in expanded_scenes),
            "scenes": expanded_scenes
        }

        logger.info(f"[页数同步] ✓ 扩展完成: {current_scene_count} → {len(expanded_scenes)} 个场景")
        print(f"[页数同步] ✓ 语音脚本已扩展为 {len(expanded_scenes)} 个场景")

        return result

    # ========== LaTeX 生成相关方法 ==========

    async def _generate_latex_with_llm(
        self,
        storyboard: Dict[str, Any],
        diagrams_dir: Path = None
    ) -> str:
        """
        使用独立的LaTeXGenerator模块生成LaTeX

        优势：
        1. 使用独立的模块，避免代码重复
        2. 统一的LaTeX生成逻辑
        3. 更容易维护和测试

        副作用：
        - 将LaTeXGenerationResult存储在self._last_latex_result中，供speech生成使用
        """
        logger.info(f"[主流程] ========== 使用独立LaTeXGenerator模块 ==========")
        logger.info(f"[主流程] 课程: {storyboard.get('title', '课程')}")
        logger.info(f"[主流程] 场景数: {len(storyboard.get('scenes', []))}")

        # 使用独立的LaTeXGenerator
        generator = LaTeXGenerator(self.llm)

        # 调用独立模块的generate方法
        result: LaTeXGenerationResult = await generator.generate(storyboard, diagrams_dir)

        if result.success:
            logger.info(f"[主流程] ✓ LaTeX生成成功")
            logger.info(f"[主流程] 期望帧数: {result.expected_frames}, 实际帧数: {result.actual_frames}")
            logger.info(f"[主流程] 违约记录: {len(result.violations)}条")
            logger.info(f"[主流程] 警告信息: {len(result.warnings)}条")

            # 新增：记录frame_mappings信息
            if result.frame_mappings:
                logger.info(f"[主流程] frame_mappings: {len(result.frame_mappings)}个frame映射")
                for i, mapping in enumerate(result.frame_mappings[:5]):  # 只显示前5个
                    logger.info(f"[主流程]   frame {i+1}: {mapping.frame_title} -> {mapping.content_summary[:30]}...")

            # 存储结果供speech生成使用（实现页数同步）
            self._last_latex_result = result
            logger.info(f"[主流程] LaTeX结果已存储，供speech生成使用")

            logger.info(f"[主流程] ========== LaTeXGenerator调用完成 ==========")
            return result.tex_content
        else:
            logger.error(f"[主流程] ✗ LaTeX生成失败: {result.error}")
            raise Exception(f"LaTeX生成失败: {result.error}")

    async def _compile_latex_with_retry(
        self,
        tex_path: Path,
        temp_dir: Path,
        max_retries: int = 3
    ) -> Dict[str, Any]:
        """
        带智能重试的LaTeX编译

        使用 PDFCompiler 模块进行编译

        Args:
            tex_path: LaTeX文件路径
            temp_dir: 临时目录
            max_retries: 最大重试次数

        Returns:
            编译结果字典
        """
        # 使用 PDFCompiler 模块
        result = await self.pdf_compiler.compile_with_retry(
            tex_path=tex_path,
            temp_dir=temp_dir,
            max_retries=max_retries
        )

        # 转换为字典格式以保持向后兼容
        return {
            'success': result.success,
            'pdf_path': str(result.pdf_path) if result.pdf_path else None,
            'error': result.error,
            'stderr': result.stderr,
            'stdout': result.stdout
        }


    async def _generate_images(
        self,
        pdf_path: Optional[str],
        output_dir: Path
    ) -> Dict[str, Any]:
        """PDF转PNG图片"""
        images_dir = output_dir / "images"
        images_dir.mkdir(exist_ok=True)

        logger.info(f"[PDF转PNG] 开始转换图片")
        logger.debug(f"[PDF转PNG] PDF路径: {pdf_path}")
        logger.debug(f"[PDF转PNG] 输出目录: {images_dir}")

        if not pdf_path or not Path(pdf_path).exists():
            logger.error(f"[PDF转PNG] ✗ PDF文件不存在: {pdf_path}")
            return {
                "success": False,
                "error": "PDF文件不存在",
                "count": 0,
                "dir": str(images_dir)
            }

        try:
            from pdf2image import convert_from_path
            logger.info(f"[PDF转PNG] pdf2image已导入，DPI: {self.cfg.latex.dpi}")

            # 转换PDF为图片
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

            logger.info(f"[PDF转PNG] ✓ 成功生成 {len(image_paths)} 张图片")
            for path in image_paths:
                logger.debug(f"[PDF转PNG]   - {Path(path).name}")

            return {
                "success": True,
                "count": len(image_paths),
                "dir": str(images_dir),
                "images": image_paths
            }

        except ImportError:
            logger.error(f"[PDF转PNG] ✗ pdf2image未安装")
            return {
                "success": False,
                "error": "pdf2image未安装，请运行: pip install pdf2image",
                "count": 0,
                "dir": str(images_dir)
            }
        except Exception as e:
            logger.error(f"[PDF转PNG] ✗ 转换异常: {str(e)}")
            import traceback
            logger.debug(f"[PDF转PNG] 异常堆栈:\n{traceback.format_exc()}")
            return {
                "success": False,
                "error": f"PDF转换失败: {str(e)}",
                "count": 0,
                "dir": str(images_dir)
            }

    async def _generate_speech(self, storyboard: Dict[str, Any]) -> Dict[str, Any]:
        """
        生成语音脚本（使用独立的SpeechGenerator模块）

        优势：
        1. 使用独立的模块，避免代码重复
        2. 支持与LaTeX帧数的页数同步
        3. 统一的语音生成逻辑
        4. 更容易维护和测试
        """
        title = storyboard.get("title", "课程")
        scenes = storyboard.get("scenes", [])

        logger.info(f"[主流程] ========== 使用独立SpeechGenerator模块 ==========")
        logger.info(f"[主流程] 课程: {title}")
        logger.info(f"[主流程] 场景数: {len(scenes)}")

        # 检查是否有LaTeX生成结果可用
        latex_result = getattr(self, '_last_latex_result', None)

        if latex_result:
            # 使用独立的SpeechGenerator，支持页数同步
            logger.info(f"[主流程] LaTeX结果可用，实现页数同步")
            logger.info(f"[主流程] LaTeX实际帧数: {latex_result.actual_frames}")

            generator = SpeechGenerator(self.llm)

            try:
                result: SpeechGenerationResult = await generator.generate(storyboard, latex_result)

                if result.success:
                    logger.info(f"[主流程] ✓ 语音生成成功")
                    logger.info(f"[主流程] 总场景数: {result.total_scenes}")
                    logger.info(f"[主流程] 警告信息: {len(result.warnings)}条")
                    logger.info(f"[主流程] ========== SpeechGenerator调用完成 ==========")
                    return result.script_data
                else:
                    logger.error(f"[主流程] ✗ 语音生成失败: {result.error}")
                    # 如果失败是因为帧数收缩问题，尝试回退方案
                    logger.info(f"[主流程] 尝试回退到原有方法...")
                    return await self._generate_speech_fallback(storyboard)

            except Exception as e:
                logger.error(f"[主流程] SpeechGenerator调用失败: {str(e)}")
                logger.info(f"[主流程] 尝试回退到原有方法...")
                return await self._generate_speech_fallback(storyboard)
        else:
            # 没有LaTeX结果，使用回退方法
            logger.warning(f"[主流程] LaTeX结果不可用，使用回退方法（无页数同步）")
            return await self._generate_speech_fallback(storyboard)

    async def _generate_video(
        self,
        speech_script: Dict[str, Any],
        images_result: Dict[str, Any],
        output_dir: Path
    ) -> Dict[str, Any]:
        """
        生成最终视频（使用 VideoSynthesizer 模块）

        Args:
            speech_script: 语音脚本（包含scenes列表）
            images_result: 图片生成结果
            output_dir: 输出目录

        Returns:
            视频生成结果字典
        """
        # 使用 VideoSynthesizer 模块
        result = await self.video_synthesizer.generate_video(
            speech_script=speech_script,
            images_result=images_result,
            output_dir=output_dir
        )

        # 转换为字典格式以保持向后兼容
        return {
            'success': result.success,
            'video_path': result.video_path,
            'duration': result.duration,
            'frames': result.frames,
            'error': result.error,
            'partial': result.partial
        }



