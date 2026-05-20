"""自定义内容生成器

处理自定义课程大纲/教案/讲义的生成
"""

import asyncio
from typing import Optional, Callable, Dict
from datetime import datetime

from shared.llm_client import LLMClient, LLMRequest, LLMResponse
from shared.prompt_builder import PromptBuilder
from shared.validators import ContentValidator
from shared.utils import extract_json
from ..knowledge_base import KnowledgeBase
from ..models import CourseContent, CourseGenerateRequest, CourseGeneratorConfig
from .base import BaseGenerator


class CustomGenerator(BaseGenerator):
    """自定义内容生成器

    负责处理基于自定义大纲/教案/讲义的课程内容生成
    """

    # 学情配置
    STUDENT_LEVEL_CONFIG = {
        "基础薄弱": {
            "description": "概念拆解到最细，计算步骤一步不跳",
            "example_count": 3,
        },
        "中等巩固": {
            "description": "概念讲透，加易混点辨析",
            "example_count": 4,
        },
        "培优拓展": {
            "description": "概念延伸拓展，加一题多解",
            "example_count": 5,
        },
    }

    def __init__(self, config: CourseGeneratorConfig):
        """初始化生成器

        Args:
            config: 生成器配置
        """
        self.config = config
        self.llm_client = LLMClient(config.llm_config)
        self.prompt_builder = PromptBuilder()
        self.knowledge_base = KnowledgeBase(config.knowledge_dir)
        self.validator = ContentValidator(self.knowledge_base)

    async def generate(
        self,
        request: CourseGenerateRequest,
        progress_callback: Optional[Callable] = None
    ) -> CourseContent:
        """生成自定义内容

        Args:
            request: 生成请求参数
            progress_callback: 进度回调函数

        Returns:
            课程内容

        Raises:
            ValueError: 参数错误
            Exception: 生成失败
        """
        self._update_progress(progress_callback, 10, "正在准备生成...")

        # 2. 构建提示词
        self._update_progress(progress_callback, 30, "正在构建提示词...")
        prompt = self._build_prompt(request)

        # 3. 调用LLM
        self._update_progress(progress_callback, 50, "正在生成内容...")

        llm_request = LLMRequest(
            messages=[{"role": "system", "content": prompt}],
            max_tokens=self.config.llm_config.max_tokens,
        )

        response = await self.llm_client.call(llm_request)

        if not response.success:
            raise Exception(f"LLM调用失败: {response.error}")

        # 4. 解析响应
        self._update_progress(progress_callback, 70, "正在解析内容...")

        content = self._parse_content(response.content, request)

        # 5. 教师自定义内容跳过自动校验（教师手动预览检查）
        # 学生课程生成由 TextbookGenerator 处理，保留其校验逻辑
        print(f"  [i] 教师自定义内容生成完成，等待手动预览检查")

        self._update_progress(progress_callback, 100, "生成完成!")

        return content

    def _build_prompt(self, request: CourseGenerateRequest) -> str:
        """构建生成提示词

        Args:
            request: 生成请求

        Returns:
            构建好的提示词
        """
        # 获取学情配置
        level_config = self.STUDENT_LEVEL_CONFIG.get(
            request.student_level,
            self.STUDENT_LEVEL_CONFIG["中等巩固"]
        )

        # 准备模板变量（所有章节都是必填的，无需条件判断）
        variables = {
            "grade": request.grade,
            "version": self._get_version_name(request.version),
            "student_level": request.student_level,
            "purpose": request.purpose,
            "example_count": level_config["example_count"],
        }

        # 自定义大纲模式变量
        variables.update({
            "chapter": request.custom_topic or "自定义课程",
            "custom_outline": request.custom_outline,
            "curriculum_requirement": "（根据自定义内容确定）",
            "knowledge_points": "（见自定义大纲）",
            "key_difficulties": "（见自定义大纲）",
            "common_mistakes": "（见自定义大纲）",
        })

        # 根据内容类型选择模板
        if request.custom_outline and request.content_type:
            template_mapping = {
                "lesson_plan": "lesson_plan",
                "teaching_script": "teaching_script",
                "board_design": "board_design",
                "review_outline": "review_outline"
            }
            template_name = template_mapping.get(request.content_type, "custom_outline")
        else:
            template_name = "custom_outline"

        return self.prompt_builder.build(template_name, variables)

    def _parse_content(
        self,
        raw_content: str,
        request: CourseGenerateRequest
    ) -> CourseContent:
        """解析LLM返回的内容

        Args:
            raw_content: LLM返回的原始内容
            request: 生成请求

        Returns:
            解析后的课程内容
        """
        # 尝试解析JSON
        json_data = extract_json(raw_content)

        if json_data and isinstance(json_data, dict):
            # JSON格式
            title = json_data.get("title", "")
            sections = json_data.get("sections", {})
        else:
            # 纯文本格式，尝试解析
            title, sections = self._parse_text_content(raw_content, request)

        # 构建元数据
        metadata = {
            "generated_at": datetime.now().isoformat(),
            "version": request.version,
            "chapter_id": request.custom_topic or "custom",
            "content_type": request.content_type,
        }

        chapter_name = request.custom_topic or "自定义课程"

        return CourseContent(
            title=title or chapter_name,
            grade=request.grade,
            chapter=chapter_name,
            version=request.version,
            student_level=request.student_level,
            purpose=request.purpose,
            sections=sections,
            metadata=metadata
        )

    def _parse_text_content(
        self,
        text: str,
        request: CourseGenerateRequest
    ) -> tuple:
        """解析纯文本格式的内容

        Args:
            text: 纯文本内容
            request: 生成请求

        Returns:
            (标题, 章节字典) 元组
        """
        lines = text.split('\n')
        title = lines[0] if lines else ""

        # 尝试按章节分隔
        sections = {}
        current_section = None
        current_content = []

        section_markers = [
            "课程导入", "导入",
            "知识点详解", "核心知识点",
            "典例精讲", "例题",
            "易错点", "易错点避雷",
            "随堂小测", "练习",
            "知识框架", "知识点框架",
            "课后拓展", "拓展",
        ]

        for line in lines[1:]:
            line = line.strip()
            if not line:
                continue

            # 检查是否是章节标题
            is_section = False
            for marker in section_markers:
                if marker in line:
                    if current_section:
                        sections[current_section] = "\n".join(current_content)
                    current_section = line
                    current_content = []
                    is_section = True
                    break

            if not is_section and current_section:
                current_content.append(line)

        # 添加最后一个章节
        if current_section and current_content:
            sections[current_section] = "\n".join(current_content)

        # 如果没有解析出章节，把整个文本作为"知识点详解"
        if not sections:
            sections["知识点详解"] = text

        return title, sections

    def _get_version_name(self, version: str) -> str:
        """获取版本的中文名称

        Args:
            version: 版本ID

        Returns:
            版本中文名称
        """
        version_names = {
            "renjiao_v1": "人教版",
            "beishi_v1": "北师大版",
            "suke_v1": "苏科版",
            "huke_v1": "沪科版",
        }
        return version_names.get(version, version)
