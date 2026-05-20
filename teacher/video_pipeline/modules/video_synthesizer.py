"""
视频合成器模块

职责：
1. 视频片段合成（图片+音频+SRT字幕）
2. 最终视频合并（FFmpeg concat）
3. SRT字幕生成
4. FFmpeg/FFprobe工具检测

设计原则：
- 使用audio_utils模块提供的TTS功能
- 完整的FFmpeg视频处理流程
- 支持字幕、转场等高级功能
"""

import asyncio
import logging
import os
import subprocess
import sys
from pathlib import Path
from typing import Dict, List, Optional, Any
from dataclasses import dataclass

# 使用统一的日志配置
from ..logging_config import get_module_logger
logger = get_module_logger(__name__, "video_synthesizer")


# ==================== 自然排序键 ====================
def natural_sort_key(s: str) -> Any:
    """
    自然排序键函数，用于文件名排序
    例如: slide_2.png < slide_10.png
    """
    import re
    return [int(text) if text.isdigit() else text.lower()
            for text in re.split(r'(\d+)', s)]


# ==================== 配置数据类 ====================
@dataclass
class VideoSynthesizerConfig:
    """视频合成器配置"""
    ffmpeg_path: str = "ffmpeg"
    ffprobe_path: str = "ffprobe"
    transition: float = 1.0  # 转场时长（秒）


@dataclass
class VideoSynthesisResult:
    """视频合成结果"""
    success: bool
    video_path: Optional[str] = None
    duration: Optional[float] = None
    frames: Optional[int] = None
    error: Optional[str] = None
    partial: bool = False


# ==================== 主合成器类 ====================
class VideoSynthesizer:
    """
    视频合成器

    功能：
    - TTS音频生成（使用audio_utils）
    - 视频片段合成（图片+音频+SRT字幕）
    - 最终视频合并
    - FFmpeg/FFprobe工具检测
    """

    def __init__(
        self,
        tts_config: Any,  # TTSConfig from config.py
        video_config: Any,  # VideoSynthesizerConfig
        audio_utils_module: Any  # audio_utils module
    ):
        """
        初始化合成器

        Args:
            tts_config: TTS配置对象（包含app_key, access_token等）
            video_config: 视频合成配置
            audio_utils_module: audio_utils模块（用于TTS功能）
        """
        self.tts_config = tts_config
        self.video_config = video_config
        self.audio_utils = audio_utils_module
        logger.info("[VideoSynthesizer] 初始化完成")

    # ==================== 主入口方法 ====================

    async def generate_video(
        self,
        speech_script: Dict[str, Any],
        images_result: Dict[str, Any],
        output_dir: Path
    ) -> VideoSynthesisResult:
        """
        生成最终视频（三阶段合成方式，支持SRT字幕）

        Args:
            speech_script: 语音脚本（包含scenes列表）
            images_result: 图片生成结果
            output_dir: 输出目录

        Returns:
            视频合成结果
        """
        from ..audio_utils import TTSGenerator, get_audio_duration

        logger.info("[VIDEO_GEN] _generate_video 方法被调用")

        # 确保video子目录存在
        video_dir = output_dir / "video"
        video_dir.mkdir(exist_ok=True)

        video_path = video_dir / "course_video.mp4"
        scenes = speech_script.get("scenes", [])

        logger.info(f"[VIDEO_GEN] 输入: {len(scenes)}个场景")

        if not scenes:
            return VideoSynthesisResult(
                success=False,
                error="没有场景数据",
                video_path=str(video_path)
            )

        # 检查TTS配置
        if not self._is_tts_config_valid():
            logger.warning("TTS 配置验证失败")
            return VideoSynthesisResult(
                success=False,
                partial=True,
                error="TTS 配置不完整，跳过语音合成",
                video_path=str(video_path)
            )

        # 检查FFmpeg
        ffmpeg_result = await self._detect_ffmpeg_tools()
        if not ffmpeg_result["ffmpeg"]:
            return VideoSynthesisResult(
                success=False,
                partial=True,
                error="FFmpeg 不可用，请确认已安装",
                video_path=str(video_path)
            )

        ffmpeg_path = ffmpeg_result["ffmpeg"]
        ffprobe_path = ffmpeg_result.get("ffprobe", "ffprobe")

        # 获取图片列表
        images_dir = output_dir / "images"
        if not images_dir.exists():
            return VideoSynthesisResult(
                success=False,
                error="图片目录不存在",
                video_path=str(video_path)
            )

        # 获取按序号排列的图片
        image_files = sorted(
            images_dir.glob("slide_*.png"),
            key=lambda p: natural_sort_key(p.name)
        )
        if not image_files:
            image_files = sorted(
                images_dir.glob("*.png"),
                key=lambda p: natural_sort_key(p.name)
            )

        if not image_files:
            return VideoSynthesisResult(
                success=False,
                error="没有找到图片文件",
                video_path=str(video_path)
            )

        # 处理图片和场景的匹配
        original_image_count = len(image_files)
        scene_count = len(scenes)

        if original_image_count > scene_count:
            logger.info(f"图片({original_image_count}) > 场景({scene_count})，使用前 {scene_count} 张图片")
            image_files = image_files[:scene_count]
        elif original_image_count < scene_count:
            logger.warning(f"图片不足：图片({original_image_count}) < 场景({scene_count})")

        logger.info(f"最终使用 {len(image_files)} 张图片进行视频合成")

        # 创建音频缓存目录
        cache_dir = output_dir / "audio"
        cache_dir.mkdir(exist_ok=True)

        # 创建临时片段目录
        temp_dir = output_dir / "temp_segments"
        temp_dir.mkdir(exist_ok=True)

        # 初始化TTS生成器（带并发控制）
        tts = TTSGenerator(
            app_key=self.tts_config.app_key,
            token=self.tts_config.access_token,
            voice=self.tts_config.voice,
            format=self.tts_config.format,
            base_url=self.tts_config.base_url,
            cache_dir=str(cache_dir),
            max_concurrent=self.tts_config.max_concurrent,
            request_interval=self.tts_config.request_interval
        )

        # ========== 阶段1: 并发生成每个场景的音频 ==========
        logger.info(f"开始生成 {len(scenes)} 个场景的音频（语句级）...")

        scene_tasks = []
        for i, scene in enumerate(scenes):
            scene_id = scene.get("frame_id", f"s{i+1}")
            narration = scene.get("text", "")

            logger.info(f"[VIDEO_GEN] 场景 {scene_id}: text长度={len(narration)}")

            scene_tasks.append(
                tts.process_scene_sentences(
                    scene_id=scene_id,
                    narration=narration,
                    audio_index=i + 1,
                    ffprobe_path=ffprobe_path,
                    ffmpeg_path=ffmpeg_path
                )
            )

        # 并发执行所有场景的音频生成
        scene_audio_results = await asyncio.gather(*scene_tasks)

        # 过滤失败的场景
        successful_scenes = [r for r in scene_audio_results if r.get("success")]
        failed_count = len(scene_audio_results) - len(successful_scenes)

        if failed_count > 0:
            logger.warning(f"有 {failed_count} 个场景音频生成失败")

        if not successful_scenes:
            return VideoSynthesisResult(
                success=False,
                error="所有场景音频生成失败",
                video_path=str(video_path)
            )

        # ========== 阶段2: 逐个合成视频片段（带SRT字幕） ==========
        logger.info(f"开始合成 {len(successful_scenes)} 个视频片段...")

        segments = []
        seg_tasks = []

        for scene_result in successful_scenes:
            audio_index = scene_result["audio_index"]
            merged_audio = scene_result["merged_audio_path"]
            sentences = scene_result["sentences"]

            # 获取对应的图片
            if audio_index - 1 < len(image_files):
                image_path = image_files[audio_index - 1]
            else:
                logger.warning(f"场景 {audio_index} 没有对应的图片")
                continue

            # 生成SRT字幕文件
            seg_base_name = f"seg_{audio_index:02d}"
            seg_video_path = temp_dir / f"{seg_base_name}.mp4"

            # 获取音频时长
            audio_duration = scene_result.get("total_duration", 0)
            if audio_duration <= 0:
                audio_duration = await get_audio_duration(merged_audio, ffprobe_path)

            # 生成SRT字幕
            srt_path = await self._generate_segment_srt(
                sentences=sentences,
                audio_duration=audio_duration,
                output_path=str(seg_video_path)
            )

            # 合成片段任务
            seg_tasks.append(
                self._create_video_segment(
                    image_path=str(image_path),
                    audio_path=merged_audio,
                    output_path=str(seg_video_path),
                    srt_path=srt_path,
                    duration=audio_duration,
                    ffmpeg_path=ffmpeg_path
                )
            )
            segments.append(seg_video_path)

        # 并发执行所有片段的合成
        segment_results = await asyncio.gather(*seg_tasks)
        failed_segments = sum(1 for r in segment_results if not r)

        if failed_segments > 0:
            logger.warning(f"有 {failed_segments} 个片段合成失败")

        if not segments:
            return VideoSynthesisResult(
                success=False,
                error="所有视频片段合成失败",
                video_path=str(video_path)
            )

        # ========== 阶段3: 合并所有片段为最终视频 ==========
        logger.info(f"合并 {len(segments)} 个片段为最终视频...")

        merge_result = await self._merge_video_segments(
            segments=segments,
            output_path=video_path,
            temp_dir=temp_dir,
            ffmpeg_path=ffmpeg_path
        )

        # 清理临时文件
        try:
            for seg in segments:
                if seg.exists():
                    seg.unlink()
            if temp_dir.exists():
                try:
                    temp_dir.rmdir()
                except:
                    pass
        except Exception as e:
            logger.warning(f"清理临时文件时出错: {str(e)[:100]}")

        if not merge_result["success"]:
            return VideoSynthesisResult(
                success=False,
                error=merge_result.get("error", "视频合并失败"),
                video_path=str(video_path)
            )

        # 验证最终视频
        if video_path.exists() and video_path.stat().st_size > 1000:
            total_duration = sum(s.get("total_duration", 3.0) for s in successful_scenes)
            logger.info(f"视频生成成功: {video_path.name} ({video_path.stat().st_size / 1024:.1f} KB)")
            return VideoSynthesisResult(
                success=True,
                video_path=str(video_path),
                duration=total_duration,
                frames=len(successful_scenes)
            )
        else:
            return VideoSynthesisResult(
                success=False,
                error="视频文件生成失败或为空",
                video_path=str(video_path)
            )

    # ==================== 辅助方法 ====================

    async def _generate_segment_srt(
        self,
        sentences: List[Dict],
        audio_duration: float,
        output_path: str
    ) -> Optional[str]:
        """
        为单个视频片段生成SRT字幕文件

        Args:
            sentences: 句子信息列表
            audio_duration: 音频总时长
            output_path: 输出视频路径

        Returns:
            SRT文件路径，失败时返回None
        """
        if not sentences:
            return None

        return self.audio_utils.generate_srt_subtitle(sentences, audio_duration, output_path)

    async def _create_video_segment(
        self,
        image_path: str,
        audio_path: str,
        output_path: str,
        srt_path: Optional[str] = None,
        duration: float = 3.0,
        ffmpeg_path: str = "ffmpeg"
    ) -> bool:
        """
        合成单个视频片段（图片+音频+SRT字幕）

        Args:
            image_path: 图片路径
            audio_path: 音频路径
            output_path: 输出视频路径
            srt_path: SRT字幕文件路径（可选）
            duration: 片段时长（秒）
            ffmpeg_path: ffmpeg路径

        Returns:
            是否成功
        """
        loop = asyncio.get_event_loop()

        # 获取音频时长
        audio_duration = duration
        pad_duration = self.video_config.transition

        def _ffmpeg():
            # 基础视频滤镜：同时调整宽高为偶数（libx264要求）
            vf_filters = ["scale=ceil(iw/2)*2:ceil(ih/2)*2"]  # 调整宽度和高度为偶数

            # 音频滤镜：在音频末尾添加静音
            af_filters = [f"apad=pad_dur={pad_duration}"]

            # 添加字幕滤镜
            srt_dir_for_ffmpeg = None
            if srt_path and Path(srt_path).exists():
                srt_path_obj = Path(srt_path).resolve()
                srt_dir = srt_path_obj.parent
                srt_filename = srt_path_obj.name
                srt_dir_for_ffmpeg = srt_dir

                subtitle_filter = f"subtitles={srt_filename}:force_style='FontSize=16,FontName=Microsoft YaHei,PrimaryColour=&HFFFFFF,OutlineColour=&H000000,BorderStyle=1,Outline=1,Shadow=1,Alignment=2,MarginV=10,Bold=0'"
                vf_filters.append(subtitle_filter)

            # 修复Windows路径问题
            def fix_path(p):
                p = str(p).replace('\\', '/')
                return p

            cmd = [
                ffmpeg_path, "-y",
                "-loop", "1", "-t", str(duration),
                "-i", fix_path(image_path),
                "-i", fix_path(audio_path),
                "-vf", ",".join(vf_filters),
                "-af", ",".join(af_filters),
                "-c:v", "libx264", "-tune", "stillimage",
                "-pix_fmt", "yuv420p", "-r", "30",
                "-c:a", "aac", "-b:a", "192k", "-ar", "44100",
                fix_path(output_path)
            ]

            # 准备subprocess.run参数
            subprocess_kwargs = {
                "capture_output": True,
                "check": True,
                "text": True,
                "env": os.environ
            }

            # Windows下需要使用shell=True
            use_shell = sys.platform == 'win32' and not ffmpeg_path.endswith('.exe')
            subprocess_kwargs["shell"] = use_shell

            # 处理SRT字幕路径
            if srt_dir_for_ffmpeg is not None:
                all_paths = [
                    Path(image_path).resolve(),
                    Path(audio_path).resolve(),
                    Path(output_path).resolve(),
                    Path(srt_path).resolve()
                ]

                # 找共同父目录
                common_parent = None
                first_parents = list(all_paths[0].parents)
                for parent in reversed(first_parents):
                    if all(p.is_relative_to(parent) for p in all_paths):
                        common_parent = parent
                        break

                # 验证common_parent是否有效
                valid_parent = False
                if common_parent:
                    if common_parent.name and str(common_parent) not in ['/', '\\', '.']:
                        try:
                            test_rel = all_paths[0].relative_to(common_parent)
                            if '..' not in str(test_rel):
                                valid_parent = True
                        except (ValueError, TypeError):
                            pass

                if valid_parent:
                    # 计算相对路径
                    image_rel = Path(image_path).resolve().relative_to(common_parent)
                    audio_rel = Path(audio_path).resolve().relative_to(common_parent)
                    output_rel = Path(output_path).resolve().relative_to(common_parent)
                    srt_rel = Path(srt_path).resolve().relative_to(common_parent)

                    # 使用相对路径
                    cmd[7] = str(image_rel).replace('\\', '/')
                    cmd[9] = str(audio_rel).replace('\\', '/')
                    cmd[-1] = str(output_rel).replace('\\', '/')

                    # 更新字幕滤镜为相对路径
                    for i, filter_str in enumerate(vf_filters):
                        if filter_str.startswith("subtitles="):
                            new_filter = f"subtitles={srt_rel}:force_style='FontSize=16,FontName=Microsoft YaHei,PrimaryColour=&HFFFFFF,OutlineColour=&H000000,BorderStyle=1,Outline=1,Shadow=1,Alignment=2,MarginV=10,Bold=0'"
                            vf_filters[i] = new_filter
                            break

                    cmd[11] = ",".join(vf_filters)
                    subprocess_kwargs["cwd"] = str(common_parent)
                else:
                    # 简单方案：SRT文件名+cwd
                    srt_cwd = Path(srt_path).resolve().parent
                    srt_filename = Path(srt_path).name

                    cmd[7] = str(Path(image_path).resolve()).replace('\\', '/')
                    cmd[9] = str(Path(audio_path).resolve()).replace('\\', '/')
                    cmd[-1] = str(Path(output_path).resolve()).replace('\\', '/')

                    for i, filter_str in enumerate(vf_filters):
                        if filter_str.startswith("subtitles="):
                            new_filter = f"subtitles={srt_filename}:force_style='FontSize=16,FontName=Microsoft YaHei,PrimaryColour=&HFFFFFF,OutlineColour=&H000000,BorderStyle=1,Outline=1,Shadow=1,Alignment=2,MarginV=10,Bold=0'"
                            vf_filters[i] = new_filter
                            break

                    cmd[11] = ",".join(vf_filters)
                    subprocess_kwargs["cwd"] = str(srt_cwd)

            result = subprocess.run(cmd, **subprocess_kwargs)
            return result

        try:
            await loop.run_in_executor(None, _ffmpeg)
            return True
        except subprocess.CalledProcessError as e:
            logger.warning(f"片段合成失败: {Path(image_path).name}")
            logger.warning(f"返回码: {e.returncode}")
            if e.stderr:
                logger.warning(f"stderr: {e.stderr[-500:] if len(e.stderr) > 500 else e.stderr}")
            return False
        except Exception as e:
            logger.warning(f"片段合成错误: {str(e)[:100]}")
            return False

    async def _merge_video_segments(
        self,
        segments: List[Path],
        output_path: Path,
        temp_dir: Path,
        ffmpeg_path: str
    ) -> Dict[str, Any]:
        """
        合并所有视频片段为最终视频

        Args:
            segments: 视频片段路径列表
            output_path: 输出视频路径
            temp_dir: 临时目录
            ffmpeg_path: ffmpeg路径

        Returns:
            合并结果
        """
        concat_file = temp_dir / "concat_list.txt"
        with open(concat_file, "w", encoding="utf-8") as f:
            for seg in segments:
                if seg.exists():
                    rel_path = seg.resolve().relative_to(concat_file.resolve().parent)
                    f.write(f"file '{rel_path.as_posix()}'\n")

        # 合并视频
        merge_cmd = [
            ffmpeg_path, "-y",
            "-f", "concat", "-safe", "0",
            "-i", str(concat_file.resolve()),
            "-c", "copy",
            str(output_path.resolve())
        ]

        result = subprocess.run(
            merge_cmd,
            capture_output=True,
            text=True,
            timeout=300
        )

        if result.returncode != 0:
            logger.error(f"FFmpeg 合并错误: {result.stderr}")
            return {"success": False, "error": f"视频合并失败: {result.stderr[:200]}"}

        return {"success": True}

    def _is_tts_config_valid(self) -> bool:
        """检查TTS配置是否有效"""
        return (
            self.tts_config.app_key and
            self.tts_config.access_token
        )

    async def _detect_ffmpeg_tools(self) -> Dict[str, Optional[str]]:
        """
        检测FFmpeg和FFprobe工具

        Returns:
            {"ffmpeg": ffmpeg_path, "ffprobe": ffprobe_path}
        """
        # FFmpeg候选路径
        ffmpeg_candidates = [
            self.video_config.ffmpeg_path,
            r"C:\ffmpeg-7.1.1-essentials_build\bin\ffmpeg.exe",
            r"C:\ProgramData\chocolatey\bin\ffmpeg.exe",
            "ffmpeg.exe",
            "ffmpeg"
        ]

        ffmpeg_working = None
        for ff_path in ffmpeg_candidates:
            try:
                result = subprocess.run(
                    [ff_path, "-version"],
                    capture_output=True,
                    check=True,
                    timeout=5
                )
                ffmpeg_working = ff_path
                logger.info(f"FFmpeg 检测成功: {ff_path}")
                break
            except Exception:
                continue

        if not ffmpeg_working:
            logger.warning(f"FFmpeg 不可用，尝试了以下路径: {ffmpeg_candidates}")
            return {"ffmpeg": None, "ffprobe": None}

        # 检测FFprobe
        ffprobe_working = None
        if ffmpeg_working.endswith("ffmpeg.exe") or ffmpeg_working.endswith("ffmpeg"):
            ffprobe_path = ffmpeg_working.replace("ffmpeg.exe", "ffprobe.exe").replace("ffmpeg", "ffprobe")
            try:
                result = subprocess.run(
                    [ffprobe_path, "-version"],
                    capture_output=True,
                    check=True,
                    timeout=5
                )
                ffprobe_working = ffprobe_path
                logger.info(f"FFprobe 检测成功: {ffprobe_path}")
            except Exception:
                pass

        if not ffprobe_working:
            ffprobe_candidates = [
                self.video_config.ffprobe_path,
                r"C:\ffmpeg-7.1.1-essentials_build\bin\ffprobe.exe",
                r"C:\ProgramData\chocolatey\bin\ffprobe.exe",
                "ffprobe.exe",
                "ffprobe"
            ]
            for fp_path in ffprobe_candidates:
                try:
                    result = subprocess.run(
                        [fp_path, "-version"],
                        capture_output=True,
                        check=True,
                        timeout=5
                    )
                    ffprobe_working = fp_path
                    logger.info(f"FFprobe 检测成功: {fp_path}")
                    break
                except Exception:
                    continue

        if not ffprobe_working:
            logger.warning("FFprobe 不可用，音频时长检测将使用默认值")

        return {
            "ffmpeg": ffmpeg_working,
            "ffprobe": ffprobe_working or "ffprobe"
        }


# ==================== 便捷函数 ====================
async def synthesize_video(
    speech_script: Dict[str, Any],
    images_result: Dict[str, Any],
    output_dir: Path,
    tts_config: Any,
    video_config: Any,
    audio_utils_module: Any
) -> VideoSynthesisResult:
    """
    便捷函数：合成视频

    Args:
        speech_script: 语音脚本
        images_result: 图片生成结果
        output_dir: 输出目录
        tts_config: TTS配置
        video_config: 视频合成配置
        audio_utils_module: audio_utils模块

    Returns:
        视频合成结果
    """
    synthesizer = VideoSynthesizer(tts_config, video_config, audio_utils_module)
    return await synthesizer.generate_video(speech_script, images_result, output_dir)
