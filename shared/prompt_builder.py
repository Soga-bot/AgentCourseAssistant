"""
提示词构建器

提供提示词模板管理和变量替换功能：
- 模板管理（内置模板 + 外部文件模板）
- 变量替换
- 版本控制
- 模板继承
"""

import os
import json
from pathlib import Path
from string import Template
from typing import Dict, Any, Optional, List
from dataclasses import dataclass, field


@dataclass
class PromptTemplate:
    """提示词模板"""
    name: str
    template: str
    version: str = "1.0"
    description: str = ""
    variables: List[str] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)


class PromptBuilder:
    """
    提示词构建器

    功能：
    - 内置模板管理
    - 外部文件模板加载
    - 变量安全替换
    - 模板继承和组合
    - 版本控制

    使用示例：
    ```python
    builder = PromptBuilder()

    # 使用内置模板
    prompt = builder.build("course_outline", {
        "grade": "七年级",
        "topic": "有理数"
    })

    # 添加自定义模板
    builder.add_template("my_template", "Hello ${name}!")

    # 从文件加载
    builder.load_templates_from_dir("./templates")
    ```
    """

    # 内置模板定义
    BUILT_IN_TEMPLATES = {
        "course_outline": r"""【角色】你是有10年教龄的初中数学特级教师，严格遵循2022版义务教育数学新课标，熟悉初中数学所有版本教材和中考考情，擅长总结解题方法。

【任务】用户需要生成初中${grade}数学的自定义专题，专题名称/粗目录为：${topic}，请你补全为符合教学逻辑的完整大纲。

【输出要求】
1. 大纲按"课时→子知识点→重难点→常考题型"的结构输出，每个子知识点标注课标要求层级（了解/理解/掌握/应用）
2. 所有内容必须在初中数学课标范围内，严禁超纲
3. 题型必须符合初中数学的考法，不能出现竞赛题、高中题
4. 输出格式为JSON，包含以下字段：
   - title: 专题标题
   - sessions: 课时列表，每课时包含：
     - session_name: 课时名称
     - knowledge_points: 知识点列表
     - difficulties: 重难点
     - question_types: 常考题型
     - curriculum_level: 课标要求

【禁忌】不得使用高中数学定理、术语，不得偏离用户的专题需求

现在开始生成大纲，请直接输出JSON：""",

        "course_content": r"""【角色设定】你是有10年教龄的初中数学特级教师，连续5年带初三毕业班，熟悉${version}初中数学教材内容，擅长把抽象知识点讲的通俗易懂，讲解适配${student_level}的学生水平。

【约束信息】
1. 本节对应课标要求：${curriculum_requirement}
2. 本节核心知识点顺序：${knowledge_points}
3. 本节重难点：${key_difficulties}
4. 本节学生高频易错点：${common_mistakes}

【生成规则】
1. 讲解深度严格匹配学情：
   ▶ 基础薄弱：概念拆解到最细，计算步骤一步不跳，每步标注依据
   ▶ 中等巩固：概念讲透，加易混点辨析，例题覆盖80%常规考点
   ▶ 培优拓展：概念延伸拓展，加一题多解、题型变形

2. 章节结构说明（所有章节均为必填，必须包含实质性内容）：

   **必填章节（必须包含实质性内容，严禁为空）：**
   ▶ 课程导入（100-200字，用生活化场景引入本节课主题）
   ▶ 学习目标（分三个维度撰写：①知识与技能目标（具体、可测量）；②过程与方法目标（体现学生活动）；③情感态度目标（恰当自然）。内容控制在100-150字）
   ▶ 知识点详解（核心章节！详细讲解每个知识点，使用简单的文本格式表达数学内容，避免复杂LaTeX，内容不得少于300字）
   ▶ 典例精讲（2-3道典型例题，每道：题目→【思路引导】→完整步骤→【易错提醒】→【方法总结】）
   ▶ 易错点（根据内容复杂度灵活调整：简单章节1-2个，复杂章节3-5个，每个写清：错误表现→错误原因→正确做法）
   ▶ 随堂小测（5道题，3基础+1中等+1提升，附完整答案和解析）
   ▶ 知识框架（用层级文本或列表形式总结本节课所有知识点）
   ▶ 课后拓展（仅1个！不要写多个，选择最有价值的生活应用或思维拓展题）

【重要输出规则】
1. JSON格式要求：
   - 所有章节必须包含且内容不能为空
   - 特别注意："易错点"是必填章节，必须在JSON中使用"易错点"作为键名
   - 所有章节内容必须是实质性文本，不能是空字符串、占位符或省略号

2. 内容质量要求：
   - "知识点详解"是核心章节，必须包含详细的概念解释、公式推导，内容不得少于300字
   - "易错点"章节必须包含至少1个具体错误案例，简单章节1-2个即可，复杂章节可写3-5个，不能省略或为空
   - 每个章节的内容都必须完整、具体，不能是"待补充"、"见教案"等占位文本
   - 数学符号可以用LaTeX格式（如\neq、\leq、\frac）或简单文本（如≠、≤、a/b），系统会自动转换
   - 易错点数量应根据实际内容决定，宁可写少写精，不要为了凑数而编造不存在的错误
   - 【禁止】内容中不得出现"待补充"、"待填充"、"SceneID:"等占位符或未完成标记

【禁忌要求】
1. 严禁超纲：几何证明只能用初中课标规定的定理
2. 严禁知识性错误：所有公式、定理、计算结果必须准确
3. 严禁出现违规表述：不得出现"刷题""提分""押题"等内容
4. 语言通俗易懂，符合12-15岁学生的理解能力

【输出格式要求】

请严格按照以下JSON格式输出（注意：章节名称必须完全匹配）：

{
  "title": "课程标题",
  "sections": {
    "导入": "内容（100-200字生活化场景引入）",
    "学习目标": "内容（分三个维度：①知识与技能（理解...、掌握...）；②过程与方法（通过...、参与...）；③情感态度（培养...、体会...），100-150字）",
    "知识点详解": "内容（详细讲解，不少于300字）",
    "典例精讲": "内容（2-3道典型例题，每道包含题目、思路引导、完整步骤、易错提醒、方法总结）",
    "易错点": "内容（根据内容复杂度：简单章节1-2个，复杂章节3-5个，每个写清错误表现、原因和正确做法）",
    "随堂小测": "内容（5道题：3基础+1中等+1提升，附完整答案和解析）",
    "知识框架": "内容（层级结构总结）",
    "课后拓展": "内容（仅1个！严格遵守！只写1个最有价值的生活应用题或思维拓展题）"
  }
}

【格式要求】
为确保内容易读性和后续渲染正确，请严格遵守以下格式规范：

1. 段落分隔：不同段落之间使用 \\n\\n 分隔（两个换行符）

2. 小标题格式：使用【标题】格式，注意【和】与文字之间不要有空格
   ✅ 正确：【一、有理数的概念】
   ❌ 错误：【 一、 有理数的概念 】（有多余空格）

3. 列举格式：
   - 数字序号后要有标点：1. 2. 3. 或 1、2、3、
   - 中文序号格式：一、二、三、（使用顿号）
   - 每个要点独占一行

4. 数学表达式：
   - 分数使用LaTeX竖式格式：\\frac{分子}{分母}（如 \\frac{1}{2}、\\frac{a}{b}）
   - 不等号使用LaTeX格式：\\neq（≠）、\\leq（≤）、\\geq（≥）
   - 其他数学符号：\\approx（≈）、\\pm（±）、\\times（×）、\\div（÷）
   - 数学表达式用$包裹：$\\frac{1}{2}$、$a \\neq b$

5. 结构清晰：每个知识点独立成段，避免连写

【格式示例】
"导入": "同学们好！\\n\\n今天我们来学习有理数。\\n\\n生活中常见的例子：..."

【关键说明】
1. 所有章节都是必填的，必须包含且内容不能为空
2. "学习目标"必须分三个维度撰写：知识与技能、过程与方法、情感态度，控制在100-150字
3. "知识点详解"必须包含详细的概念解释、公式推导，内容不得少于300字
4. "易错点"数量要求：至少1个，简单章节1-2个即可，复杂章节可写3-5个，根据实际内容决定
5. "典例精讲"需要2-3道典型例题，每道包含完整的思路引导和解题步骤
6. "随堂小测"需要5道题（3基础+1中等+1提升），必须附完整答案和解析
7. 易错点宁可写少写精，不要为了凑数量而编造不存在的错误

现在开始生成内容：""",

        "lesson_plan": """【角色设定】你是有15年教龄的初中数学特级教师，教学处主任，擅长撰写规范的教案。

【教学任务】
课题：${custom_topic}
教学内容：${custom_outline}

【教案撰写要求】
1. 教学目标要分三个维度：
   - 知识与技能目标（具体、可测量）
   - 过程与方法目标（体现学生活动）
   - 情感态度与价值观目标（恰当、自然）

2. 教学重点和难点：
   - 教学重点：本节课的核心内容
   - 教学难点：学生理解困难的地方

3. 教学过程（按时间分配）：
   - 导入新课（3-5分钟）：创设情境，激发兴趣
   - 探究新知（15-20分钟）：师生互动，建构知识
   - 例题讲解（10-15分钟）：示范解题，总结方法
   - 巩固练习（8-10分钟）：学生练习，及时反馈
   - 课堂小结（2-3分钟）：梳理知识，形成体系
   - 布置作业（1-2分钟）：分层作业，巩固提高

4. 板书设计：简洁明了，突出重点

【输出格式】
{
  "title": "教案标题",
  "sections": {
    "教学目标": "分三个维度撰写...",
    "教学重点": "本节课核心内容",
    "教学难点": "学生理解困难之处",
    "教学方法": "讲授法、讨论法、练习法等",
    "教学准备": "教具、学具准备",
    "教学过程": "按环节详细描述",
    "板书设计": "简洁的板书布局"
  }
}

现在开始撰写教案：""",

        "teaching_script": """【角色设定】你是经验丰富的初中数学教师，擅长撰写课堂逐字稿。

【教学内容】
课题：${custom_topic}
教学内容：${custom_outline}

【逐字稿撰写要求】
1. 语言风格：口语化，亲切自然，使用设问引导思考
2. 结构要求：导入语、知识讲解、互动提问、例题分析、总结语
3. 细节要求：标注教师动作、预设学生回答、公式用LaTeX格式

【输出格式】
{
  "title": "逐字稿标题",
  "sections": {
    "导入语": "同学们好，今天我们来学习...",
    "新课讲解": "首先，请同学们思考...",
    "师生互动": "（提问）谁来说说你的想法？...",
    "例题讲解": "来看这道例题，第一步...",
    "课堂总结": "今天我们学习了...",
    "结束语": "好，这节课就到这里，下课！"
  }
}

现在开始撰写逐字稿：""",

        "board_design": """【角色设定】你是资深数学教师，擅长设计简洁有效的板书。

【教学内容】
课题：${custom_topic}
教学内容：${custom_outline}

【板书设计原则】
1. 简洁明了：一课一板，突出重点
2. 层次清晰：主标题、副标题、内容分区
3. 图文并茂：文字、公式、图形结合

【输出格式】
{
  "title": "板书设计标题",
  "sections": {
    "主标题": "居中，大字",
    "左侧板书": "知识点、公式、定理",
    "右侧板书": "图形、例题、示意图",
    "底部板书": "重点总结、作业布置"
  }
}

现在开始设计板书：""",

        "review_outline": """【角色设定】你是教学经验丰富的初三数学教师，擅长专题复习。

【复习任务】
专题：${custom_topic}
复习范围：${custom_outline}

【复习课设计要求】
1. 知识梳理：构建知识网络图
2. 考点分析：中考考点分布
3. 方法总结：通性通法
4. 典例精讲：中考真题

【输出格式】
{
  "title": "复习串讲标题",
  "sections": {
    "知识网络": "用思维导图展示",
    "核心考点": "中考考点和分值",
    "重点公式": "涉及的公式定理",
    "解题方法": "常用方法和技巧",
    "典例精讲": "精选例题详解",
    "易错提醒": "常见错误及避坑"
  }
}

现在开始撰写复习大纲：""",

        "custom_outline": """【角色设定】你是有10年教龄的初中数学特级教师，擅长设计课程大纲。

【任务描述】
用户提供了自定义内容：${custom_topic}
需要将其整理为完整的教学大纲。

【大纲设计要求】
1. 结构完整：主题、知识点、重难点、流程
2. 层次清晰：按逻辑顺序排列
3. 可操作性强：具体内容、时间分配

【输出格式】
{
  "title": "课程大纲标题",
  "sections": {
    "课程概述": "简要介绍课程主题和目标",
    "知识点分解": "列出本课包含的知识点",
    "重点难点": "标注重点和难点",
    "教学流程": "按环节设计教学活动",
    "时间分配": "各环节建议时间"
  }
}

现在开始设计大纲：""",

        "course_modify": """【角色】同核心课程生成模板

【原内容】
${original_content}

【用户修改要求】${user_request}

【要求】
1. 保留原有结构，仅修改用户要求调整的部分
2. 其他内容保持不变
3. 所有公式、计算结果必须准确
4. 使用JSON格式输出，结构与原内容一致

现在开始修改：""",

        "video_storyboard": """【角色】你是专业的数学教学视频分镜设计师，擅长将数学题目拆解为易懂的视觉化教学步骤。

【题目】${problem}

【难度】${difficulty}（预计${frame_count}帧）

【任务】请设计详细的教学分镜，要求：
1. 每帧包含：sceneID、frameTitle、narration（旁白）、keyPoints（关键点）、equations（公式）
2. 采用苏格拉底式教学，每帧设置引导性问题
3. 视觉效果要清晰：HIGHLIGHT高亮、RED强调、BOLD加粗

【输出JSON格式】
{
  "title": "题目标题",
  "difficulty": "难度",
  "totalSlides": 帧数,
  "scenes": [
    {
      "sceneID": "s1",
      "frameTitle": "帧标题",
      "narration": "旁白文案",
      "socraticQuestion": "引导问题",
      "keyPoints": ["关键点1", "关键点2"],
      "equations": ["公式1", "公式2"],
      "visualActions": "视觉描述"
    }
  ]
}

现在开始设计分镜：""",
    }

    def __init__(self, template_dir: Optional[str] = None):
        self.template_dir = Path(template_dir) if template_dir else None
        self._templates: Dict[str, PromptTemplate] = {}
        self._load_built_in_templates()

        # 从外部目录加载模板
        if self.template_dir and self.template_dir.exists():
            self.load_templates_from_dir(self.template_dir)

    def _load_built_in_templates(self):
        """加载内置模板"""
        for name, template in self.BUILT_IN_TEMPLATES.items():
            self._templates[name] = PromptTemplate(
                name=name,
                template=template,
                variables=self._extract_variables(template)
            )

    def _extract_variables(self, template: str) -> List[str]:
        """从模板中提取变量名"""
        import re
        pattern = r'\$\{(\w+)\}'
        return list(set(re.findall(pattern, template)))

    def add_template(
        self,
        name: str,
        template: str,
        version: str = "1.0",
        description: str = "",
        metadata: Dict[str, Any] = None
    ):
        """
        添加自定义模板

        Args:
            name: 模板名称
            template: 模板内容
            version: 版本号
            description: 描述
            metadata: 元数据
        """
        self._templates[name] = PromptTemplate(
            name=name,
            template=template,
            version=version,
            description=description,
            variables=self._extract_variables(template),
            metadata=metadata or {}
        )

    def remove_template(self, name: str):
        """移除模板"""
        if name in self._templates:
            del self._templates[name]

    def load_templates_from_dir(self, directory: str):
        """
        从目录加载模板文件

        支持的文件格式：
        - .txt: 纯文本模板
        - .json: JSON格式模板（包含name、template、version等）
        - .md: Markdown格式模板
        """
        dir_path = Path(directory)
        if not dir_path.exists():
            return

        for file in dir_path.glob("*"):
            if file.is_file():
                if file.suffix == ".json":
                    self._load_json_template(file)
                elif file.suffix in [".txt", ".md"]:
                    self._load_text_template(file)

    def _load_json_template(self, file_path: Path):
        """加载JSON格式模板"""
        try:
            with open(file_path, encoding="utf-8") as f:
                data = json.load(f)
            self._templates[data["name"]] = PromptTemplate(
                name=data["name"],
                template=data["template"],
                version=data.get("version", "1.0"),
                description=data.get("description", ""),
                variables=self._extract_variables(data["template"]),
                metadata=data.get("metadata", {})
            )
        except Exception as e:
            print(f"  [!] 加载模板失败 {file_path}: {e}")

    def _load_text_template(self, file_path: Path):
        """加载文本格式模板"""
        try:
            with open(file_path, encoding="utf-8") as f:
                content = f.read()
            name = file_path.stem
            self._templates[name] = PromptTemplate(
                name=name,
                template=content,
                variables=self._extract_variables(content)
            )
        except Exception as e:
            print(f"  [!] 加载模板失败 {file_path}: {e}")

    def build(
        self,
        template_name: str,
        variables: Dict[str, Any],
        strict: bool = False
    ) -> str:
        """
        构建提示词

        Args:
            template_name: 模板名称
            variables: 模板变量
            strict: 严格模式，未定义变量时抛出异常

        Returns:
            构建后的提示词

        Raises:
            ValueError: 模板不存在或严格模式下变量缺失
        """
        template_obj = self._templates.get(template_name)
        if not template_obj:
            available = list(self._templates.keys())
            raise ValueError(f"模板不存在: {template_name}，可用模板: {available}")

        # 检查变量
        if strict:
            missing = set(template_obj.variables) - set(variables.keys())
            if missing:
                raise ValueError(f"缺少变量: {missing}")

        # 安全替换（使用Template.safe_substitute避免变量缺失时崩溃）
        try:
            result = Template(template_obj.template).safe_substitute(**variables)
            return result
        except Exception as e:
            raise ValueError(f"模板构建失败: {e}")

    def build_with_default(
        self,
        template_name: str,
        variables: Dict[str, Any],
        default_values: Dict[str, Any] = None
    ) -> str:
        """
        使用默认值构建提示词

        Args:
            template_name: 模板名称
            variables: 模板变量
            default_values: 默认值字典

        Returns:
            构建后的提示词
        """
        if default_values:
            merged = {**default_values, **variables}
        else:
            merged = variables
        return self.build(template_name, merged)

    def get_template(self, name: str) -> Optional[PromptTemplate]:
        """获取模板对象"""
        return self._templates.get(name)

    def list_templates(self) -> List[str]:
        """列出所有模板名称"""
        return list(self._templates.keys())

    def list_template_info(self) -> List[Dict[str, Any]]:
        """列出所有模板的详细信息"""
        return [
            {
                "name": t.name,
                "version": t.version,
                "description": t.description,
                "variables": t.variables,
            }
            for t in self._templates.values()
        ]

    def export_template(self, name: str, output_path: str):
        """
        导出模板到文件

        Args:
            name: 模板名称
            output_path: 输出文件路径（.json或.txt）
        """
        template = self._templates.get(name)
        if not template:
            raise ValueError(f"模板不存在: {name}")

        output = Path(output_path)
        if output.suffix == ".json":
            data = {
                "name": template.name,
                "template": template.template,
                "version": template.version,
                "description": template.description,
                "variables": template.variables,
                "metadata": template.metadata,
            }
            with open(output, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        else:
            with open(output, "w", encoding="utf-8") as f:
                f.write(template.template)

    def validate_template(self, template: str) -> List[str]:
        """
        验证模板语法

        Args:
            template: 模板内容

        Returns:
            错误列表（空表示无错误）
        """
        errors = []

        # 检查变量语法
        import re
        variables = re.findall(r'\$\{(\w+)\}', template)
        for var in variables:
            if not re.match(r'^[a-zA-Z_]\w*$', var):
                errors.append(f"无效变量名: ${{{var}}}")

        # 检查未闭合的变量
        open_count = template.count('${')
        close_count = template.count('}')
        if open_count != close_count:
            errors.append("变量未正确闭合")

        return errors

    def compose(self, template_names: List[str], separator: str = "\n\n") -> str:
        """
        组合多个模板

        Args:
            template_names: 模板名称列表
            separator: 分隔符

        Returns:
            组合后的模板
        """
        parts = []
        for name in template_names:
            template = self._templates.get(name)
            if template:
                parts.append(template.template)
            else:
                raise ValueError(f"模板不存在: {name}")
        return separator.join(parts)


# ==================== 便捷函数 ====================

def build_prompt(
    template_name: str,
    variables: Dict[str, Any],
    template_dir: Optional[str] = None
) -> str:
    """
    便捷的提示词构建函数

    Args:
        template_name: 模板名称
        variables: 模板变量
        template_dir: 自定义模板目录

    Returns:
        构建后的提示词
    """
    builder = PromptBuilder(template_dir)
    return builder.build(template_name, variables)

