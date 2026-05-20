"""数据模型模块

包含课程生成相关的所有数据模型：
- CourseGenerateRequest: 生成请求参数
- CourseContent: 生成结果内容
- CourseGeneratorConfig: 生成器配置
"""

from .request import CourseGenerateRequest
from .content import CourseContent
from .config import CourseGeneratorConfig

__all__ = [
    "CourseGenerateRequest",
    "CourseContent",
    "CourseGeneratorConfig",
]
