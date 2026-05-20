"""
具体Agent实现模块

包含所有具体的Agent实现，如：
- 课程生成Agent
- 学习助教Agent
- 视频生成Agent
- 质量检查Agent
"""
from .course_generation import CourseGenerationAgent
from .learning_tutor import LearningTutorAgent
from .video_generation import VideoGenerationAgent

__all__ = [
    "CourseGenerationAgent",
    "LearningTutorAgent",
    "VideoGenerationAgent",
]
