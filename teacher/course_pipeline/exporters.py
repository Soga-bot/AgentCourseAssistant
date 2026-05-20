"""
导出器

支持多种格式的文档导出：
- Word文档
- PDF文档
- Markdown文档
- HTML文档
- LaTeX文档
"""

import asyncio
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Dict, Any, List
from datetime import datetime
import re


class BaseExporter(ABC):
    """导出器基类"""

    @abstractmethod
    async def export(self, content: Dict, output_path: str) -> str:
        """
        导出内容

        Args:
            content: 课程内容（字典格式）
            output_path: 输出文件路径

        Returns:
            输出文件路径
        """
        pass

    def _format_sections(self, sections: Dict[str, str]) -> str:
        """格式化章节内容"""
        lines = []
        for section_name, section_content in sections.items():
            lines.append(f"\n## {section_name}\n")
            lines.append(section_content)
        return "\n".join(lines)


class WordExporter(BaseExporter):
    """
    Word文档导出器

    使用python-docx库导出Word文档
    """

    def __init__(self):
        self._docx = None

    def _ensure_module(self):
        """确保python-docx可用"""
        if self._docx is None:
            try:
                from docx import Document
                self._docx = Document
            except ImportError:
                raise ImportError(
                    "需要安装 python-docx 库: pip install python-docx"
                )

    async def export(self, content: Dict, output_path: str) -> str:
        """导出为Word文档"""
        self._ensure_module()
        Document = self._docx

        doc = Document()

        # 添加标题
        title = content.get("title", "课程内容")
        doc.add_heading(title, 0)

        # 添加元数据
        meta = content.get("metadata", {})
        if meta:
            p = doc.add_paragraph()
            p.add_run(f"年级: {content.get('grade', '')}\n")
            p.add_run(f"章节: {content.get('chapter', '')}\n")
            p.add_run(f"学情: {content.get('student_level', '')}\n")
            p.add_run(f"用途: {content.get('purpose', '')}\n")
            if meta.get("generated_at"):
                p.add_run(f"生成时间: {meta['generated_at'][:10]}\n")

        # 添加章节内容
        sections = content.get("sections", {})
        diagrams = content.get("diagrams", {})

        for section_name, section_content in sections.items():
            doc.add_heading(section_name, 1)
            doc.add_paragraph(section_content)

            # 添加该章节的图示（如果有）
            section_diagrams = diagrams.get(section_name, [])
            for diagram in section_diagrams:
                diagram_path = diagram.get("path", "")
                if diagram_path and Path(diagram_path).exists():
                    try:
                        # 添加图片说明
                        doc.add_paragraph(f"图示：{diagram.get('type', '')}")
                        # 添加图片
                        doc.add_picture(diagram_path, width=None)
                    except Exception as e:
                        print(f"  [!] 无法添加图示 {diagram_path}: {e}")

        # 保存文件
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        doc.save(str(output_path))

        return str(output_path)


class PDFExporter(BaseExporter):
    """
    PDF文档导出器

    支持两种方式：
    1. 使用pandoc转换（推荐）
    2. 使用报告类生成PDF
    """

    def __init__(self, method: str = "pandoc"):
        self.method = method
        self._word_exporter = WordExporter()

    async def export(self, content: Dict, output_path: str) -> str:
        """导出为PDF文档"""
        output_path = Path(output_path)

        if self.method == "pandoc":
            # 先生成Word，再用pandoc转PDF
            temp_word = output_path.with_suffix(".docx")
            await self._word_exporter.export(content, str(temp_word))
            await self._convert_with_pandoc(temp_word, output_path)
            # 删除临时Word文件
            temp_word.unlink()
        else:
            # 使用其他方法
            raise ValueError(f"不支持的PDF生成方式: {self.method}")

        return str(output_path)

    async def _convert_with_pandoc(self, input_path: Path, output_path: Path):
        """使用pandoc转换"""
        import subprocess

        try:
            result = subprocess.run(
                ["pandoc", "-f", "docx", "-t", "pdf", "-o", str(output_path), str(input_path)],
                capture_output=True,
                text=True,
                timeout=60
            )
            if result.returncode != 0:
                raise Exception(f"pandoc转换失败: {result.stderr}")
        except FileNotFoundError:
            raise Exception(
                "未找到pandoc命令，请先安装: https://pandoc.org/installing.html"
            )


class MarkdownExporter(BaseExporter):
    """Markdown文档导出器"""

    async def export(self, content: Dict, output_path: str) -> str:
        """导出为Markdown文档"""
        lines = []

        # 添加标题
        title = content.get("title", "课程内容")
        lines.append(f"# {title}\n")

        # 添加元数据
        meta = content.get("metadata", {})
        if meta or content.get("grade"):
            lines.append("## 课程信息\n")
            if content.get("grade"):
                lines.append(f"- **年级**: {content.get('grade')}")
            if content.get("chapter"):
                lines.append(f"- **章节**: {content.get('chapter')}")
            if content.get("student_level"):
                lines.append(f"- **学情**: {content.get('student_level')}")
            if content.get("purpose"):
                lines.append(f"- **用途**: {content.get('purpose')}")
            if meta.get("generated_at"):
                lines.append(f"- **生成时间**: {meta['generated_at'][:10]}")
            lines.append("")

        # 添加章节内容
        sections = content.get("sections", {})
        diagrams = content.get("diagrams", {})

        for section_name, section_content in sections.items():
            lines.append(f"\n## {section_name}\n")
            lines.append(section_content)

            # 添加该章节的图示（如果有）
            section_diagrams = diagrams.get(section_name, [])
            for diagram in section_diagrams:
                diagram_path = diagram.get("path", "")
                if diagram_path:
                    # 将绝对路径转换为相对路径
                    try:
                        rel_path = str(Path(diagram_path).relative_to(Path(output_path).parent))
                    except ValueError:
                        rel_path = diagram_path
                    lines.append(f"\n**图示**: {diagram.get('type', '')}\n")
                    lines.append(f"![{diagram.get('type', '图示')}]({rel_path})\n")

        # 保存文件
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        content_str = "\n".join(lines)
        output_path.write_text(content_str, encoding="utf-8")

        return str(output_path)


class HTMLExporter(BaseExporter):
    """HTML文档导出器"""

    async def export(self, content: Dict, output_path: str) -> str:
        """导出为HTML文档"""
        # HTML模板
        html_template = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{title}</title>
    <style>
        body {{
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', 'PingFang SC', 'Microsoft YaHei', sans-serif;
            max-width: 800px;
            margin: 40px auto;
            padding: 20px;
            line-height: 1.8;
        }}
        h1 {{ color: #333; border-bottom: 2px solid #667eea; padding-bottom: 10px; }}
        h2 {{ color: #555; margin-top: 30px; }}
        .meta {{ background: #f5f5f5; padding: 15px; border-radius: 8px; margin: 20px 0; }}
        .meta p {{ margin: 5px 0; }}
        .section {{ margin: 30px 0; }}
    </style>
    <script src="https://polyfill.io/v3/polyfill.min.js?features=es6"></script>
    <script id="MathJax-script" async src="https://cdn.jsdelivr.net/npm/mathjax@3/es5/tex-mml-chtml.js"></script>
</head>
<body>
    <h1>{title}</h1>
    <div class="meta">{meta}</div>
    <div class="content">{sections}</div>
</body>
</html>"""

        # 构建元数据HTML
        meta_html = ""
        if content.get("grade"):
            meta_html += f"<p><strong>年级:</strong> {content['grade']}</p>"
        if content.get("chapter"):
            meta_html += f"<p><strong>章节:</strong> {content['chapter']}</p>"
        if content.get("student_level"):
            meta_html += f"<p><strong>学情:</strong> {content['student_level']}</p>"

        # 构建章节HTML
        sections_html = ""
        diagrams = content.get("diagrams", {})
        for section_name, section_content in content.get("sections", {}).items():
            sections_html += f'<div class="section">\n'
            sections_html += f'  <h2>{section_name}</h2>\n'
            # 转换换行为段落
            paragraphs = section_content.split('\n')
            for p in paragraphs:
                if p.strip():
                    sections_html += f'  <p>{p}</p>\n'
            # 添加该章节的图示（如果有）
            section_diagrams = diagrams.get(section_name, [])
            for diagram in section_diagrams:
                diagram_path = diagram.get("path", "")
                if diagram_path:
                    # 将绝对路径转换为相对路径
                    try:
                        rel_path = str(Path(diagram_path).relative_to(Path(output_path).parent))
                    except ValueError:
                        rel_path = diagram_path
                    sections_html += f'  <div style="text-align: center; margin: 20px 0;">\n'
                    sections_html += f'    <p style="color: #666;"><strong>{diagram.get("type", "图示")}</strong></p>\n'
                    sections_html += f'    <img src="{rel_path}" alt="{diagram.get("type", "图示")}" style="max-width: 100%; height: auto;">\n'
                    sections_html += f'  </div>\n'
            sections_html += f'</div>\n'

        # 填充模板
        html_content = html_template.format(
            title=content.get("title", "课程内容"),
            meta=meta_html,
            sections=sections_html
        )

        # 保存文件
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(html_content, encoding="utf-8")

        return str(output_path)


class LaTeXExporter(BaseExporter):
    """
    LaTeX文档导出器

    使用XeLaTeX编译，支持中文和数学公式
    生成专业的PDF排版效果
    """

    def __init__(self, compiler: str = "xelatex"):
        """
        初始化LaTeX导出器

        Args:
            compiler: LaTeX编译器 ('xelatex', 'pdflatex', 'lualatex')
        """
        self.compiler = compiler

    async def export(self, content: Dict, output_path: str) -> str:
        """
        导出为LaTeX文档

        Args:
            content: 课程内容（字典格式）
            output_path: 输出文件路径（.tex）

        Returns:
            输出文件路径
        """
        # 生成LaTeX代码
        latex_code = self._generate_latex(content)

        # 保存.tex文件
        tex_path = Path(output_path)
        tex_path.parent.mkdir(parents=True, exist_ok=True)
        tex_path.write_text(latex_code, encoding="utf-8")

        # 可选：自动编译为PDF
        pdf_path = tex_path.with_suffix(".pdf")
        if self._compile_latex(tex_path, pdf_path):
            return str(pdf_path)

        return str(tex_path)

    def _generate_latex(self, content: Dict) -> str:
        """生成LaTeX代码"""
        title = content.get("title", "课程内容")

        # 构建元数据部分
        meta_lines = []
        if content.get("grade"):
            meta_lines.append(f"\\textbf{{年级}}：{content['grade']} \\\\")
        if content.get("chapter"):
            meta_lines.append(f"\\textbf{{章节}}：{content.get('chapter', '')} \\\\")
        if content.get("student_level"):
            meta_lines.append(f"\\textbf{{学情}}：{content['student_level']} \\\\")
        if content.get("purpose"):
            meta_lines.append(f"\\textbf{{用途}}：{content['purpose']}")

        # 构建章节内容（包含图示）
        sections = content.get("sections", {})
        diagrams = content.get("diagrams", {})
        section_latex = self._format_sections_for_latex(sections, diagrams)

        # 完整的LaTeX文档模板 - 使用format()避免大括号转义问题
        latex_template = r"""\documentclass[12pt,a4paper]{article}

% ==================================================
% 宏包配置
% ==================================================
\usepackage{ctex}               % 中文支持
\usepackage{amsmath,amssymb}    % 数学公式
\usepackage{geometry}
\usepackage{hyperref}           % 超链接
\usepackage{xcolor}
\usepackage{enumitem}
\usepackage{graphicx}
\usepackage{booktabs}
\usepackage{fancyhdr}
\usepackage{lastpage}

% ==================================================
% 页面设置
% ==================================================
\geometry{left=2.5cm, right=2.5cm, top=2.5cm, bottom=2.5cm}

% ==================================================
% 字体配置（可选）
% ==================================================
\setCJKmainfont{SimSun}       % 宋体
\setCJKsansfont{SimHei}       % 黑体
\setCJKmonofont{FangSong}     % 仿宋

% ==================================================
% 样式定义
% ==================================================
\titleformat{\centering\LARGE\bfseries{#1}\par}
\sectionformat{\centering\Large\bfseries{第\thesection 节\ #2}\par}
\subsectionformat{\bfseries{#1}}

% 页眉页脚
\pagestyle{fancy}
\fancyhf[HF]{\footnotesize{""" + title + r"""}}
\fancyhf[HL]{\footnotesize{初中数学课程}}
\fancyhf[HR]{\footnotesize{\thepage}}
\fancyhf[FL]{\footnotesize{第\thepage\ 页}}
\fancyhf[HL]{\footnotesize{第\thepage\ 页}}

% ==================================================
% 文档信息
% ==================================================
\title{""" + title + r"""}
\author{智能课程生成系统}
\date{\today}

% ==================================================
% 文档开始
% ==================================================
\begin{document}

\maketitle

% ==================================================
% 课程信息
% ==================================================
\section*{课程信息}

\begin{tabular}{|l|l|}
\hline
""" + " | ".join(meta_lines) + r"""
\hline
\end{tabular}

\vspace{1cm}

% ==================================================
% 课程内容
% ==================================================
""" + section_latex + r"""

\end{document}
"""

        return latex_template

    def _format_sections_for_latex(self, sections: Dict[str, str], diagrams: Dict[str, list] = None) -> str:
        """格式化章节内容为LaTeX"""
        latex_sections = []

        for section_name, section_content in sections.items():
            # 转换章节标题
            section_name_latex = self._escape_latex(section_name)

            # 转换内容
            content_latex = self._convert_content_to_latex(section_content)

            latex_sections.append(f"\\section{{{section_name_latex}}}\n")
            latex_sections.append(content_latex)

            # 添加该章节的图示（如果有）
            if diagrams and section_name in diagrams:
                section_diagrams = diagrams[section_name]
                for i, diagram in enumerate(section_diagrams):
                    diagram_path = diagram.get("path", "")
                    if diagram_path and Path(diagram_path).exists():
                        # 添加图示说明
                        diagram_type = self._escape_latex(diagram.get("type", "图示"))
                        latex_sections.append(f"\n\\textbf{{{diagram_type}}}\n")
                        # 添加图片（使用figure环境）
                        latex_sections.append(f"\\begin{{figure}}[h]\n")
                        latex_sections.append(f"\\centering\n")
                        latex_sections.append(f"\\includegraphics[width=0.8\\textwidth]{{{diagram_path}}}\n")
                        latex_sections.append(f"\\end{{figure}}\n")

            latex_sections.append("\n")

        return "\n".join(latex_sections)

    def _convert_content_to_latex(self, content: str) -> str:
        """
        将内容转换为LaTeX格式

        处理：
        - 段落转换
        - 公式格式转换
        - 列表转换
        - 特殊字符转义
        """
        if not content:
            return ""

        lines = content.split('\n')
        latex_lines = []

        in_list = False
        list_level = 0
        list_type = None

        for i, line in enumerate(lines):
            line = line.rstrip()

            # 检测列表类型
            if re.match(r'^\s*[-•·]\s+', line):
                # 无序列表
                if not in_list:
                    in_list = True
                    list_level = 1
                    list_type = 'itemize'
                    latex_lines.append("\\begin{itemize}")
                # 提取列表项
                item_content = re.sub(r'^\s*[-•·]\s*', '', line)
                latex_lines.append("  \\item " + self._escape_latex(item_content))
                continue

            elif re.match(r'^\s*\d+[\.\)]\s+', line):
                # 有序列表
                if not in_list or list_type != 'enumerate':
                    if in_list and list_type == 'itemize':
                        latex_lines.append("\\end{itemize}")
                    in_list = True
                    list_type = 'enumerate'
                    latex_lines.append("\\begin{enumerate}")
                # 提取列表项
                item_content = re.sub(r'^\s*\d+[\.\)]\s*', '', line)
                latex_lines.append("  \\item " + self._escape_latex(item_content))
                continue

            elif in_list:
                # 列表结束
                if list_type == 'itemize':
                    latex_lines.append("\\end{itemize}")
                else:
                    latex_lines.append("\\end{enumerate}")
                in_list = False
                list_type = None

            # 处理标题
            elif line.startswith('###'):
                title = line.replace('###', '').strip()
                latex_lines.append("\\subsection{" + self._escape_latex(title) + "}")
            elif line.startswith('##'):
                title = line.replace('##', '').strip()
                latex_lines.append("\\section{" + self._escape_latex(title) + "}")
            elif line.startswith('#'):
                title = line.replace('#', '').strip()
                latex_lines.append("\\section{" + self._escape_latex(title) + "}")

            # 处理加粗
            elif line.startswith('**') and line.endswith('**'):
                title = line.replace('**', '').strip()
                latex_lines.append("\\textbf{" + self._escape_latex(title) + "}")

            # 处理数学公式（简单检测）
            elif '$' in line:
                # 转换为LaTeX公式格式
                processed_line = self._process_math_formulas(line)
                latex_lines.append(processed_line)

            # 处理普通段落
            elif line.strip():
                # 检测是否是强调（>开头的引用）
                if line.startswith('>'):
                    quote_content = line[1:].strip()
                    latex_lines.append("\\textcolor{gray}{\\small " + self._escape_latex(quote_content) + "}}")
                else:
                    # 普通段落
                    processed_line = self._escape_latex(line)
                    latex_lines.append(processed_line + r" \\")

    def _process_math_formulas(self, line: str) -> str:
        r"""
        处理行中的数学公式

        将 $...$ 格式转换为 \(...\) 或 \\[...\\]
        """
        # 行内公式 $...$
        line = re.sub(r'\$([^$]+)\$', r'\\(\1\\)', line)
        # 独立公式 $$...$$
        line = re.sub(r'\$\$([^$]+)\$\$', r'\\[\1\\]', line)
        return line

    def _escape_latex(self, text: str) -> str:
        """
        转义LaTeX特殊字符

        注意：不转义数学符号，因为它们需要在公式中使用
        """
        # 已经在数学环境中的内容不做处理
        latex_special_chars = {
            '\\': '\\textbackslash{}',
            '{': '\\{',
            '}': '\\}',
            '%': '\\%',
            '#': '\\#',
            '$': '\\$',
            '&': '\\&',
            '_': '\\_',
            '~': '\\textasciitilde{}',
            '^': '\\^{}',
        }

        # 但对于常见数学符号，不进行转义
        math_symbols = {'∑', '∫', '√', '∞', '±', '°', '≤', '≥', '≠', '≈', '∈', '∪'}

        result = []
        i = 0
        while i < len(text):
            # 检查是否在数学符号中
            if text[i] in math_symbols:
                result.append(text[i])
                i += 1
                continue

            # 检查是否需要转义
            found = False
            for char, escaped in latex_special_chars.items():
                if text[i] == char:
                    result.append(escaped)
                    found = True
                    break

            if not found:
                result.append(text[i])
            i += 1

        return "".join(result)

    def _compile_latex(self, tex_path: Path, pdf_path: Path) -> bool:
        """
        编译LaTeX为PDF

        Args:
            tex_path: .tex文件路径
            pdf_path: 输出PDF路径

        Returns:
            编译是否成功
        """
        import subprocess

        try:
            # 第一次编译
            subprocess.run(
                [self.compiler, "-interaction=nonstopmode",
                 "-output-directory=" + str(tex_path.parent),
                 str(tex_path)],
                capture_output=True,
                timeout=60,
                check=False
            )

            # 第二次编译（处理引用和目录）
            subprocess.run(
                [self.compiler, "-interaction=nonstopmode",
                 "-output-directory=" + str(tex_path.parent),
                 str(tex_path)],
                capture_output=True,
                timeout=60,
                check=False
            )

            # 检查PDF是否生成
            if pdf_path.exists() and pdf_path.stat().st_size > 1000:
                return True

            return False

        except FileNotFoundError:
            print(f"  [!] 未找到{self.compiler}，请安装TeX发行版")
            return False
        except subprocess.TimeoutExpired:
            print(f"  [!] LaTeX编译超时")
            return False
        except Exception as e:
            print(f"  [!] LaTeX编译失败: {e}")
            return False


class ExporterFactory:
    """
    导出器工厂

    根据文件扩展名自动选择合适的导出器
    """

    _exporters = {
        ".docx": WordExporter,
        ".pdf": PDFExporter,
        ".md": MarkdownExporter,
        ".html": HTMLExporter,
        ".tex": LaTeXExporter,
    }

    @classmethod
    def get_exporter(cls, output_path: str) -> BaseExporter:
        """
        根据输出文件路径获取对应的导出器

        Args:
            output_path: 输出文件路径

        Returns:
            导出器实例

        Raises:
            ValueError: 不支持的文件格式
        """
        output_path = Path(output_path)
        suffix = output_path.suffix.lower()

        exporter_class = cls._exporters.get(suffix)
        if not exporter_class:
            raise ValueError(
                f"不支持的输出格式: {suffix}，"
                f"支持的格式: {', '.join(cls._exporters.keys())}"
            )

        return exporter_class()

    @classmethod
    async def export(
        cls,
        content: Dict,
        output_path: str,
        exporter: BaseExporter = None
    ) -> str:
        """
        导出内容（便捷方法）

        Args:
            content: 课程内容
            output_path: 输出文件路径
            exporter: 自定义导出器（可选）

        Returns:
            输出文件路径
        """
        if exporter is None:
            exporter = cls.get_exporter(output_path)

        return await exporter.export(content, output_path)


# ==================== 便捷函数 ====================

async def export_to_word(content: Dict, output_path: str) -> str:
    """导出为Word文档"""
    return await WordExporter().export(content, output_path)


async def export_to_pdf(content: Dict, output_path: str) -> str:
    """导出为PDF文档"""
    return await PDFExporter().export(content, output_path)


async def export_to_markdown(content: Dict, output_path: str) -> str:
    """导出为Markdown文档"""
    return await MarkdownExporter().export(content, output_path)


async def export_to_html(content: Dict, output_path: str) -> str:
    """导出为HTML文档"""
    return await HTMLExporter().export(content, output_path)


async def export_to_latex(content: Dict, output_path: str) -> str:
    """导出为LaTeX文档"""
    return await LaTeXExporter().export(content, output_path)

