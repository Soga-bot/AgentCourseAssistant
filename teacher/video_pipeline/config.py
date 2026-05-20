"""
视频生成配置模块
视频生成配置模块
"""
import os
from dataclasses import dataclass, field
from typing import Optional, List
from enum import Enum


class ProblemDifficulty(Enum):
    """题目难度等级枚举"""
    SIMPLE = "简单"      # 6帧：一步计算
    MEDIUM = "中等"      # 9帧：2-3步推导
    COMPLEX = "复杂"     # 12帧：多步综合
    ADVANCED = "竞赛"    # 15帧：探究/竞赛


# 难度与帧数的映射关系
DIFFICULTY_FRAMES = {
    ProblemDifficulty.SIMPLE: 6,
    ProblemDifficulty.MEDIUM: 9,
    ProblemDifficulty.COMPLEX: 12,
    ProblemDifficulty.ADVANCED: 15,
}


@dataclass
class VideoConfig:
    """视频生成基础配置"""
    # LLM 配置
    model: str = "doubao-seed-2-0-pro-260215"
    api_key: Optional[str] = None
    base_url: str = "https://ark.cn-beijing.volces.com/api/v3"
    temperature: float = 0.1
    max_tokens: int = 16000
    max_retries: int = 5
    request_interval: float = 2.0
    timeout: int = 180

    # 输出配置
    output_dir: str = "./output/videos"
    temp_dir: str = "./temp/videos"

    def __post_init__(self):
        """自动从环境变量读取配置"""
        if self.api_key is None:
            self.api_key = os.getenv("VIDEO_API_KEY") or os.getenv("LLM_API_KEY")
        if os.getenv("VIDEO_MODEL"):
            self.model = os.getenv("VIDEO_MODEL")
        if os.getenv("VIDEO_BASE_URL"):
            self.base_url = os.getenv("VIDEO_BASE_URL")
        if os.getenv("VIDEO_TEMPERATURE"):
            self.temperature = float(os.getenv("VIDEO_TEMPERATURE"))
        if os.getenv("VIDEO_MAX_TOKENS"):
            self.max_tokens = int(os.getenv("VIDEO_MAX_TOKENS"))
        if os.getenv("VIDEO_MAX_RETRIES"):
            self.max_retries = int(os.getenv("VIDEO_MAX_RETRIES"))
        if os.getenv("VIDEO_REQUEST_INTERVAL"):
            self.request_interval = float(os.getenv("VIDEO_REQUEST_INTERVAL"))
        if os.getenv("VIDEO_TIMEOUT"):
            self.timeout = int(os.getenv("VIDEO_TIMEOUT"))
        if os.getenv("VIDEO_OUTPUT_DIR"):
            self.output_dir = os.getenv("VIDEO_OUTPUT_DIR")
        if os.getenv("VIDEO_TEMP_DIR"):
            self.temp_dir = os.getenv("VIDEO_TEMP_DIR")


@dataclass
class TTSConfig:
    """TTS 语音合成配置"""
    # 阿里云 NLS 配置
    app_key: Optional[str] = None
    access_token: Optional[str] = None
    voice: str = "zhida"  # 发音人
    format: str = "mp3"
    base_url: str = "https://nls-gateway-cn-shanghai.aliyuncs.com/stream/v1/tts"

    # 并发控制
    max_concurrent: int = 2
    request_interval: float = 3.0

    def __post_init__(self):
        """自动从环境变量读取配置"""
        if self.app_key is None:
            # 支持多种环境变量名
            self.app_key = os.getenv("TTS_APPKEY") or os.getenv("S5_TTS_APPKEY")
        if self.access_token is None:
            # 支持多种环境变量名
            self.access_token = os.getenv("TTS_TOKEN") or os.getenv("S5_TTS_TOKEN")
        if os.getenv("TTS_VOICE") or os.getenv("S5_TTS_VOICE"):
            self.voice = os.getenv("TTS_VOICE") or os.getenv("S5_TTS_VOICE")
        if os.getenv("TTS_FORMAT") or os.getenv("S5_TTS_FORMAT"):
            self.format = os.getenv("TTS_FORMAT") or os.getenv("S5_TTS_FORMAT")
        if os.getenv("TTS_BASE_URL") or os.getenv("S5_TTS_BASE_URL"):
            self.base_url = os.getenv("TTS_BASE_URL") or os.getenv("S5_TTS_BASE_URL")
        if os.getenv("TTS_MAX_CONCURRENT") or os.getenv("S5_TTS_MAX_CONCURRENT"):
            val = os.getenv("TTS_MAX_CONCURRENT") or os.getenv("S5_TTS_MAX_CONCURRENT")
            self.max_concurrent = int(val)
        if os.getenv("TTS_REQUEST_INTERVAL") or os.getenv("S5_TTS_REQUEST_INTERVAL"):
            val = os.getenv("TTS_REQUEST_INTERVAL") or os.getenv("S5_TTS_REQUEST_INTERVAL")
            self.request_interval = float(val)

    def is_valid(self) -> bool:
        """检查 TTS 配置是否有效"""
        if not self.app_key or self.app_key in ["", "your_tts_appkey_here", "YOUR_TTS_APPKEY_HERE"]:
            return False
        if not self.access_token or self.access_token in ["", "YOUR_ACCESS_TOKEN"]:
            return False
        return True


@dataclass
class LaTeXConfig:
    """LaTeX 生成配置"""
    latex_compiler: str = "xelatex"  # 改用XeLaTeX编译器
    dpi: int = 150

    # Beamer 主题配置
    theme: str = "Madrid"
    colortheme: str = "default"
    font: str = "ctex"  # 中文支持

    def __post_init__(self):
        """自动从环境变量读取配置"""
        if os.getenv("LATEX_COMPILER"):
            self.latex_compiler = os.getenv("LATEX_COMPILER")
        if os.getenv("LATEX_DPI"):
            self.dpi = int(os.getenv("LATEX_DPI"))
        if os.getenv("LATEX_THEME"):
            self.theme = os.getenv("LATEX_THEME")
        if os.getenv("LATEX_COLOR_THEME"):
            self.colortheme = os.getenv("LATEX_COLOR_THEME")


@dataclass
class VideoGenConfig:
    """完整视频生成配置"""
    video: VideoConfig = field(default_factory=VideoConfig)
    tts: TTSConfig = field(default_factory=TTSConfig)
    latex: LaTeXConfig = field(default_factory=LaTeXConfig)

    # FFmpeg 配置
    ffmpeg_path: str = "ffmpeg"
    ffprobe_path: str = "ffprobe"
    transition: float = 1.0  # 转场时长（秒）

    def __post_init__(self):
        """自动从环境变量读取配置"""
        if os.getenv("FFMPEG_PATH"):
            self.ffmpeg_path = os.getenv("FFMPEG_PATH")
        if os.getenv("FFPROBE_PATH"):
            self.ffprobe_path = os.getenv("FFPROBE_PATH")
        if os.getenv("VIDEO_TRANSITION"):
            self.transition = float(os.getenv("VIDEO_TRANSITION"))

    def get_output_dir(self, course_id: str) -> str:
        """
        获取指定课程的统一输出目录

        新的目录结构：output/course_{course_id}/
        ├── video/               # 视频文件
        ├── images/              # 图片资源
        ├── audio/               # 音频文件（TTS生成）
        ├── storyboard.json      # 分镜脚本
        └── speech.json          # 语音脚本
        """
        # 使用统一的课程输出目录
        course_dir = os.path.join("./output", f"course_{course_id}")

        # 确保子目录存在
        video_dir = os.path.join(course_dir, "video")
        images_dir = os.path.join(course_dir, "images")
        audio_dir = os.path.join(course_dir, "audio")

        os.makedirs(video_dir, exist_ok=True)
        os.makedirs(images_dir, exist_ok=True)
        os.makedirs(audio_dir, exist_ok=True)

        return course_dir

    def get_temp_dir(self, course_id: str) -> str:
        """获取指定课程的临时目录"""
        return os.path.join(self.video.temp_dir, f"course_{course_id}")
