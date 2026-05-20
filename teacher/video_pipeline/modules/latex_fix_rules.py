# -*- coding: utf-8 -*-
"""
LaTeX 错误修复规则表（外置补丁文件）

此文件包含所有 LaTeX 编译错误的修复规则。
当发现新的错误模式时，只需在此文件中添加规则即可。

使用方法：
    from .latex_fix_rules import LATEX_FIX_RULES, EXTRA_PACKAGES_NEEDED, REQUIRED_PACKAGES

规则格式：
    '错误模式': ('修复内容', '说明', 是否需要宏包)
"""

from typing import Dict, Tuple

# ==================== LaTeX 错误修复规则表 ====================
# 可扩展的规则表，涵盖所有常见的 LaTeX 编译错误
# 格式: {错误模式: (修复内容, 说明, 是否需要宏包)}
LATEX_FIX_RULES: Dict[str, Tuple[str, str, bool]] = {
    # ==================== 数学符号替换 ====================
    # 非标准比较符号 -> 标准符号
    r'\\gt': ('>', r'比较符号 \gt -> >', False),
    r'\\lt': ('<', r'比较符号 \lt -> <', False),
    r'\\ne': (r'\\neq', r'不等号 \ne -> \neq', False),
    # 注释：\\le, \\ge, \\leq, \\geq 已移除，因为：
    # 1. 这些模式有正则表达式错误（\l, \g不是有效转义）
    # 2. Unicode符号 ≤ 和 ≥ 已有专门处理（见下方Unicode规则）
    r'\\neq': (r'\\neq', r'不等号 \neq（已是标准）', False),

    # 注释：\\times, \\div, \\pm, \\mp 已移除
    # 原因：作为正则表达式时存在无效转义序列（\t, \d, \p等）
    # 这些LaTeX命令已经是标准形式，无需替换

    # ==================== 全角字符替换 ====================
    '（': ('(', r'全角左括号 -> 半角', False),
    '）': (')', r'全角右括号 -> 半角', False),
    '「': ('(', r'全角左引号 -> 半角括号', False),
    '」': (')', r'全角右引号 -> 半角括号', False),
    '【': ('[', r'全角左方括号 -> 半角', False),
    '】': (']', r'全角右方括号 -> 半角', False),
    '，': (',', r'全角逗号 -> 半角（数学模式外）', False),
    '：': (':', r'全角冒号 -> 半角', False),
    '；': (';', r'全角分号 -> 半角', False),
    '！': ('!', r'全角感叹号 -> 半角', False),
    '？': ('?', r'全角问号 -> 半角', False),

    # ==================== Unicode 数学符号 ====================
    # 注意：replacement字符串需要双反斜杠，因为作为regex replacement时会被处理
    '∠': (r'$\\angle$', r'Unicode angle -> LaTeX', False),
    '△': (r'$\\triangle$', r'Unicode triangle -> LaTeX', False),
    '⊙': (r'$\\odot$', r'Unicode circle -> LaTeX', False),
    '∥': (r'$\\parallel$', r'Unicode parallel -> LaTeX', False),
    '⊥': (r'$\\perp$', r'Unicode perpendicular -> LaTeX', False),
    '°': (r'$^\\circ$', r'Unicode degree -> LaTeX', False),
    '≌': (r'$\\cong$', r'Unicode congruent -> LaTeX', False),
    '∽': (r'$\\sim$', r'Unicode similar -> LaTeX', False),
    '∈': (r'$\\in$', r'Unicode in -> LaTeX', False),
    '∪': (r'$\\cup$', r'Unicode union -> LaTeX', False),
    '∩': (r'$\\cap$', r'Unicode intersection -> LaTeX', False),
    '±': (r'$\\pm$', r'Unicode plusminus -> LaTeX', False),
    '√': (r'$\\sqrt{}$', r'Unicode sqrt -> LaTeX', False),
    '∑': (r'$\\sum$', r'Unicode sum -> LaTeX', False),
    '∏': (r'$\\prod$', r'Unicode product -> LaTeX', False),
    '∞': (r'$\\infty$', r'Unicode infinity -> LaTeX', False),
    '≠': (r'$\\neq$', r'Unicode not equal -> LaTeX', False),
    '≤': (r'$\\le$', r'Unicode leq -> LaTeX', False),
    '≥': (r'$\\ge$', r'Unicode geq -> LaTeX', False),
    '÷': (r'$\\div$', r'Unicode divide -> LaTeX', False),
    '×': (r'$\\times$', r'Unicode times -> LaTeX', False),

    # ==================== Unicode 上标字符（2025升级版）====================
    'ⁿ': (r'^n', r'Unicode上标ⁿ -> LaTeX', False),
    '¹': (r'^1', r'Unicode上标¹ -> LaTeX', False),
    '²': (r'^2', r'Unicode上标² -> LaTeX', False),
    '³': (r'^3', r'Unicode上标³ -> LaTeX', False),
    '⁴': (r'^4', r'Unicode上标⁴ -> LaTeX', False),
    '⁵': (r'^5', r'Unicode上标⁵ -> LaTeX', False),
    '⁶': (r'^6', r'Unicode上标⁶ -> LaTeX', False),
    '⁷': (r'^7', r'Unicode上标⁷ -> LaTeX', False),
    '⁸': (r'^8', r'Unicode上标⁸ -> LaTeX', False),
    '⁹': (r'^9', r'Unicode上标⁹ -> LaTeX', False),
    '⁰': (r'^0', r'Unicode上标⁰ -> LaTeX', False),
    '⁺': (r'^+', r'Unicode上标⁺ -> LaTeX', False),
    '⁻': (r'^-', r'Unicode上标⁻ -> LaTeX', False),

    # ==================== Unicode 下标字符 ====================
    '₀': (r'_0', r'Unicode下标₀ -> LaTeX', False),
    '₁': (r'_1', r'Unicode下标₁ -> LaTeX', False),
    '₂': (r'_2', r'Unicode下标₂ -> LaTeX', False),
    '₃': (r'_3', r'Unicode下标₃ -> LaTeX', False),
    '₄': (r'_4', r'Unicode下标₄ -> LaTeX', False),
    '₅': (r'_5', r'Unicode下标₅ -> LaTeX', False),
    '₆': (r'_6', r'Unicode下标₆ -> LaTeX', False),
    '₇': (r'_7', r'Unicode下标₇ -> LaTeX', False),
    '₈': (r'_8', r'Unicode下标₈ -> LaTeX', False),
    '₉': (r'_9', r'Unicode下标₉ -> LaTeX', False),

    # ==================== 圆圈数字（2025升级版） ====================
    '①': (r'(1)', r'圆圈数字① -> (1)', False),
    '②': (r'(2)', r'圆圈数字② -> (2)', False),
    '③': (r'(3)', r'圆圈数字③ -> (3)', False),
    '④': (r'(4)', r'圆圈数字④ -> (4)', False),
    '⑤': (r'(5)', r'圆圈数字⑤ -> (5)', False),
    '⑥': (r'(6)', r'圆圈数字⑥ -> (6)', False),
    '⑦': (r'(7)', r'圆圈数字⑦ -> (7)', False),
    '⑧': (r'(8)', r'圆圈数字⑧ -> (8)', False),
    '⑨': (r'(9)', r'圆圈数字⑨ -> (9)', False),
    '⑩': (r'(10)', r'圆圈数字⑩ -> (10)', False),

    # ==================== 过度转义修复（2025升级版）====================
    r'\\\\\\': (r'\\', r'三个反斜杠->两个（过度转义）', False),

    # ==================== 禁忌宏包（需要移除）====================
    r'\\usepackage\[utf8\]\{inputenc\}': ('', r'Tectonic不支持inputenc[utf8]', False),
    r'\\usepackage\{inputenc\}': ('', r'Tectonic不支持inputenc', False),
    r'\\usepackage\[T1\]\{fontenc\}': ('', r'Tectonic不支持fontenc', False),

    # ==================== 错误的文档类声明 ====================
    r'\\documentclass\[UTF8\]\{beamer\}\s*\\usepackage\{ctex\}': (
        r'\\documentclass[UTF8,aspectratio=169]{ctexbeamer}',
        r'beamer+ctex -> ctexbeamer',
        False
    ),

    # ==================== 重复命令 ====================
    r'\\item\s+\\item\s+': (r'\\item ', r'重复的 \item 命令', False),
    r'\n{3,}': ('\n\n', r'多余空行（保留2个）', False),

    # ==================== 输入栈优化（2025升级版）====================
    # 展平深层嵌套的itemize环境，减少输入栈使用
    r'\\begin{itemize}\s*\\item\s+([^\n]+?)\s*\\begin{itemize}\s*\\item\s+([^\n]+?)\s*\\end{itemize}\s*\\end{itemize}': (
        r'\\begin{itemize}\n  \\item \1\n  \\item \2\n\\end{itemize}',
        r'展平双层itemize嵌套（减少输入栈）',
        False
    ),

    # ==================== cases环境格式修复（2025升级版）====================
    # 修复cases环境中的错误换行符：在cases内部将 `\ ` 替换为 `\\`
    # 注意：在raw string中，\\表示两个反斜杠，在regex中匹配一个字面反斜杠
    r'(\\begin{cases}.*?) \\ ': (
        r'\1\\\\ ',
        r'cases内部换行: \  -> \\',
        False
    ),
}

# ==================== 需要额外宏包的命令 ====================
# 用于自动添加宏包
# 格式: {命令名: 宏包名}
EXTRA_PACKAGES_NEEDED: Dict[str, str] = {
    # mathrsfs 包（花体字母）
    'mathscr': 'mathrsfs',
    'mathcal': 'mathrsfs',  # \mathcal 在某些情况下需要 mathrsfs

    # esint 包（积分符号）
    # 'fint': 'esint',
    # 'iiint': 'esint',

    # physics 包（物理符号）
    # 'ket': 'physics',
    # 'bra': 'physics',
    # 'abs': 'physics',
    # 'norm': 'physics',

    # mathtools 包（扩展 amsmath）
    # 'DeclarePairedDelimiter': 'mathtools',
    # 'abs': 'mathtools',
    # 'norm': 'mathtools',
}

# ==================== 必需的宏包列表 ====================
# 格式: {宏包名: \usepackage声明}
REQUIRED_PACKAGES: Dict[str, str] = {
    'amsmath': r'\usepackage{amsmath}',
    'amssymb': r'\usepackage{amssymb}',
    'amsthm': r'\usepackage{amsthm}',
    'graphicx': r'\usepackage{graphicx}',
    'xcolor': r'\usepackage{xcolor}',
    'booktabs': r'\usepackage{booktabs}',
    'multicol': r'\usepackage{multicol}',
    # 注意: enumitem 和 paralist 与 beamer 类不兼容，已禁用
    # beamer 内置了列表环境管理，使用这些包会导致 "Undefined control sequence" 错误
    # 'enumitem': r'\usepackage{enumitem}' + '\n' + r'\setlistdepth{99}',
    # 'paralist': r'\usepackage{paralist}',
}

# 模块加载时输出版本信息
import logging
logger = logging.getLogger(__name__)
logger.info("[LaTeX修复规则] 加载2025升级版规则表")
logger.info("[LaTeX修复规则]   - 必需宏包: %d个", len(REQUIRED_PACKAGES))
logger.info("[LaTeX修复规则]   - 修复规则: %d条", len(LATEX_FIX_RULES))
# logger.info("[LaTeX修复规则]   - 新增: paralist紧凑列表宏包")  # 已禁用（与beamer不兼容）


# ==================== 辅助函数 ====================

def add_rule(pattern: str, replacement: str, description: str, needs_package: bool = False):
    r"""
    添加新的修复规则

    Args:
        pattern: 正则表达式模式
        replacement: 替换内容
        description: 规则说明
        needs_package: 是否需要额外宏包
    """
    LATEX_FIX_RULES[pattern] = (replacement, description, needs_package)


def add_package_dependency(command: str, package: str):
    r"""
    添加命令与宏包的依赖关系

    Args:
        command: LaTeX 命令名（不含反斜杠）
        package: 所需的宏包名
    """
    EXTRA_PACKAGES_NEEDED[command] = package


def add_required_package(package: str, declaration: str = None):
    r"""
    添加必需的宏包

    Args:
        package: 宏包名
        declaration: \usepackage 声明（可选，默认自动生成）
    """
    if declaration is None:
        declaration = r'\usepackage{' + package + '}'
    REQUIRED_PACKAGES[package] = declaration


def get_rules_summary() -> str:
    r"""获取规则摘要"""
    categories = {
        '数学符号': sum(1 for p, (_, d, _) in LATEX_FIX_RULES.items() if '符号' in d),
        '全角字符': sum(1 for p, (_, d, _) in LATEX_FIX_RULES.items() if '全角' in d),
        'Unicode': sum(1 for p, (_, d, _) in LATEX_FIX_RULES.items() if 'Unicode' in d),
        '宏包': sum(1 for p, (_, d, _) in LATEX_FIX_RULES.items() if '宏包' in d),
        '重复': sum(1 for p, (_, d, _) in LATEX_FIX_RULES.items() if '重复' in d),
        '其他': sum(1 for p, (_, d, _) in LATEX_FIX_RULES.items()
                   if not any(k in d for k in ['符号', '全角', 'Unicode', '宏包', '重复'])),
    }

    separator = '=' * 40
    return f"""
LaTeX 修复规则表摘要
{separator}
数学符号替换: {categories['数学符号']} 条
全角字符替换: {categories['全角字符']} 条
Unicode 符号: {categories['Unicode']} 条
禁忌宏包移除: {categories['宏包']} 条
重复命令修复: {categories['重复']} 条
其他修复: {categories['其他']} 条
{separator}
总计: {len(LATEX_FIX_RULES)} 条规则

额外宏包依赖: {len(EXTRA_PACKAGES_NEEDED)} 个
必需宏包: {len(REQUIRED_PACKAGES)} 个
"""


# ==================== 模块加载时自动验证 ====================
def _validate_all_regex_patterns():
    """在模块加载时验证所有正则表达式是否有效"""
    import re
    logger = None  # 延迟导入，避免循环依赖

    invalid_patterns = []
    for pattern, (replacement, description, needs_package) in LATEX_FIX_RULES.items():
        try:
            compiled = re.compile(pattern)
            # 替换字符串验证：只有包含 \1-\9 的反向引用时需要注意
            # 其他情况（如 \neq）都是有效的字面替换
        except re.error as e:
            invalid_patterns.append((pattern, str(e)))
        except Exception as e:
            invalid_patterns.append((pattern, f"未知错误: {e}"))

    if invalid_patterns:
        error_msg = "LaTeX修复规则表包含无效的正则表达式：\n"
        for pattern, error in invalid_patterns[:5]:
            error_msg += f"\n  模式: {repr(pattern)[:60]}\n  错误: {error}\n"

        if logger is None:
            print("[latex_fix_rules] " + error_msg)
        else:
            logger.error("[latex_fix_rules] " + error_msg.strip())

        raise ValueError(f"发现 {len(invalid_patterns)} 个无效的正则表达式")


# 模块导入时自动验证
_validate_all_regex_patterns()
