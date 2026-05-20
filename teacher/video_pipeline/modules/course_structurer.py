"""
结构化内容生成器 - CourseStructurer

将非结构化内容转换为标准的 course.json 格式
供简化流程使用
"""

import logging
from typing import Dict, Any, Optional, List
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class CourseStructureResult:
    """结构化内容生成结果"""
    success: bool
    course_json: Optional[Dict[str, Any]] = None
    error: Optional[str] = None
    partial: bool = False  # 是否为部分结果（分批生成时第二批失败）
    missing_sections: Optional[List[str]] = None  # 缺失的sections列表


class CourseStructurer:
    """
    结构化内容生成器

    功能: 将主题或简短内容转换为完整的 course.json 格式
    用途: 让简化流程支持任意输入
    """

    def __init__(self, llm_client):
        """
        初始化

        Args:
            llm_client: LLM 客户端
        """
        self.llm_client = llm_client

    async def structure_content(
        self,
        title: str,
        content: str = "",
        grade: str = "初中",
        chapter: str = ""
    ) -> CourseStructureResult:
        """
        将非结构化内容转换为 course.json 格式

        Args:
            title: 课程标题/主题
            content: 可选的详细内容
            grade: 年级
            chapter: 章节

        Returns:
            CourseStructureResult
        """
        from shared.llm_client import LLMRequest, LLMResponse

        logger.info(f"[结构化生成] 开始: {title}")
        logger.info(f"[结构化生成] 年级: {grade}, 章节: {chapter}")

        # 构建提示词
        prompt = f"""# 任务
你是一位经验丰富的初中数学教师，需要为课程生成结构化内容。

# 课程信息
- 标题/主题: {title}
- 年级: {grade}
- 章节: {chapter if chapter else "自动推断"}
{"- 参考内容: " + content if content else ""}

# 要求
生成完整的课程结构化内容，包含以下8个section（每个section都要详细、分点分段论述）：

## 内容组织要求（重要）

**每个section都必须做到：**
1. **分点分段**：使用清晰的分段标记，如【一、】、【二、】等
2. **详细论述**：每个知识点至少3-5句话详细解释
3. **层次分明**：主标题、副标题、要点层层展开
4. **具体举例**：每个概念后给出数学实例说明（使用"例如"、"如"等学术化表达）
5. **避免省略**：不要用"..."、"等等"表示省略

**【重要】整体语言风格要求**：
- **知识点详解部分**：使用学术化、规范化的数学语言
- 客观陈述，不使用对话式表达（如"我们来"、"大家看"、"同学们"等）
- 不使用拟人化、情感化描述（如"大家庭"、"朋友"等）
- 使用"例如"、"如下"等学术化连接词，而非"举个例子"
- 直接给出定义、性质、公式，避免冗长铺垫和叙述性描述

## 8个section的具体要求

1. **导入**（2-3段）
   - 第一段：生活实例或问题情境（具体描述）
   - 第二段：引出本节课要解决的问题
   - 第三段：激发学生思考的提问

2. **学习目标**（2-3段，分点列出）
   - 知识与技能目标：学生要掌握什么知识点、什么技能
   - 过程与方法目标：通过什么方法学习
   - 情感态度价值观目标：培养什么思维品质
   - 格式：使用"1. ""2. ""3. "分点列出

3. **知识点详解**（5-8段，最详细）
   - 【一、定义】详细解释概念（2-3段）
     * 第一段：使用学术化语言直接陈述概念
     * 第二段：给出严格数学定义
     * 第三段：概念辨析与注意事项
   - 【二、性质/公式】分条列出（每条1-2段）
     * 性质1：陈述性质+数学表达式+应用举例
     * 性质2：陈述性质+数学表达式+应用举例
   - 【三、适用范围】说明使用条件
   - 【四、注意事项】提醒要点

   **【重要】知识点详解的语言风格要求**：
   - 使用学术化、规范化的数学语言
   - 客观陈述知识点，不使用对话式表达（如"我们来"、"大家看"等）
   - 不使用拟人化、情感化描述（如"大家庭"、"朋友"等）
   - 直接给出定义、性质、公式，避免冗长铺垫
   - 举例用于说明概念，而非讲故事

4. **典例精讲**（3-5道例题，**每题可拆分为1-2页**）
   - **分页原则**：简单例题1页完成，复杂例题拆分为2页
   - **拆分方案**：
     * 第1页：【题目】+【思路引导】（审题和分析）
     * 第2页：【完整步骤】+【答案】+【易错提醒】（求解和总结）
   - **标题规范**：只写"例题1"、"例题1（续）"、"例题2"等，**严禁**把题目内容放在标题中
   - **分页方式**：不同例题用"===分页==="，同一例题拆分用"===续页==="

   简单例题格式（1页完成）：
   【例题1】
   【题目】计算：2x + 3 = 7
   【思路引导】这是一元一次方程，需要通过移项求解
   【完整步骤】①移项得 2x = 4 ②求解得 x = 2
   【答案】x = 2
   【易错提醒】移项时要变号

   ===分页===

   复杂例题格式（拆分为2页）：
   【例题2】
   【题目】计算：-1^4 + (1 - 0.5) × 1/3 × [2 - (-3)²]
   【思路引导】这是有理数混合运算，先确定运算顺序：乘方→括号→乘除→加减

   ===续页===

   【例题2（续）】
   【完整步骤】①先算乘方：-1^4 = -1，(-3)² = 9  ②算括号：1 - 0.5 = 0.5，2 - 9 = -7  ③算乘除：0.5 × 1/3 × (-7) = -7/6  ④算加减：-1 + (-7/6) = -13/6
   【答案】-13/6
   【易错提醒】注意-1^4 = -1而不是1

5. **易错点**（3-5个，每个详细）
   - 易错点1：错误现象→错误原因→正确做法
   - 易错点2：错误现象→错误原因→正确做法
   - 每个易错点用具体例子说明

6. **随堂小测**（3-5题，每2题一组分页）
   - 【第1组】练习题1-2：完整题目
   - ===分页===
   - 【第2组】练习题3-4：完整题目
   - ===分页===（如果有练习题5）
   - 【第3组】练习题5：完整题目
   - **重要**：每2道题用"===分页==="分隔，确保PDF每页最多2道题

   示例格式：
   【第1组】
   练习题1：计算 2x + 3 = 7

   练习题2：解方程 x - 1 = 3

   ===分页===

   【第2组】
   练习题3：...

7. **知识框架**（结构化总结）
   - 使用分层结构呈现
   - 包含本节课所有核心内容

8. **课后拓展**（2-3个拓展方向）
   - 拓展1：具体内容
   - 拓展2：具体内容
   - 每个拓展要具体可行

# 输出格式（纯JSON，不要其他内容）
```json
{{
  "title": "{title}",
  "grade": "{grade}",
  "chapter": "{'第X章' if not chapter else chapter}",
  "sections": {{
    "导入": "第一段内容。第二段内容。第三段内容。",
    "学习目标": "1. 知识与技能：掌握... 2. 过程与方法：通过... 3. 情感态度：培养...",
    "知识点详解": "【一、定义】概念阐述...数学定义...概念辨析...【二、性质】性质1陈述+数学表达式+实例...性质2陈述+数学表达式+实例...",
    "典例精讲": "【例题1】\\n【题目】计算：2x + 3 = 7\\n【思路引导】这是一元一次方程，需要通过移项求解\\n【完整步骤】①移项得 2x = 4 ②求解得 x = 2\\n【答案】x = 2\\n【易错提醒】移项时要变号\\n\\n===分页===\\n\\n【例题2】\\n【题目】计算：-1^4 + (1 - 0.5) × 1/3 × [2 - (-3)²]\\n【思路引导】这是有理数混合运算，先确定运算顺序：乘方→括号→乘除→加减\\n\\n===续页===\\n\\n【例题2（续）】\\n【完整步骤】①先算乘方：-1^4 = -1，(-3)² = 9  ②算括号：1 - 0.5 = 0.5，2 - 9 = -7  ③算乘除：0.5 × 1/3 × (-7) = -7/6  ④算加减：-1 + (-7/6) = -13/6\\n【答案】-13/6\\n【易错提醒】注意-1^4 = -1而不是1\\n\\n===分页===\\n\\n【例题3】\\n【题目】...\\n【思路引导】...\\n【完整步骤】...\\n【答案】...\\n【易错提醒】...",
    "易错点": "易错点1：...错误原因：...正确做法：...易错点2：...",
    "随堂小测": "【第1组】练习题1：完整题目...练习题2：完整题目...\\n\\n===分页===\\n\\n【第2组】练习题3：完整题目...",
    "知识框架": "本节课知识结构：...",
    "课后拓展": "仅1个！生活应用题或思维拓展题（严格限制，不要写多个）"
  }}
}}
```

# 内容质量检查清单
- [ ] 每个section是否分点分段？
- [ ] 每个知识点是否详细论述（不少于3句话）？
- [ ] 是否有具体例子说明？
- [ ] 是否避免使用省略号"..."？
- [ ] 例题和练习是否完整？

请开始生成:"""

        try:
            # ===== 4批分批生成策略（2025年升级版） =====
            # 适用于长章节内容，避免单次生成截断
            # 第1批：导入 + 学习目标 + 知识点详解_A（前半部分）
            # 第2批：知识点详解_B（后半部分）+ 摘要传递
            # 第3批：典例精讲_A（前半部分例题）+ 摘要传递
            # 第4批：典例精讲_B（后半部分）+ 易错点 + 其他sections + 摘要传递

            logger.info(f"[结构化生成] ===== 使用4批分批生成策略（2025升级版） =====")

            import json
            from shared.utils import extract_json

            # ==================== 第1批：导入 + 学习目标 + 知识点详解_A ====================
            logger.info(f"[结构化生成] ===== 第1批开始：导入 + 学习目标 + 知识详解（前半） =====")

            batch1_prompt = prompt + f"""

# 重要提示（分批生成）
本次是第1批生成，请生成以下3个section：
1. **导入**
2. **学习目标**
3. **知识点详解_A**（只生成前半部分的知识点，约占全部知识点的50%）

请按以下JSON格式输出：
```json
{{
  "title": "{title}",
  "grade": "{grade}",
  "chapter": "{chapter if chapter else '第X章'}",
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
- 每个知识点详细论述，至少3-5句话
- 停在适当位置，不要试图生成所有知识点

请开始生成第1批内容:"""

            request1 = LLMRequest(
                messages=[{"role": "user", "content": batch1_prompt}],
                temperature=0.1,
                max_tokens=16000
            )

            response1: LLMResponse = await self.llm_client.call(request1)

            if not response1.success:
                logger.error(f"[结构化生成] 第1批LLM调用失败: {response1.error}")
                return CourseStructureResult(
                    success=False,
                    error=f"第1批LLM调用失败: {response1.error}"
                )

            result1 = extract_json(response1.content)
            if not result1 or "sections" not in result1:
                logger.error(f"[结构化生成] 第1批解析失败")
                return CourseStructureResult(
                    success=False,
                    error="第1批解析失败"
                )

            logger.info(f"[结构化生成] 第1批成功，已生成: {list(result1['sections'].keys())}")

            # 生成第1批的摘要（供后续批次使用）
            summary1 = self._generate_batch_summary(result1, batch_num=1)
            logger.info(f"[结构化生成] 第1批摘要已生成")

            # ==================== 第2批：知识点详解_B（后半部分） ====================
            logger.info(f"[结构化生成] ===== 第2批开始：知识点详解（后半部分） =====")
            logger.info(f"[结构化生成] 第1批摘要：{summary1[:150]}...")

            # 提取已生成的知识点列表
            knowledge_points_summary = self._extract_knowledge_points_summary(
                result1['sections'].get('知识点详解_A', '')
            )

            batch2_prompt = f"""# 任务
继续为课程生成剩余内容。

# 课程信息
- 标题：{title}
- 年级：{grade}
- 章节：{chapter if chapter else "未知章节"}

# 前面已生成的内容摘要
{summary1}

# 已生成的知识点
{knowledge_points_summary}

# 本次任务
请生成**知识点详解_B**（后半部分的知识点）：
- 继续生成剩余的知识点（如：运算、应用、综合等）
- 与前面已生成的知识点保持连贯，不要重复
- 使用【四、】【五、】等标记继续编号
- 每个知识点详细论述，至少3-5句话

请按以下JSON格式输出：
```json
{{
  "知识点详解_B": "【四、...】【五、】...（后半部分知识点，继续编号）"
}}
```

请开始生成第2批内容:"""

            request2 = LLMRequest(
                messages=[{"role": "user", "content": batch2_prompt}],
                temperature=0.1,
                max_tokens=16000
            )

            response2: LLMResponse = await self.llm_client.call(request2)

            if not response2.success:
                logger.error(f"[结构化生成] 第2批LLM调用失败: {response2.error}")
                # 返回部分结果
                result1["partial"] = True
                result1["missing_sections"] = ["知识点详解_B", "典例精讲", "易错点", "随堂小测", "知识框架", "课后拓展"]
                return CourseStructureResult(
                    success=True,
                    course_json=self._convert_batch1_to_final(result1),
                    partial=True,
                    missing_sections=["知识点详解_B", "典例精讲", "易错点", "随堂小测", "知识框架", "课后拓展"]
                )

            result2 = extract_json(response2.content)
            if not result2:
                logger.error(f"[结构化生成] 第2批解析失败")
                return CourseStructureResult(
                    success=False,
                    error="第2批解析失败"
                )

            logger.info(f"[结构化生成] 第2批成功，已生成: {list(result2.keys())}")

            # 合并知识点详解
            combined_knowledge_detail = self._merge_knowledge_details(
                result1['sections'].get('知识点详解_A', ''),
                result2.get('知识点详解_B', '')
            )

            # 生成第2批的摘要
            summary2 = self._generate_batch_summary({
                "导入": result1['sections'].get('导入', ''),
                "学习目标": result1['sections'].get('学习目标', ''),
                "知识点详解": combined_knowledge_detail
            }, batch_num=2)

            # ==================== 第3批：典例精讲_A（前半部分例题） ====================
            logger.info(f"[结构化生成] ===== 第3批开始：典例精讲（前半例题） =====")
            logger.info(f"[结构化生成] 第2批摘要：{summary2[:150]}...")

            batch3_prompt = f"""# 任务
继续为课程生成剩余内容。

# 课程信息
- 标题：{title}
- 年级：{grade}

# 前面已生成的内容摘要
{summary2}

# 本次任务
请生成**典例精讲_A**（前半部分例题）：
- 生成前2道例题（例题1、例题2）
- 例题应覆盖前面已生成的主要知识点
- 每道例题包含：题目、思路引导、完整步骤、答案、易错提醒
- 不同例题间用"===分页==="分隔

请按以下JSON格式输出：
```json
{{
  "典例精讲_A": "【例题1】\\n【题目】...\\n【思路引导】...\\n【完整步骤】...\\n【答案】...\\n【易错提醒】...\\n\\n===分页===\\n\\n【例题2】..."
}}
```

请开始生成第3批内容:"""

            request3 = LLMRequest(
                messages=[{"role": "user", "content": batch3_prompt}],
                temperature=0.1,
                max_tokens=16000
            )

            response3: LLMResponse = await self.llm_client.call(request3)

            if not response3.success:
                logger.error(f"[结构化生成] 第3批LLM调用失败: {response3.error}")
                # 返回部分结果
                partial_result = self._convert_batch1_2_to_final(result1, result2, combined_knowledge_detail)
                partial_result["partial"] = True
                partial_result["missing_sections"] = ["典例精讲_B", "易错点", "随堂小测", "知识框架", "课后拓展"]
                return CourseStructureResult(
                    success=True,
                    course_json=partial_result,
                    partial=True,
                    missing_sections=["典例精讲_B", "易错点", "随堂小测", "知识框架", "课后拓展"]
                )

            result3 = extract_json(response3.content)
            if not result3:
                logger.error(f"[结构化生成] 第3批解析失败")
                return CourseStructureResult(
                    success=False,
                    error="第3批解析失败"
                )

            logger.info(f"[结构化生成] 第3批成功，已生成: {list(result3.keys())}")

            # ==================== 第4批：典例精讲_B + 易错点 + 其他sections ====================
            logger.info(f"[结构化生成] ===== 第4批开始：典例精讲（后半）+ 其他sections =====")
            logger.info(f"[结构化生成] 第3批摘要（例题）：{examples_summary[:150]}...")

            # 提取已生成的例题信息
            examples_summary = self._extract_examples_summary(result3.get('典例精讲_A', ''))

            batch4_prompt = f"""# 任务
继续为课程生成最后的内容。

# 课程信息
- 标题：{title}
- 年级：{grade}

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
  "典例精讲_B": "【例题3】\\n【题目】...\\n【思路引导】...\\n【完整步骤】...\\n【答案】...\\n【易错提醒】...\\n\\n===分页===\\n\\n【例题4】...",
  "易错点": "易错点1：...错误原因：...正确做法：...易错点2：...",
  "随堂小测": "【第1组】练习题1...练习题2...\\n\\n===分页===\\n\\n【第2组】练习题3...",
  "知识框架": "本节课知识结构：...",
  "课后拓展": "仅1个！生活应用题或思维拓展题（严格限制，不要写多个）"
}}
```

请开始生成第4批内容:"""

            request4 = LLMRequest(
                messages=[{"role": "user", "content": batch4_prompt}],
                temperature=0.1,
                max_tokens=16000
            )

            response4: LLMResponse = await self.llm_client.call(request4)

            if not response4.success:
                logger.error(f"[结构化生成] 第4批LLM调用失败: {response4.error}")
                # 返回部分结果
                partial_result = self._convert_batch1_2_3_to_final(
                    result1, result2, result3, combined_knowledge_detail
                )
                partial_result["partial"] = True
                partial_result["missing_sections"] = ["典例精讲_B", "易错点", "随堂小测", "知识框架", "课后拓展"]
                return CourseStructureResult(
                    success=True,
                    course_json=partial_result,
                    partial=True,
                    missing_sections=["典例精讲_B", "易错点", "随堂小测", "知识框架", "课后拓展"]
                )

            result4 = extract_json(response4.content)
            if not result4:
                logger.error(f"[结构化生成] 第4批解析失败")
                return CourseStructureResult(
                    success=False,
                    error="第4批解析失败"
                )

            logger.info(f"[结构化生成] 第4批成功，已生成: {list(result4.keys())}")

            # ==================== 合并所有批次结果 ====================
            result = self._merge_all_batches(
                result1, result2, result3, result4,
                combined_knowledge_detail, title, grade, chapter
            )

            logger.info(f"[结构化生成] ===== 4批生成完成，共{len(result['sections'])}个sections =====")
            logger.info(f"[结构化生成] 最终sections列表: {list(result['sections'].keys())}")

            # ==================== 增强验证：检测重复、遗漏、逻辑断裂 ====================
            logger.info(f"[结构化生成] ===== 开始增强验证（2025升级版） =====")
            required_sections = ["导入", "学习目标", "知识点详解", "典例精讲", "易错点", "随堂小测", "知识框架", "课后拓展"]
            missing_sections = []
            incomplete_sections = []
            low_quality_sections = []

            for section in required_sections:
                if section not in result["sections"]:
                    missing_sections.append(section)
                else:
                    content = result["sections"][section]

                    # 检查1：是否有省略标记
                    if "..." in content or "……" in content or "等等" in content:
                        incomplete_sections.append(section)

                    # 检查2：内容质量（字数和结构）
                    quality_check = self._check_content_quality(section, content)
                    if not quality_check["passed"]:
                        low_quality_sections.append(f"{section}({quality_check['reason']})")
                        logger.warning(f"[结构化生成] '{section}'内容质量不足: {quality_check['reason']}")

            # ==================== 增强验证：检测重复、遗漏、逻辑断裂 ====================
            validation_result = await self._advanced_validation(result, title, grade, chapter)

            logger.info(f"[结构化生成] 验证结果：重复={validation_result['has_duplicates']}, 断裂={validation_result['has_gaps']}")

            if validation_result["has_duplicates"]:
                logger.warning(f"[结构化生成] 检测到重复内容: {validation_result['duplicates']}")
                logger.info(f"[结构化生成] 尝试自动修复重复内容...")
                # 尝试修复重复内容
                result = await self._fix_duplicates(result, validation_result['duplicates'], title, grade, chapter)
                logger.info(f"[结构化生成] 重复内容修复完成")

            if validation_result["has_gaps"]:
                logger.warning(f"[结构化生成] 检测到逻辑断裂: {validation_result['gaps']}")
                logger.info(f"[结构化生成] 尝试自动修复逻辑断裂...")
                # 尝试修复逻辑断裂
                result = await self._fix_gaps(result, validation_result['gaps'], title, grade, chapter)
                logger.info(f"[结构化生成] 逻辑断裂修复完成")

            if missing_sections:
                logger.warning(f"[结构化生成] 缺少section: {missing_sections}")
                return CourseStructureResult(
                    success=False,
                    error=f"缺少section: {missing_sections}"
                )

            if incomplete_sections:
                logger.warning(f"[结构化生成] section包含省略标记: {incomplete_sections}")
                # 尝试重新生成不完整的section
                result = await self._regenerate_incomplete_sections(
                    result, incomplete_sections, title, grade, chapter
                )

            if low_quality_sections:
                logger.warning(f"[结构化生成] 内容质量不足的section: {low_quality_sections}")
                # 对于质量不足的section，尝试重新生成
                sections_to_regenerate = [s.split('(')[0] for s in low_quality_sections]
                result = await self._regenerate_incomplete_sections(
                    result, sections_to_regenerate, title, grade, chapter
                )

            # 确保基本信息完整
            if "title" not in result:
                result["title"] = title
            if "grade" not in result:
                result["grade"] = grade
            if "chapter" not in result:
                result["chapter"] = chapter if chapter else "未知章节"

            logger.info(f"[结构化生成] ===== 课件生成成功（2025升级版） =====")
            logger.info(f"[结构化生成] 最终输出：8个sections全部生成完成")
            return CourseStructureResult(
                success=True,
                course_json=result
            )

        except Exception as e:
            logger.error(f"[结构化生成] 异常: {e}")
            import traceback
            logger.error(traceback.format_exc())
            return CourseStructureResult(
                success=False,
                error=f"生成异常: {str(e)}"
            )

    async def _regenerate_incomplete_sections(
        self,
        course_json: Dict,
        incomplete_sections: list,
        title: str,
        grade: str,
        chapter: str
    ) -> Dict:
        """
        重新生成不完整的section

        Args:
            course_json: 当前的course.json
            incomplete_sections: 需要重新生成的section列表
            title: 课程标题
            grade: 年级
            chapter: 章节

        Returns:
            更新后的course_json
        """
        from shared.llm_client import LLMRequest, LLMResponse

        logger.info(f"[结构化生成] 重新生成不完整section: {incomplete_sections}")

        sections_to_regenerate = "、".join(incomplete_sections)

        prompt = f"""# 任务
你需要重新生成课程中的某些section，要求内容完整、具体，不要使用省略标记。

# 课程信息
- 标题: {title}
- 年级: {grade}
- 章节: {chapter}

# 需要重新生成的section
{sections_to_regenerate}

# 要求
- 内容要完整、具体，不要使用"..."、"……"、"等等"等省略标记
- 内容要符合初中学生的认知水平
- 每个section至少150字

# 输出格式（纯JSON，不要其他内容）
```json
{{"""

        for section in incomplete_sections:
            prompt += f'\n  "{section}": "完整具体的内容...",'

        prompt = prompt.rstrip(',') + "\n}\n```"

        try:
            request = LLMRequest(
                messages=[{"role": "user", "content": prompt}],
                temperature=0.1,
                max_tokens=16000
            )

            response: LLMResponse = await self.llm_client.call(request)

            if response.success:
                import json
                from shared.utils import extract_json

                result = extract_json(response.content)
                if result:
                    # 更新不完整的section
                    for section, content in result.items():
                        if section in incomplete_sections:
                            course_json["sections"][section] = content
                            logger.info(f"[结构化生成] 已更新: {section}")

        except Exception as e:
            logger.error(f"[结构化生成] 重新生成失败: {e}")

    def _generate_batch_summary(self, batch_result: Dict, batch_num: int) -> str:
        """
        生成批次内容的摘要，供后续批次使用

        Args:
            batch_result: 批次生成结果
            batch_num: 批次编号

        Returns:
            摘要文本
        """
        sections = batch_result.get("sections", {})
        summary_parts = []

        # 导入摘要
        if "导入" in sections:
            import_text = sections["导入"]
            summary_parts.append(f"导入：{import_text[:100]}...")

        # 学习目标摘要
        if "学习目标" in sections:
            objectives = sections["学习目标"]
            # 提取关键学习目标
            objectives_list = [obj.strip() for obj in objectives.split('。') if obj.strip()]
            summary_parts.append(f"学习目标：{'; '.join(objectives_list[:3])}")

        # 知识点详解摘要
        if "知识点详解" in sections or "知识点详解_A" in sections:
            knowledge = sections.get("知识点详解", sections.get("知识点详解_A", ""))
            # 提取知识点列表
            knowledge_points = self._extract_knowledge_points_list(knowledge)
            if knowledge_points:
                summary_parts.append(f"已生成知识点：{'; '.join(knowledge_points)}")

        return "\n\n".join(summary_parts)

    def _extract_knowledge_points_summary(self, knowledge_detail: str) -> str:
        """
        从知识点详解中提取知识点摘要

        Args:
            knowledge_detail: 知识点详解文本

        Returns:
            知识点摘要文本
        """
        knowledge_points = self._extract_knowledge_points_list(knowledge_detail)
        if knowledge_points:
            return f"已生成的知识点：{'; '.join(knowledge_points)}"
        return "已生成部分知识点"

    def _extract_knowledge_points_list(self, knowledge_text: str) -> List[str]:
        """
        从知识点详解文本中提取知识点列表

        Args:
            knowledge_text: 知识点详解文本

        Returns:
            知识点名称列表
        """
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
            for para in paragraphs[:5]:  # 最多取前5段
                para = para.strip()
                if para and len(para) > 10:
                    # 提取前15个字作为知识点名称
                    knowledge_points.append(para[:15].replace('\n', ' '))

        return knowledge_points

    def _merge_knowledge_details(self, detail_a: str, detail_b: str) -> str:
        """
        合并两部分的知识点详解

        Args:
            detail_a: 知识点详解_A（前半部分）
            detail_b: 知识点详解_B（后半部分）

        Returns:
            合并后的完整知识点详解
        """
        import re

        # 提取detail_b中的实际内容（去掉可能存在的标记）
        detail_b_content = detail_b

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

        # 检查是否需要重新编号
        if re.search(r'【[一二三四五六七八九十\d]+)、', detail_b):
            detail_b_content = re.sub(r'【[一二三四五六七八九十\d]+)、', renumber, detail_b)

        return detail_a + "\n\n" + detail_b_content

    def _convert_batch1_to_final(self, batch1_result: Dict) -> Dict:
        """将第1批结果转换为最终格式"""
        result = {
            "title": batch1_result.get("title", ""),
            "grade": batch1_result.get("grade", ""),
            "chapter": batch1_result.get("chapter", ""),
            "sections": {}
        }

        # 转换sections
        sections = batch1_result.get("sections", {})
        if "导入" in sections:
            result["sections"]["导入"] = sections["导入"]
        if "学习目标" in sections:
            result["sections"]["学习目标"] = sections["学习目标"]
        if "知识点详解_A" in sections:
            result["sections"]["知识点详解"] = sections["知识点详解_A"]

        return result

    def _convert_batch1_2_to_final(self, batch1: Dict, batch2: Dict, combined_knowledge: str) -> Dict:
        """将第1、2批结果转换为最终格式"""
        result = {
            "title": batch1.get("title", ""),
            "grade": batch1.get("grade", ""),
            "chapter": batch1.get("chapter", ""),
            "sections": {}
        }

        sections1 = batch1.get("sections", {})

        # 从第1批获取
        if "导入" in sections1:
            result["sections"]["导入"] = sections1["导入"]
        if "学习目标" in sections1:
            result["sections"]["学习目标"] = sections1["学习目标"]

        # 合并知识点详解
        result["sections"]["知识点详解"] = combined_knowledge

        return result

    def _convert_batch1_2_3_to_final(self, batch1: Dict, batch2: Dict, batch3: Dict, combined_knowledge: str) -> Dict:
        """将第1、2、3批结果转换为最终格式"""
        result = self._convert_batch1_2_to_final(batch1, batch2, combined_knowledge)

        # 从第3批获取典例精讲_A
        sections3 = batch3.get("sections", {})
        if "典例精讲_A" in sections3:
            result["sections"]["典例精讲"] = sections3["典例精讲_A"]

        return result

    def _extract_examples_summary(self, examples_text: str) -> str:
        """
        从典例精讲文本中提取例题摘要

        Args:
            examples_text: 典例精讲文本

        Returns:
            例题摘要文本
        """
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
        """
        合并所有4批的结果

        Args:
            batch1: 第1批结果
            batch2: 第2批结果
            batch3: 第3批结果
            batch4: 第4批结果
            combined_knowledge: 合并后的知识点详解
            title: 标题
            grade: 年级
            chapter: 章节

        Returns:
            完整的course.json
        """
        result = {
            "title": title,
            "grade": grade,
            "chapter": chapter if chapter else "未知章节",
            "sections": {}
        }

        sections1 = batch1.get("sections", {})

        # 从第1批获取
        if "导入" in sections1:
            result["sections"]["导入"] = sections1["导入"]
        if "学习目标" in sections1:
            result["sections"]["学习目标"] = sections1["学习目标"]

        # 合并知识点详解
        result["sections"]["知识点详解"] = combined_knowledge

        # 合并典例精讲
        examples_a = batch3.get("sections", {}).get("典例精讲_A", "")
        examples_b = batch4.get("典例精讲_B", "")
        if examples_a and examples_b:
            result["sections"]["典例精讲"] = examples_a + "\n\n" + examples_b
        elif examples_a:
            result["sections"]["典例精讲"] = examples_a
        elif examples_b:
            result["sections"]["典例精讲"] = examples_b

        # 从第4批获取其他sections
        sections4 = batch4.get("sections", {})
        for section_name in ["易错点", "随堂小测", "知识框架", "课后拓展"]:
            if section_name in sections4:
                result["sections"][section_name] = sections4[section_name]

        return result

    def _check_content_quality(self, section_name: str, content: str) -> Dict[str, Any]:
        """
        检查内容质量是否符合标准

        Args:
            section_name: section名称
            content: section内容

        Returns:
            {"passed": bool, "reason": str}
        """
        import re

        # 不同section的最低字数要求
        min_length_requirements = {
            "导入": 100,
            "学习目标": 150,  # 新增
            "知识点详解": 400,  # 最重要，要求最详细
            "典例精讲": 300,
            "易错点": 200,
            "随堂小测": 200,
            "知识框架": 150,
            "课后拓展": 100
        }

        min_length = min_length_requirements.get(section_name, 150)

        # 检查1：字数是否达标
        if len(content) < min_length:
            return {
                "passed": False,
                "reason": f"字数不足({len(content)}/{min_length})"
            }

        # 检查2：是否有分段标记（针对知识点详解）
        if section_name == "知识点详解":
            # 检查是否有【】分段或至少有明显的段落分隔
            has_structure = (
                '【' in content and '】' in content  # 有分段标记
                or content.count('。') >= 5  # 至少5个句子
                or content.count('\n\n') >= 2  # 至少2个空行（段落分隔）
            )
            if not has_structure:
                return {
                    "passed": False,
                    "reason": "缺乏结构分段"
                }

        # 检查3：典例精讲是否包含例题
        if section_name == "典例精讲":
            has_examples = (
                '例题' in content
                or '练习' in content
                or '题目' in content
            )
            if not has_examples:
                return {
                    "passed": False,
                    "reason": "缺少例题"
                }

        # 检查4：是否全是重复内容
        # 简单检查：如果有超过50%的内容是重复的句子
        sentences = re.split(r'[。！？\n]', content)
        sentences = [s.strip() for s in sentences if s.strip()]
        if len(sentences) > 5:
            unique_sentences = set(sentences)
            if len(unique_sentences) / len(sentences) < 0.5:
                return {
                    "passed": False,
                    "reason": "内容重复率过高"
                }

        return {"passed": True, "reason": ""}

    def _get_default_course_content(self, title: str, grade: str, chapter: str) -> Dict:
        """
        当LLM生成完全失败时，返回默认的课程内容模板

        这是一个兜底方案，确保流程不会因为LLM问题而中断
        """
        logger.warning(f"[结构化生成] 使用默认内容模板: {title}")

        return {
            "title": title,
            "grade": grade,
            "chapter": chapter if chapter else "自定义章节",
            "sections": {
                "导入": f"今天我们学习{title}的相关知识。请认真听讲，积极思考。",
                "学习目标": f"1. 知识与技能：掌握{title}的基本概念和性质。\\n2. 过程与方法：通过例题分析，学会运用{title}解决问题。\\n3. 情感态度：培养严谨的数学思维习惯。",
                "知识点详解": f"本节课的核心知识点是{title}的基本概念、性质和运算方法。请同学们重点理解并掌握。",
                "典例精讲": "例题1：基础应用题\\n题目：请根据所学知识完成练习。\\n解析：运用本节课的核心知识点可以解决。\\n\\n例题2：综合应用题\\n题目：结合实际场景解决问题。\\n解析：分析题目条件，运用知识点求解。",
                "易错点": f"在学习{title}时，同学们容易混淆相关概念，请务必注意区分。",
                "随堂小测": "练习题1：基础知识巩固\\n练习题2：应用能力提升\\n练习题3：综合能力考查",
                "知识框架": f"本节课我们学习了{title}的相关内容，包括基本概念、性质和应用方法。",
                "课后拓展": f"请同学们课后复习{title}的相关知识，预习下一节课内容，拓展自己的知识面。"
            }
        }

    async def _advanced_validation(
        self, course_json: Dict, title: str, grade: str, chapter: str
    ) -> Dict[str, Any]:
        """
        高级验证：检测重复、遗漏、逻辑断裂

        Args:
            course_json: 课程JSON
            title: 标题
            grade: 年级
            chapter: 章节

        Returns:
            验证结果字典
        """
        import re

        result = {
            "has_duplicates": False,
            "has_gaps": False,
            "duplicates": [],
            "gaps": []
        }

        sections = course_json.get("sections", {})

        # 检测1：知识点详解中的重复知识点
        if "知识点详解" in sections:
            knowledge = sections["知识点详解"]
            knowledge_points = self._extract_knowledge_points_list(knowledge)
            # 检查是否有重复的知识点名称
            unique_points = []
            duplicates = []
            for point in knowledge_points:
                if point in unique_points:
                    duplicates.append(point)
                else:
                    unique_points.append(point)

            if duplicates:
                result["has_duplicates"] = True
                result["duplicates"].extend([f"知识点详解重复: {dup}" for dup in duplicates])

        # 检测2：典例精讲中的重复例题
        if "典例精讲" in sections:
            examples = sections["典例精讲"]
            example_nums = re.findall(r'【例题(\d+)】', examples)
            if len(example_nums) != len(set(example_nums)):
                result["has_duplicates"] = True
                result["duplicates"].append("典例精讲存在重复编号的例题")

        # 检测3：逻辑断裂 - 知识点到例题的覆盖
        if "知识点详解" in sections and "典例精讲" in sections:
            knowledge = sections["知识点详解"]
            examples = sections["典例精讲"]

            # 提取知识点关键词
            knowledge_keywords = self._extract_keywords(knowledge)
            # 提取例题关键词
            example_keywords = self._extract_keywords(examples)

            # 检查是否有知识点没有对应的例题
            uncovered = []
            for kw in knowledge_keywords[:5]:  # 检查前5个主要知识点
                if kw not in example_keywords and len(kw) > 2:
                    uncovered.append(kw)

            if len(uncovered) > 3:  # 如果超过3个主要知识点没有覆盖
                result["has_gaps"] = True
                result["gaps"].append(f"知识点覆盖不足，未覆盖: {', '.join(uncovered[:3])}")

        # 检测4：易错点是否与知识点对应
        if "易错点" in sections and "知识点详解" in sections:
            mistakes = sections["易错点"]
            knowledge = sections["知识点详解"]

            # 检查易错点是否提到了具体知识点
            knowledge_points = self._extract_knowledge_points_list(knowledge)
            if knowledge_points:
                found_any = any(point in mistakes for point in knowledge_points)
                if not found_any:
                    result["has_gaps"] = True
                    result["gaps"].append("易错点未明确对应具体知识点")

        return result

    def _extract_keywords(self, text: str) -> List[str]:
        """
        从文本中提取关键词

        Args:
            text: 文本内容

        Returns:
            关键词列表
        """
        import re
        # 提取2-4个字的连续汉字或词组
        keywords = []
        pattern = r'[\u4e00-\u9fa5]{2,4}'
        matches = re.findall(pattern, text)
        # 过滤掉常见词
        common_words = {'这个', '一个', '可以', '应该', '需要', '方法', '问题', '情况', '内容', '计算', '求解', '步骤', '结果'}
        for match in matches:
            if match not in common_words and match not in keywords:
                keywords.append(match)
        return keywords[:10]  # 返回前10个关键词

    async def _fix_duplicates(
        self, course_json: Dict, duplicates: List[str], title: str, grade: str, chapter: str
    ) -> Dict:
        """
        修复重复内容

        Args:
            course_json: 课程JSON
            duplicates: 重复项列表
            title: 标题
            grade: 年级
            chapter: 章节

        Returns:
            修复后的课程JSON
        """
        logger.info(f"[结构化生成] 尝试修复重复内容: {duplicates}")

        # 对于重复内容，尝试重新生成受影响的section
        sections_to_regenerate = []

        for dup in duplicates:
            if "知识点详解" in dup:
                sections_to_regenerate.append("知识点详解")
            elif "典例精讲" in dup:
                sections_to_regenerate.append("典例精讲")

        if sections_to_regenerate:
            # 使用现有的重新生成机制
            result = await self._regenerate_incomplete_sections(
                course_json, sections_to_regenerate, title, grade, chapter
            )
            return result

        return course_json

    async def _fix_gaps(
        self, course_json: Dict, gaps: List[str], title: str, grade: str, chapter: str
    ) -> Dict:
        """
        修复逻辑断裂

        Args:
            course_json: 课程JSON
            gaps: 断裂项列表
            title: 标题
            grade: 年级
            chapter: 章节

        Returns:
            修复后的课程JSON
        """
        logger.info(f"[结构化生成] 尝试修复逻辑断裂: {gaps}")

        # 对于逻辑断裂，尝试通过重新生成易错点来弥补
        if any("知识点覆盖不足" in gap or "易错点未明确对应" in gap for gap in gaps):
            logger.info(f"[结构化生成] 重新生成易错点以增强知识点对应")
            result = await self._regenerate_incomplete_sections(
                course_json, ["易错点"], title, grade, chapter
            )
            return result

        return course_json
