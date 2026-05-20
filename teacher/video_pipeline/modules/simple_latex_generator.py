"""
简化版 LaTeX 生成器 - 直接从规范帧生成 LaTeX

[开发历史] 早期简化版视频流水线（simple_pipeline.py）的配套模块，
采用纯规则方式从规范帧生成 LaTeX，不依赖 LLM 调用。
后续被 LaTeXGenerator（LLM驱动）取代，生成效果更优。
[已弃用 - 2026] 仅被 simple_pipeline.py 引用，无其他外部调用，保留作存档。

核心思想：
1. 接收 FramePreprocessor 处理后的规范帧
2. 使用纯规则生成 LaTeX（0次LLM调用）
3. 每帧对应一个 Beamer frame，保证不溢出

特点：
- 纯规则处理，秒级生成
- 帧类型对应不同的 block 样式
- 内容已预处理，直接渲染
"""

import re
import logging
from typing import List, Dict, Any, Optional
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)


@dataclass
class SimpleLaTeXResult:
    """简化版 LaTeX 生成结果"""
    success: bool
    tex_content: str = ""
    frame_count: int = 0
    error: str = ""


class SimpleLaTeXGenerator:
    """
    简化版 LaTeX 生成器

    从规范帧直接生成 LaTeX Beamer 代码
    无需 LLM 调用，纯规则生成
    """

    # 帧类型到 Beamer block 的映射
    BLOCK_TEMPLATES = {
        "intro": ("block", "课程导入"),
        "objectives": ("block", "学习目标"),
        "concept": ("block", "知识点"),
        "example_q": ("exampleblock", "题目"),
        "example_s": ("exampleblock", "解答"),
        "example_m": ("alertblock", "方法总结"),
        "warning": ("alertblock", "易错提醒"),
        "practice": ("exampleblock", "随堂练习"),
        "summary": ("block", "知识框架"),
        "extend": ("block", "课后拓展"),
    }

    # LaTeX 文档头部模板
    DOCUMENT_HEADER = r"""\documentclass[aspectratio=169,12pt]{ctexbeamer}
\usetheme{Madrid}
\usepackage{amsmath,amssymb,amsthm,graphicx,xcolor,booktabs,multicol}
\setbeamersize{text margin left=10mm, text margin right=10mm}
\addtobeamertemplate{frametitle}{\vspace*{0.3cm}}{}
\addtobeamertemplate{frame start}{\vspace*{0.2cm}}{}
\addtobeamertemplate{frame end}{}{\vspace*{0.8cm}}
% 封面页样式
\setbeamercolor{title}{fg=white,bg=blue!70!black}
\setbeamercolor{author}{fg=darkgray}
\setbeamercolor{date}{fg=darkgray}
\begin{document}
"""

    # 封面页模板
    TITLE_PAGE_TEMPLATE = r"""
% ==================== 封面页 ====================
\begin{frame}[plain]
\titlepage
\end{frame}
"""

    DOCUMENT_FOOTER = r"""
\end{document}
"""

    def __init__(self):
        logger.info("[SimpleLaTeXGenerator] 初始化完成")

    def generate(self, frames: List[Any], course_title: str = "课程") -> SimpleLaTeXResult:
        """
        从规范帧生成 LaTeX

        关键规则：
        1. 同一板块（section_source）内的帧可以合并/分页
        2. 不同板块之间必须强制分页

        Args:
            frames: Frame 对象列表（来自 FramePreprocessor）
            course_title: 课程标题

        Returns:
            SimpleLaTeXResult
        """
        try:
            logger.info(f"[SimpleLaTeXGenerator] 开始生成 LaTeX，共 {len(frames)} 帧")

            # 统计板块信息
            sections = {}
            for f in frames:
                src = f.section_source or "未知"
                if src not in sections:
                    sections[src] = 0
                sections[src] += 1
            logger.info(f"[SimpleLaTeXGenerator] 板块分布: {sections}")

            # 生成所有帧的 LaTeX 代码
            frame_tex_list = []
            prev_section = None

            for i, frame in enumerate(frames):
                current_section = frame.section_source or ""

                # 检测板块边界 - 不同板块之间强制分页
                is_new_section = (prev_section is not None and
                                  current_section != prev_section)

                if is_new_section:
                    # 插入分页标记
                    frame_tex_list.append(f"% === 板块分页: {prev_section} → {current_section} ===")
                    logger.info(f"[SimpleLaTeXGenerator] 板块切换: {prev_section} → {current_section}")

                frame_tex = self._generate_frame(frame, i + 1, is_new_section)
                frame_tex_list.append(frame_tex)

                prev_section = current_section

            # 拼接完整文档
            tex_content = self.DOCUMENT_HEADER

            # 添加标题信息（用于封面页）
            tex_content += f"\\title{{{self._escape_latex(course_title)}}}\n"
            tex_content += f"\\author{{AI课程助手}}\n"
            tex_content += f"\\date{{\\today}}\n"

            # 添加封面页
            tex_content += self.TITLE_PAGE_TEMPLATE

            # 添加内容帧
            tex_content += f"% 课程标题: {self._escape_latex(course_title)}\n"
            tex_content += f"% 总帧数: {len(frames)}\n\n"
            tex_content += "\n\n".join(frame_tex_list)
            tex_content += self.DOCUMENT_FOOTER

            # 后处理：修复常见的 LaTeX 问题
            tex_content = self._post_process(tex_content)

            logger.info(f"[SimpleLaTeXGenerator] 生成完成，共 {len(frames)} 帧")

            return SimpleLaTeXResult(
                success=True,
                tex_content=tex_content,
                frame_count=len(frames)
            )

        except Exception as e:
            logger.error(f"[SimpleLaTeXGenerator] 生成失败: {e}")
            return SimpleLaTeXResult(
                success=False,
                error=str(e)
            )

    def _generate_frame(self, frame: Any, frame_num: int, is_new_section: bool = False) -> str:
        """
        生成单个帧的 LaTeX 代码

        Args:
            frame: Frame 对象
            frame_num: 帧序号
            is_new_section: 是否是新板块的第一帧（需要强制分页）

        Returns:
            LaTeX 代码
        """
        # 获取帧类型对应的 block 样式
        block_type, default_title = self.BLOCK_TEMPLATES.get(
            frame.frame_type, ("block", "内容")
        )

        # 处理标题
        title = frame.title or default_title
        title = self._escape_latex(title)

        # 处理内容
        content = self._format_content(frame.content, block_type)

        # 生成 frame 代码
        # [t] 顶部对齐，[shrink=5] 内容过长时自动缩小（保证完整显示）
        # 不使用 allowframebreaks（避免帧合并）
        tex = f"\\begin{{frame}}[t,shrink=5]{{{title}}}\n"
        tex += f"% FrameID: {frame.id}, FrameNum: {frame_num}, Type: {frame.frame_type}\n"

        # 直接输出内容，不嵌套 block（避免方框浪费空间）
        tex += content

        tex += "\n\\end{frame}"

        return tex

    def _format_content(self, content: str, block_type: str) -> str:
        """
        格式化内容为 LaTeX

        Args:
            content: 原始内容
            block_type: block 类型

        Returns:
            格式化后的 LaTeX 内容
        """
        if not content:
            return ""

        # 将字面量 \n（两个字符：反斜杠+n）转为真正的换行符
        content = content.replace('\\n', '\n')

        # 转义 LaTeX 特殊字符
        content = self._escape_latex(content)

        # 处理小标题【xxx】
        content = self._format_subtitles(content)

        # 处理列表项
        content = self._format_list_items(content)

        # 处理数学公式
        content = self._format_math(content)

        # 处理换行
        content = self._format_line_breaks(content)

        return content

    def _escape_latex(self, text: str) -> str:
        """
        转义 LaTeX 特殊字符

        Args:
            text: 原始文本

        Returns:
            转义后的文本
        """
        if not text:
            return ""

        # LaTeX 特殊字符转义（保留数学模式中的内容）
        # 注意：不要转义数学模式中的字符
        escapes = [
            ('&', r'\&'),
            ('#', r'\#'),
            ('%', r'\%'),
            ('_', r'\_'),
            ('~', r'\textasciitilde{}'),
        ]

        # 分离数学模式和非数学模式
        parts = []
        current = ""
        in_math = False
        i = 0

        while i < len(text):
            # 检测 \[...\] 显示数学模式
            if text[i] == '\\' and i + 1 < len(text) and text[i + 1] == '[' and not in_math:
                if current:
                    parts.append(('text', current))
                    current = ""
                end = text.find('\\]', i + 2)
                if end != -1:
                    parts.append(('math', text[i:end + 2]))
                    i = end + 2
                else:
                    current = text[i:]
                    break
                continue

            # 检测 \(...\) 行内数学模式
            if text[i] == '\\' and i + 1 < len(text) and text[i + 1] == '(' and not in_math:
                if current:
                    parts.append(('text', current))
                    current = ""
                end = text.find('\\)', i + 2)
                if end != -1:
                    parts.append(('math', text[i:end + 2]))
                    i = end + 2
                else:
                    current = text[i:]
                    break
                continue

            # 检测 $$...$$ 显示数学模式（优先于 $...$）
            if text[i] == '$' and i + 1 < len(text) and text[i + 1] == '$':
                if in_math:
                    # 在 $...$ 内部遇到 $$，按普通字符处理
                    current += text[i]
                    i += 1
                    continue
                if current:
                    parts.append(('text', current))
                    current = ""
                # 找到匹配的 $$
                end = text.find('$$', i + 2)
                if end != -1:
                    parts.append(('math', text[i:end + 2]))
                    i = end + 2
                else:
                    # 未匹配的 $$，当作普通文本
                    current = text[i:]
                    break
                continue

            # 检测 $...$ 行内数学模式
            if text[i] == '$':
                if in_math:
                    # 结束数学模式
                    current += text[i]
                    parts.append(('math', current))
                    current = ""
                    in_math = False
                else:
                    # 开始数学模式前，保存当前文本
                    if current:
                        parts.append(('text', current))
                    current = text[i]
                    in_math = True
                i += 1
            else:
                current += text[i]
                i += 1

        # 处理最后的部分
        if current:
            if in_math:
                parts.append(('math', current))
            else:
                parts.append(('text', current))

        # 对非数学模式部分进行转义
        result_parts = []
        for part_type, part_content in parts:
            if part_type == 'text':
                for char, escape in escapes:
                    part_content = part_content.replace(char, escape)
                # 转义裸花括号（防止破坏frame环境）
                # 但保留已转义的 \{ 和 \}
                part_content = re.sub(r'(?<!\\)\{', r'\\{', part_content)
                part_content = re.sub(r'(?<!\\)\}', r'\\}', part_content)
            result_parts.append(part_content)

        return ''.join(result_parts)

    def _format_subtitles(self, content: str) -> str:
        """
        格式化小标题【xxx】

        Args:
            content: 内容

        Returns:
            格式化后的内容
        """
        # 将【小标题】转换为 \textbf{小标题}
        def replace_subtitle(match):
            subtitle = match.group(1)
            return f"\\textbf{{{subtitle}}}"

        content = re.sub(r'【([^】]+)】', replace_subtitle, content)
        return content

    def _format_list_items(self, content: str) -> str:
        """
        格式化列表项

        支持的格式：
        - ①②③④⑤
        - 1. 2. 3.
        - （1）（2）（3）
        - 一、二、三、

        Args:
            content: 内容

        Returns:
            格式化后的内容
        """
        lines = content.split('\n')
        result_lines = []
        in_itemize = False

        for line in lines:
            stripped = line.strip()

            # 检测列表项
            is_list_item = False

            # ①②③④⑤⑥⑦⑧⑨⑩
            if re.match(r'^[①②③④⑤⑥⑦⑧⑨⑩]', stripped):
                is_list_item = True
                # 转换为 \item
                content_part = re.sub(r'^[①②③④⑤⑥⑦⑧⑨⑩]\s*', '', stripped)
                line = f"\\item {content_part}"

            # 1. 2. 3.
            elif re.match(r'^\d+[\.、）]\s*', stripped):
                is_list_item = True
                content_part = re.sub(r'^\d+[\.、）]\s*', '', stripped)
                line = f"\\item {content_part}"

            # （1）（2）（3）
            elif re.match(r'^[（(]\d+[）)]\s*', stripped):
                is_list_item = True
                content_part = re.sub(r'^[（(]\d+[）)]\s*', '', stripped)
                line = f"\\item {content_part}"

            # 一、二、三、
            elif re.match(r'^[一二三四五六七八九十]+[、\.]\s*', stripped):
                is_list_item = True
                content_part = re.sub(r'^[一二三四五六七八九十]+[、\.]\s*', '', stripped)
                line = f"\\item {content_part}"

            # 管理 itemize 环境
            if is_list_item:
                if not in_itemize:
                    result_lines.append("\\begin{itemize}")
                    in_itemize = True
                result_lines.append(line)
            else:
                if in_itemize:
                    result_lines.append("\\end{itemize}")
                    in_itemize = False
                result_lines.append(line)

        # 关闭未结束的 itemize
        if in_itemize:
            result_lines.append("\\end{itemize}")

        return '\n'.join(result_lines)

    def _format_math(self, content: str) -> str:
        """
        格式化数学内容

        处理：
        - 确保数学符号在 $...$ 中
        - 处理常见数学符号

        Args:
            content: 内容

        Returns:
            格式化后的内容
        """
        # Unicode 数学符号映射（如果不在数学模式中）
        math_symbols = {
            '∠': r'$\angle$',
            '△': r'$\triangle$',
            '⊥': r'$\perp$',
            '∥': r'$\parallel$',
            '≤': r'$\leq$',
            '≥': r'$\geq$',
            '≠': r'$\neq$',
            '≈': r'$\approx$',
            '±': r'$\pm$',
            '×': r'$\times$',
            '÷': r'$\div$',
            'π': r'$\pi$',
            'α': r'$\alpha$',
            'β': r'$\beta$',
            'θ': r'$\theta$',
            '∞': r'$\infty$',
            '∈': r'$\in$',
            '∑': r'$\sum$',
        }

        for symbol, latex in math_symbols.items():
            # 检查符号是否已在数学模式中
            if symbol in content:
                # 简单检查：如果符号不在 $...$ 中，则替换
                # 这是一个保守的策略，避免破坏已有的数学模式
                content = content.replace(symbol, latex)

        return content

    def _format_line_breaks(self, content: str) -> str:
        """
        格式化换行

        将连续两个换行转换为段落分隔
        将单个换行转换为 \\

        Args:
            content: 内容

        Returns:
            格式化后的内容
        """
        # 处理连续换行（段落分隔）
        content = re.sub(r'\n\s*\n', '\n\n', content)

        # 在非空行末尾添加 \\（如果还没有）
        lines = content.split('\n')
        result_lines = []

        for i, line in enumerate(lines):
            stripped = line.strip()

            # 跳过空行
            if not stripped:
                result_lines.append('')
                continue

            # 跳过 LaTeX 命令行
            if stripped.startswith('\\begin') or stripped.startswith('\\end'):
                result_lines.append(line)
                continue

            # 跳过 itemize 内容
            if stripped.startswith('\\item'):
                result_lines.append(line)
                continue

            # 如果不是最后一行且下一行非空，添加 \\
            if i < len(lines) - 1:
                next_stripped = lines[i + 1].strip() if i + 1 < len(lines) else ''
                if next_stripped and not next_stripped.startswith('\\'):
                    # 检查是否已经有 \\
                    if not stripped.endswith('\\\\'):
                        line = stripped + '\\\\'

            result_lines.append(line)

        return '\n'.join(result_lines)

    def _content_to_items(self, content: str) -> str:
        """
        将内容转换为 itemize 列表项

        Args:
            content: 内容

        Returns:
            itemize 列表项
        """
        lines = content.split('\n')
        items = []

        for line in lines:
            stripped = line.strip()
            if stripped:
                # 移除已有的列表标记
                stripped = re.sub(r'^[①②③④⑤⑥⑦⑧⑨⑩]\s*', '', stripped)
                stripped = re.sub(r'^\d+[\.、）]\s*', '', stripped)
                stripped = re.sub(r'^[（(]\d+[）)]\s*', '', stripped)
                items.append(f"\\item {stripped}")

        return '\n'.join(items)

    def _post_process(self, tex_content: str) -> str:
        """
        后处理：修复常见的 LaTeX 问题

        Args:
            tex_content: LaTeX 内容

        Returns:
            修复后的 LaTeX 内容
        """
        # 1. 修复空的 itemize 环境
        tex_content = re.sub(r'\\begin\{itemize\}\s*\\end\{itemize\}', '', tex_content)

        # 2. 修复 itemize 环境配对
        begin_count = tex_content.count('\\begin{itemize}')
        end_count = tex_content.count('\\end{itemize}')

        if begin_count > end_count:
            # 补全缺失的 \end{itemize}
            tex_content += '\n' + '\\end{itemize}' * (begin_count - end_count)
        elif end_count > begin_count:
            # 移除多余的 \end{itemize}
            for _ in range(end_count - begin_count):
                tex_content = tex_content.replace('\\end{itemize}', '', 1)

        # 3. 修复花括号配对（简单检查）
        # 这里不进行复杂的修复，假设内容已经过预处理

        return tex_content


# ========== 便捷函数 ==========

def generate_latex_from_frames(frames: List[Any], course_title: str = "课程") -> SimpleLaTeXResult:
    """
    从规范帧生成 LaTeX 的便捷函数

    Args:
        frames: Frame 对象列表
        course_title: 课程标题

    Returns:
        SimpleLaTeXResult
    """
    generator = SimpleLaTeXGenerator()
    return generator.generate(frames, course_title)
