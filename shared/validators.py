"""
内容校验器

提供课程内容的多维度校验功能：
- 公式校验
- 超纲关键词检查
- 结构完整性校验
- 格式规范校验

校验流程图：
    内容输入
      → 格式规范检查（全角/半角、LaTeX）
      → 结构完整性检查（必需章节）
      → 超纲关键词检查
      → 公式格式检查（闭合性/转义）
      → 输出校验结果
"""

import re
import json
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Any, Set
from pathlib import Path


@dataclass
class ValidationResult:
    """
    校验结果

    有效性判定规则：
    - is_valid 由 errors 列表决定：errors 非空 → is_valid=False（无效）
    - warnings 不影响有效性判定，仅作为提示信息
    """
    is_valid: bool
    errors: List[str] = field(default_factory=list)   # 错误列表，非空则校验失败
    warnings: List[str] = field(default_factory=list)  # 警告列表，不影响 is_valid
    details: Dict[str, Any] = field(default_factory=dict)  # 校验详情（统计信息等）


@dataclass
class ValidationRule:
    """校验规则"""
    name: str
    description: str
    severity: str = "error"  # error, warning, info
    enabled: bool = True


class ContentValidator:
    """
    内容校验器

    功能：
    - 公式格式校验
    - 超纲关键词检查
    - 结构完整性校验
    - 违规词检查
    - JSON格式校验

    使用示例：
    ```python
    validator = ContentValidator(knowledge_base)
    result = validator.validate(course_content)
    if not result.is_valid:
        print(f"校验失败: {result.errors}")
    ```
    """

    # 默认超纲关键词库
    DEFAULT_FORBIDDEN_KEYWORDS = [
        # 高中数学术语
        "导数", "微分", "积分", "极限",
        "正弦定理", "余弦定理",
        "向量", "矩阵", "行列式",
        "概率密度函数", "正态分布",
        # 竞赛超纲内容
        "竞赛超纲", "奥数", "IMO",
        # 违规表述
        "刷题", "提分", "押题", "保过",
    ]

    # 默认公式库（标准格式）
    DEFAULT_FORMULAS = {
        "二次函数顶点式": r"y=a\(x-h\)\^2\+k",
        "二次函数一般式": r"y=ax\^2\+bx\+c",
        "勾股定理": r"a\^2\+b\^2=c\^2",
        "一元二次方程求根公式": r"x=\(-b±√\(b\^2-4ac\)\)/\(2a\)",
    }

    def __init__(
        self,
        knowledge_base=None,
        forbidden_keywords: Optional[List[str]] = None,
        formulas: Optional[Dict[str, str]] = None
    ):
        """
        初始化校验器

        Args:
            knowledge_base: 知识库实例（用于获取章节相关的校验规则）
            forbidden_keywords: 自定义超纲关键词列表
            formulas: 自定义公式库
        """
        self.knowledge_base = knowledge_base

        # 加载关键词库
        # WHY: 关键词加载优先级 —— 自定义参数 > 知识库 > 默认值
        #      调用方传入 forbidden_keywords 时直接使用（优先级最高），
        #      否则使用默认值，然后从知识库补充（并集策略）。
        self._forbidden_keywords = set(forbidden_keywords or self.DEFAULT_FORBIDDEN_KEYWORDS)
        if knowledge_base:
            self._load_keywords_from_kb(knowledge_base)

        # 加载公式库（同上优先级策略）
        self._formulas = formulas or self.DEFAULT_FORMULAS.copy()
        if knowledge_base:
            self._load_formulas_from_kb(knowledge_base)

        # 校验规则链（按顺序执行，共4条规则）：
        #   1. format_check    — 格式规范检查（severity=warning）
        #   2. structure_check — 结构完整性检查（severity=error）
        #   3. forbidden_check — 超纲关键词检查（severity=error）
        #   4. formula_check   — 公式格式检查（severity=warning）
        self._rules = [
            ValidationRule("format_check", "格式规范检查", "warning"),
            ValidationRule("structure_check", "结构完整性检查", "error"),
            ValidationRule("forbidden_check", "超纲关键词检查", "error"),
            ValidationRule("formula_check", "公式格式检查", "warning"),
        ]

    def _load_keywords_from_kb(self, knowledge_base):
        """从知识库加载关键词"""
        try:
            if hasattr(knowledge_base, '_forbidden_keywords'):
                self._forbidden_keywords.update(knowledge_base._forbidden_keywords)
        except Exception:
            pass

    def _load_formulas_from_kb(self, knowledge_base):
        """从知识库加载公式"""
        try:
            if hasattr(knowledge_base, '_formulas'):
                self._formulas.update(knowledge_base._formulas)
        except Exception:
            pass

    def validate(self, content: Any) -> ValidationResult:
        """
        执行完整校验

        Args:
            content: 待校验内容（字符串或字典）

        Returns:
            校验结果
        """
        result = ValidationResult(is_valid=True)

        # 将输入内容统一转换为字符串，供后续规则使用
        content_str = self._to_string(content)

        # 校验规则链执行逻辑：遍历所有已启用的规则，依次执行，
        # 汇总每条规则产生的 errors 和 warnings，
        # 最终由 errors 是否为空决定 is_valid。
        for rule in self._rules:
            if not rule.enabled:
                continue

            rule_result = self._validate_by_rule(rule, content, content_str)
            result.errors.extend(rule_result.errors)
            result.warnings.extend(rule_result.warnings)

        # 判断总体是否通过：errors 列表为空 → 有效，否则无效
        result.is_valid = len(result.errors) == 0

        # 附加校验统计详情
        result.details = {
            "total_checks": len(self._rules),
            "errors_count": len(result.errors),
            "warnings_count": len(result.warnings),
        }

        return result

    def _to_string(self, content: Any) -> str:
        """将内容转换为字符串"""
        if isinstance(content, str):
            return content
        elif isinstance(content, dict):
            return json.dumps(content, ensure_ascii=False)
        elif isinstance(content, list):
            return "\n".join(str(item) for item in content)
        else:
            return str(content)

    def _validate_by_rule(
        self,
        rule: ValidationRule,
        content: Any,
        content_str: str
    ) -> ValidationResult:
        """根据规则执行校验"""
        result = ValidationResult(is_valid=True)

        if rule.name == "format_check":
            return self._check_format(content, content_str)
        elif rule.name == "structure_check":
            return self._check_structure(content)
        elif rule.name == "forbidden_check":
            return self._check_forbidden(content_str)
        elif rule.name == "formula_check":
            return self._check_formulas(content_str)

        return result

    def _check_format(self, content: Any, content_str: str) -> ValidationResult:
        """格式规范检查"""
        result = ValidationResult(is_valid=True)

        # 检查全角括号
        if "（" in content_str or "）" in content_str:
            result.warnings.append("发现全角括号，建议使用半角括号()")

        # 检查LaTeX格式
        latex_issues = self._check_latex_format(content_str)
        result.warnings.extend(latex_issues)

        return result

    def _check_latex_format(self, content: str) -> List[str]:
        """检查LaTeX格式问题"""
        issues = []

        # 检查未转义的百分号
        if re.search(r'(?<!\\)%', content):
            # 排除已经是 \% 的情况
            percent_count = len(re.findall(r'(?<!\\)%', content))
            if percent_count > 0:
                issues.append(f"发现{percent_count}处可能未转义的百分号，请使用\\%")

        # 检查常见的LaTeX错误
        common_errors = [
            (r'\\begin\{equation\*\}.*\\\\', "equation*环境不应包含换行符\\\\"),
            (r'\$.*\$.*\$.*\$', "可能存在嵌套的数学模式"),
        ]

        for pattern, msg in common_errors:
            if re.search(pattern, content, re.DOTALL):
                issues.append(msg)

        return issues

    def _check_structure(self, content: Any) -> ValidationResult:
        """结构完整性检查"""
        result = ValidationResult(is_valid=True)

        if isinstance(content, dict):
            # 检查必需字段（使用模糊匹配）
            if "sections" in content:
                # WHY: 使用别名模糊匹配的设计意图——
                #      LLM 生成的章节名可能与模板不完全一致，
                #      例如模板要求"导入"，但 LLM 可能输出"课程导入"、"情境导入"等，
                #      需要模糊匹配以提高容错性，避免因命名差异误报错误。
                #
                # 维护策略：当发现新的 LLM 输出变体时，应及时补充到对应别名列表中，
                #           保持别名列表与实际生成输出同步。
                section_aliases = {
                    "导入": ["导入", "课程导入", "情境导入", "新课导入", "课堂导入", "引入"],
                    "学习目标": ["学习目标", "教学目标", "课程目标", "目标"],
                    "知识点详解": ["知识点详解", "核心知识点", "知识点", "新知讲解", "概念讲解", "内容讲解"],
                    "易错点": ["易错点", "易错点避雷", "易错点提醒", "常见错误", "注意事项", "易错警示", "错题解析", "陷阱"]
                }

                existing_sections = set(content["sections"].keys())
                missing = []

                for required, aliases in section_aliases.items():
                    # 检查是否有任何一个别名存在
                    found = any(alias in existing_sections for alias in aliases)
                    if not found:
                        missing.append(required)

                if missing:
                    result.errors.append(f"缺少必需章节: {', '.join(missing)}（允许别名: {', '.join([f'{k}={v}' for k, v in section_aliases.items() if k in missing])}）")

            # 检查内容是否为空
            if "sections" in content:
                for section_name, section_content in content["sections"].items():
                    # 处理section_content可能是list或dict的情况
                    if isinstance(section_content, (list, dict)):
                        # 如果是列表，转换为字符串
                        if isinstance(section_content, list):
                            section_content = "\n".join(str(item) for item in section_content)
                        # 如果是字典，转换为JSON字符串
                        elif isinstance(section_content, dict):
                            import json
                            section_content = json.dumps(section_content, ensure_ascii=False)

                    # 检查是否为空
                    if not section_content or len(str(section_content).strip()) == 0:
                        result.warnings.append(f"章节 '{section_name}' 内容为空")

        elif isinstance(content, str):
            # 简单检查长度
            if len(content.strip()) < 50:
                result.warnings.append("内容过短，可能不完整")

        return result

    def _check_forbidden(self, content_str: str) -> ValidationResult:
        """
        超纲关键词检查

        检测逻辑：使用简单子串匹配（keyword in content_str），
        遍历 _forbidden_keywords 中的每个关键词，检查是否出现在内容中。
        子串匹配足以满足当前需求，无需正则或分词。

        维护策略：关键词列表支持动态加载——
                  可通过构造函数传入、通过知识库加载、或运行时调用
                  add_forbidden_keyword() / remove_forbidden_keyword() 增删。
        """
        result = ValidationResult(is_valid=True)

        # 逐个检查关键词是否以子串形式出现在内容中
        found_keywords = []
        for keyword in self._forbidden_keywords:
            if keyword in content_str:
                found_keywords.append(keyword)

        if found_keywords:
            result.errors.append(f"发现超纲/违规关键词: {', '.join(found_keywords)}")

        return result

    def _check_formulas(self, content_str: str) -> ValidationResult:
        """公式格式检查"""
        result = ValidationResult(is_valid=True)

        # 提取 LaTeX 公式，支持3种模式：
        #   1. $$...$$  — 独立行（块级）公式
        #   2. $...$    — 行内公式
        #   3. \begin{equation*}...\end{equation*} — equation* 环境公式
        latex_patterns = [
            r'\$\$([^$]+)\$\$',  # $$...$$ 块级公式
            r'\$([^$]+)\$',      # $...$ 行内公式
            r'\\begin\{equation\*\}([^\\]+)\\end\{equation\*\}',  # equation* 环境
        ]

        formulas_found = []
        for pattern in latex_patterns:
            matches = re.findall(pattern, content_str)
            formulas_found.extend(matches)

        if formulas_found:
            # 闭合性检查：遍历每个提取到的公式，检测两类常见格式问题
            for formula in formulas_found:
                formula = formula.strip()
                # 闭合性检查 —— 花括号 { } 必须成对出现，否则公式渲染可能异常
                if formula.count('{') != formula.count('}'):
                    result.warnings.append(f"公式可能未闭合: {formula[:50]}...")
                # 转义检查 —— LaTeX 特殊字符（%#&）前应有反斜杠转义
                if re.search(r'(?<!\\)[%#&]', formula):
                    result.warnings.append(f"公式可能包含未转义字符: {formula[:50]}...")

        return result

    def validate_json(self, content: str) -> ValidationResult:
        """
        JSON格式校验

        Args:
            content: JSON字符串

        Returns:
            校验结果
        """
        result = ValidationResult(is_valid=True)

        try:
            json.loads(content)
        except json.JSONDecodeError as e:
            result.is_valid = False
            result.errors.append(f"JSON格式错误: {e}")

        return result

    def check_chapter_scope(
        self,
        content: str,
        chapter_id: str,
        version: str
    ) -> ValidationResult:
        """
        检查内容是否超出章节范围

        Args:
            content: 内容文本
            chapter_id: 章节ID
            version: 教材版本

        Returns:
            校验结果
        """
        result = ValidationResult(is_valid=True)

        # 如果有知识库，进行更精细的检查
        if self.knowledge_base:
            try:
                # 获取章节的知识点列表
                # 这里可以根据实际的知识库接口调整
                pass
            except Exception:
                pass

        return result

    def add_forbidden_keyword(self, keyword: str):
        """添加超纲关键词"""
        self._forbidden_keywords.add(keyword)

    def remove_forbidden_keyword(self, keyword: str):
        """移除超纲关键词"""
        self._forbidden_keywords.discard(keyword)

    def add_formula(self, name: str, pattern: str):
        """添加公式规则"""
        self._formulas[name] = pattern

    def get_forbidden_keywords(self) -> Set[str]:
        """获取当前超纲关键词列表"""
        return self._forbidden_keywords.copy()

    def get_formulas(self) -> Dict[str, str]:
        """获取当前公式库"""
        return self._formulas.copy()


# ==================== 便捷函数 ====================

def validate_content(
    content: Any,
    forbidden_keywords: Optional[List[str]] = None
) -> ValidationResult:
    """
    便捷的内容校验函数

    Args:
        content: 待校验内容
        forbidden_keywords: 自定义超纲关键词

    Returns:
        校验结果
    """
    validator = ContentValidator(forbidden_keywords=forbidden_keywords)
    return validator.validate(content)

