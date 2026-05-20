"""
课程内容生成器

核心业务逻辑：
- 查询知识库
- 构建提示词
- 调用LLM生成内容
- 校验内容
- 返回结果
"""

import asyncio
import json
import logging
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Any
from pathlib import Path
from datetime import datetime

logger = logging.getLogger(__name__)

from shared.llm_client import LLMClient, LLMRequest, LLMResponse, LLMConfig
from shared.prompt_builder import PromptBuilder
from shared.validators import ContentValidator, ValidationResult
from .knowledge_base import KnowledgeBase, ChapterInfo
from .models import CourseGenerateRequest, CourseContent, CourseGeneratorConfig


class CourseGenerator:
    """
    课程内容生成器

    流程：
    1. 查询知识库，获取章节信息
    2. 构建提示词
    3. 调用LLM生成内容
    4. 校验内容（公式、超纲、结构）
    5. 返回结果

    使用示例：
    ```python
    config = CourseGeneratorConfig()
    generator = CourseGenerator(config)

    request = CourseGenerateRequest(
        version="renjiao_v1",
        grade="七年级上册",
        chapter_id="c1_youshu",
        student_level="基础薄弱",
        purpose="学生自学"
    )

    content = await generator.generate(request)
    print(content.title)
    ```
    """

    # 学情映射配置
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

    def __init__(self, config: CourseGeneratorConfig = None):
        self.config = config or CourseGeneratorConfig()

        # 初始化组件
        self.llm_client = LLMClient(self.config.llm_config)
        self.prompt_builder = PromptBuilder()
        self.knowledge_base = KnowledgeBase(self.config.knowledge_dir)
        self.validator = ContentValidator(self.knowledge_base)

        print("[CourseGenerator] 初始化完成")
        print(f"  知识库目录: {self.config.knowledge_dir}")
        print(f"  LLM模型: {self.config.llm_config.model}")

    async def generate(
        self,
        request: CourseGenerateRequest,
        progress_callback: Optional[callable] = None,
        task_id: Optional[str] = None
    ) -> CourseContent:
        """
        生成课程内容

        Args:
            request: 生成请求参数
            progress_callback: 进度回调函数

        Returns:
            课程内容

        Raises:
            ValueError: 参数错误或章节不存在
            Exception: 生成失败
        """
        self._update_progress(progress_callback, 5, "正在初始化...")

        # 1. 查询知识库
        if request.custom_topic:
            # 自定义专题模式
            chapter_info = None
            self._update_progress(progress_callback, 10, "正在准备自定义专题...")
        else:
            # 教材章节模式
            self._update_progress(progress_callback, 10, "正在查询章节信息...")
            chapter_info = self.knowledge_base.get_chapter_info(
                request.version,
                request.grade,
                request.chapter_id
            )
            if not chapter_info:
                raise ValueError(
                    f"章节不存在: {request.version} / {request.grade} / {request.chapter_id}"
                )
            self._update_progress(progress_callback, 15, "已获取章节信息...")

        # 2. 构建提示词
        self._update_progress(progress_callback, 20, "正在构建提示词...")
        prompt = self._build_prompt(request, chapter_info)
        self._update_progress(progress_callback, 25, "提示词构建完成...")

        # 3. 调用LLM（4批分批生成策略 - 2025升级版）
        # 针对长章节避免截断，分批生成：
        # - 第1批：导入 + 学习目标 + 知识点详解_A（前半部分）
        # - 第2批：知识点详解_B（后半部分）
        # - 第3批：典例精讲_A（前半例题）
        # - 第4批：典例精讲_B + 易错点 + 其他sections

        import logging
        logger = logging.getLogger(__name__)
        logger.info(f"[课程生成] ===== 使用4批分批生成策略（2025升级版） =====")

        # 获取课程信息用于批次传递
        course_title = chapter_info.chapter_name if chapter_info else request.custom_topic or "未知课程"
        course_grade = request.grade
        course_chapter = request.version

        self._update_progress(progress_callback, 30, "正在连接AI服务...")

        # ==================== 第1批：导入 + 学习目标 + 知识点详解_A ====================
        logger.info(f"[课程生成] ===== 第1批开始：导入 + 学习目标 + 知识详解（前半） =====")
        self._update_progress(progress_callback, 32, "正在生成第1批内容...")

        batch1_prompt = prompt + f"""

# 重要提示（分批生成）
本次是第1批生成，请生成以下3个section：
1. **导入**
2. **学习目标**
3. **知识点详解_A**（只生成前半部分的知识点，约占全部知识点的50%）

请按以下JSON格式输出：
```json
{{
  "title": "{course_title}",
  "grade": "{course_grade}",
  "chapter": "{course_title}",
  "sections": {{
    "导入": "...",
    "学习目标": "...",
    "知识点详解_A": "【一、...】【二、】...（前半部分知识点，使用【】标记分点）"
  }}
}}
```

**知识点详解_A的要求**：
- 生成前半部分的基础概念知识点（如：定义、分类、基本性质等）
- 使用【一、】【二、】等标记明确分点
- **根据知识点复杂度决定详细程度**：
  - 复杂知识点（如定义、定理、公式）：详细阐述，包括定义、性质、公式、示例、应用等
  - 简单知识点（如直观性质、几何意义）：简洁阐述，讲清楚即可，不冗余
- 内容要专业、准确、有深度
- **语言风格（重要）**：使用专业术语、纯理论阐述
  - 禁止："同学们"、"大家"、"简单来说"、"大家庭"、"接下来"、"首先"等情感化/口语化表达
  - 使用："定义"、"性质"、"定理"、"例如"、"即"、"如下"等学术化表达
  - 直接陈述知识点，开门见山

请开始生成第1批内容:"""

        request1 = LLMRequest(
            messages=[{"role": "system", "content": batch1_prompt}],
            temperature=0.1,
            max_tokens=16000
        )

        response1 = await self.llm_client.call(request1)

        if not response1.success:
            logger.error(f"[课程生成] 第1批LLM调用失败: {response1.error}")
            raise Exception(f"第1批LLM调用失败: {response1.error}")

        # 解析第1批结果
        from shared.utils import extract_json
        result1 = extract_json(response1.content)
        if not result1 or "sections" not in result1:
            logger.error(f"[课程生成] 第1批解析失败")
            raise Exception("第1批解析失败")

        logger.info(f"[课程生成] 第1批成功，已生成: {list(result1['sections'].keys())}")

        # 生成第1批摘要
        summary1 = self._generate_batch_summary(result1, batch_num=1)
        logger.info(f"[课程生成] 第1批摘要已生成")

        self._update_progress(progress_callback, 42, "第1批完成，正在生成第2批...")

        # ==================== 第2批：知识点详解_B（后半部分） ====================
        logger.info(f"[课程生成] ===== 第2批开始：知识点详解（后半部分） =====")
        logger.info(f"[课程生成] 第1批摘要：{summary1[:150]}...")

        # 提取已生成的知识点列表
        knowledge_points_summary = self._extract_knowledge_points_summary(
            result1['sections'].get('知识点详解_A', '')
        )

        batch2_prompt = f"""# 任务
继续为课程生成剩余内容。

# 课程信息
- 标题：{course_title}
- 年级：{course_grade}
- 章节：{course_title}

# 前面已生成的内容摘要
{summary1}

# 已生成的知识点
{knowledge_points_summary}

# 本次任务
请生成**知识点详解_B**（后半部分的知识点）：
- 继续生成剩余的知识点（如：运算、应用、综合等）
- 与前面已生成的知识点保持连贯，不要重复
- 使用【四、】【五、】等标记继续编号
- **根据知识点复杂度决定详细程度**：
  - 复杂知识点（如定义、定理、公式）：详细阐述，包括定义、性质、公式、示例、应用等
  - 简单知识点（如直观性质、几何意义）：简洁阐述，讲清楚即可，不冗余
- 内容要专业、准确、有深度
- **语言风格（重要）**：使用专业术语、纯理论阐述
  - 禁止："同学们"、"大家"、"简单来说"、"大家庭"、"接下来"、"首先"等情感化/口语化表达
  - 使用："定义"、"性质"、"定理"、"例如"、"即"、"如下"等学术化表达
  - 直接陈述知识点，开门见山

请按以下JSON格式输出：
```json
{{
  "知识点详解_B": "【四、...】【五、】...（后半部分知识点，继续编号）"
}}
```

【数学公式格式要求（必须严格遵守）】
- 所有数学表达式必须用 `$...$`（行内）或 `$$...$$`（独立成行）包裹
- 分数必须用 `$\\frac{{分子}}{{分母}}$`，禁止用斜杠如 a/b
- 多行对齐公式必须用 `$$\\begin{{align*}}...\\end{{align*}}$$`，每行末尾用 `\\\\` 换行
- 特殊符号正确使用：`$\\times$`、`$\\div$`、`$\\leq$`、`$\\geq$`、`$\\neq$`
- 绝对值用 `$|a|$`，乘方用 `$a^n$`

请开始生成第2批内容:"""

        request2 = LLMRequest(
            messages=[{"role": "user", "content": batch2_prompt}],
            temperature=0.1,
            max_tokens=16000
        )

        response2 = await self.llm_client.call(request2)

        if not response2.success:
            logger.error(f"[课程生成] 第2批LLM调用失败: {response2.error}")
            raise Exception(f"第2批LLM调用失败: {response2.error}")

        result2 = extract_json(response2.content)
        if not result2:
            logger.error(f"[课程生成] 第2批解析失败")
            raise Exception("第2批解析失败")

        logger.info(f"[课程生成] 第2批成功，已生成: {list(result2.keys())}")

        # 合并知识点详解（添加异常保护）
        try:
            combined_knowledge_detail = self._merge_knowledge_details(
                result1['sections'].get('知识点详解_A', ''),
                result2.get('知识点详解_B', '')
            )
            logger.info(f"[课程生成] 知识点合并成功，长度: {len(combined_knowledge_detail)} 字符")
        except Exception as merge_error:
            logger.error(f"[课程生成] 知识点合并失败: {merge_error}")
            raise Exception(f"知识点详解合并失败: {merge_error}") from merge_error

        # 生成第2批摘要（添加异常保护）
        try:
            summary2 = self._generate_batch_summary({
                "导入": result1['sections'].get('导入', ''),
                "学习目标": result1['sections'].get('学习目标', ''),
                "知识点详解": combined_knowledge_detail
            }, batch_num=2)
            logger.info(f"[课程生成] 第2批摘要生成成功")
        except Exception as summary_error:
            logger.error(f"[课程生成] 第2批摘要生成失败: {summary_error}")
            raise Exception(f"第2批摘要生成失败: {summary_error}") from summary_error

        self._update_progress(progress_callback, 52, "第2批完成，正在生成第3批...")

        # ==================== 第3批：典例精讲_A（前半部分例题） ====================
        logger.info(f"[课程生成] ===== 第3批开始：典例精讲（前半例题） =====")
        logger.info(f"[课程生成] 第2批摘要：{summary2[:150]}...")

        batch3_prompt = f"""# 任务
继续为课程生成剩余内容。

# 课程信息
- 标题：{course_title}
- 年级：{course_grade}

# 前面已生成的内容摘要
{summary2}

# 本次任务
请生成**典例精讲_A**（前半部分例题）：
- 生成前2道例题（例题1、例题2）
- 例题应覆盖前面已生成的主要知识点
- 每道例题包含：题目、思路引导、完整步骤、答案、易错提醒
- 不同例题间用空行分隔即可

请按以下JSON格式输出：
```json
{{
  "典例精讲_A": "【例题1】\\n【题目】...\\n【思路引导】...\\n【完整步骤】...\\n【答案】...\\n【易错提醒】...\\n\\n【例题2】..."
}}
```

【数学公式格式要求（必须严格遵守）】
- 所有数学表达式必须用 `$...$`（行内）或 `$$...$$`（独立成行）包裹，无一例外
- 分数必须用 `$\\frac{{分子}}{{分母}}$`，禁止用斜杠如 a/b
- **完整步骤中的多行运算过程**必须用 `$$\\begin{{align*}}...\\end{{align*}}$$`，每行末尾用 `\\\\` 换行对齐
- 特殊符号：`$\\times$`（乘）、`$\\div$`（除）、`$\\leq$`、`$\\geq$`、`$\\neq$`
- 绝对值用 `$|a|$`，乘方用 `$a^n$`，括号用 `$(-2)^3$` 而非 `$-2^3$`

请开始生成第3批内容:"""

        request3 = LLMRequest(
            messages=[{"role": "user", "content": batch3_prompt}],
            temperature=0.1,
            max_tokens=16000
        )

        response3 = await self.llm_client.call(request3)

        if not response3.success:
            logger.error(f"[课程生成] 第3批LLM调用失败: {response3.error}")
            raise Exception(f"第3批LLM调用失败: {response3.error}")

        result3 = extract_json(response3.content)
        if not result3:
            logger.error(f"[课程生成] 第3批解析失败")
            raise Exception("第3批解析失败")

        logger.info(f"[课程生成] 第3批成功，已生成: {list(result3.keys())}")

        # 提取例题摘要（添加异常保护）
        try:
            examples_summary = self._extract_examples_summary(result3.get('典例精讲_A', ''))
            logger.info(f"[课程生成] 例题摘要提取成功")
        except Exception as extract_error:
            logger.error(f"[课程生成] 例题摘要提取失败: {extract_error}")
            # 使用默认值，不中断流程
            examples_summary = "已生成前2道例题"

        self._update_progress(progress_callback, 62, "第3批完成，正在生成第4批...")

        # ==================== 第4批：典例精讲_B + 易错点 + 其他sections ====================
        logger.info(f"[课程生成] ===== 第4批开始：典例精讲（后半）+ 其他sections =====")
        logger.info(f"[课程生成] 第3批摘要（例题）：{examples_summary[:150]}...")

        batch4_prompt = f"""# 任务
继续为课程生成最后的内容。

# 课程信息
- 标题：{course_title}
- 年级：{course_grade}

# 前面已生成的例题
{examples_summary}

# 本次任务
请生成以下内容：
1. **典例精讲_B**（后半部分例题，2-3道例题，继续编号）
2. **易错点**（3-5个易错点，结合前面知识点和例题）
3. **随堂小测**（3-5题，分2-3组）
4. **知识框架**（结构化总结）
5. **课后拓展**（2-3个拓展方向）

请按以下JSON格式输出：
```json
{{
  "典例精讲_B": "【例题3】\\n【题目】...\\n【思路引导】...\\n【完整步骤】...\\n【答案】...\\n【易错提醒】...\\n\\n【例题4】...",
  "易错点": "易错点1：...错误原因：...正确做法：...易错点2：...",
  "随堂小测": "【第1组】练习题1...练习题2...\\n\\n【第2组】练习题3...",
  "知识框架": "本节课知识结构：...",
  "课后拓展": "仅1个！生活应用题或思维拓展题（严格限制，不要写多个）"
}}
```

【数学公式格式要求（必须严格遵守）】
- 所有数学表达式必须用 `$...$`（行内）或 `$$...$$`（独立成行）包裹，无一例外
- 分数必须用 `$\\frac{{分子}}{{分母}}$`，禁止用斜杠如 a/b
- **完整步骤中的多行运算过程**必须用 `$$\\begin{{align*}}...\\end{{align*}}$$`，每行末尾用 `\\\\` 换行对齐
- 随堂小测中的数学内容同样必须用 `$...$` 包裹
- 特殊符号：`$\\times$`（乘）、`$\\div$`（除）、`$\\leq$`、`$\\geq$`、`$\\neq$`
- 绝对值用 `$|a|$`，乘方用 `$a^n$`，括号用 `$(-2)^3$` 而非 `$-2^3$`

请开始生成第4批内容:"""

        request4 = LLMRequest(
            messages=[{"role": "user", "content": batch4_prompt}],
            temperature=0.1,
            max_tokens=16000
        )

        response4 = await self.llm_client.call(request4)

        if not response4.success:
            logger.error(f"[课程生成] 第4批LLM调用失败: {response4.error}")
            raise Exception(f"第4批LLM调用失败: {response4.error}")

        result4 = extract_json(response4.content)
        if not result4:
            logger.error(f"[课程生成] 第4批解析失败")
            raise Exception("第4批解析失败")

        logger.info(f"[课程生成] 第4批成功，已生成: {list(result4.keys())}")

        # ==================== 合并所有批次结果 ====================
        try:
            merged_json = self._merge_all_batches(
                result1, result2, result3, result4,
                combined_knowledge_detail, course_title, course_grade, course_title
            )
            logger.info(f"[课程生成] 所有批次合并成功")
        except Exception as merge_all_error:
            logger.error(f"[课程生成] 所有批次合并失败: {merge_all_error}")
            raise Exception(f"所有批次合并失败: {merge_all_error}") from merge_all_error

        logger.info(f"[课程生成] ===== 4批生成完成（2025升级版） =====")
        logger.info(f"[课程生成] 最终sections: {list(merged_json['sections'].keys())}")

        self._update_progress(progress_callback, 68, "AI内容生成完成，正在接收响应...")

        # 4. 解析响应（直接使用合并后的dict，避免json.dumps→json.loads导致LaTeX反斜杠被转义）
        self._update_progress(progress_callback, 65, "正在解析AI响应...")

        title = merged_json.get("title", "")
        sections = merged_json.get("sections", {})
        sections = self._normalize_sections(sections)

        metadata = {
            "generated_at": datetime.now().isoformat(),
            "version": request.version,
            "chapter_id": request.chapter_id,
            "content_type": request.content_type,
        }

        if chapter_info:
            chapter_name = chapter_info.chapter_name
        else:
            chapter_name = request.custom_topic or "自定义专题"

        content = CourseContent(
            title=title or f"{request.grade} - {chapter_name}",
            grade=request.grade,
            chapter=chapter_name,
            version=request.version,
            student_level=request.student_level,
            purpose=request.purpose,
            sections=sections,
            metadata=metadata
        )
        self._update_progress(progress_callback, 75, "内容解析完成...")

        # 5. 校验内容（教师自定义内容跳过自动校验）
        is_custom_teacher_content = request.custom_outline and request.content_type in [
            'lesson_plan', 'teaching_script', 'board_design', 'review_outline'
        ]

        if is_custom_teacher_content:
            # 教师自定义内容：跳过自动校验，由教师手动预览检查
            print(f"  [i] 教师自定义内容生成完成，等待手动预览检查")
        elif self.config.enable_validation:
            # 学生课程内容：进行自动校验
            self._update_progress(progress_callback, 80, "正在校验内容格式...")

            validation_result = self.validator.validate(content.to_dict())

            if not validation_result.is_valid:
                print(f"  [!] 校验失败: {validation_result.errors}")

                if self.config.max_retries_on_validation_fail > 0:
                    print(f"  [i] 尝试重新生成...")
                    # 这里可以实现重新生成的逻辑
                    # 暂时跳过
                else:
                    raise Exception(f"内容校验失败: {validation_result.errors}")

            if validation_result.warnings:
                print(f"  [i] 校验警告: {validation_result.warnings}")

            self._update_progress(progress_callback, 85, "校验完成...")

        # 6. 完成
        self._update_progress(progress_callback, 95, "正在准备返回结果...")
        self._update_progress(progress_callback, 100, "课程生成完成!")

        return content

    def _build_prompt(
        self,
        request: CourseGenerateRequest,
        chapter_info: Optional[ChapterInfo]
    ) -> str:
        """构建生成提示词"""
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

        if chapter_info:
            # 教材章节模式
            variables.update({
                "chapter": chapter_info.chapter_name,
                "curriculum_requirement": chapter_info.curriculum_requirement,
                "knowledge_points": "、".join(chapter_info.knowledge_points),
                "key_difficulties": "、".join(chapter_info.key_difficulties),
                "common_mistakes": "、".join(chapter_info.common_mistakes),
            })
        elif request.custom_outline:
            # 自定义大纲模式 - 教师提供了详细的大纲/手稿
            variables.update({
                "chapter": request.custom_topic or "自定义课程",
                "custom_outline": request.custom_outline,
                "curriculum_requirement": "（根据自定义内容确定）",
                "knowledge_points": "（见自定义大纲）",
                "key_difficulties": "（见自定义大纲）",
                "common_mistakes": "（见自定义大纲）",
            })
        else:
            # 自定义专题模式 - 只有专题名称
            variables.update({
                "chapter": request.custom_topic or "自定义专题",
                "curriculum_requirement": "了解",
                "knowledge_points": "（根据专题内容确定）",
                "key_difficulties": "（根据专题内容确定）",
                "common_mistakes": "（根据专题内容确定）",
            })

        # 使用模板构建提示词
        if chapter_info:
            # 教材章节模式：生成学生课件
            template_name = "course_content"
        elif request.custom_outline and request.content_type:
            # 自定义内容模式：根据内容类型选择教师专用模板
            template_mapping = {
                "lesson_plan": "lesson_plan",
                "teaching_script": "teaching_script",
                "board_design": "board_design",
                "review_outline": "review_outline"
            }
            template_name = template_mapping.get(request.content_type, "custom_outline")
        elif request.custom_outline:
            # 自定义大纲模式（未指定类型）
            template_name = "custom_outline"
        else:
            # 自定义专题模式
            template_name = "course_outline"

        return self.prompt_builder.build(template_name, variables)

    def _parse_content(
        self,
        raw_content: str,
        request: CourseGenerateRequest,
        chapter_info: Optional[ChapterInfo],
        task_id: Optional[str] = None
    ) -> CourseContent:
        """解析LLM返回的内容"""
        # 尝试解析JSON
        from shared.utils import extract_json
        import logging
        import os
        from pathlib import Path

        logger = logging.getLogger(__name__)

        # 保存原始响应用于调试
        if task_id:
            try:
                output_dir = Path(os.getenv("OUTPUT_DIR", "./output"))
                debug_dir = output_dir / task_id
                debug_dir.mkdir(parents=True, exist_ok=True)
                raw_response_file = debug_dir / "llm_raw_response.txt"
                raw_response_file.write_text(raw_content, encoding="utf-8")
                logger.info(f"[DEBUG] 已保存LLM原始响应到: {raw_response_file}")
            except Exception as e:
                logger.warning(f"无法保存LLM原始响应: {e}")

        json_data = extract_json(raw_content)

        if json_data and isinstance(json_data, dict):
            # JSON格式
            logger.info(f"[DEBUG] JSON解析成功，title={json_data.get('title', 'N/A')}")
            title = json_data.get("title", "")
            sections = json_data.get("sections", {})
            # 规范化sections类型，确保所有值都是字符串
            sections = self._normalize_sections(sections)
        else:
            # JSON解析失败，尝试文本格式
            logger.warning(f"[DEBUG] JSON解析失败，尝试文本解析")
            title, sections = self._parse_text_content(raw_content, request)

        # 构建元数据
        metadata = {
            "generated_at": datetime.now().isoformat(),
            "version": request.version,
            "chapter_id": request.chapter_id,
            "content_type": request.content_type,  # 添加内容类型，用于前端识别教师自定义内容
        }

        if chapter_info:
            chapter_name = chapter_info.chapter_name
        else:
            chapter_name = request.custom_topic or "自定义专题"

        return CourseContent(
            title=title or f"{request.grade} - {chapter_name}",
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
        """解析纯文本格式的内容"""
        # 简单的文本解析逻辑
        # 实际实现可能需要更复杂的解析

        lines = text.split('\n')
        title = lines[0] if lines else ""

        # 尝试按章节分隔
        sections = {}
        current_section = None
        current_content = []

        # 章节标记到标准名称的映射
        section_markers = {
            "课程导入": "导入",
            "导入": "导入",
            "学习目标": "学习目标",
            "教学目标": "学习目标",
            "课程目标": "学习目标",
            "目标": "学习目标",
            "知识点详解": "知识点详解",
            "核心知识点": "知识点详解",
            "典例精讲": "典例精讲",
            "例题": "典例精讲",
            "易错点": "易错点",
            "易错点避雷": "易错点",
            "随堂小测": "随堂小测",
            "练习": "随堂小测",
            "知识框架": "知识框架",
            "知识点框架": "知识框架",
            "课后拓展": "课后拓展",
            "拓展": "课后拓展",
        }

        for line in lines[1:]:
            line = line.strip()
            if not line:
                continue

            # 检查是否是章节标题
            is_section = False
            normalized_section_name = None
            for marker, standard_name in section_markers.items():
                if marker in line:
                    if current_section:
                        sections[current_section] = "\n".join(current_content)
                    # 使用标准化的章节名称，而不是原始行
                    current_section = standard_name
                    current_content = []
                    is_section = True
                    normalized_section_name = standard_name
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

    def _normalize_sections(self, sections: Dict) -> Dict[str, str]:
        """
        规范化sections字典，确保所有值都是字符串类型

        Args:
            sections: 原始sections字典（可能包含list、dict等类型）

        Returns:
            规范化后的sections字典（所有值都是字符串）
        """
        normalized = {}
        import json

        for section_name, section_content in sections.items():
            if isinstance(section_content, str):
                # 已经是字符串，直接使用
                normalized[section_name] = section_content
            elif isinstance(section_content, list):
                # 列表转换为换行分隔的字符串
                normalized[section_name] = "\n".join(str(item) for item in section_content)
            elif isinstance(section_content, dict):
                # 字典转换为JSON字符串
                normalized[section_name] = json.dumps(section_content, ensure_ascii=False)
            else:
                # 其他类型转换为字符串
                normalized[section_name] = str(section_content)

        return normalized

    def _get_version_name(self, version: str) -> str:
        """获取版本的中文名称"""
        version_names = {
            "renjiao_v1": "人教版",
            "beishi_v1": "北师大版",
            "suke_v1": "苏科版",
            "huke_v1": "沪科版",
        }
        return version_names.get(version, version)

    def _update_progress(self, callback: Optional[callable], percent: int, message: str):
        """更新进度"""
        if callback:
            callback(percent, message)

    async def generate_outline(
        self,
        grade: str,
        topic: str,
        progress_callback: Optional[callable] = None
    ) -> Dict:
        """
        生成自定义专题大纲

        Args:
            grade: 年级
            topic: 专题名称
            progress_callback: 进度回调

        Returns:
            大纲内容（字典格式）
        """
        self._update_progress(progress_callback, 20, "正在生成大纲...")

        # 构建提示词
        prompt = self.prompt_builder.build("course_outline", {
            "grade": grade,
            "topic": topic
        })

        # 调用LLM
        response = await self.llm_client.call(LLMRequest(
            messages=[{"role": "system", "content": prompt}]
        ))

        if not response.success:
            raise Exception(f"LLM调用失败: {response.error}")

        # 解析JSON
        from shared.utils import extract_json
        outline = extract_json(response.content)

        if not outline:
            raise Exception("无法解析大纲JSON")

        self._update_progress(progress_callback, 100, "大纲生成完成!")

        return outline

    def _generate_batch_summary(self, batch_result: Dict, batch_num: int) -> str:
        """
        生成批次内容的摘要，供后续批次使用

        支持两种输入格式：
        1. 完整格式：{"title": "...", "sections": {...}}
        2. 简化格式：{"导入": "...", "学习目标": "...", ...}
        """
        # 智能提取sections：兼容两种输入格式
        if "sections" in batch_result:
            # 完整格式
            sections = batch_result["sections"]
        else:
            # 简化格式：直接使用batch_result作为sections
            sections = batch_result

        summary_parts = []

        # 导入摘要
        if "导入" in sections:
            import_text = sections["导入"]
            summary_parts.append(f"导入：{import_text[:100]}...")

        # 学习目标摘要
        if "学习目标" in sections:
            objectives = sections["学习目标"]
            objectives_list = [obj.strip() for obj in objectives.split('。') if obj.strip()]
            summary_parts.append(f"学习目标：{'; '.join(objectives_list[:3])}")

        # 知识点详解摘要
        if "知识点详解" in sections or "知识点详解_A" in sections:
            knowledge = sections.get("知识点详解", sections.get("知识点详解_A", ""))
            knowledge_points = self._extract_knowledge_points_list(knowledge)
            if knowledge_points:
                summary_parts.append(f"已生成知识点：{'; '.join(knowledge_points)}")

        return "\n\n".join(summary_parts)

    def _extract_knowledge_points_summary(self, knowledge_detail: str) -> str:
        """从知识点详解中提取知识点摘要"""
        knowledge_points = self._extract_knowledge_points_list(knowledge_detail)
        if knowledge_points:
            return f"已生成的知识点：{'; '.join(knowledge_points)}"
        return "已生成部分知识点"

    def _extract_knowledge_points_list(self, knowledge_text: str) -> List[str]:
        """从知识点详解文本中提取知识点列表"""
        import re
        knowledge_points = []

        # 尝试匹配【一、...】【二、】...等标记
        pattern = r'【([一二三四五六七八九十\d]+)、([^】]+)】'
        matches = re.findall(pattern, knowledge_text)
        for num, name in matches:
            knowledge_points.append(f"{name}")

        # 如果没有找到【】标记，尝试按段落分割
        if not knowledge_points:
            paragraphs = re.split(r'\n\s*\n', knowledge_text)
            for para in paragraphs[:5]:
                para = para.strip()
                if para and len(para) > 10:
                    knowledge_points.append(para[:15].replace('\n', ' '))

        return knowledge_points

    def _merge_knowledge_details(self, detail_a: str, detail_b: str) -> str:
        """
        合并两部分的知识点详解（容错版本 - 方案1）

        包含括号平衡检查和异常处理，确保即使遇到复杂格式也能正常合并
        """
        import re

        # 防御性检查：确保输入有效
        if not detail_a:
            logger.warning(f"[课程生成] 知识点合并：detail_a为空")
            return detail_b or ""
        if not detail_b:
            logger.warning(f"[课程生成] 知识点合并：detail_b为空")
            return detail_a

        # 方案1：尝试智能合并（带重新编号）
        try:
            # 检查括号平衡：简单检查括号是否成对
            def check_parentheses(text):
                """检查文本中括号是否基本平衡"""
                left_count = text.count('（') + text.count('(') + text.count('【')
                right_count = text.count('）') + text.count(')') + text.count('】')
                return left_count == right_count

            # 如果两部分都有括号不平衡问题，记录警告
            if not check_parentheses(detail_a):
                logger.warning(f"[课程生成] detail_a可能存在括号不平衡")
            if not check_parentheses(detail_b):
                logger.warning(f"[课程生成] detail_b可能存在括号不平衡")

            # 统计前半部分的知识点数量
            prefix_count_list = [len(re.findall(r'【[一二三四五六七八九十\d]+)、', detail_a))]

            # 将后半部分的标记重新编号，接上前半部分
            def renumber(match):
                prefix_count_list[0] += 1
                chinese_nums = ['一', '二', '三', '四', '五', '六', '七', '八', '九', '十']
                num = prefix_count_list[0]
                if num <= 10:
                    return f'【{chinese_nums[num-1]}、'
                return f'【{num}、'

            # 检查是否需要重新编号（增加额外的安全检查）
            has_numbering = bool(re.search(r'【[一二三四五六七八九十\d]+)、', detail_b))

            if has_numbering:
                # 使用限制性更强的正则，避免误匹配
                try:
                    # 只匹配简单的【数字、】模式，不处理嵌套括号
                    detail_b_content = re.sub(r'(?<!【)\【([一二三四五六七八九十\d]+)、(?![^】]*】)', renumber, detail_b)
                except Exception as regex_error:
                    logger.warning(f"[课程生成] 正则重新编号失败: {regex_error}")
                    detail_b_content = detail_b
            else:
                detail_b_content = detail_b

            logger.info(f"[课程生成] 知识点合并成功，使用重新编号")
            return detail_a + "\n\n" + detail_b_content

        except Exception as merge_error:
            # ============ 降级策略：直接拼接 ============
            logger.warning(f"[课程生成] 智能合并失败，使用降级策略: {merge_error}")
            logger.info(f"[课程生成] 降级策略：直接拼接两部分内容")

            # 直接拼接，不进行任何重新编号处理
            result = detail_a + "\n\n" + detail_b

            # 验证拼接结果的基本有效性
            if len(result) < len(detail_a) + len(detail_b):
                logger.error(f"[课程生成] 拼接结果长度异常，可能存在内容丢失")
            else:
                logger.info(f"[课程生成] 降级拼接成功，总长度: {len(result)} 字符")

            return result

    def _extract_examples_summary(self, examples_text: str) -> str:
        """从典例精讲文本中提取例题摘要"""
        import re
        summary_parts = []

        # 提取例题信息
        pattern = r'【例题(\d+)】'
        matches = re.findall(pattern, examples_text)
        if matches:
            summary_parts.append(f"已生成例题：{', '.join(f'例题{m}' for m in matches)}")

        # 提取例题涉及的知识点
        topics = []
        for match in re.finditer(r'【题目】([^\n]{5,50})', examples_text):
            topic = match.group(1).strip()
            if len(topic) > 5:
                topics.append(f"例题涉及：{topic[:20]}...")

        if topics:
            summary_parts.extend(topics[:2])

        return "\n".join(summary_parts) if summary_parts else "已生成部分例题"

    def _merge_all_batches(
        self, batch1: Dict, batch2: Dict, batch3: Dict, batch4: Dict,
        combined_knowledge: str, title: str, grade: str, chapter: str
    ) -> Dict:
        """合并所有4批的结果（2025升级版 - 兼容扁平和嵌套JSON）"""
        result = {
            "title": title,
            "grade": grade,
            "chapter": chapter if chapter else "未知章节",
            "sections": {}
        }

        # 获取sections（兼容两种格式）
        # 格式1: {"sections": {...}}
        # 格式2: {"key": "value", ...}（扁平）
        def get_sections(batch: Dict) -> Dict:
            """从批次结果中提取sections，兼容两种格式"""
            if "sections" in batch:
                return batch["sections"]
            # 如果没有sections键，假设整个batch就是sections
            return batch

        sections1 = get_sections(batch1)
        sections3 = get_sections(batch3)
        sections4 = get_sections(batch4)

        # 从第1批获取
        if "导入" in sections1:
            result["sections"]["导入"] = sections1["导入"]
        if "学习目标" in sections1:
            result["sections"]["学习目标"] = sections1["学习目标"]

        # 合并知识点详解
        result["sections"]["知识点详解"] = combined_knowledge

        # 合并典例精讲
        examples_a = sections3.get("典例精讲_A", "")
        examples_b = sections4.get("典例精讲_B", "")
        if examples_a and examples_b:
            result["sections"]["典例精讲"] = examples_a + "\n\n" + examples_b
        elif examples_a:
            result["sections"]["典例精讲"] = examples_a
        elif examples_b:
            result["sections"]["典例精讲"] = examples_b

        # 从第4批获取其他sections（2025升级版 - 修复）
        for section_name in ["易错点", "随堂小测", "知识框架", "课后拓展"]:
            if section_name in sections4:
                result["sections"][section_name] = sections4[section_name]
                logger.info(f"[课程生成] 合并section: {section_name}")

        logger.info(f"[课程生成] 最终合并sections数量: {len(result['sections'])}")
        return result


# ==================== 便捷函数 ====================

async def generate_course(
    version: str,
    grade: str,
    chapter_id: str,
    student_level: str = "中等巩固",
    purpose: str = "学生自学",
    api_key: str = None
) -> CourseContent:
    """
    便捷的课程生成函数

    Args:
        version: 教材版本
        grade: 年级
        chapter_id: 章节ID
        student_level: 学情
        purpose: 用途
        api_key: API密钥

    Returns:
        课程内容
    """
    config = CourseGeneratorConfig(
        llm_config=LLMConfig(api_key=api_key)
    )
    generator = CourseGenerator(config)

    request = CourseGenerateRequest(
        version=version,
        grade=grade,
        chapter_id=chapter_id,
        student_level=student_level,
        purpose=purpose
    )

    return await generator.generate(request)

