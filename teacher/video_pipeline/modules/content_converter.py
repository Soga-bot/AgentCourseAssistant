"""
内容转换器模块

职责：
1. LaTeX格式转换（内容→LaTeX代码）
2. 数学符号转换（Unicode→LaTeX）
3. TTS预处理（文本→TTS可读格式）
4. 文本增强（加粗、列表提取等）

设计原则：
- 纯函数，无状态
- 可独立测试
- 不依赖其他pipeline组件
"""

import re
import logging
from typing import List, Dict, Any

# 使用统一的日志配置
from ..logging_config import get_module_logger
logger = get_module_logger(__name__, "content_converter")


class ContentConverter:
    """
    内容转换器

    处理各种文本格式转换需求：
    - 普通文本 → LaTeX代码
    - Unicode数学符号 → LaTeX命令
    - 含数学符号文本 → TTS可读文本
    - 文本增强和格式化
    """

    def __init__(self):
        """初始化转换器"""
        logger.info("[ContentConverter] 初始化完成")

    # ==================== LaTeX转换 ====================

    def convert_to_latex(self, content: str) -> str:
        r"""
        将普通课程内容转换为LaTeX格式

        转换规则：
        1. **加粗** → \\textbf{加粗}
        2. 数字. → \item 数字.
        3. 空行 → \\vspace{0.3cm}
        4. 多个空格 → 单个空格
        5. 【方括号标记】 → \\textbf{标记}（修复LaTeX编译错误）
        """
        if not content:
            return ""

        # 【新增】优先处理方括号标记，避免LaTeX编译错误
        # 将 [xxx] 转换为 \textbf{xxx}
        # 只处理常见的标记：[题目]、[思路引导]、[完整步骤]、[易错提醒]、[方法总结]等
        bracket_patterns = [
            (r'\[题目\]', r'\\textbf{题目}'),
            (r'\[思路引导\]', r'\\textbf{思路引导}'),
            (r'\[完整步骤\]', r'\\textbf{完整步骤}'),
            (r'\[易错提醒\]', r'\\textbf{易错提醒}'),
            (r'\[方法总结\]', r'\\textbf{方法总结}'),
            (r'\[答案\]', r'\\textbf{答案}'),
            (r'\[解析\]', r'\\textbf{解析}'),
        ]
        for pattern, replacement in bracket_patterns:
            content = re.sub(pattern, replacement, content)

        # 1. 处理加粗标记 **text** → \\textbf{text}
        latex = re.sub(r'\*\*([^*]+)\*\*', r'\\textbf{\1}', content)

        # 2. 处理列表项 "数字." → \\item 数字.
        latex = re.sub(r'^(\d+)\.\s+', r'\\item \1. ', latex, flags=re.MULTILINE)

        # 3. 处理空行
        latex = re.sub(r'\n\s*\n', '\n\\vspace{0.3cm}\n', latex)

        # 4. 压缩多个空格
        latex = re.sub(r' +', ' ', latex)

        return latex

    # ==================== 数学符号转换 ====================

    def convert_math_notation(self, text: str) -> str:
        """
        转换数学符号为LaTeX格式

        处理内容：
        1. 上标：x² → x^{2}
        2. 下标：a₁ → a_{1}
        3. 分数：1/2 → \\frac{1}{2}
        4. 希腊字母：α → \\alpha
        5. 数学符号：≥ → \\geq
        """
        if not text:
            return ""

        # 上标转换
        text = re.sub(r'([a-zA-Z])²', r'\1^{2}', text)
        text = re.sub(r'([a-zA-Z])³', r'\1^{3}', text)

        # 下标转换（简单情况）
        text = re.sub(r'([a-zA-Z])₁', r'\1_{1}', text)
        text = re.sub(r'([a-zA-Z])₂', r'\1_{2}', text)
        text = re.sub(r'([a-zA-Z])₃', r'\1_{3}', text)

        # 希腊字母
        greek_letters = {
            'α': r'$\alpha$', 'β': r'$\beta$', 'γ': r'$\gamma$',
            'δ': r'$\delta$', 'ε': r'$\varepsilon$', 'θ': r'$\theta$',
            'π': r'$\pi$', 'σ': r'$\sigma$', 'φ': r'$\phi$',
            'ω': r'$\omega$', 'Δ': r'$\Delta$', 'Σ': r'$\Sigma$'
        }
        for greek, latex_code in greek_letters.items():
            text = text.replace(greek, latex_code)

        # 数学符号
        math_symbols = {
            '≥': r'$\geq$', '≤': r'$\leq$', '≠': r'$\neq$',
            '≈': r'$\approx$', '∞': r'$\infty$', '√': r'$\sqrt{}$',
            '°': '度', '′': '分', '″': '秒'
        }
        for symbol, replacement in math_symbols.items():
            text = text.replace(symbol, replacement)

        return text

    def normalize_latex_commands(self, text: str) -> str:
        r"""
        规范化LaTeX命令，将各种变体统一为标准格式

        处理内容：
        1. 非标准命令 → 标准命令：\neqq → \neq, \leqq → \leq
        2. 修复常见错误格式
        3. 统一分数表示

        Args:
            text: 包含LaTeX命令的文本

        Returns:
            规范化后的文本
        """
        if not text:
            return ""

        # 非标准LaTeX命令映射（直接字符串替换）
        # 注意：这里不用正则，直接用字符串替换，因为LaTeX命令是固定的
        replacements = [
            # 不等于符号的各种变体 → 标准格式
            (r'\neqq', r'\neq'),
            (r'\not=', r'\neq'),

            # 小于等于的各种变体 → 标准格式
            (r'\leqq', r'\leq'),

            # 大于等于的各种变体 → 标准格式
            (r'\geqq', r'\geq'),

            # 约等于的各种变体（保持\approx不变，只处理变体）
            (r'\simeq', r'\approx'),
        ]

        # 应用替换
        for variant, standard in replacements:
            text = text.replace(variant, standard)

        return text

    # ==================== TTS预处理 ====================

    def process_for_tts(self, text: str) -> str:
        """
        处理文本以适配TTS朗读

        处理规则：
        1. LaTeX命令 → 可读文本
        2. 数学符号 → 可读文本
        3. 连续字母 → 分隔（AB → A B）
        4. 标点符号规范化
        """
        if not text:
            return ""

        # 1. 移除LaTeX命令
        text = re.sub(r'\\[a-zA-Z]+', '', text)
        text = re.sub(r'[{}$&#^_~%]', '', text)

        # 2. 几何符号处理
        geometric_patterns = [
            (r'∠([A-Z]{2,6})', lambda m: '角' + ' '.join(m.group(1))),
            (r'△([A-Z]{2,6})', lambda m: '三角形' + ' '.join(m.group(1))),
            (r'⊙([A-Z]{1,6})', lambda m: '圆 ' + ' '.join(m.group(1))),
            (r'∥', ' 平行于 '), (r'⊥', ' 垂直于 '),
        ]
        for pattern, replacement in geometric_patterns:
            if callable(replacement):
                text = re.sub(pattern, replacement, text)
            else:
                text = re.sub(pattern, replacement, text)

        # 3. 上标下标处理
        text = re.sub(r'([a-zA-Z])²', r'\1的平方', text)
        text = re.sub(r'([a-zA-Z])³', r'\1的三次方', text)
        text = re.sub(r'([a-zA-Z])₁', r'\1一', text)
        text = re.sub(r'([a-zA-Z])₂', r'\1二', text)
        text = re.sub(r'([a-zA-Z])₃', r'\1三', text)

        # 4. 数学符号处理
        math_replacements = {
            '≥': ' 大于等于 ', '≤': ' 小于等于 ',
            '≠': ' 不等于 ', '≈': ' 约等于 ',
            '±': ' 正负 ', '∞': ' 无穷大 '
        }
        for symbol, readable in math_replacements.items():
            text = text.replace(symbol, readable)

        # 5. 连续大写字母分隔
        text = re.sub(r'\b([A-Z]{2,6})\b', lambda m: ' '.join(m.group(1)), text)

        # 6. 度数符号
        text = text.replace('°', '度')

        return text.strip()

    # ==================== 文本增强工具 ====================

    def bold_keywords(self, text: str) -> str:
        """
        加粗关键词
        识别并加粗常见关键词
        """
        if not text:
            return ""

        # 定义关键词列表
        keywords = [
            '定义', '定理', '公理', '推论', '性质',
            '注意', '重要', '关键', '例如', '比如',
            '总结', '结论', '因此', '所以'
        ]

        for keyword in keywords:
            text = re.sub(
                f'({keyword})',
                r'**\1**',
                text,
                flags=re.IGNORECASE
            )

        return text

    def extract_list_items(self, text: str) -> List[str]:
        """
        从文本中提取列表项

        支持格式：
        1. "1. xxx", "2. xxx"
        2. "- xxx"
        3. "• xxx"
        """
        if not text:
            return []

        items = []

        # 尝试多种列表格式
        # 格式1：数字. 开头
        items.extend(re.findall(r'^\d+\.\s*(.+)$', text, flags=re.MULTILINE))

        # 格式2：- 开头
        items.extend(re.findall(r'^-\s*(.+)$', text, flags=re.MULTILINE))

        # 格式3：• 开头
        items.extend(re.findall(r'^•\s*(.+)$', text, flags=re.MULTILINE))

        return [item.strip() for item in items if item.strip()]

    # ==================== 辅助方法 ====================

    def ensure_content_completeness(
        self,
        title: str,
        content: str,
        scene: Dict[str, Any]
    ) -> str:
        """
        确保内容完整性

        如果内容过短，使用scene中的其他字段补充
        """
        min_length = 50

        if len(content) >= min_length:
            return content

        # 尝试从其他字段获取内容
        additional_parts = []

        if 'narration' in scene and scene['narration']:
            additional_parts.append(scene['narration'])

        if 'examples' in scene and scene['examples']:
            additional_parts.append(scene['examples'])

        if 'notes' in scene and scene['notes']:
            additional_parts.append(scene['notes'])

        # 组合内容
        if additional_parts:
            content = content + '\n\n' + '\n\n'.join(additional_parts)

        # 如果仍然太短，生成默认内容
        if len(content) < min_length:
            content = self._generate_default_content_by_title(title, scene)

        return content

    def generate_default_content_by_title(
        self,
        title: str,
        scene: Dict[str, Any]
    ) -> str:
        """
        根据标题生成默认内容
        """
        frame_type = scene.get('frameType', '')
        scene_id = scene.get('sceneID', '')

        # 根据场景类型生成默认内容
        if '导入' in title or 'introduction' in title.lower():
            return f"本节课我们来学习{title}。"
        elif '目标' in title or 'objective' in title.lower():
            return f"本节课的学习目标是掌握{title}。"
        elif '定义' in title or 'definition' in title.lower():
            return f"首先，我们来了解{title}的定义。"
        elif '定理' in title or 'theorem' in title.lower():
            return f"接下来，我们学习{title}。"
        elif '例题' in title or 'example' in title.lower():
            return f"下面通过例题来理解{title}。"
        elif '练习' in title or 'exercise' in title.lower():
            return f"现在请同学们做练习：{title}。"
        elif '总结' in title or 'summary' in title.lower():
            return f"本节课我们学习了{title}。"
        else:
            return f"关于{title}，我们需要了解以下内容。"


# 便捷函数
def convert_content_to_latex(content: str) -> str:
    """便捷函数：内容转LaTeX"""
    converter = ContentConverter()
    return converter.convert_to_latex(content)


def process_text_for_tts(text: str) -> str:
    """便捷函数：文本TTS预处理"""
    converter = ContentConverter()
    return converter.process_for_tts(text)
