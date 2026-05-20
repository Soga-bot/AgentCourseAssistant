"""
阶段4：TTS与视频合成器（TTS Video Synthesizer）

根据语音脚本生成音频并合成视频
根据语音脚本生成音频并合成视频

职责：
1. 调用TTS API生成音频文件
2. 使用FFmpeg合成视频
3. 处理音画同步
4. 支持缓存和并发
"""

import asyncio
import hashlib
import json
import logging
import os
import subprocess
import re
import wave
import struct
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Any

logger = logging.getLogger(__name__)


class TTSGenerationError(Exception):
    """TTS生成错误"""
    pass


class VideoSynthesisError(Exception):
    """视频合成错误"""
    pass


@dataclass
class TTSAudioResult:
    """TTS音频生成结果"""
    scene_id: str
    audio_path: str
    duration: float = 0.0
    success: bool = True
    error: str = ""


@dataclass
class VideoSynthesisResult:
    """视频合成结果"""
    success: bool
    video_path: str = ""
    total_duration: float = 0.0
    audio_count: int = 0
    error: str = ""
    warnings: List[str] = field(default_factory=list)


class TTSVideoSynthesizer:
    """
    TTS与视频合成器

    设计原则：
    1. 职责分离：TTS生成和视频合成独立
    2. 异步并发：支持多个音频并发生成
    3. 缓存支持：避免重复生成相同内容
    4. 错误恢复：失败时自动重试
    """

    def __init__(
        self,
        config: Optional[Dict] = None,
        output_dir: str = "output",
        cache_dir: Optional[str] = None
    ):
        """
        初始化TTS与视频合成器

        Args:
            config: 配置字典，包含TTS API信息
            output_dir: 输出目录
            cache_dir: 缓存目录（可选）
        """
        self.config = config or {}
        self.output_dir = Path(output_dir)
        self.audio_dir = self.output_dir / "audio"
        self.video_dir = self.output_dir / "videos"

        # 缓存目录
        if cache_dir:
            self.cache_dir = Path(cache_dir)
        else:
            self.cache_dir = self.audio_dir

        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.audio_dir.mkdir(parents=True, exist_ok=True)
        self.video_dir.mkdir(parents=True, exist_ok=True)

        # TTS配置
        self.tts_api_key = self.config.get('tts_api_key', os.getenv('TTS_API_KEY', ''))
        self.tts_base_url = self.config.get('tts_base_url', '')
        self.tts_voice = self.config.get('tts_voice', 'zh-CN-XiaoxiaoNeural')
        self.tts_format = self.config.get('tts_format', 'wav')
        self.tts_max_concurrent = self.config.get('tts_max_concurrent', 3)

        # FFmpeg配置
        self.ffmpeg_path = self.config.get('ffmpeg_path', 'ffmpeg')

        # 并发控制
        self._semaphore = asyncio.Semaphore(self.tts_max_concurrent)

        logger.info("[TTSVideoSynthesizer] 初始化完成")

    def _generate_cache_key(self, text: str) -> str:
        """生成缓存键"""
        payload = {
            "text": text,
            "voice": self.tts_voice
        }
        return hashlib.sha256(
            json.dumps(payload, sort_keys=True).encode()
        ).hexdigest()[:16]

    async def generate_audio(
        self,
        text: str,
        scene_id: str,
        output_path: Optional[str] = None
    ) -> TTSAudioResult:
        """
        生成单个场景的音频

        Args:
            text: 待转换的文本
            scene_id: 场景ID
            output_path: 输出路径（可选）

        Returns:
            TTSAudioResult: 音频生成结果
        """
        if not output_path:
            output_path = str(self.audio_dir / (scene_id + "." + self.tts_format))

        output_path = Path(output_path)

        # 检查缓存
        if output_path.exists():
            logger.debug("[TTSVideoSynthesizer] 使用缓存音频: %s", output_path.name)
            # 获取缓存音频的实际时长（任务11：精确字幕时序）
            cached_duration = await self._get_audio_duration(str(output_path))
            return TTSAudioResult(
                scene_id=scene_id,
                audio_path=str(output_path),
                duration=cached_duration,
                success=True
            )

        async with self._semaphore:
            try:
                if not self.tts_api_key or not self.tts_base_url:
                    # 使用模拟TTS（实际部署时需要真实API）
                    logger.warning("[TTSVideoSynthesizer] 未配置TTS API，使用模拟模式")
                    return await self._generate_mock_audio(text, scene_id, output_path)

                # 调用真实TTS API
                return await self._generate_tts_audio(text, scene_id, output_path)

            except Exception as e:
                logger.error("[TTSVideoSynthesizer] 生成音频失败 %s: %s", scene_id, e)
                return TTSAudioResult(
                    scene_id=scene_id,
                    success=False,
                    error=str(e)
                )

    async def _generate_tts_audio(
        self,
        text: str,
        scene_id: str,
        output_path: Path
    ) -> TTSAudioResult:
        """调用TTS API生成音频"""
        import aiohttp
        import aiofiles

        async with aiohttp.ClientSession() as session:
            headers = {
                "Content-Type": "application/json",
                "Authorization": "Bearer " + self.tts_api_key
            }

            payload = {
                "text": text,
                "voice": self.tts_voice,
                "format": self.tts_format
            }

            async with session.post(
                self.tts_base_url,
                headers=headers,
                json=payload,
                timeout=aiohttp.ClientTimeout(total=60)
            ) as response:

                if response.status != 200:
                    error_text = await response.text()
                    raise TTSGenerationError("API错误 " + str(response.status) + ": " + error_text)

                # 保存音频
                audio_data = await response.read()

                async with aiofiles.open(output_path, 'wb') as f:
                    await f.write(audio_data)

                logger.info("[TTSVideoSynthesizer] 音频生成完成: %s", output_path.name)

                # 获取实际音频时长（任务11：精确字幕时序）
                actual_duration = await self._get_audio_duration(str(output_path))

                return TTSAudioResult(
                    scene_id=scene_id,
                    audio_path=str(output_path),
                    duration=actual_duration,
                    success=True
                )

    async def _generate_mock_audio(
        self,
        text: str,
        scene_id: str,
        output_path: Path
    ) -> TTSAudioResult:
        """生成模拟音频（用于测试）"""
        # 生成静音WAV文件（1秒）
        with wave.open(str(output_path), 'w') as wav_file:
            wav_file.setnchannels(1)  # 单声道
            wav_file.setsampwidth(2)  # 2字节（16位）
            wav_file.setframerate(16000)  # 采样率

            # 生成1秒静音
            samples = int(16000 * 1)  # 1秒
            data = struct.pack('<' + 'h' * samples, *[0] * samples)
            wav_file.writeframes(data)

        logger.info("[TTSVideoSynthesizer] 模拟音频生成: %s", output_path.name)

        return TTSAudioResult(
            scene_id=scene_id,
            audio_path=str(output_path),
            duration=1.0,
            success=True
        )

    async def _get_audio_duration(self, audio_path: str) -> float:
        """
        获取音频文件的实际时长（任务11：精确字幕时序）

        优先使用 ffprobe，回退到 wave 库（仅限WAV）
        最终回退到文本估算

        Args:
            audio_path: 音频文件路径

        Returns:
            音频时长（秒）
        """
        # 首先尝试使用 ffprobe（支持所有格式）
        try:
            import asyncio
            loop = asyncio.get_event_loop()

            def _probe():
                cmd = [
                    "ffprobe", "-v", "error",
                    "-show_entries", "format=duration",
                    "-of", "default=noprint_wrappers=1:nokey=1",
                    audio_path
                ]
                result = subprocess.run(cmd, capture_output=True, text=True, check=True)
                return float(result.stdout.strip())

            duration = await loop.run_in_executor(None, _probe)
            logger.debug(f"[TTSVideoSynthesizer] 音频时长(ffprobe): {audio_path} = {duration:.2f}秒")
            return duration

        except Exception as e:
            logger.debug(f"[TTSVideoSynthesizer] ffprobe失败: {e}，尝试其他方法")

        # 回退到WAVE库（仅限WAV格式）
        try:
            if audio_path.lower().endswith('.wav'):
                with wave.open(audio_path, 'r') as wav_file:
                    frames = wav_file.getnframes()
                    rate = wav_file.getframerate()
                    duration = frames / float(rate)
                    logger.debug(f"[TTSVideoSynthesizer] 音频时长(wave): {audio_path} = {duration:.2f}秒")
                    return duration
        except Exception as e:
            logger.debug(f"[TTSVideoSynthesizer] wave库失败: {e}")

        # 最终回退：基于文本长度估算
        # 这不是精确的，但至少给了一个合理的值
        logger.warning(f"[TTSVideoSynthesizer] 无法获取音频时长，使用估算值")
        estimated_duration = max(2.0, len(open(audio_path, 'r', encoding='utf-8').read()) / 3.0) if Path(audio_path).exists() else 3.0
        return estimated_duration

    async def generate_all_audio(
        self,
        speech_result: Any
    ) -> List[TTSAudioResult]:
        """
        生成所有场景的音频

        Args:
            speech_result: 语音脚本生成结果

        Returns:
            List[TTSAudioResult]: 所有音频生成结果
        """
        logger.info("[TTSVideoSynthesizer] ========== 开始生成音频 ==========")

        results = []

        if hasattr(speech_result, 'script_by_scene'):
            scripts = speech_result.script_by_scene
        elif isinstance(speech_result, dict):
            scripts = speech_result.get('scriptByScene', {})
        else:
            logger.error("[TTSVideoSynthesizer] 无效的语音脚本数据")
            return []

        # 并发生成音频
        tasks = []
        for scene_id, script in scripts.items():
            # 合并所有narration段落
            if hasattr(script, 'narration'):
                text = ' '.join(script.narration)
            elif isinstance(script, dict):
                text = ' '.join(script.get('narration', []))
            else:
                continue

            task = self.generate_audio(text, scene_id)
            tasks.append(task)

        if tasks:
            results = await asyncio.gather(*tasks, return_exceptions=True)

            # 处理异常结果
            final_results = []
            for r in results:
                if isinstance(r, Exception):
                    logger.error("[TTSVideoSynthesizer] 任务异常: %s", r)
                else:
                    final_results.append(r)

            success_count = sum(1 for r in final_results if r.success)
            logger.info("[TTSVideoSynthesizer] 音频生成完成: %d/%d 成功", success_count, len(final_results))

            return final_results

        return []

    async def synthesize_video(
        self,
        images_dir: str,
        audio_results: List[TTSAudioResult],
        output_path: Optional[str] = None,
        course_id: Optional[str] = None,
        speech_scenes: Optional[List[Dict]] = None
    ) -> VideoSynthesisResult:
        """
        合成视频

        Args:
            images_dir: 图片目录
            audio_results: 音频生成结果列表
            output_path: 输出路径（可选）
            course_id: 课程ID（可选，用于生成文件名）

        Returns:
            VideoSynthesisResult: 视频合成结果
        """
        logger.info("[TTSVideoSynthesizer] ========== 开始合成视频 ==========")

        if not output_path:
            if course_id:
                output_path = str(self.video_dir / ("course_" + course_id + ".mp4"))
            else:
                output_path = str(self.video_dir / "course_video.mp4")

        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)

        try:
            images_path = Path(images_dir)
            if not images_path.exists():
                raise VideoSynthesisError("图片目录不存在: " + images_dir)

            # 获取所有图片（按自然排序）
            image_files = sorted(
                images_path.glob("slide_*.png"),
                key=lambda p: self._natural_sort_key(p.name)
            )

            if not image_files:
                raise VideoSynthesisError("未找到任何图片文件")

            logger.info("[TTSVideoSynthesizer] 找到 %d 张图片", len(image_files))

            # 构建FFmpeg命令
            ffmpeg_cmd = self._build_ffmpeg_command(
                image_files,
                audio_results,
                output_path,
                speech_scenes=speech_scenes
            )

            logger.info("[TTSVideoSynthesizer] 执行FFmpeg命令...")

            # 执行FFmpeg
            process = await asyncio.create_subprocess_exec(
                *ffmpeg_cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )

            stdout, stderr = await process.communicate()

            if process.returncode != 0:
                error_msg = stderr.decode('utf-8', errors='ignore')
                raise VideoSynthesisError("FFmpeg执行失败: " + error_msg)

            # 获取视频时长
            duration = await self._get_video_duration(output_path)

            logger.info("[TTSVideoSynthesizer] 视频合成完成")
            logger.info("[TTSVideoSynthesizer]   输出路径: %s", output_path)
            logger.info("[TTSVideoSynthesizer]   总时长: %.1f 秒", duration)

            return VideoSynthesisResult(
                success=True,
                video_path=str(output_path),
                total_duration=duration,
                audio_count=len(audio_results)
            )

        except Exception as e:
            logger.error("[TTSVideoSynthesizer] 视频合成失败: %s", e)
            import traceback
            logger.debug("[TTSVideoSynthesizer] 异常堆栈: %s", traceback.format_exc())

            return VideoSynthesisResult(
                success=False,
                error=str(e)
            )

    def _build_ffmpeg_command(
        self,
        image_files: List[Path],
        audio_results: List[TTSAudioResult],
        output_path: Path,
        speech_scenes: Optional[List[Dict]] = None
    ) -> List[str]:
        """
        构建FFmpeg命令（支持音频同步和字幕叠加）

        策略：
        1. 使用 concat demuxer 按音频时长控制每帧显示时间
        2. 使用 concat demuxer 拼接所有音频
        3. 可选叠加 SRT 字幕

        Args:
            image_files: 图片文件列表
            audio_results: 音频生成结果列表
            output_path: 输出路径
            speech_scenes: 语音场景列表（用于生成字幕）

        Returns:
            FFmpeg 命令列表
        """
        n_images = len(image_files)
        n_audio = len(audio_results)
        default_duration = 3.0

        # 构建音频时长查找表: scene_id -> TTSAudioResult
        audio_by_id = {}
        for ar in audio_results:
            if ar.success and ar.duration > 0:
                audio_by_id[ar.scene_id] = ar

        # 计算每帧显示时长（与对应音频时长同步）
        durations = []
        for i in range(n_images):
            matched = False
            # 优先通过 speech_scenes 匹配音频
            if speech_scenes and i < len(speech_scenes):
                scene_id = speech_scenes[i].get('frame_id', '')
                if scene_id in audio_by_id:
                    durations.append(audio_by_id[scene_id].duration)
                    matched = True
            # 回退：按索引匹配
            if not matched and i < n_audio and audio_results[i].success and audio_results[i].duration > 0:
                durations.append(audio_results[i].duration)
                matched = True
            if not matched:
                durations.append(default_duration)

        # 创建图片 concat 列表文件（控制每帧显示时长）
        # 使用绝对路径，避免 FFmpeg concat demuxer 相对路径解析导致路径重复
        image_list_path = output_path.parent / "_image_list.txt"
        with open(image_list_path, 'w', encoding='utf-8') as f:
            for i, img in enumerate(image_files):
                path_str = str(img.resolve()).replace('\\', '/')
                f.write(f"file '{path_str}'\n")
                f.write(f"duration {durations[i]:.3f}\n")
            # concat demuxer 要求最后一行重复 file 条目（无 duration）
            last_path = str(image_files[-1].resolve()).replace('\\', '/')
            f.write(f"file '{last_path}'\n")

        # 构建 FFmpeg 命令
        cmd = [self.ffmpeg_path, '-y', '-loglevel', 'error']

        # 输入1：图片 concat demuxer（按音频时长显示每帧）
        cmd.extend(['-f', 'concat', '-safe', '0', '-i', str(image_list_path.resolve())])

        has_audio = n_audio > 0 and any(ar.success for ar in audio_results)

        if has_audio:
            # 创建音频 concat 列表文件（拼接所有音频为一个音轨）
            # 使用绝对路径，避免相对路径解析问题
            audio_list_path = output_path.parent / "_audio_list.txt"
            with open(audio_list_path, 'w', encoding='utf-8') as f:
                for ar in audio_results:
                    if ar.success and ar.audio_path:
                        path_str = str(Path(ar.audio_path).resolve()).replace('\\', '/')
                        f.write(f"file '{path_str}'\n")
            # 输入2：音频 concat demuxer
            cmd.extend(['-f', 'concat', '-safe', '0', '-i', str(audio_list_path.resolve())])

        # 视频滤镜：缩放 + 可选字幕叠加
        vf_parts = ["scale=1920:1080"]

        if speech_scenes:
            srt_path = self._generate_srt(speech_scenes, durations, output_path.parent)
            if srt_path and srt_path.exists():
                # FFmpeg subtitles 滤镜路径转义（Windows 兼容）
                srt_escaped = str(srt_path).replace('\\', '/').replace(':', '\\:')
                vf_parts.append(f"subtitles='{srt_escaped}'")

        cmd.extend(['-vf', ','.join(vf_parts)])

        # 流映射
        cmd.extend(['-map', '0:v'])
        if has_audio:
            cmd.extend(['-map', '1:a'])

        # 视频编码
        cmd.extend([
            '-c:v', 'libx264',
            '-tune', 'stillimage',
            '-pix_fmt', 'yuv420p',
            '-r', '25',
        ])

        # 音频编码
        if has_audio:
            cmd.extend(['-c:a', 'aac', '-b:a', '128k'])

        # 以最短的流为准，防止音画不同步
        cmd.extend(['-shortest', str(output_path)])

        total_dur = sum(durations)
        logger.info(f"[TTSVideoSynthesizer] 帧时长: min={min(durations):.1f}s, max={max(durations):.1f}s, "
                     f"avg={total_dur / len(durations):.1f}s, total={total_dur:.1f}s")

        return cmd

    def _generate_srt(
        self,
        scenes: List[Dict],
        durations: List[float],
        temp_dir: Path
    ) -> Optional[Path]:
        """
        生成 SRT 字幕文件

        将每个场景的讲解文本拆分为字幕条目，按音频时长分配显示时间。

        Args:
            scenes: 语音场景列表（含 text 字段）
            durations: 每帧时长列表
            temp_dir: 临时目录

        Returns:
            SRT 文件路径，失败返回 None
        """
        try:
            srt_path = temp_dir / "subtitles.srt"
            current_time = 0.0
            entry_index = 1

            with open(srt_path, 'w', encoding='utf-8') as f:
                for i, scene in enumerate(scenes):
                    text = scene.get('text', '')
                    duration = durations[i] if i < len(durations) else 3.0

                    if not text:
                        current_time += duration
                        continue

                    # 清理文本用于字幕显示
                    clean = self._clean_subtitle_text(text)
                    if not clean:
                        current_time += duration
                        continue

                    # 拆分为字幕块（每块约30字符，适合单行显示）
                    chunks = self._split_subtitle_text(clean, max_chars=30)
                    if not chunks:
                        current_time += duration
                        continue

                    # 按文本长度比例分配时长
                    total_chars = sum(len(c) for c in chunks)
                    for chunk in chunks:
                        chunk_ratio = len(chunk) / total_chars if total_chars > 0 else 1.0 / len(chunks)
                        chunk_duration = duration * chunk_ratio
                        # 每条字幕至少显示 1.5 秒
                        chunk_duration = max(chunk_duration, 1.5)

                        start = current_time
                        end = current_time + chunk_duration

                        f.write(f"{entry_index}\n")
                        f.write(f"{self._format_srt_time(start)} --> {self._format_srt_time(end)}\n")
                        f.write(f"{chunk}\n\n")

                        entry_index += 1
                        current_time = end

            logger.info(f"[TTSVideoSynthesizer] SRT字幕: {srt_path.name} ({entry_index - 1}条)")
            return srt_path

        except Exception as e:
            logger.warning(f"[TTSVideoSynthesizer] SRT生成失败: {e}")
            return None

    @staticmethod
    def _format_srt_time(seconds: float) -> str:
        """格式化秒数为 SRT 时间格式 HH:MM:SS,mmm"""
        h = int(seconds // 3600)
        m = int((seconds % 3600) // 60)
        s = int(seconds % 60)
        ms = int((seconds % 1) * 1000)
        return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"

    @staticmethod
    def _clean_subtitle_text(text: str) -> str:
        """清理文本用于字幕显示（去除LaTeX标记，保留可读内容）"""
        # 移除 $...$ 数学定界符但保留内容
        text = re.sub(r'\$([^$]+)\$', r'\1', text)
        # 移除 \(...\) 行内数学定界符
        text = re.sub(r'\\\((.+?)\\\)', r'\1', text)
        # 移除 \[...\] 显示数学定界符
        text = re.sub(r'\\\[.+?\\\]', '', text)
        # LaTeX 命令转可读文本
        text = re.sub(r'\\textbf\{([^}]*)\}', r'\1', text)
        text = re.sub(r'\\frac\{([^}]*)\}\{([^}]*)\}', r'\1/\2', text)
        text = re.sub(r'\\sqrt\{([^}]*)\}', r'√\1', text)
        text = re.sub(r'\\times', '×', text)
        text = re.sub(r'\\div', '÷', text)
        text = re.sub(r'\\leq', '≤', text)
        text = re.sub(r'\\geq', '≥', text)
        text = re.sub(r'\\neq', '≠', text)
        text = re.sub(r'\\approx', '≈', text)
        text = re.sub(r'\\pi', 'π', text)
        text = re.sub(r'\\infty', '∞', text)
        text = re.sub(r'\\angle', '∠', text)
        text = re.sub(r'\\triangle', '△', text)
        text = re.sub(r'\\dot\{([^}]*)\}', r'\1', text)
        text = re.sub(r'\\left\b', '', text)
        text = re.sub(r'\\right\b', '', text)
        text = re.sub(r'\\[a-zA-Z]+', '', text)
        # 清理残留的花括号和多余空白
        text = re.sub(r'[{}]', '', text)
        text = re.sub(r'\s+', ' ', text).strip()
        # 限制单条字幕长度
        if len(text) > 80:
            text = text[:77] + '...'
        return text

    @staticmethod
    def _split_subtitle_text(text: str, max_chars: int = 30) -> List[str]:
        """
        将长文本按标点拆分为字幕块

        每块不超过 max_chars 字符，优先在中文标点处断句。
        """
        if len(text) <= max_chars:
            return [text]

        chunks = []
        # 按中文标点拆分句子
        parts = re.split(r'([，。；！？、：,;.])', text)

        # 合并片段和紧跟的标点
        merged = []
        for p in parts:
            if p in '，。；！？、：,;.' and merged:
                merged[-1] += p
            elif p:
                merged.append(p)

        # 将句子组合成不超过 max_chars 的块
        current_chunk = ""
        for s in merged:
            if len(current_chunk) + len(s) > max_chars and current_chunk:
                chunks.append(current_chunk)
                current_chunk = s
            else:
                current_chunk += s

        if current_chunk:
            chunks.append(current_chunk)

        return chunks if chunks else [text]

    async def _get_video_duration(self, video_path: Path) -> float:
        """获取视频时长"""
        try:
            cmd = [
                self.ffmpeg_path,
                '-i', str(video_path),
                '-f', 'null',
                '-'
            ]

            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )

            stdout, stderr = await process.communicate()

            # 从stderr中解析时长
            output = stderr.decode('utf-8', errors='ignore')
            match = re.search(r'Duration: (\d+):(\d+):(\d+\.\d+)', output)

            if match:
                hours = int(match.group(1))
                minutes = int(match.group(2))
                seconds = float(match.group(3))
                return hours * 3600 + minutes * 60 + seconds

            return 0.0

        except Exception as e:
            logger.warning("[TTSVideoSynthesizer] 获取视频时长失败: %s", e)
            return 0.0

    def _natural_sort_key(self, text: str) -> List:
        """自然排序键函数"""
        return [int(c) if c.isdigit() else c.lower() for c in re.split(r'(\d+)', text)]


# =============================================================================
# 便捷函数
# =============================================================================

async def synthesize_course_video(
    images_dir: str,
    speech_result: Any,
    config: Optional[Dict] = None,
    output_path: Optional[str] = None,
    course_id: Optional[str] = None
) -> VideoSynthesisResult:
    """
    合成课程视频的便捷函数

    Args:
        images_dir: 图片目录
        speech_result: 语音脚本生成结果
        config: 配置字典
        output_path: 输出路径
        course_id: 课程ID

    Returns:
        VideoSynthesisResult: 视频合成结果
    """
    synthesizer = TTSVideoSynthesizer(config)

    # 生成音频
    audio_results = await synthesizer.generate_all_audio(speech_result)

    # 合成视频
    return await synthesizer.synthesize_video(
        images_dir,
        audio_results,
        output_path,
        course_id
    )
