"""
数学符号朗读规则处理器

职责：
1. 将LaTeX数学公式转换为适合TTS朗读的中文文本
2. 处理数学符号的特殊朗读规则（如省略的乘号、正负号等）
3. 确保数学公式朗读的准确性和自然度

朗读规则：
- -3 → "负三"（数字前的负号读作"负"）
- a - b → "a减b"（表达式间的减号读作"减"）
- 2x → "2乘以x"（省略的乘号要读出来）
- (x+1) → "括号x加1括号"或"左括号x加1右括号"
- x² → "x的平方"
- |x| → "x的绝对值"
- √x → "x的算术平方根"
"""

import re
import logging
from typing import Dict, List, Tuple, Optional

logger = logging.getLogger(__name__)


class MathSymbolReader:
    """
    数学符号朗读规则处理器

    使用示例：
    ```python
    # 处理单个文本
    processed, rules = MathSymbolReader.process("-3 + 2x = 1")
    # processed: "负三加2乘以x等于1"

    # 处理包含LaTeX的文本
    processed, rules = MathSymbolReader.process("$x^2 - 3x + 2 = 0$")
    # processed: "x的平方减3乘以x加2等于0"
    ```
    """

    # ========== 朗读规则定义 ==========
    # 按优先级排序（优先级越高越先应用）
    READING_RULES = [
        {
            "name": "sqrt_unicode",
            "priority": 1,
            "description": "算术平方根的读法（Unicode符号）：√x → x的算术平方根",
            "patterns": [
                (r'√\s*([^\\s，。]+)', r'\1的算术平方根'),
            ],
            "examples": [("√x", "x的算术平方根"), ("√2", "2的算术平方根")]
        },
        {
            "name": "absolute_value",
            "priority": 2,
            "description": "绝对值的读法：|x| → x的绝对值",
            "patterns": [
                (r'\|([^|]+)\|', r'\1的绝对值'),
            ],
            "examples": [("|x|", "x的绝对值"), ("|-3|", "负3的绝对值")]
        },
        {
            "name": "negative_number",
            "priority": 3,
            "description": "负数的读法：-3 → 负三",
            "patterns": [
                # 匹配：负数（负号后跟数字）
                # -3 → 负三, -5.5 → 负五点五
                (r'-(\d+\.?\d*)', r'负\1'),
            ],
            "examples": [("-3", "负三"), ("-5.5", "负五点五"), ("-0.5", "负零点五")]
        },
        {
            "name": "power_2_3",
            "priority": 4,
            "description": "平方和立方的读法",
            "patterns": [
                # x^2 → x的平方, y^3 → y的立方
                (r'([a-zA-Z])\^2', r'\1的平方'),
                (r'([a-zA-Z])\^3', r'\1的立方'),
            ],
            "examples": [("x^2", "x的平方"), ("y^3", "y的立方")]
        },
        {
            "name": "power_general",
            "priority": 5,
            "description": "一般幂的读法：x^n → x的n次方",
            "patterns": [
                (r'([a-zA-Z])\^(\d+)', r'\1的\2次方'),
            ],
            "examples": [("x^5", "x的5次方"), ("a^10", "a的10次方")]
        },
        {
            "name": "fraction_simple",
            "priority": 6,
            "description": "简单分数的读法：1/2 → 二分之一",
            "patterns": [
                # 匹配：\frac{1}{2} → 1除以2 → 特殊处理 → 二分之一
                # 这里先转换为"1除以2"，后面会有特殊数字朗读处理
                (r'\\frac\{(\d+)\}\{(\d+)\}', r'\1分之\2'),
            ],
            "examples": [("1/2", "二分之一"), ("3/4", "四分之三")]
        },
        {
            "name": "fraction_general",
            "priority": 7,
            "description": "一般分数的读法：a/b → a除以b",
            "patterns": [
                (r'\\frac\{([^}]+)\}\{([^}]+)\}', r'\1除以\2'),
            ],
            "examples": [("a/b", "a除以b"), ("(x+1)/(x-1)", "x加1除以x减1")]
        },
        {
            "name": "sqrt_latex",
            "priority": 8,
            "description": "算术平方根的读法（LaTeX）：\\sqrt{x} → x的算术平方根",
            "patterns": [
                (r'\\sqrt\{([^}]+)\}', r'\1的算术平方根'),
            ],
            "examples": [("\\sqrt{x}", "x的算术平方根"), ("\\sqrt{2}", "2的算术平方根")]
        },
        {
            "name": "implicit_multiply_parentheses",
            "priority": 9,
            "description": "括号前的省略乘号：a(b+1) → a乘以括号b加1括号",
            "patterns": [
                # a(b+1) → a乘以(b+1) → 后面处理括号
                (r'([a-zA-Z\d])\s*\(', r'\1乘以('),
                # )a → )乘以a
                (r'\)\s*([a-zA-Z\d])', r')乘以\1'),
            ],
            "examples": [("a(b+1)", "a乘以括号b加1括号"), ("2(x+1)", "2乘以括号x加1括号")]
        },
        {
            "name": "implicit_multiply_number_letter",
            "priority": 10,
            "description": "数字与字母间的省略乘号：2x → 2乘以x",
            "patterns": [
                (r'(\d+)\s*([a-zA-Z])', r'\1乘以\2'),
            ],
            "examples": [("2x", "2乘以x"), ("3a", "3乘以a"), ("5y", "5乘以y")]
        },
        {
            "name": "parentheses_full",
            "priority": 11,
            "description": "括号的完整朗读：() → 括号...括号",
            "patterns": [
                # 先将所有左括号统一化
                (r'\(', '（'),
                # 将所有右括号统一化
                (r'\)', '）'),
            ],
            "examples": [("x+1", "x加1"), ("(x+1)", "括号x加1括号")]
        },
        {
            "name": "arithmetic_operators",
            "priority": 13,
            "description": "算术运算符的读法",
            "patterns": [
                # 在LaTeX中：\+, -, \times, \div
                (r'\\\+', '加'),
                (r'\\times', '乘以'),
                (r'\\div', '除以'),
                (r'\\pm', '正负'),
            ],
            "examples": [("a+b", "a加b"), ("a×b", "a乘以b"), ("a÷b", "a除以b")]
        },
        {
            "name": "plus_minus_in_text",
            "priority": 14,
            "description": "文本中的加减号读法（避免与负号冲突）",
            "patterns": [
                # 已被处理的负数不再处理，这里只处理表达式中的加减号
                # a - b → a减b（在字母或数字之间）
                (r'([a-zA-Z\d）])\s*-\s*([a-zA-Z\d（])', r'\1减\2'),
                (r'([a-zA-Z\d）])\s*\+\s*([a-zA-Z\d（])', r'\1加\2'),
                (r'([a-zA-Z\d）])\s*=\s*([a-zA-Z\d（])', r'\1等于\2'),
            ],
            "examples": [("a - b", "a减b"), ("x + y", "x加y"), ("a = b", "a等于b")]
        },
        {
            "name": "degree_symbol",
            "priority": 14,
            "description": "度数符号：° → 度",
            "patterns": [
                (r'°', '度'),
            ],
            "examples": [("60°", "60度"), ("∠ABC = 90°", "角A B C等于90度")]
        },
        {
            "name": "angle_symbol",
            "priority": 15,
            "description": "角度符号：∠ABC → 角ABC（字母间加空格）",
            "patterns": [
                (r'∠([A-Z]+)', r'角\1'),
            ],
            "examples": [("∠ABC", "角A B C")]
        },
        {
            "name": "triangle_symbol",
            "priority": 16,
            "description": "三角形符号：△ABC → 三角形ABC（字母间加空格）",
            "patterns": [
                (r'△([A-Z]+)', r'三角形\1'),
            ],
            "examples": [("△ABC", "三角形A B C")]
        },
        # ========== 初中数学特有规则 ==========
        {
            "name": "ratio_symbol",
            "priority": 17,
            "description": "比例符号：a:b → a比b",
            "patterns": [
                (r'([a-zA-Z0-9]+)\s*:\s*([a-zA-Z0-9]+)', r'\1比\2'),
            ],
            "examples": [("a:b", "a比b"), ("2:3", "2比3"), ("x:y", "x比y")]
        },
        {
            "name": "coordinate_reading",
            "priority": 18,
            "description": "坐标读法：(2, 3) → 坐标2 3（括号已处理，只需添加坐标前缀）",
            "patterns": [
                # 匹配括号内用逗号分隔的数字/字母
                (r'（\s*(\d+)\s*，\s*(\d+)\s*）', r'坐标\1 \2'),
                (r'（\s*([a-zA-Z])\s*，\s*([a-zA-Z])\s*）', r'坐标\1 \2'),
                (r'（\s*(\d+)\s*，\s*([a-zA-Z])\s*）', r'坐标\1 \2'),
                (r'（\s*([a-zA-Z])\s*，\s*(\d+)\s*）', r'坐标\1 \2'),
            ],
            "examples": [("（2，3）", "坐标2 3"), ("（x，y）", "坐标x y")]
        },
        {
            "name": "set_symbols",
            "priority": 19,
            "description": "集合符号：∪→并集，∩→交集，∈→属于，⊆→包含于",
            "patterns": [
                (r'∪', '并集'),
                (r'∩', '交集'),
                (r'∈', '属于'),
                (r'⊆', '包含于'),
                (r'⊂', '真包含于'),
                (r'∉', '不属于'),
            ],
            "examples": [("A∪B", "A并集B"), ("A∩B", "A交集B"), ("x∈A", "x属于A")]
        },
        {
            "name": "function_notation",
            "priority": 20,
            "description": "函数符号：f(x) → f x（简化读法）",
            "patterns": [
                # 匹配函数名(参数)模式，如 f(x), g(x) 等
                (r'([a-zA-Z]+)（([a-zA-Z0-9]+)）', r'\1 \2'),
                (r'([a-zA-Z]+)（\s*([a-zA-Z0-9]+)\s*）', r'\1 \2'),
            ],
            "examples": [("f（x）", "f x"), ("g（x）", "g x")]
        },
        {
            "name": "parallel_perpendicular",
            "priority": 21,
            "description": "平行与垂直符号：∥ → 平行于，⊥ → 垂直于",
            "patterns": [
                (r'∥', '平行于'),
                (r'⊥', '垂直于'),
            ],
            "examples": [("AB∥CD", "A B平行于C D"), ("AB⊥CD", "A B垂直于C D")]
        },
    ]

    # ========== 特殊数字朗读 ==========
    # 某些分数需要特殊处理
    SPECIAL_FRACTIONS = {
        "1分之2": "二分之一",
        "1分之3": "三分之一",
        "2分之1": "二分之一",
        "3分之1": "三分之一",
        "1分之4": "四分之一",
        "3分之4": "四分之三",
        "1分之5": "五分之一",
        "4分之5": "五分之四",
    }

    @classmethod
    def process(cls, text: str, enable_brackets: bool = True) -> Tuple[str, List[str]]:
        """
        处理数学符号朗读

        Args:
            text: 包含数学符号或LaTeX公式的文本
            enable_brackets: 是否完整朗读括号（默认True）
                           True: "x加1括号" → False: "左括号x加1右括号"

        Returns:
            (处理后的文本, 应用的规则名称列表)

        Examples:
            >>> MathSymbolReader.process("-3 + 2x")
            ("负三加2乘以x", ["negative_number", "implicit_multiply_number_letter"])

            >>> MathSymbolReader.process("$x^2 - 3x + 2 = 0$")
            ("x的平方减3乘以x加2等于0", ["power_2", "implicit_multiply", "arithmetic_operators"])
        """
        if not text:
            return "", []

        processed = text
        rules_applied = []

        # 按优先级应用规则
        for rule in sorted(cls.READING_RULES, key=lambda x: x["priority"]):
            # 括号处理可选
            if rule["name"] == "parentheses_full" and not enable_brackets:
                continue

            rule_name = rule["name"]
            patterns = rule.get("patterns", [])

            for pattern, replacement in patterns:
                try:
                    # 检查是否匹配
                    if re.search(pattern, processed):
                        # 应用替换
                        new_processed = re.sub(pattern, replacement, processed)

                        # 如果有变化，记录规则
                        if new_processed != processed:
                            processed = new_processed
                            if rule_name not in rules_applied:
                                rules_applied.append(rule_name)
                                logger.debug(f"[MathSymbolReader] 应用规则: {rule_name}")

                except re.error as e:
                    logger.warning(f"[MathSymbolReader] 规则 {rule_name} 正则错误: {e}")

        # 后处理：特殊分数
        processed = cls._process_special_fractions(processed)

        # 后处理：字母间添加空格（用于连续大写字母）
        processed = cls._add_spaces_between_letters(processed)

        return processed, rules_applied

    @classmethod
    def _process_special_fractions(cls, text: str) -> str:
        """处理特殊分数朗读"""
        for old, new in cls.SPECIAL_FRACTIONS.items():
            text = text.replace(old, new)
        return text

    @classmethod
    def _add_spaces_between_letters(cls, text: str) -> str:
        """在连续的英文大写字母间添加空格（用于ABC → A B C）"""
        # 匹配连续的2-6个大写字母
        def add_spaces(match):
            letters = match.group(1)
            return ' '.join(letters)

        # 处理：角ABC → 角A B C
        text = re.sub(r'角([A-Z]{2,6})', lambda m: '角' + ' '.join(m.group(1)), text)
        # 处理：三角形ABC → 三角形A B C
        text = re.sub(r'三角形([A-Z]{2,6})', lambda m: '三角形' + ' '.join(m.group(1)), text)
        # 处理：圆ABC → 圆A B C
        text = re.sub(r'圆([A-Z]{2,6})', lambda m: '圆' + ' '.join(m.group(1)), text)
        # 处理：点AB → 点A B
        text = re.sub(r'点([A-Z]{2,6})', lambda m: '点' + ' '.join(m.group(1)), text)

        return text

    @classmethod
    def get_reading_example(cls, latex: str) -> str:
        """
        获取LaTeX公式的朗读示例

        Args:
            latex: LaTeX公式字符串

        Returns:
            朗读文本
        """
        processed, _ = cls.process(latex)
        return processed

    @classmethod
    def explain_rule(cls, rule_name: str) -> Optional[Dict]:
        """获取规则的详细说明"""
        for rule in cls.READING_RULES:
            if rule["name"] == rule_name:
                return rule
        return None

    @classmethod
    def list_all_rules(cls) -> List[Dict]:
        """列出所有朗读规则"""
        return [
            {
                "name": rule["name"],
                "description": rule["description"],
                "priority": rule["priority"],
                "examples": rule.get("examples", [])
            }
            for rule in cls.READING_RULES
        ]


# ==================== 便捷函数 ====================

def process_math_text(text: str, enable_brackets: bool = True) -> str:
    """
    处理数学文本的朗读

    Args:
        text: 包含数学符号的文本
        enable_brackets: 是否完整朗读括号

    Returns:
        处理后的文本

    Examples:
        >>> process_math_text("-3 + 2x")
        "负三加2乘以x"
    """
    processed, _ = MathSymbolReader.process(text, enable_brackets)
    return processed


def explain_math_reading(latex: str) -> Dict:
    """
    解释LaTeX公式的朗读方式

    Returns:
        {
            "original": "原始LaTeX",
            "reading": "朗读文本",
            "rules_used": ["应用的规则列表"]
        }
    """
    processed, rules = MathSymbolReader.process(latex)
    return {
        "original": latex,
        "reading": processed,
        "rules_used": rules
    }

