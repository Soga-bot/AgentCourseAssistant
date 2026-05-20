"""
共享模块

提供双模式系统（视频模式 + 课程模式）共享的基础组件
"""

from .llm_client import LLMClient, LLMRequest, LLMResponse
from .prompt_builder import PromptBuilder
from .validators import ContentValidator, ValidationResult
from .utils import sanitize_json_output, extract_json
from .database import (
    UserDatabase,
    CourseDatabase,
    ShareDatabase,
    HistoryDatabase,
    user_db,
    course_db,
    share_db,
    history_db,
    init_all_databases,
)

__all__ = [
    "LLMClient",
    "LLMRequest",
    "LLMResponse",
    "PromptBuilder",
    "ContentValidator",
    "ValidationResult",
    "sanitize_json_output",
    "extract_json",
    "UserDatabase",
    "CourseDatabase",
    "ShareDatabase",
    "HistoryDatabase",
    "user_db",
    "course_db",
    "share_db",
    "history_db",
    "init_all_databases",
]
