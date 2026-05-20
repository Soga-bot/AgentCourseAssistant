"""
音频处理工具模块
提供 TTS、音频处理、SRT 字幕生成功能
提供 TTS、音频处理、SRT 字幕生成功能

功能：
- 阿里云 NLS TTS 语音合成（逐句生成）
- 音频时长检测（FFprobe）
- 音频合并（FFmpeg concat，带备选方案）
- SRT 字幕生成（长句自动切分）
"""
import asyncio
import hashlib
import json
import logging
import os
import subprocess
import tempfile
from pathlib import Path
from typing import List, Dict, Optional, Any

import aiohttp
import aiofiles

# 使用统一的日志配置
from .logging_config import get_module_logger
logger = get_module_logger(__name__, "audio_utils")

__all__ = [
    "get_audio_duration",
    "generate_audio",
    "merge_audio_files",
    "generate_cache_key",
    "split_text_for_subtitle",
    "seconds_to_srt_time",
    "generate_srt_subtitle",
    "TTSGenerator",
]


async def get_audio_duration(audio_path: str, ffprobe_path: str = "ffprobe") -> float:
    """
    使用 ffprobe 获取音频时长

    Args:
        audio_path: 音频文件路径
        ffprobe_path: ffprobe 可执行文件路径

    Returns:
        音频时长（秒），失败时返回默认值 3.0
    """
    loop = asyncio.get_event_loop()

    def _probe():
        cmd = [
            ffprobe_path, "-v", "error",
            "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1",
            audio_path
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, check=True)
        return float(result.stdout.strip())

    try:
        return await loop.run_in_executor(None, _probe)
    except:
        return 3.0


async def generate_audio(
    text: str,
    output_path: str,
    app_key: str,
    token: str,
    voice: str = "zhida",
    format: str = "mp3",
    base_url: str = "https://nls-gateway-cn-shanghai.aliyuncs.com/stream/v1/tts",
    timeout: int = 60
) -> bool:
    """
    异步生成单个音频（阿里云 NLS TTS）

    Args:
        text: 要转换的文本
        output_path: 输出音频文件路径
        app_key: 阿里云 AppKey
        token: 阿里云 AccessToken
        voice: 发音人（zhida, zhichu 等）
        format: 音频格式（mp3, wav, mp4）
        base_url: TTS API 地址
        timeout: 请求超时时间（秒）

    Returns:
        是否成功
    """
    if not app_key or not token:
        return False

    path = Path(output_path)

    # 检查缓存
    if path.exists():
        return True

    try:
        async with aiohttp.ClientSession() as session:
            payload = {
                "appkey": app_key,
                "token": token,
                "text": text,
                "format": format,
                "sample_rate": 16000,
                "voice": voice
            }

            async with session.post(
                base_url,
                json=payload,
                timeout=aiohttp.ClientTimeout(total=timeout)
            ) as response:
                if response.status != 200:
                    return False

                audio_data = await response.read()

                if not audio_data:
                    return False

                path.parent.mkdir(parents=True, exist_ok=True)
                async with aiofiles.open(path, "wb") as f:
                    await f.write(audio_data)

                return True

    except Exception:
        return False


async def merge_audio_files(
    audio_paths: List[str],
    output_path: str,
    ffmpeg_path: str = "ffmpeg"
) -> bool:
    """
    使用 ffmpeg 合并多个音频文件（带备选方案）

    Args:
        audio_paths: 音频文件路径列表
        output_path: 输出音频文件路径
        ffmpeg_path: ffmpeg 可执行文件路径

    Returns:
        是否成功
    """
    if not audio_paths:
        logger.error("[merge_audio_files] 音频路径列表为空")
        return False

    # 确保输出目录存在
    output_dir = Path(output_path).parent
    output_dir.mkdir(parents=True, exist_ok=True)

    # 如果只有一个文件，直接复制
    if len(audio_paths) == 1:
        import shutil
        try:
            shutil.copy(audio_paths[0], output_path)
            logger.info(f"[merge_audio_files] 单文件复制: {audio_paths[0]} -> {output_path}")
            return True
        except Exception as e:
            logger.error(f"[merge_audio_files] 单文件复制失败: {e}")
            return False

    loop = asyncio.get_event_loop()

    # 方法1: 使用 concat demuxer（最可靠）
    def _ffmpeg_concat_demuxer():
        list_file = tempfile.NamedTemporaryFile(mode='w', suffix='.txt', delete=False)
        try:
            for audio_path in audio_paths:
                abs_path = Path(audio_path).resolve()
                safe_path = str(abs_path).replace('\\', '/')
                list_file.write(f"file '{safe_path}'\n")
            list_file.close()

            cmd = [
                ffmpeg_path, "-y",
                "-f", "concat",
                "-safe", "0",
                "-i", list_file.name,
                "-c", "copy",
                output_path
            ]

            result = subprocess.run(
                cmd,
                capture_output=True,
                check=True,
                text=True,
                shell=False
            )
            return result
        finally:
            try:
                os.unlink(list_file.name)
            except:
                pass

    # 方法2: 使用 concat filter（备选）
    def _ffmpeg_concat_filter():
        cmd = [ffmpeg_path, "-y"]

        for audio_path in audio_paths:
            cmd.extend(["-i", audio_path])

        n = len(audio_paths)
        filter_complex = f"{''.join([f'[{i}:0]' for i in range(n)])}concat=n={n}:v=0:a=1[out]"

        cmd.extend([
            "-filter_complex", filter_complex,
            "-map", "[out]",
            output_path
        ])

        result = subprocess.run(
            cmd,
            capture_output=True,
            check=True,
            text=True,
            shell=False
        )
        return result

    # 先尝试 concat demuxer
    try:
        await loop.run_in_executor(None, _ffmpeg_concat_demuxer)
        logger.info(f"[merge_audio_files] 合并成功 (demuxer): {output_path}")
        return True
    except subprocess.CalledProcessError as e:
        logger.warning(f"[merge_audio_files] concat demuxer 失败，尝试 filter 方法")
        pass
    except Exception as e:
        logger.warning(f"[merge_audio_files] concat demuxer 异常: {e}")

    # 再尝试 concat filter
    try:
        await loop.run_in_executor(None, _ffmpeg_concat_filter)
        logger.info(f"[merge_audio_files] 合并成功 (filter): {output_path}")
        return True
    except subprocess.CalledProcessError as e:
        logger.warning(f"[merge_audio_files] concat filter 失败: {e}")
        pass
    except Exception as e:
        logger.warning(f"[merge_audio_files] concat filter 异常: {e}")

    # 最后降级方案：使用第一段音频
    import shutil
    try:
        shutil.copy(audio_paths[0], output_path)
        logger.info(f"[merge_audio_files] 降级方案成功 (复制第一段): {output_path}")
        return True
    except Exception as e:
        logger.error(f"[merge_audio_files] 所有方法失败: {e}")
        return False


def generate_cache_key(text: str, voice: str) -> str:
    """生成缓存键"""
    payload = {
        "text": text,
        "voice": voice
    }
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True).encode()
    ).hexdigest()[:16]


def split_text_for_subtitle(text: str, max_chars: int = 56) -> List[str]:
    """
    将文本切分成适合字幕显示的片段

    优先在标点符号处切分
    """
    if len(text) <= max_chars:
        return [text]

    segments = []
    current_segment = ""

    # 优先切分点（按优先级排序）
    split_points = [
        ('。', '！', '？', '\n'),  # 句末标点
        ('；', '：', '，'),        # 逗号类
        ('、',)                   # 顿号
    ]

    i = 0
    while i < len(text):
        current_segment += text[i]

        if len(current_segment) >= max_chars:
            split_found = False

            for punct_list in split_points:
                for j in range(len(current_segment) - 1, -1, -1):
                    if current_segment[j] in punct_list:
                        segments.append(current_segment[:j + 1])
                        current_segment = current_segment[j + 1:]
                        split_found = True
                        break
                if split_found:
                    break

            if not split_found:
                segments.append(current_segment[:max_chars])
                current_segment = current_segment[max_chars:]

        i += 1

    if current_segment:
        segments.append(current_segment)

    return segments


def seconds_to_srt_time(seconds: float) -> str:
    """将秒数转换为 SRT 时间格式 (HH:MM:SS,mmm)"""
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    secs = int(seconds % 60)
    millisecs = int((seconds % 1) * 1000)
    return f"{hours:02d}:{minutes:02d}:{secs:02d},{millisecs:03d}"


def generate_srt_subtitle(
    sentence_infos: List[Dict],
    audio_duration: float,
    output_path: str
) -> Optional[str]:
    """
    生成 SRT 字幕文件（长句自动切分）

    Args:
        sentence_infos: 句子信息列表 [{"text": "第一句话", "duration": 2.5}, ...]
        audio_duration: 音频总时长（秒）
        output_path: 输出视频路径（用于确定SRT文件路径）

    Returns:
        SRT 文件路径，失败时返回 None
    """
    if not sentence_infos:
        return None

    output_path_abs = Path(output_path).resolve()
    srt_path = str(output_path_abs.with_suffix('.srt'))

    srt_content = []
    subtitle_index = 1
    current_time = 0

    for sentence_info in sentence_infos:
        text = sentence_info.get("text", "")
        duration = sentence_info.get("duration", 0)

        if duration <= 0:
            min_time = 2.0
            chars_per_second = 5.0
            duration = max(min_time, len(text) / chars_per_second)

        max_chars_per_line = 28
        max_lines = 2
        max_chars_per_subtitle = max_chars_per_line * max_lines

        text_segments = split_text_for_subtitle(text, max_chars_per_subtitle)
        segment_duration = duration / len(text_segments)

        for segment in text_segments:
            start_time = current_time
            end_time = current_time + segment_duration

            start_srt = seconds_to_srt_time(start_time)
            end_srt = seconds_to_srt_time(end_time)

            srt_content.append(f"{subtitle_index}")
            srt_content.append(f"{start_srt} --> {end_srt}")
            srt_content.append(segment)
            srt_content.append("")

            subtitle_index += 1
            current_time = end_time

    try:
        Path(srt_path).parent.mkdir(parents=True, exist_ok=True)
        with open(srt_path, 'w', encoding='utf-8-sig') as f:
            f.write('\n'.join(srt_content))
        return srt_path
    except Exception:
        return None


class TTSGenerator:
    """
    TTS 音频生成器
    支持并发控制、缓存、语句级处理
    """

    def __init__(
        self,
        app_key: str,
        token: str,
        voice: str = "zhida",
        format: str = "mp3",
        base_url: str = "https://nls-gateway-cn-shanghai.aliyuncs.com/stream/v1/tts",
        cache_dir: Optional[str] = None,
        max_concurrent: int = 1,
        request_interval: float = 3.0
    ):
        self.app_key = app_key
        self.token = token
        self.voice = voice
        self.format = format
        self.base_url = base_url

        self._semaphore = asyncio.Semaphore(max_concurrent)
        self._last_request_time = 0

        if cache_dir:
            self.cache_dir = Path(cache_dir)
        else:
            self.cache_dir = Path("./output/audio")
        self.cache_dir.mkdir(parents=True, exist_ok=True)

    def _generate_cache_key(self, text: str) -> str:
        """生成缓存键"""
        payload = {
            "text": text,
            "voice": self.voice
        }
        return hashlib.sha256(
            json.dumps(payload, sort_keys=True).encode()
        ).hexdigest()[:16]

    async def generate_audio(self, text: str, output_path: str) -> bool:
        """
        异步生成单个音频（带缓存和并发控制）
        异步生成单个音频（带缓存和并发控制）
        """
        if not self.app_key or not self.token:
            return False

        path = Path(output_path)

        if path.exists():
            return True

        async with self._semaphore:
            try:
                async with aiohttp.ClientSession() as session:
                    headers = {"Content-Type": "application/json"}

                    payload = {
                        "appkey": self.app_key,
                        "token": self.token,
                        "text": text,
                        "format": self.format,
                        "sample_rate": 16000,
                        "voice": self.voice
                    }

                    async with session.post(
                        self.base_url,
                        headers=headers,
                        json=payload,
                        timeout=aiohttp.ClientTimeout(total=60)
                    ) as response:

                        if response.status != 200:
                            error_text = await response.text()
                            print(f"[TTS错误] API返回非200状态码: {response.status}")
                            print(f"[TTS错误] 响应内容: {error_text[:200]}")
                            logger.error(f"[TTS] API返回状态码 {response.status}: {error_text[:200]}")
                            return False

                        audio_data = await response.read()

                        if not audio_data:
                            print(f"[TTS错误] API返回空数据, 文本: {text[:50]}...")
                            logger.error(f"[TTS] API返回空数据, 文本: {text[:50]}...")
                            return False

                        path.parent.mkdir(parents=True, exist_ok=True)
                        async with aiofiles.open(path, "wb") as f:
                            await f.write(audio_data)

                        return True

            except Exception as e:
                print(f"[TTS错误] 生成音频异常: {str(e)}, 文本: {text[:50]}...")
                logger.error(f"[TTS] 生成音频异常: {str(e)}, 文本: {text[:50]}...")
                return False

    async def get_audio_duration(self, audio_path: str, ffprobe_path: str = "ffprobe") -> float:
        """获取音频时长"""
        return await get_audio_duration(audio_path, ffprobe_path)

    def _split_narration_to_sentences(self, narration) -> List[str]:
        """
        将旁白文本切分成句子列表
        支持两种格式：
        1. 列表格式（LLM 扩写后的格式）：直接使用
        2. 字符串格式（旧格式）：需要切分
        """
        # 如果是列表格式（LLM 扩写后的格式）
        if isinstance(narration, list):
            return [str(n).strip() for n in narration if n and str(n).strip()]

        # 如果是字符串格式（旧格式），需要切分
        if not narration or not isinstance(narration, str):
            return []

        # 清理文本
        import re
        cleaned = narration.strip().replace('\n', ' ').replace('\r', ' ')
        cleaned = re.sub(r'\s+', ' ', cleaned)

        # 按标点符号切分（中英文）
        parts = re.split(r'([。！？；，.!?;,])', cleaned)

        sentences = []
        for i in range(0, len(parts) - 1, 2):
            if i + 1 < len(parts):
                sentence = (parts[i] + parts[i + 1]).strip()
                if sentence and len(sentence) > 1:
                    sentences.append(sentence)

        # 处理剩余文本
        if len(parts) % 2 == 1 and parts[-1].strip() and len(parts[-1].strip()) > 1:
            sentences.append(parts[-1].strip())

        # 如果切分失败，将整个文本作为一个句子
        if not sentences and cleaned:
            sentences = [cleaned]

        return sentences

    async def process_scene_sentences(
        self,
        scene_id: str,
        narration: str,
        audio_index: int,
        ffprobe_path: str = "ffprobe",
        ffmpeg_path: str = "ffmpeg"
    ) -> Dict:
        """
        处理单个场景的旁白，按句子切分并生成音频
        处理单个场景的旁白，按句子切分并生成音频

        Args:
            scene_id: 场景ID
            narration: 旁白文本（字符串，会被切分成句子）
            audio_index: 音频序号（用于文件命名）
            ffprobe_path: ffprobe 路径
            ffmpeg_path: ffmpeg 路径

        Returns:
            {
                "scene_id": "s1",
                "audio_index": 1,
                "sentences": [
                    {"text": "第一句话", "duration": 2.5}
                ],
                "merged_audio_path": "path/to/slide_01.mp3",
                "success": True
            }
        """
        print(f"[TTS] 处理场景 {scene_id}, narration长度: {len(narration)}")
        logger.info(f"[TTS] 处理场景 {scene_id}, narration长度: {len(narration)}")

        # 将字符串旁白切分成句子列表
        all_sentences = self._split_narration_to_sentences(narration)

        if not all_sentences:
            return {
                "scene_id": scene_id,
                "audio_index": audio_index,
                "sentences": [],
                "success": False,
                "error": "无有效句子"
            }

        # 为每句话生成音频
        sentence_audios = []
        for idx, sentence in enumerate(all_sentences):
            temp_audio_path = self.cache_dir / f"slide_{audio_index:02d}_temp_{len(sentence_audios)}.mp3"

            print(f"[TTS] 生成第 {idx+1}/{len(all_sentences)} 个句子音频: {sentence[:30]}...")
            logger.info(f"[TTS] 生成第 {idx+1}/{len(all_sentences)} 个句子音频: {sentence[:30]}...")

            success = await self.generate_audio(sentence, str(temp_audio_path))
            if success:
                duration = await self.get_audio_duration(str(temp_audio_path), ffprobe_path)
                sentence_audios.append({
                    "text": sentence,
                    "audio_path": str(temp_audio_path),
                    "duration": duration
                })
                print(f"[TTS] 句子音频生成成功, 时长: {duration}秒")
            else:
                print(f"[TTS错误] 句子音频生成失败: {sentence[:30]}...")

        if not sentence_audios:
            print(f"[TTS错误] 场景 {scene_id} 所有句子音频生成失败")
            logger.error(f"[TTS] 场景 {scene_id} 所有句子音频生成失败")
            return {
                "scene_id": scene_id,
                "audio_index": audio_index,
                "sentences": [],
                "success": False,
                "error": "所有句子音频生成失败"
            }

        # 合并音频
        final_audio_path = self.cache_dir / f"slide_{audio_index:02d}.mp3"

        print(f"[TTS] 合并 {len(sentence_audios)} 个句子音频到: {final_audio_path}")
        logger.info(f"[TTS] 合并 {len(sentence_audios)} 个句子音频到: {final_audio_path}")

        merge_success = await self._merge_audio_files(
            [s["audio_path"] for s in sentence_audios],
            str(final_audio_path),
            ffmpeg_path
        )

        # 验证合并后的文件是否存在
        if not final_audio_path.exists():
            print(f"[TTS错误] 合并后的音频文件不存在: {final_audio_path}")
            logger.error(f"[TTS] 合并后的音频文件不存在: {final_audio_path}")
            return {
                "scene_id": scene_id,
                "audio_index": audio_index,
                "sentences": [],
                "success": False,
                "error": "合并后的音频文件不存在"
            }

        if final_audio_path.stat().st_size < 1000:
            print(f"[TTS警告] 合并后的音频文件过小: {final_audio_path.stat().st_size} bytes")
            logger.warning(f"[TTS] 合并后的音频文件过小: {final_audio_path.stat().st_size} bytes")

        # 清理临时文件
        for s in sentence_audios:
            try:
                Path(s["audio_path"]).unlink()
            except:
                pass

        return {
            "scene_id": scene_id,
            "audio_index": audio_index,
            "sentences": sentence_audios,
            "merged_audio_path": str(final_audio_path),
            "total_duration": sum(s["duration"] for s in sentence_audios),
            "success": True
        }

    async def _merge_audio_files(self, audio_paths: List[str], output_path: str, ffmpeg_path: str = "ffmpeg"):
        """使用 ffmpeg 合并多个音频文件"""
        await merge_audio_files(audio_paths, output_path, ffmpeg_path)

    async def test_tts_availability(self) -> Dict[str, Any]:
        """
        测试 TTS 服务是否可用（预检功能）

        通过生成一个短音频来验证 TTS 配置是否正确

        Returns:
            {
                "available": bool,
                "error": str or None,
                "test_text": str
            }
        """
        import tempfile
        import os

        test_text = "测试"  # 简短测试文本
        test_file = os.path.join(self.cache_dir, "_tts_test.mp3")

        logger.info(f"[TTS预检] 测试 TTS 服务可用性...")
        print(f"[TTS预检] 开始测试 TTS 服务...")

        try:
            # 尝试生成测试音频
            success = await self.generate_audio(test_text, test_file)

            if success:
                logger.info("[TTS预检] TTS 服务可用")
                print(f"[TTS预检] ✓ TTS 服务正常")
                # 清理测试文件
                try:
                    if os.path.exists(test_file):
                        os.remove(test_file)
                except:
                    pass
                return {"available": True, "error": None, "test_text": test_text}
            else:
                logger.warning("[TTS预检] TTS 生成失败")
                print(f"[TTS预检] ✗ TTS 生成失败")
                return {"available": False, "error": "音频生成失败", "test_text": test_text}

        except Exception as e:
            error_msg = str(e)
            logger.error(f"[TTS预检] TTS 测试异常: {error_msg}")
            print(f"[TTS预检] ✗ 异常: {error_msg}")
            return {"available": False, "error": error_msg, "test_text": test_text}
