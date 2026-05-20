"""生成器配置模型

定义课程生成器的配置参数
"""

from dataclasses import dataclass
from shared.llm_client import LLMConfig


@dataclass
class CourseGeneratorConfig:
    """课程生成器配置

    Attributes:
        llm_config: LLM客户端配置
        knowledge_dir: 知识库目录路径
        output_dir: 输出目录路径（用于保存生成的图示等）
        enable_validation: 是否启用内容校验
        max_retries_on_validation_fail: 校验失败时的最大重试次数
    """
    llm_config: LLMConfig = None
    knowledge_dir: str = "./teacher/knowledge"
    output_dir: str = "./output"
    enable_validation: bool = True
    max_retries_on_validation_fail: int = 1

    def __post_init__(self):
        """初始化后处理，确保llm_config不为空"""
        if self.llm_config is None:
            self.llm_config = LLMConfig()
