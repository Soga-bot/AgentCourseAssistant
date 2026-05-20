"""
阶段1B：教学设计专家（Storyboard Designer）

将内容理解结果转化为教学故事板框架
将内容理解结果转化为教学故事板框架

职责：
1. 分析内容理解结果
2. 设计教学流程（分帧策略）
3. 生成每帧的讲解要点
4. 不考虑JSON格式，专注于教学逻辑
"""

import asyncio
import json
import logging
import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Any

# 使用统一的日志配置
from ..logging_config import get_module_logger
logger = get_module_logger(__name__, "storyboard_designer")


@dataclass
class StoryboardFrame:
    """单帧故事板"""
    scene_id: str
    stage: str
    sub_stage: str = ""
    frame_title: str = ""
    main_content: str = ""
    narration: str = ""
    key_points: List[str] = field(default_factory=list)
    visual_actions: List[str] = field(default_factory=list)
    needs_diagram: bool = False
    diagram_spec: Dict = field(default_factory=dict)
    duration_hint: int = 30
    is_extended: bool = False


@dataclass
class StoryboardDesignResult:
    """故事板设计结果"""
    success: bool
    frames: List[StoryboardFrame] = field(default_factory=list)
    total_frames: int = 0
    title: str = ""
    error: str = ""


class StoryboardDesigner:
    """
    教学设计专家

    设计原则：
    1. 职责单一：只负责教学设计，不考虑格式
    2. 基于结构化输入：使用阶段1的知识点结果
    3. 教学逻辑：按照教学流程设计帧序列
    4. 内容完整：确保每帧都有实质性内容
    """

    # ========== 两阶段生成提示词 ==========

    # 阶段1：框架生成（仅结构，不生成具体内容）
    STAGE1_OUTLINE_PROMPT = """# 角色
你是课程教学设计专家，负责规划教学流程框架。

# ⚠️ stage字段强制要求
stage字段必须严格使用以下7个值之一（禁止使用其他名称）：
- title（标题页）
- objectives（学习目标）
- intro（情境导入）
- concept（新知呈现）
- example（例题示范）
- practice（巩固练习）
- summary（课堂小结）

# 核心原则
**结构清晰** - 只关注框架设计，不涉及具体内容生成。

# 任务
基于课程内容分析结果，规划 {target_frames} 帧的教学流程框架。

# 输入：课程内容分析结果
{understanding_result}

# 输出要求（⚠️ 只输出框架结构，不生成具体内容）

## 帧1
sceneID: s1
stage: 标题页
slideType: title
frameTitle: [具体标题]
subStage: [如果需要子阶段]

（重复{target_frames}帧）

# 教学流程参考模板
{expansion_rules}

# ⚠️ 关键约束
1. **不生成** mainContent、narration、keyPoints（这些在阶段2生成）
2. 只规划：sceneID、stage、slideType、frameTitle、subStage
3. 确保流程符合教学逻辑
4. 根据知识点数量合理分配帧数
5. **必须包含"学习目标"(objectives)帧** - 这是强制要求，不能跳过

# 输出格式示例（8帧标准模板）
## 帧1
sceneID: s1
stage: title
slideType: title
frameTitle: [课程标题]

## 帧2
sceneID: s2
stage: objectives
slideType: objectives
frameTitle: 学习目标

## 帧3
sceneID: s3
stage: intro
slideType: intro
frameTitle: [导入标题]

（继续到第{target_frames}帧）

请生成教学流程框架：
"""

    # 阶段2：内容生成（基于框架生成完整内容）
    STAGE2_CONTENT_PROMPT = """# 角色
你是课程内容撰写专家，负责为教学框架生成详细内容。

# ⚠️ stage字段强制要求
stage必须严格使用：title/objectives/intro/concept/example/practice/summary
禁止使用："开篇导入"、"新知讲授"、"巩固提升"、"结课收尾"等别名

# 核心原则
**内容完整** - 确保每帧内容达到最低字数要求，无占位符。

# 任务
基于已验证的教学框架，为每一帧生成详细内容。

# 课程信息
课程标题: {title}
目标帧数: {target_frames}

# 教学框架（已验证）
{framework_guidance}

# 课程内容分析结果（参考）
{understanding_result}

# 每帧内容要求

## mainContent（幻灯片内容）⚠️ **绝对禁止**：
- 禁止：mainContent为空或null
- 禁止：使用"..."、"等"、"之类"省略内容
- 禁止：只有标题没有实际内容

✅ **最低字数要求（强制）**：
- 标题页（title）：0-20字
- 学习目标（objectives）：最低50字
- 情境导入（intro）：最低50字
- 知识点详解（concept）：最低100字
- 例题示范（example）：最低80字
- 巩固练习（practice）：最低60字
- 课堂小结（summary）：最低40字

✅ **完整内容应包含**：
- 概念帧：定义 + 性质 + 特点（用\\begin{{itemize}}...\\end{{itemize}}列表格式）
- 应用帧：实例 + 方法 + 步骤
- 例题帧：题目 + 分析 + 解答
- 总结帧：要点回顾 + 方法总结

⚠️ **例题帧标题格式要求（最高优先级，必须严格遵守）**：
- frameTitle只能写："典例精讲1"、"典例精讲2"、"例题1"、"例题2"等简洁格式
- **严禁**将题目内容放在标题中（如禁止："典例精讲1：计算下列各题"、"例题1：计算2x+3=7"）
- 题目完整内容必须放在mainContent的正文中，使用单独的段落

✅ **例题帧内容格式要求（必须按此结构组织）**：
mainContent必须按以下结构组织（使用换行或明显分隔）：
- 题目：（完整题目内容，单独一段）
- 思路引导：（解题思路分析）
- 完整步骤：（详细解答步骤）
- 易错提醒：（常见错误和注意事项）
- 方法总结：（解题方法总结）

⚠️ **小标题格式要求（必须使用LaTeX加粗）**：
- 必须使用：\\textbf{{思路引导}}、\\textbf{{完整步骤}}、\\textbf{{易错提醒}}、\\textbf{{方法总结}}
- 确保小标题与正文内容有明显区分

⚠️ **分页指导（避免内容溢出）**：
- 每个场景内容应聚焦一个主题，保持内容连贯
- 易错点、课堂小结等较长板块应独立成帧
- 内容过长时LaTeX生成器会自动处理分页，无需手动拆分场景ID

✅ **内容排版要求（避免文字堆砌）**：
- 使用结构化格式：问题→原因→做法（用换行分隔）
- 长文本拆分：单个item超过50字时拆分为多个子项
- 使用简洁表达：避免重复描述，去掉冗余修饰
- 数学公式简化：用$...$而非复杂环境
- 易错点/典例精讲类：每帧最多3个要点，每个要点不超过2行

## narration（旁白讲解）⚠️ **关键要求**：
- 使用"我们"、"同学们"营造互动感
- **逐步展开，不要跳跃推理**（最重要！）
- 每一步都要说明"为什么这样想"
- 长度：每帧50-150字

⚠️ **"搭架子"教学原则**：
- **概念帧**：先讲"是什么"和"怎么用"，再深入细节
  - 禁止：直接跳到复杂应用或高级推论
  - 正确：先建立框架，再逐步完善
- **例题帧**：先讲"大方向"和"解题思路"，再展开步骤
  - 初步分析只列"解题的大方向"，不深入具体证明细节
  - 例如："第一步证X=Y，第二步用定理Z"（正确的大方向）
  - 禁止在初步分析时出现高级结论或复杂变形

## keyPoints（核心要点）⚠️ **强制要求**：
- **每帧必须包含3-5个核心要点**（用|分隔）
- 要点必须是具体的知识点或步骤，不是空泛描述
- 禁止："要点待补充"、"内容待填充"
- 概念帧：列出定义、性质、特点
- 例题帧：列出分析步骤、解答方法

## 图示需求判断
根据course_type和知识点内容判断是否需要图示：
- 几何课程（geometry）：需要图示，类型为geometry或triangle_aux
- 函数课程（function）：需要图示，类型为function_plot或function_multi
- 统计课程（statistics）：需要图示，类型为chart或histogram
- 代数课程（algebra）：一般不需要图示

# 输出格式
## 帧1: [frameTitle]
mainContent: [完整内容，达到最低字数要求]
narration: [详细的旁白讲解，50-150字，逐步展开不跳跃]
keyPoints: [要点1|要点2|要点3]
visualActions: [HIGHLIGHT:定理名称|RED:关键结论|TYPE:图形描述]
needsDiagram: [true/false]
diagramSpec: [{{json格式图示规格}}]

（重复所有帧）

# ⚠️ 强制要求
1. 每帧mainContent必须完整且达标字数
2. 禁止占位符，禁止省略号
3. 每帧必须有3-5个具体keyPoints

请基于框架生成详细内容：

# ⚠️ 子场景规划规则（内容过长时自动分页）
当某帧内容过长需要分页时，请自动规划为子场景：

## ⚠️ frameTitle命名规则（强制遵守）：
- **禁止在frameTitle中添加分页标记**：如 (1/2)、(2/2)、($\frac{1}{2}$)、](1/2) 等
- 子场景标题使用字母后缀：如 "例题1a"、"例题1b"、"练习题a"、"练习题b"
- 原场景标题保持不变，子场景只需加字母后缀
- 违规示例：`例题1（1/2）`、`练习题]($\frac{1}{2}$)` ❌
- 正确示例：`例题1a`、`练习题a` ✅

## practice类型（练习题）分页规则：
- **超过2道题时必须分页**
- 子场景ID格式：s7a, s7b, s7c（按字母顺序）
- 每个子场景最多2道题，格式：
  ```
  1. （题型）题目内容...
  A. 选项A  B. 选项B  C. 选项C  D. 选项D
  答案：X 解析：解析内容...
  ```
- 每个子场景必须有独立的完整narration

## concept/example类型分页规则：
- **内容超过350字时考虑分页**
- 子场景ID格式：s4a, s4b, s4c（按字母顺序）
- 按逻辑层次分割（概念→性质→应用）
- 每个子场景聚焦一个主题，保持连贯性
- 每个子场景必须有独立的完整narration

## 子场景输出格式：
当需要生成子场景时，按照以下格式输出：
## 帧7a: [标题a]
sceneID: s7a
stage: [原stage类型]
frameTitle: [标题 + "a"后缀，如"例题1a"]
mainContent: [完整内容]
narration: [独立讲解]
keyPoints: [要点1|要点2|要点3]

## 帧7b: [标题b]
sceneID: s7b
stage: [原stage类型]
frameTitle: [标题 + "b"后缀，如"例题1b"]
mainContent: [完整内容]
narration: [独立讲解]
keyPoints: [要点1|要点2|要点3]

⚠️ **注意**：生成子场景后，总帧数会超过初始规划，这是正常的。

# ⚠️ 动态扩展规则
- 当summary帧内容过多时，支持自动扩展为s6a/s6b/s6c...
- s6a: 核心定理列表 + 方法提炼
- s6b: 易错点总结 + 拓展思考
- s6c: 更多扩展内容（如需要）
- 每个扩展帧聚焦一个主题，避免单页内容过多
"""

    # ========== 原完整提示词（保留作为备用） ==========
    DESIGN_PROMPT = """# 角色
你是课程教学设计专家，擅长将结构化的课程内容转化为详细的教学视频分镜。

# 核心原则
**教学效果优先** - 确保每帧内容完整、讲解清晰、循序渐进。

# 任务
基于课程内容分析结果，生成 {target_frames} 帧的教学分镜。

# 输入：课程内容分析结果
{understanding_result}

# 教学流程设计原则

## 标准教学流程（9帧版本）
1. **s1 标题页**（title）：课程标题展示
2. **s2 学习目标**（objectives）：展示学习目标
3. **s3 情境导入**（intro）：生活实例或问题引入
4. **s4-s6 新知呈现**（concept）：每个知识点1-2帧
5. **s7 例题示范**（example）：1帧（如有例题内容）
6. **s8 课堂小结**（summary）：总结回顾

## 简化教学流程（6帧版本）
1. **s1 标题页**（title）
2. **s2 学习目标**（objectives）
3. **s3-s4 新知呈现**（concept）：每个知识点1帧
4. **s5 小结**（summary）

## 扩展教学流程（12帧版本）
1. **s1 标题页**（title）
2. **s2 学习目标**（objectives）
3. **s3 情境导入**（intro）
4. **s4-s7 新知呈现**（concept）：每个知识点1-2帧
5. **s8-s9 例题示范**（example）：2帧
6. **s10 方法总结**（practice）：解题方法或技巧
7. **s11 课堂小结**（summary）：总结回顾

# 每帧内容要求

## mainContent（幻灯片内容）⚠️ **绝对禁止**：
- 禁止：mainContent为空或null
- 禁止：mainContent为"本知识点包含以下内容：基本概念和定义..."
- 禁止：使用"..."、"等"、"之类"省略内容
- 禁止：只有标题没有实际内容

✅ **最低字数要求（强制）**：
- 标题页（title）：0-20字
- 学习目标（objectives）：最低50字
- 情境导入（intro）：最低50字
- 知识点详解（concept）：最低100字
- 例题示范（example）：最低80字
- 巩固练习（practice）：最低60字
- 课堂小结（summary）：最低40字

✅ **完整内容应包含**：
- 概念帧：定义 + 性质 + 特点（用\\begin{{itemize}}...\\end{{itemize}}列表格式）
- 应用帧：实例 + 方法 + 步骤
- 例题帧：题目 + 分析 + 解答
- 总结帧：要点回顾 + 方法总结

⚠️ **例题帧标题格式要求（最高优先级，必须严格遵守）**：
- frameTitle只能写："典例精讲1"、"典例精讲2"、"例题1"、"例题2"等简洁格式
- **严禁**将题目内容放在标题中（如禁止："典例精讲1：计算下列各题"、"例题1：计算2x+3=7"）
- 题目完整内容必须放在mainContent的正文中，使用单独的段落

✅ **例题帧内容格式要求（必须按此结构组织）**：
mainContent必须按以下结构组织（使用换行或明显分隔）：
- 题目：（完整题目内容，单独一段）
- 思路引导：（解题思路分析）
- 完整步骤：（详细解答步骤）
- 易错提醒：（常见错误和注意事项）
- 方法总结：（解题方法总结）

⚠️ **小标题格式要求（必须使用LaTeX加粗）**：
- 必须使用：\\textbf{{思路引导}}、\\textbf{{完整步骤}}、\\textbf{{易错提醒}}、\\textbf{{方法总结}}
- 确保小标题与正文内容有明显区分

⚠️ **分页指导（避免内容溢出）**：
- 每个场景内容应聚焦一个主题，保持内容连贯
- 易错点、课堂小结等较长板块应独立成帧
- 内容过长时LaTeX生成器会自动处理分页，无需手动拆分场景ID

✅ **内容排版要求（避免文字堆砌）**：
- 使用结构化格式：问题→原因→做法（用换行分隔）
- 长文本拆分：单个item超过50字时拆分为多个子项
- 使用简洁表达：避免重复描述，去掉冗余修饰
- 数学公式简化：用$...$而非复杂环境
- 易错点/典例精讲类：每帧最多3个要点，每个要点不超过2行

## narration（旁白讲解）⚠️ **关键要求**：
- 使用"我们"、"同学们"营造互动感
- **逐步展开，不要跳跃推理**（最重要！）
- 每一步都要说明"为什么这样想"
- 长度：每帧50-150字

⚠️ **"搭架子"教学原则**：
- **概念帧**：先讲"是什么"和"怎么用"，再深入细节
  - 禁止：直接跳到复杂应用或高级推论
  - 正确：先建立框架，再逐步完善
- **例题帧**：先讲"大方向"和"解题思路"，再展开步骤
  - 初步分析只列"解题的大方向"，不深入具体证明细节
  - 例如："第一步证X=Y，第二步用定理Z"（正确的大方向）
  - 禁止在初步分析时出现高级结论或复杂变形

## keyPoints（核心要点）⚠️ **强制要求**：
- **每帧必须包含3-5个核心要点**（用|分隔）
- 要点必须是具体的知识点或步骤，不是空泛描述
- 禁止："要点待补充"、"内容待填充"
- 概念帧：列出定义、性质、特点
- 例题帧：列出分析步骤、解答方法

## slideType（帧类型）
- title：标题页
- objectives：学习目标
- intro：情境导入
- concept：新知呈现（知识点讲解）
- example：例题示范
- example_continue：例题续页（复杂例题的第二页）
- practice：巩固练习
- summary：课堂小结

⚠️ **例题帧拆分规则**：
- 简单例题：1帧完成，包含【题目】【思路引导】【完整步骤】【答案】【易错提醒】
- 复杂例题：拆分为2帧
  * 第1帧（example）：【题目】+【思路引导】
  * 第2帧（example_continue）：【完整步骤】+【答案】+【易错提醒】
- 第2帧标题格式："例题X（续）"

# 图示需求判断

根据course_type和知识点内容判断是否需要图示：

## 几何课程（geometry）
- **需要图示**：涉及图形、角度、位置关系
- **图示类型**：geometry（基本图形）、triangle_aux（带辅助线的三角形）

## 函数课程（function）
- **需要图示**：涉及函数、图像
- **图示类型**：function_plot（函数图像）、function_multi（多函数对比）

## 统计课程（statistics）
- **需要图示**：涉及数据、图表
- **图示类型**：chart（统计图表）、histogram（直方图）

## 代数课程（algebra）
- **一般不需要图示**（除非涉及几何意义）

# 图示规格格式（精简版）
```json
{{"type": "图示类型", "title": "图示标题", "具体参数": "..."}}
```

## 常用图示类型及参数

### geometry - 基本几何图形
{{"type": "geometry", "shape": "triangle", "vertices": [[0,0], [4,0], [2,3]], "labels": ["A", "B", "C"], "title": "三角形ABC"}}

### function_plot - 函数图像
{{"type": "function_plot", "function": "x^2", "xRange": [-3, 3], "yRange": [-1, 10], "title": "二次函数图像"}}

### chart - 统计图表
{{"type": "chart", "chartType": "bar", "data": {{"categories": ["A", "B"], "values": [10, 20]}}, "title": "统计图"}}

# ⚠️ 子场景规划规则（内容过长时自动分页）
当某帧内容过长需要分页时，请自动规划为子场景：

## ⚠️ frameTitle命名规则（强制遵守）：
- **禁止在frameTitle中添加分页标记**：如 (1/2)、(2/2)、($\frac{1}{2}$)、](1/2) 等
- 子场景标题使用字母后缀：如 "例题1a"、"例题1b"、"练习题a"、"练习题b"
- 原场景标题保持不变，子场景只需加字母后缀
- 违规示例：`例题1（1/2）`、`练习题]($\frac{1}{2}$)` ❌
- 正确示例：`例题1a`、`练习题a` ✅

## practice类型（练习题）分页规则：
- **超过2道题时必须分页**
- 子场景ID格式：s7a, s7b, s7c（按字母顺序）
- 每个子场景最多2道题，格式清晰（题目一行+选项一行+解析一行）
- 每个子场景必须有独立的完整narration

## concept/example类型分页规则：
- **内容超过350字时考虑分页**
- 子场景ID格式：s4a, s4b, s4c（按字母顺序）
- 按逻辑层次分割，保持语义完整
- 每个子场景必须有独立的完整narration

## 子场景输出格式示例：
当需要分页时，按以下格式输出：
## 帧7a: 练习题a
sceneID: s7a
stage: practice
slideType: practice
frameTitle: 练习题a
mainContent: [第1-2题完整内容]
narration: [第1-2题的独立讲解]
keyPoints: [要点1|要点2|要点3]
visualActions: [...]
needsDiagram: false
diagramSpec: {{}}

## 帧7b: 练习题b
sceneID: s7b
stage: practice
slideType: practice
frameTitle: 练习题b
mainContent: [第3-5题完整内容]
narration: [第3-5题的独立讲解]
keyPoints: [要点1|要点2|要点3]

⚠️ **注意**：生成子场景后，实际总帧数可能超过初始规划的{target_frames}帧，这是正常的。

# 输出格式
## 帧1
sceneID: s1
stage: 标题页
slideType: title
frameTitle: 帧标题
mainContent: 完整内容（禁止占位符）
narration: 旁白讲解
keyPoints: 要点1|要点2|要点3
visualActions: HIGHLIGHT:定理名称|RED:关键结论|TYPE:图形描述
needsDiagram: false
diagramSpec: {{}}

（重复所有帧，包括子场景）

# ⚠️ 强制要求（必须遵守）

## 子场景分页规则（零容忍 - 违反即失败）
1. **practice类型（练习题）分页**：
   - **超过2道题时必须分页**，使用子场景s7a, s7b, s7c...
   - 每个子场景最多2道题
   - 禁止将5道题挤在一个场景中
   - 违反示例：s7包含5道题 ❌
   - 正确示例：s7a(2题) + s7b(2题) + s7c(1题) ✅

2. **concept/example类型分页**：
   - **内容超过350字时必须分页**，使用子场景s4a, s4b...
   - 按逻辑层次分割（概念→性质→应用）
   - 禁止将过多内容挤在一个场景中
   - 违反示例：s6包含800字内容 ❌
   - 正确示例：s6a(概念) + s6b(性质) + s6c(应用) ✅

3. **子场景ID格式要求**：
   - 必须使用字母后缀：s7a, s7b, s7c（按字母顺序）
   - 每个子场景必须有独立的完整narration
   - 每个子场景必须有独立的keyPoints

## 内容完整性（零容忍）
1. **每帧mainContent必须完整且达标字数**：
   - 禁止占位符，禁止省略号
   - 禁止空内容或仅标题
   - 字数不达标的内容视为无效输出

2. **字数统计规则**：
   - 只计算mainContent的中文字符数
   - 标点符号计入字数
   - LaTeX命令不计入字数

3. **narration必须详细**：
   - 每帧50-150字的口语化讲解
   - 体现思维过程，逐步展开

4. **needsDiagram和diagramSpec匹配**：
   - needsDiagram=true时必须提供有效diagramSpec

5. **slideType准确**：
   - 按照教学流程正确标记每帧类型

## 违规后果
- practice超过2道题未分页：生成失败，需重新生成 ❌
- concept超过350字未分页：生成失败，需重新生成 ❌
- mainContent为空或字数不足：生成失败，需重新生成 ❌
- 使用占位符或省略号：生成失败，需重新生成 ❌

请基于课程内容分析结果生成详细的分镜（确保每帧mainContent达到最低字数要求，严格遵守分页规则）：
"""

    # 扩展规则模板（灵活结构指导，内容驱动）
    EXPANSION_TEMPLATES = {
        "default": """教学流程结构指导（内容驱动，灵活调整）：

必选帧（必须包含）：
- s1 标题页 (stage: title)
- s2 学习目标 (stage: objectives) - 必须包含，不能跳过
- 最后1帧 课堂小结 (stage: summary)

可选帧（根据内容需要添加）：
- 情境导入 (stage: intro) - 如有生活实例可添加1帧
- 新知呈现/知识点详解 (stage: concept) - 每个知识点1-2帧，确保完整
- 例题示范 (stage: example) - 根据题目数量分配帧数
- 巩固练习 (stage: practice) - 如需要可添加
- 易错点提醒 (stage: concept) - 如有典型错误可单独成帧

分帧原则（内容优先）：
- 知识点详解：1个知识点可拆为2-3帧（概念+性质+应用）
- 例题示范：每1-2道题一帧，确保讲解清晰
- 单帧容量：每个item尽量控制在1-2行，超过5个item考虑拆分
- 不要为了凑帧数而合并不同主题
- 不要为了减少帧数而删减重要内容

参考帧数：{target_frames}帧（仅供参考，根据实际内容调整）
"""
    }

    def __init__(self, llm_client, max_tokens: int = 10000, max_concurrent: int = 3, request_interval: float = 1.0):
        """
        初始化教学设计专家

        Args:
            llm_client: LLM客户端实例
            max_tokens: 最大token数（默认10000，确保生成完整内容）
            max_concurrent: 最大并发数（默认3）
            request_interval: 请求间隔秒数（默认1.0）
        """
        self.llm_client = llm_client
        self.max_tokens = max_tokens
        self.max_concurrent = max_concurrent
        self.request_interval = request_interval

        # 并发控制
        self._semaphore = asyncio.Semaphore(max_concurrent)
        self._request_lock = asyncio.Lock()
        self._last_request_time = 0

        logger.info("[StoryboardDesigner] 初始化完成，max_tokens=%d, max_concurrent=%d, request_interval=%.1fs",
                    max_tokens, max_concurrent, request_interval)

    # ========== 两阶段生成方法 ==========

    async def _generate_with_two_stages(
        self,
        title: str,
        understanding_result: Any,
        understanding_json: str,
        target_frames: int,
        expansion_rules: str
    ) -> StoryboardDesignResult:
        """两阶段生成：框架 + 内容

        阶段1：生成教学框架（结构）
        阶段2：基于框架生成完整内容

        优点：
        - Prompt专注：每个阶段只关注一个任务
        - 快速失败：框架有问题立即重试
        - 易于调试：可以单独测试每个阶段
        """
        from shared.llm_client import LLMRequest

        logger.info("[StoryboardDesigner] ========== 两阶段生成开始 ==========")

        # ========== 阶段1：框架生成 ==========
        logger.info("[StoryboardDesigner] 阶段1: 生成教学框架...")

        outline_prompt = self.STAGE1_OUTLINE_PROMPT.format(
            understanding_result=understanding_json,
            target_frames=target_frames,
            expansion_rules=expansion_rules
        )

        max_stage1_retries = 2
        outline = None

        for attempt in range(max_stage1_retries):
            try:
                if attempt > 0:
                    logger.info("[StoryboardDesigner] 阶段1重试 %d/%d", attempt + 1, max_stage1_retries)

                request = LLMRequest(
                    messages=[{"role": "user", "content": outline_prompt}],
                    temperature=0.0,  # 框架生成需要确定性，避免结构不稳定
                    max_tokens=16000
                )

                response = await self.llm_client.call(request)

                if not response.success:
                    logger.error("[StoryboardDesigner] 阶段1失败: %s", response.error)
                    continue

                # 解析框架
                outline = self._parse_outline(response.content, target_frames)

                # 验证框架结构
                validation = self._validate_outline_structure(outline, target_frames)
                if not validation["valid"]:
                    logger.warning("[StoryboardDesigner] 阶段1验证失败: %s", validation["errors"])
                    # 使用默认框架
                    outline = self._create_default_outline(understanding_result, target_frames)
                    logger.info("[StoryboardDesigner] 使用默认教学框架")
                    break

                logger.info("[StoryboardDesigner] ✓ 阶段1完成: 框架验证通过")
                break

            except Exception as e:
                logger.error("[StoryboardDesigner] 阶段1异常(尝试%d): %s", attempt + 1, str(e))
                if attempt == max_stage1_retries - 1:
                    outline = self._create_default_outline(understanding_result, target_frames)
                    logger.info("[StoryboardDesigner] 使用默认教学框架")

        if outline is None:
            outline = self._create_default_outline(understanding_result, target_frames)

        # ========== 阶段2：内容生成 ==========
        logger.info("[StoryboardDesigner] 阶段2: 基于框架生成详细内容...")

        # 格式化框架为指导文本
        framework_guidance = self._format_frame_guidance(outline, target_frames)

        content_prompt = self.STAGE2_CONTENT_PROMPT.format(
            title=title,
            target_frames=target_frames,
            framework_guidance=framework_guidance,
            understanding_result=understanding_json
        )

        max_stage2_retries = 2
        storyboard = None

        for attempt in range(max_stage2_retries):
            try:
                if attempt > 0:
                    logger.info("[StoryboardDesigner] 阶段2重试 %d/%d", attempt + 1, max_stage2_retries)

                request = LLMRequest(
                    messages=[{"role": "user", "content": content_prompt}],
                    temperature=0.1,  # 教育内容需要准确性，降低温度减少幻觉
                    max_tokens=self.max_tokens
                )

                response = await self.llm_client.call(request)

                if not response.success:
                    logger.error("[StoryboardDesigner] 阶段2失败: %s", response.error)
                    continue

                # 解析完整故事板
                storyboard = self._parse_storyboard(response.content, target_frames, title)

                # 验证内容完整性
                invalid_frames = self._validate_content_completeness(storyboard)
                if invalid_frames:
                    logger.warning("[StoryboardDesigner] 阶段2: 检测到%d帧内容不足", len(invalid_frames))
                    # 尝试重新生成内容不足的帧
                    storyboard = await self._regenerate_invalid_frames(
                        storyboard, invalid_frames, understanding_result, title
                    )

                logger.info("[StoryboardDesigner] ✓ 阶段2完成: 内容生成完成")
                break

            except Exception as e:
                logger.error("[StoryboardDesigner] 阶段2异常(尝试%d): %s", attempt + 1, str(e))
                if attempt == max_stage2_retries - 1:
                    # 最后使用回退结果
                    return self._create_fallback_result(title, understanding_result, target_frames, str(e))

        if storyboard is None:
            return self._create_fallback_result(title, understanding_result, target_frames, "内容生成失败")

        logger.info("[StoryboardDesigner] ========== 两阶段生成完成 ==========")
        return storyboard

    def _parse_outline(self, content: str, frame_count: int) -> List[Dict]:
        """解析阶段1生成的框架

        返回格式:
        [
            {"sceneID": "s1", "stage": "标题页", "slideType": "title", "frameTitle": "...", "subStage": ""},
            ...
        ]
        """
        outline = []
        lines = content.split('\n')

        current_frame = {}

        for line in lines:
            line = line.strip()
            if not line:
                continue

            # 检测新帧开始
            if line.startswith("## 帧") or line.startswith("# 帧") or line.startswith("帧"):
                if current_frame:
                    outline.append(current_frame)
                    current_frame = {}
                continue

            # 解析字段
            if ':' in line or '：' in line:
                if ':' in line:
                    key, value = line.split(':', 1)
                else:
                    key, value = line.split('：', 1)

                key = key.strip().lower()
                value = value.strip()

                if key == 'sceneid' or key == 'scene':
                    current_frame["sceneID"] = value
                elif key == 'stage' or key == '阶段':
                    current_frame["stage"] = value
                elif key == 'slidetype':
                    current_frame["slideType"] = value
                elif key == 'frametitle' or key == '标题':
                    current_frame["frameTitle"] = value
                elif key == 'substage' or key == 'sub_stage':
                    current_frame["subStage"] = value

        # 添加最后一帧
        if current_frame:
            outline.append(current_frame)

        # 如果解析为空，创建默认框架
        if not outline:
            logger.warning("[StoryboardDesigner] 框架解析为空，使用默认框架")
            return self._create_default_outline_list(frame_count)

        return outline

    def _create_default_outline_list(self, frame_count: int) -> List[Dict]:
        """创建默认框架列表"""
        default_types = ["title", "objectives", "intro", "concept", "concept", "concept",
                        "example", "example", "summary", "summary", "practice", "summary"]

        outline = []
        for i in range(frame_count):
            slide_type = default_types[i] if i < len(default_types) else "concept"
            outline.append({
                "sceneID": f"s{i + 1}",
                "stage": slide_type,
                "slideType": slide_type,
                "frameTitle": f"帧{i + 1}",
                "subStage": ""
            })
        return outline

    def _validate_outline_structure(self, outline: List[Dict], target_frames: int) -> Dict:
        """验证框架结构

        返回:
        {
            "valid": bool,
            "errors": List[str]
        }
        """
        errors = []

        # 检查帧数
        if len(outline) != target_frames:
            errors.append(f"帧数不匹配: 期望{target_frames}, 实际{len(outline)}")

        # 检查每帧必需字段
        required_fields = ["sceneID", "stage", "frameTitle"]
        valid_stages = ["title", "objectives", "intro", "concept", "example", "practice", "summary",
                       "标题页", "学习目标", "情境导入", "新知呈现", "例题示范", "巩固练习", "课堂小结"]

        for idx, frame in enumerate(outline):
            for field in required_fields:
                if field not in frame or not frame[field]:
                    errors.append(f"帧{idx + 1}缺少字段: {field}")

            # 检查stage是否有效
            stage = frame.get("stage", "")
            if stage not in valid_stages:
                errors.append(f"帧{idx + 1}的stage无效: {stage}")

        return {
            "valid": len(errors) == 0,
            "errors": errors
        }

    def _create_default_outline(self, understanding_result: Any, target_frames: int) -> List[Dict]:
        """基于理解结果创建默认框架"""
        outline = []

        # s1 标题页
        outline.append({
            "sceneID": "s1",
            "stage": "title",
            "slideType": "title",
            "frameTitle": understanding_result.title if hasattr(understanding_result, 'title') else "课程标题",
            "subStage": ""
        })

        # s2 学习目标
        outline.append({
            "sceneID": "s2",
            "stage": "objectives",
            "slideType": "objectives",
            "frameTitle": "学习目标",
            "subStage": ""
        })

        # s3 情境导入
        outline.append({
            "sceneID": "s3",
            "stage": "intro",
            "slideType": "intro",
            "frameTitle": "情境导入",
            "subStage": ""
        })

        # 知识点帧
        kp_count = len(understanding_result.knowledge_points) if hasattr(understanding_result, 'knowledge_points') else 3
        scene_idx = 4

        for i in range(min(kp_count, target_frames - scene_idx - 1)):
            kp = understanding_result.knowledge_points[i]
            outline.append({
                "sceneID": f"s{scene_idx}",
                "stage": "concept",
                "slideType": "concept",
                "frameTitle": kp.name if hasattr(kp, 'name') else f"知识点{i + 1}",
                "subStage": ""
            })
            scene_idx += 1

        # 补足帧数
        while len(outline) < target_frames:
            outline.append({
                "sceneID": f"s{len(outline) + 1}",
                "stage": "summary",
                "slideType": "summary",
                "frameTitle": "课堂小结",
                "subStage": ""
            })

        return outline

    def _format_frame_guidance(self, outline: List[Dict], target_frames: int) -> str:
        """将框架格式化为阶段2的指导文本

        格式:
        ## 帧1: [frameTitle]
        - stage: [stage]
        - slideType: [slideType]
        - subStage: [subStage]
        """
        guidance_lines = []

        for frame in outline:
            scene_id = frame.get("sceneID", "")
            frame_title = frame.get("frameTitle", "")
            stage = frame.get("stage", "")
            slide_type = frame.get("slideType", "")
            sub_stage = frame.get("subStage", "")

            guidance_lines.append(f"## {scene_id}: {frame_title}")
            guidance_lines.append(f"- stage: {stage}")
            guidance_lines.append(f"- slideType: {slide_type}")
            if sub_stage:
                guidance_lines.append(f"- subStage: {sub_stage}")
            guidance_lines.append("")

        return "\n".join(guidance_lines)

    async def design(
        self,
        title: str,
        understanding_result: Any,
        target_frames: int = 9
    ) -> StoryboardDesignResult:
        """
        设计教学故事板

        使用两阶段生成策略：
        - 阶段1：生成教学框架（结构）
        - 阶段2：基于框架生成完整内容

        Args:
            title: 课程标题
            understanding_result: 阶段1的内容理解结果
            target_frames: 目标帧数

        Returns:
            StoryboardDesignResult: 故事板设计结果
        """
        logger.info("[StoryboardDesigner] ========== 开始设计故事板 ==========")
        logger.info("[StoryboardDesigner] 课程标题: %s", title)
        logger.info("[StoryboardDesigner] 目标帧数: %d", target_frames)

        # 构建理解结果JSON字符串
        understanding_json = self._serialize_understanding_result(understanding_result)

        # 获取扩展规则（使用灵活结构指导）
        expansion_rules = self.EXPANSION_TEMPLATES["default"].format(
            target_frames=target_frames
        )

        # 使用两阶段生成
        try:
            storyboard = await self._generate_with_two_stages(
                title=title,
                understanding_result=understanding_result,
                understanding_json=understanding_json,
                target_frames=target_frames,
                expansion_rules=expansion_rules
            )

            if storyboard.success:
                logger.info("[StoryboardDesigner] ✓ 故事板设计完成")
                logger.info("[StoryboardDesigner]   - 总帧数: %d", storyboard.total_frames)
                logger.info("[StoryboardDesigner]   - 需要图示: %d 帧", sum(1 for f in storyboard.frames if f.needs_diagram))
            else:
                logger.warning("[StoryboardDesigner] 故事板设计使用回退结果: %s", storyboard.error)

            return storyboard

        except Exception as e:
            logger.error("[StoryboardDesigner] 设计异常: %s", str(e))
            import traceback
            logger.debug("[StoryboardDesigner] 异常堆栈: %s", traceback.format_exc()[:500])
            return self._create_fallback_result(title, understanding_result, target_frames, str(e))

    async def design_with_separation(
        self,
        title: str,
        understanding_result: Any,
        target_frames: int = 9,
        use_separation: bool = True
    ) -> StoryboardDesignResult:
        """
        使用方案A（三阶段分离）设计教学故事板

        流程：
        1. TeachingFlowDesigner - 规划教学流程
        2. ContentGenerator - 生成具体内容
        3. LayoutDesigner - 应用排版设计

        Args:
            title: 课程标题
            understanding_result: 阶段1的内容理解结果
            target_frames: 目标帧数
            use_separation: 是否使用分离模式（默认True）

        Returns:
            StoryboardDesignResult: 故事板设计结果
        """
        if not use_separation:
            # 使用原有方法
            return await self.design(title, understanding_result, target_frames)

        logger.info("[StoryboardDesigner] ========== 方案A：三阶段分离模式 ==========")
        logger.info("[StoryboardDesigner] 课程: %s, 目标帧数: %d", title, target_frames)

        try:
            # ========== 阶段1: 教学流程规划 ==========
            from .teaching_flow_designer import TeachingFlowDesigner

            flow_designer = TeachingFlowDesigner(self.llm_client)
            flow_result = await flow_designer.design_flow(title, understanding_result, target_frames)

            if not flow_result.success:
                logger.error("[StoryboardDesigner] 流程规划失败: %s", flow_result.error)
                return self._convert_to_storyboard_result(
                    self._create_fallback_result(title, understanding_result, target_frames, flow_result.error)
                )

            logger.info("[StoryboardDesigner] ✓ 阶段1完成: 规划%d帧", flow_result.total_frames)

            # ========== 阶段2: 内容生成 ==========
            from .content_generator import ContentGenerator

            content_generator = ContentGenerator(self.llm_client)
            content_result = await content_generator.generate_content(
                flow_result.frames,
                title,
                understanding_result
            )

            if not content_result.success:
                logger.error("[StoryboardDesigner] 内容生成失败: %s", content_result.error)
                return self._convert_to_storyboard_result(
                    self._create_fallback_result(title, understanding_result, target_frames, content_result.error)
                )

            logger.info("[StoryboardDesigner] ✓ 阶段2完成: 生成%d帧内容", content_result.total_frames)

            # ========== 阶段3: 排版设计 ==========
            from .layout_designer import LayoutDesigner

            layout_designer = LayoutDesigner(self.llm_client)
            layout_result = await layout_designer.design_layout(
                content_result.frames,
                understanding_result.course_type
            )

            if not layout_result.success:
                logger.error("[StoryboardDesigner] 排版设计失败: %s", layout_result.error)
                return self._convert_to_storyboard_result(
                    self._create_fallback_result(title, understanding_result, target_frames, layout_result.error)
                )

            logger.info("[StoryboardDesigner] ✓ 阶段3完成: 排版%d帧", layout_result.total_frames)

            # ========== 完成 ==========
            logger.info("[StoryboardDesigner] ========== 方案A完成 ==========")
            logger.info("[StoryboardDesigner]   - 总帧数: %d", layout_result.total_frames)
            logger.info("[StoryboardDesigner]   - 需要图示: %d帧", sum(1 for f in layout_result.frames if f.needs_diagram))

            return layout_result

        except Exception as e:
            logger.error("[StoryboardDesigner] 方案A执行异常: %s", str(e))
            import traceback
            logger.debug("[StoryboardDesigner] 异常堆栈: %s", traceback.format_exc()[:500])
            return self._convert_to_storyboard_result(
                self._create_fallback_result(title, understanding_result, target_frames, str(e))
            )

    def _convert_to_storyboard_result(self, result: Any) -> StoryboardDesignResult:
        """转换不同类型的结果为StoryboardDesignResult"""
        # 如果已经是StoryboardDesignResult，直接返回
        if isinstance(result, StoryboardDesignResult):
            return result
        # 否则创建一个空的结果
        return StoryboardDesignResult(success=False, error=str(result))

    def _serialize_understanding_result(self, result: Any) -> str:
        """将内容理解结果序列化为JSON字符串"""
        # 将KnowledgePoint对象转为字典
        knowledge_points = []
        for kp in result.knowledge_points:
            kp_dict = {
                "name": kp.name,
                "content": kp.content,
                "category": kp.category,
                "key_theorems": kp.key_theorems,
                "needs_diagram": kp.needs_diagram,
                "diagram_type": kp.diagram_type
            }
            knowledge_points.append(kp_dict)

        understanding_dict = {
            "course_type": result.course_type,
            "objectives": result.objectives,
            "knowledge_points": knowledge_points,
            "teaching_structure": result.teaching_structure
        }

        return json.dumps(understanding_dict, ensure_ascii=False, indent=2)

    def _parse_storyboard(self, content: str, frame_count: int, title: str) -> StoryboardDesignResult:
        """解析故事板内容"""
        frames = []

        # 按场景分割（支持多种格式）
        sections = self._split_sections(content)

        # 动态检测实际生成的帧数（可能超过target_frames，因为有子场景）
        actual_frame_count = min(len(sections), frame_count * 2)  # 最多2倍，防止无限

        logger.info("[StoryboardDesigner] 解析storyboard: 期望%d帧, 检测到%d个section",
                    frame_count, actual_frame_count)

        for i in range(actual_frame_count):
            try:
                # 查找对应的场景内容
                section = sections[i] if i < len(sections) else ""

                frame = self._parse_frame(section, i) if section else self._create_default_frame(i)
                frames.append(frame)
            except Exception as e:
                logger.warning("[StoryboardDesigner] 解析帧%d失败: %s", i+1, e)
                frames.append(self._create_default_frame(i))

        # 使用实际解析出的帧数
        actual_total = len(frames)

        # ========== 子场景规则验证 ==========
        frames = self._validate_and_fix_sub_scenes(frames)

        return StoryboardDesignResult(
            success=True,
            frames=frames,
            total_frames=actual_total,
            title=title
        )

    def _split_sections(self, content: str) -> List[str]:
        """分割内容为多个场景（支持子场景如 帧7a, 帧7b）"""
        # 尝试按"## 帧"分割（支持子场景格式如 "## 帧7a"）
        if "## 帧" in content:
            sections = content.split("## 帧")
        elif "# 帧" in content:
            sections = content.split("# 帧")
        elif "sceneID:" in content:
            # 按sceneID分割（支持 s7a, s7b 格式）
            pattern = r'\nsceneID:\s*\w+'
            sections = re.split(pattern, content)
        else:
            # 按段落分割
            sections = [p for p in content.split('\n\n') if p.strip()]

        return [s.strip() for s in sections if s.strip()]

    def _validate_and_fix_sub_scenes(self, frames: List[StoryboardFrame]) -> List[StoryboardFrame]:
        """
        验证并修复子场景分页规则

        检查规则：
        1. practice类型：超过2道题必须分页
        2. concept/example类型：超过350字必须分页
        """
        import re

        fixed_frames = []
        i = 0

        while i < len(frames):
            frame = frames[i]

            # 检测practice类型的题目数量
            if frame.stage in ['practice', '练习', '巩固练习']:
                question_count = self._count_questions_in_content(frame.main_content)

                if question_count > 2:
                    # 需要分页：拆分成子场景
                    logger.warning(
                        f"[StoryBoard验证] s{i+1}({frame.stage})有{question_count}道题，需要分页"
                    )

                    # 拆分题目
                    questions = self._split_questions(frame.main_content)
                    sub_frames = self._create_sub_frames_for_questions(
                        frame, questions, i
                    )
                    fixed_frames.extend(sub_frames)
                    i += 1
                    continue

            # 检测concept/example类型的字数
            if frame.stage in ['concept', 'example', '知识点详解', '例题示范']:
                # 计算中文字符数（去除LaTeX命令）
                chinese_chars = len(re.sub(r'\\[a-zA-Z{}$^_\\]+', '', frame.main_content))

                if chinese_chars > 350:
                    logger.warning(
                        f"[StoryBoard验证] s{i+1}({frame.stage})有{chinese_chars}字，需要分页"
                    )

                    # 拆分内容
                    sub_contents = self._split_long_content(frame.main_content)
                    sub_frames = self._create_sub_frames_for_content(
                        frame, sub_contents, i
                    )
                    fixed_frames.extend(sub_frames)
                    i += 1
                    continue

            # 无需分页，直接添加
            fixed_frames.append(frame)
            i += 1

        if len(fixed_frames) != len(frames):
            logger.info(
                f"[StoryBoard验证] 分页修复: {len(frames)}帧 → {len(fixed_frames)}帧"
            )

        return fixed_frames

    def _count_questions_in_content(self, content: str) -> int:
        """统计内容中的题目数量"""
        import re
        # 匹配 "1. "、"2. "、"①、"②" 等题目标记
        patterns = [
            r'\n\d+\.\s',  # 1. 2. 3.
            r'\n[①②③④⑤⑥⑦⑧⑨⑩]\s',  # 圆圈数字
            r'\n基础题|中等题|提升题',  # 题型标记
        ]
        count = 0
        for pattern in patterns:
            matches = re.findall(pattern, content)
            count += len(matches)
        return max(count, content.count('题目：'))

    def _split_questions(self, content: str) -> List[str]:
        """拆分内容中的题目"""
        import re
        # 按题目编号分割
        questions = re.split(r'\n(?=\d+\.\s|\([一二三四五六七八九十]+\))', content)
        return [q.strip() for q in questions if q.strip()]

    def _split_long_content(self, content: str) -> List[str]:
        """拆分过长内容"""
        import re
        # 按段落或itemize分割
        if '\\begin{itemize}' in content:
            # 提取所有item
            items = re.findall(r'\\item\s+([^\n]+)', content)
            # 每个子场景最多3个item
            chunks = []
            for i in range(0, len(items), 3):
                chunk_items = items[i:i+3]
                chunk_content = "\\begin{itemize}\n"
                for item in chunk_items:
                    chunk_content += f"\\item {item}\n"
                chunk_content += "\\end{itemize}"
                chunks.append(chunk_content)
            return chunks
        else:
            # 按段落分割
            paragraphs = content.split('\n\n')
            chunks = []
            current_chunk = ""
            for para in paragraphs:
                if len(current_chunk) + len(para) > 200:
                    chunks.append(current_chunk.strip())
                    current_chunk = para
                else:
                    current_chunk += "\n\n" + para if current_chunk else para
            if current_chunk:
                chunks.append(current_chunk.strip())
            return chunks

    def _create_sub_frames_for_questions(
        self,
        original_frame: StoryboardFrame,
        questions: List[str],
        base_index: int
    ) -> List[StoryboardFrame]:
        """为题目创建子场景帧"""
        sub_frames = []
        questions_per_frame = 2  # 每个子场景最多2道题

        for i in range(0, len(questions), questions_per_frame):
            chunk_questions = questions[i:i+questions_per_frame]
            sub_id = chr(97 + i // questions_per_frame)  # a, b, c...

            sub_frame = StoryboardFrame(
                scene_id=f"s{base_index + 1}{sub_id}",
                stage=original_frame.stage,
                frame_title=f"{original_frame.frame_title}（{i//questions_per_frame + 1}）",
                main_content="\n\n".join(chunk_questions),
                narration=f"{original_frame.narration}（第{i//questions_per_frame + 1}部分）"
            )
            sub_frames.append(sub_frame)

        return sub_frames

    def _create_sub_frames_for_content(
        self,
        original_frame: StoryboardFrame,
        contents: List[str],
        base_index: int
    ) -> List[StoryboardFrame]:
        """为长内容创建子场景帧"""
        sub_frames = []

        for i, content in enumerate(contents):
            sub_id = chr(97 + i)  # a, b, c...

            sub_frame = StoryboardFrame(
                scene_id=f"s{base_index + 1}{sub_id}",
                stage=original_frame.stage,
                frame_title=f"{original_frame.frame_title}（{i+1}/{len(contents)}）",
                main_content=content,
                narration=f"{original_frame.narration}（第{i+1}部分）"
            )
            sub_frames.append(sub_frame)

        return sub_frames

    def _parse_frame(self, section: str, index: int) -> StoryboardFrame:
        """解析单帧内容"""
        frame = StoryboardFrame(
            scene_id=f"s{index + 1}",
            stage="未知"
        )

        lines = section.split('\n')

        for line in lines:
            line = line.strip()
            if not line or line.startswith('#'):
                continue

            # 解析各种字段
            if line.lower().startswith('sceneid:') or line.lower().startswith('scene:'):
                frame.scene_id = line.split(':', 1)[-1].strip()
            elif line.startswith('stage:') or line.startswith('阶段:'):
                frame.stage = line.split(':', 1)[-1].strip()
            elif line.startswith('subStage:') or line.startswith('sub_stage:'):
                frame.sub_stage = line.split(':', 1)[-1].strip()
            elif line.startswith('slideType:') or line.startswith('slidetype:'):
                frame.stage = line.split(':', 1)[-1].strip()  # slideType映射到stage
            elif line.startswith('frameTitle:') or line.startswith('frametitle:') or line.startswith('标题:'):
                frame.frame_title = line.split(':', 1)[-1].strip()
            elif line.startswith('mainContent:') or line.startswith('maincontent:'):
                frame.main_content = line.split(':', 1)[-1].strip()
            elif line.startswith('narration:') or line.startswith('旁白:'):
                frame.narration = line.split(':', 1)[-1].strip()
            elif line.startswith('keyPoints:') or line.startswith('keypoints:'):
                points = line.split(':', 1)[-1].strip()
                frame.key_points = [p.strip() for p in points.split('|') if p.strip()]
            elif line.startswith('visualActions:') or line.startswith('visualactions:'):
                actions = line.split(':', 1)[-1].strip()
                frame.visual_actions = [a.strip() for a in actions.split('|') if a.strip()]
            elif line.startswith('needsDiagram:') or line.startswith('needsdiagram:'):
                frame.needs_diagram = "true" in line.lower() or "是" in line
            elif line.startswith('diagramSpec:') or line.startswith('diagramspec:'):
                # 尝试解析JSON
                try:
                    spec_str = line.split(':', 1)[-1].strip()
                    frame.diagram_spec = json.loads(spec_str)
                except:
                    frame.diagram_spec = {}

        # 确保有基本内容
        if not frame.frame_title:
            frame.frame_title = f"帧{index + 1}"
        if not frame.narration:
            frame.narration = "我们来看这帧内容"

        return frame

    def _create_default_frame(self, index: int) -> StoryboardFrame:
        """创建默认帧"""
        return StoryboardFrame(
            scene_id=f"s{index + 1}",
            stage="待定",
            frame_title=f"帧{index + 1}",
            narration="待填充",
            key_points=["要点待补充"]
        )

    def _create_fallback_result(
        self,
        title: str,
        understanding_result: Any,
        target_frames: int,
        error: str
    ) -> StoryboardDesignResult:
        """创建回退故事板"""
        logger.warning("[StoryboardDesigner] 使用回退策略")

        frames = []
        scene_idx = 1

        # s1 标题页
        frames.append(StoryboardFrame(
            scene_id="s1",
            stage="title",
            frame_title=title,
            main_content=title,
            narration=f"同学们好，今天我们学习{title}"
        ))

        # s2 学习目标
        if understanding_result.objectives:
            objectives_content = "\\begin{itemize}\n"
            for obj in understanding_result.objectives[:3]:
                objectives_content += f"\\item {obj}\n"
            objectives_content += "\\end{itemize}"

            frames.append(StoryboardFrame(
                scene_id="s2",
                stage="objectives",
                frame_title="学习目标",
                main_content=objectives_content,
                narration="让我们看看今天的学习目标"
            ))
            scene_idx = 3
        else:
            scene_idx = 2

        # 知识点帧
        for kp in understanding_result.knowledge_points[:target_frames - scene_idx]:
            needs_diagram = kp.needs_diagram
            diagram_spec = {}

            if needs_diagram and kp.diagram_type:
                diagram_spec = self._create_default_diagram_spec(kp.diagram_type, kp.name)

            frames.append(StoryboardFrame(
                scene_id=f"s{scene_idx}",
                stage="concept",
                frame_title=kp.name,
                main_content=kp.content,
                narration=f"我们来看{kp.name}的相关内容",
                needs_diagram=needs_diagram,
                diagram_spec=diagram_spec
            ))
            scene_idx += 1

        # 补足帧数
        while len(frames) < target_frames:
            frames.append(StoryboardFrame(
                scene_id=f"s{len(frames) + 1}",
                stage="summary",
                frame_title="课堂小结",
                main_content="本节课我们学习了核心知识点",
                narration="同学们，今天我们一起学习了这些内容"
            ))

        return StoryboardDesignResult(
            success=False,
            frames=frames,
            total_frames=target_frames,
            title=title,
            error=error
        )

    def _create_default_diagram_spec(self, diagram_type: str, title: str) -> Dict:
        """创建默认图示规格"""
        if diagram_type == "geometry":
            return {
                "type": "geometry",
                "shape": "triangle",
                "vertices": [[0, 0], [4, 0], [2, 3]],
                "labels": ["A", "B", "C"],
                "title": title
            }
        elif diagram_type == "function_plot":
            return {
                "type": "function_plot",
                "function": "x^2",
                "xRange": [-3, 3],
                "yRange": [-1, 10],
                "title": title
            }
        elif diagram_type == "chart":
            return {
                "type": "chart",
                "chartType": "bar",
                "data": {"categories": ["A", "B"], "values": [10, 20]},
                "title": title
            }
        else:
            return {}

    def _validate_content_completeness(self, storyboard: StoryboardDesignResult) -> List[int]:
        """验证内容完整性，返回内容不足的帧索引列表

        检查规则：
        - mainContent字数是否达到最低要求
        - keyPoints是否包含3-5个要点
        - 是否使用了占位符

        Returns:
            List[int]: 内容不足的帧索引（从0开始）
        """
        invalid_indices = []

        min_length_map = {
            "title": 0,
            "objectives": 50,
            "intro": 50,
            "concept": 100,
            "example": 80,
            "practice": 60,
            "summary": 40,
        }

        placeholder_keywords = ["待补充", "待填充", "待定", "省略", "等等", "之类"]

        for idx, frame in enumerate(storyboard.frames):
            # 检查mainContent字数
            content_len = len(frame.main_content.strip()) if frame.main_content else 0
            min_len = min_length_map.get(frame.stage, 50)

            if content_len < min_len:
                logger.warning("[StoryboardDesigner] 帧%s mainContent过短: %d字（要求>=%d字）",
                              frame.scene_id, content_len, min_len)
                invalid_indices.append(idx)
                continue

            # 检查是否包含占位符
            if any(keyword in (frame.main_content or "") for keyword in placeholder_keywords):
                logger.warning("[StoryboardDesigner] 帧%s 包含占位符", frame.scene_id)
                invalid_indices.append(idx)
                continue

            # 检查keyPoints数量（概念帧和例题帧需要3-5个要点）
            if frame.stage in ["concept", "example", "practice"]:
                points_count = len([p for p in frame.key_points if p.strip()])
                if points_count < 3:
                    logger.warning("[StoryboardDesigner] 帧%s keyPoints过少: %d个（要求3-5个）",
                                  frame.scene_id, points_count)
                    invalid_indices.append(idx)

        return invalid_indices

    async def _regenerate_invalid_frames(
        self,
        storyboard: StoryboardDesignResult,
        invalid_indices: List[int],
        understanding_result: Any,
        title: str
    ) -> StoryboardDesignResult:
        """重新生成内容不足的帧

        Args:
            storyboard: 原故事板
            invalid_indices: 需要重新生成的帧索引
            understanding_result: 内容理解结果
            title: 课程标题

        Returns:
            StoryboardDesignResult: 更新后的故事板
        """
        from shared.llm_client import LLMRequest

        for idx in invalid_indices:
            frame = storyboard.frames[idx]
            scene_id = frame.scene_id

            logger.info("[StoryboardDesigner] 重新生成帧%s: %s", scene_id, frame.frame_title)

            # 构建重新生成的提示词
            regenerate_prompt = f"""请为以下场景重新生成完整内容，确保达到字数要求：

场景ID: {scene_id}
帧类型: {frame.stage}
帧标题: {frame.frame_title}

⚠️ **最低字数要求**：
- 标题页（title）：0-20字
- 学习目标（objectives）：最低50字
- 情境导入（intro）：最低50字
- 知识点详解（concept）：最低100字
- 例题示范（example）：最低80字
- 巩固练习（practice）：最低60字
- 课堂小结（summary）：最低40字

⚠️ **核心要点要求**：
- 必须包含3-5个具体要点（用|分隔）
- 要点必须是具体知识点，不是空泛描述

请按照以下格式输出（仅输出替换内容，不要输出其他文字）：

mainContent: [完整的幻灯片内容，达到最低字数要求]
keyPoints: [要点1|要点2|要点3]
narration: [详细的旁白讲解，50-150字，逐步展开不跳跃]
"""

            try:
                request = LLMRequest(
                    messages=[{"role": "user", "content": regenerate_prompt}],
                    temperature=0.1,  # 教育内容需要准确性
                    max_tokens=16000
                )

                response = await self.llm_client.call(request)
                if response.success:
                    # 解析重新生成的内容
                    self._update_frame_from_regeneration(frame, response.content)
                    logger.info("[StoryboardDesigner] ✓ 帧%s 重新生成完成", scene_id)
                else:
                    logger.warning("[StoryboardDesigner] 帧%s 重新生成失败: %s", scene_id, response.error)

            except Exception as e:
                logger.error("[StoryboardDesigner] 帧%s 重新生成异常: %s", scene_id, str(e))

        return storyboard

    def _update_frame_from_regeneration(self, frame: StoryboardFrame, content: str):
        """从重新生成的内容更新帧数据"""
        lines = content.split('\n')

        for line in lines:
            line = line.strip()
            if line.startswith('mainContent:') or line.startswith('maincontent:'):
                frame.main_content = line.split(':', 1)[-1].strip()
            elif line.startswith('keyPoints:') or line.startswith('keypoints:'):
                points = line.split(':', 1)[-1].strip()
                frame.key_points = [p.strip() for p in points.split('|') if p.strip()]
            elif line.startswith('narration:') or line.startswith('旁白:'):
                frame.narration = line.split(':', 1)[-1].strip()
