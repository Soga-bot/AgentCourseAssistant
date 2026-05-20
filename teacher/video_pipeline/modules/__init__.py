"""
视频生成模块包

采用五阶段架构 + 模块化设计：
- 阶段0: 智能难度判断 (IntelligentDifficultyJudge)
- 阶段1: 内容理解 (ContentUnderstandingExpert)
- 阶段2: 分镜生成 (StoryboardDesigner + FormatConverter)
  - 方案A三阶段分离：
    - TeachingFlowDesigner（教学流程规划）
    - ContentGenerator（内容生成）
    - LayoutDesigner（排版设计）
- 阶段3: 语音脚本生成 (SpeechScriptGenerator)
- 阶段4: TTS与视频合成 (TTSVideoSynthesizer)

采用模块化分离架构，实现沉浸式生成
"""

# 内容处理模块
from .content_processor import ContentProcessor

# ========== 方案A：三阶段分离模块 ==========
# 阶段2A-1: 教学流程规划
from .teaching_flow_designer import (
    TeachingFlowDesigner,
    TeachingFlowResult,
    FrameStructure
)

# 阶段2A-2: 内容生成
from .content_generator import (
    ContentGenerator,
    ContentGenerationResult,
    ContentFrame
)

# 阶段2A-3: 排版设计
from .layout_designer import LayoutDesigner

# 阶段0: 智能难度判断（动态帧数）
from .intelligent_difficulty_judge import (
    IntelligentDifficultyJudge,
    DifficultyAnalysis,
    analyze_frame_count
)

# 阶段1: 内容理解
from .content_understanding import (
    ContentUnderstandingExpert,
    ContentUnderstandingResult,
    KnowledgePoint
)

# 阶段2A: 教学设计
from .storyboard_designer import (
    StoryboardDesigner,
    StoryboardDesignResult,
    StoryboardFrame
)

# 阶段2B: 格式转换
from .format_converter import (
    FormatConverter,
    FormatResult,
    convert_to_json,
    convert_to_json_async
)

# 阶段3: 语音脚本生成
from .speech_script_generator import (
    SpeechScriptGenerator,
    SpeechScriptResult,
    SpeechScript
)

# 阶段4: TTS与视频合成
from .tts_video_synthesizer import (
    TTSVideoSynthesizer,
    VideoSynthesisResult,
    TTSAudioResult
)

# 保留旧模块以保持兼容性
from .storyboard_generator import (
    StoryboardGenerationExpert,
    StoryboardGenerationResult,
    StoryboardScene
)

# 轻量分镜映射器 (简化路径专用)
from .course_to_video_mapper import (
    CourseToVideoMapper,
    LightweightScene,
    map_course_to_storyboard
)

# 结构化内容生成器 (简化路径预处理)
from .course_structurer import (
    CourseStructurer,
    CourseStructureResult
)

__all__ = [
    # 内容处理
    'ContentProcessor',

    # 阶段0: 智能难度判断（动态帧数）
    'IntelligentDifficultyJudge',
    'DifficultyAnalysis',
    'analyze_frame_count',

    # 阶段1: 内容理解
    'ContentUnderstandingExpert',
    'ContentUnderstandingResult',
    'KnowledgePoint',

    # ========== 方案A：三阶段分离模块 ==========
    # 阶段2A-1: 教学流程规划
    'TeachingFlowDesigner',
    'TeachingFlowResult',
    'FrameStructure',

    # 阶段2A-2: 内容生成
    'ContentGenerator',
    'ContentGenerationResult',
    'ContentFrame',

    # 阶段2A-3: 排版设计
    'LayoutDesigner',

    # 阶段2A: 教学设计（协调者）
    'StoryboardDesigner',
    'StoryboardDesignResult',
    'StoryboardFrame',

    # 阶段2B: 格式转换
    'FormatConverter',
    'FormatResult',
    'convert_to_json',
    'convert_to_json_async',

    # 阶段3: 语音脚本生成
    'SpeechScriptGenerator',
    'SpeechScriptResult',
    'SpeechScript',

    # 阶段4: TTS与视频合成
    'TTSVideoSynthesizer',
    'VideoSynthesisResult',
    'TTSAudioResult',

    # 保留旧模块以保持兼容性
    'StoryboardGenerationExpert',
    'StoryboardGenerationResult',
    'StoryboardScene',

    # 轻量分镜映射器 (简化路径专用)
    'CourseToVideoMapper',
    'LightweightScene',
    'map_course_to_storyboard',

    # 结构化内容生成器 (简化路径预处理)
    'CourseStructurer',
    'CourseStructureResult'
]
