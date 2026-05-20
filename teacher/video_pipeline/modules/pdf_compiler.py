"""
PDF编译器模块

职责：
1. LaTeX编译（使用XeLaTeX）
2. 错误诊断和智能修复
3. 多次重试机制
4. 各种LaTeX错误的修复策略

设计原则：
- 独立的编译逻辑
- 完整的错误处理
- 可配置的修复策略
"""

import re
import logging
import subprocess
from pathlib import Path
from typing import Dict, Any, Optional
from dataclasses import dataclass

# 使用统一的日志配置
from ..logging_config import get_module_logger
logger = get_module_logger(__name__, "pdf_compiler")


@dataclass
class PDFCompileResult:
    """PDF编译结果"""
    success: bool
    pdf_path: Optional[Path] = None
    error: Optional[str] = None
    stderr: Optional[str] = None
    stdout: Optional[str] = None


@dataclass
class PDFCompilerConfig:
    """PDF编译器配置"""
    latex_compiler: str = "xelatex"  # 使用XeLaTeX编译器
    max_retries: int = 2  # XeLaTeX通常需要编译2次以生成正确的目录
    timeout: int = 120


class PDFCompiler:
    """
    PDF编译器

    功能：
    - 使用XeLaTeX编译LaTeX文件
    - 智能错误诊断
    - 多种错误修复策略
    - 自动重试机制
    """

    def __init__(self, config: Optional[PDFCompilerConfig] = None):
        """
        初始化编译器

        Args:
            config: PDF编译器配置，如果为None则使用默认配置
        """
        self.config = config or PDFCompilerConfig()
        logger.info(f"[PDFCompiler] 初始化完成 (编译器: {self.config.latex_compiler})")

    # ==================== 主编译方法 ====================

    async def compile_with_retry(
        self,
        tex_path: Path,
        temp_dir: Path,
        max_retries: Optional[int] = None
    ) -> PDFCompileResult:
        """
        带智能重试的LaTeX编译

        Args:
            tex_path: LaTeX文件路径
            temp_dir: 临时目录
            max_retries: 最大重试次数（如果为None则使用配置值）

        Returns:
            编译结果
        """
        # 读取原始LaTeX内容
        with open(tex_path, 'r', encoding='utf-8') as f:
            original_tex = f.read()

        current_tex = original_tex
        retries = max_retries or self.config.max_retries

        for attempt in range(retries):
            logger.info(f"[智能编译] 第{attempt + 1}次尝试编译...")

            # 尝试编译
            result = await self._compile_pdf(tex_path, temp_dir)

            if result.success:
                logger.info(f"[智能编译] ✓ 编译成功")
                return result

            # 编译失败，分析错误
            error_msg = result.error or ''
            stderr = result.stderr or ''
            stdout = result.stdout or ''

            logger.warning(f"[智能编译] 编译失败: {error_msg}")

            # 诊断错误类型
            error_type = self._diagnose_latex_error(stderr, stdout)
            logger.info(f"[智能编译] 错误类型: {error_type}")

            if attempt == retries - 1:
                # 最后一次尝试失败，不再重试
                break

            # 根据错误类型选择修复策略
            if error_type == 'bracket':
                logger.info(f"[智能编译] 尝试修复括号问题...")
                current_tex = self._fix_bracket_error(current_tex, stderr)

            elif error_type == 'missing_item':
                logger.info(f"[智能编译] 尝试修复item缺失问题...")
                current_tex = self._fix_missing_item_error(current_tex, stderr)

            elif error_type == 'math_mode':
                logger.info(f"[智能编译] 尝试修复数学模式...")
                current_tex = self._fix_math_mode_error(current_tex, stderr)

            elif error_type == 'missing_number':
                logger.info(f"[智能编译] 尝试修复数字缺失问题...")
                current_tex = self._fix_missing_number_error(current_tex, stderr)

            elif error_type == 'overfull':
                logger.info(f"[智能编译] 尝试修复内容溢出...")
                current_tex = self._fix_overfull_warning(current_tex, stdout)

            else:
                # 未知错误，尝试通用修复
                logger.info(f"[智能编译] 尝试通用修复...")
                current_tex = self._smart_latex_sanitize(current_tex)

            # 保存修复后的LaTeX内容
            with open(tex_path, 'w', encoding='utf-8') as f:
                f.write(current_tex)

        # 所有尝试都失败
        return PDFCompileResult(
            success=False,
            error=f'编译失败，已重试{retries}次',
            stderr=stderr,
            stdout=stdout
        )

    async def _compile_pdf(
        self,
        tex_path: Path,
        temp_dir: Path
    ) -> PDFCompileResult:
        """
        使用Tectonic编译PDF

        Args:
            tex_path: LaTeX文件路径
            temp_dir: 输出目录

        Returns:
            编译结果
        """
        try:
            logger.info(f"[PDF编译] 开始编译 {tex_path.name}")
            logger.debug(f"[PDF编译] 编译器: {self.config.latex_compiler}")
            logger.debug(f"[PDF编译] 输出目录: {temp_dir}")

            # 运行XeLaTeX
            # XeLaTeX参数说明：
            # -interaction=nonstopmode: 遇到错误不停止，继续编译
            # -halt-on-error: 遇到严重错误时停止
            # 注意：不使用-output-directory参数（Windows路径反斜杠会导致解析错误）
            # 使用cwd参数设置工作目录，输出文件会生成在工作目录中
            process_result = subprocess.run(
                [
                    self.config.latex_compiler,
                    "-interaction=nonstopmode",
                    str(tex_path.name)  # 只传递文件名，不使用完整路径
                ],
                capture_output=True,
                text=True,
                encoding='utf-8',
                errors='replace',
                timeout=self.config.timeout,
                cwd=temp_dir  # 设置工作目录为输出目录（解决路径反斜杠问题）
            )

            # 动态获取PDF文件名（基于tex文件名）
            pdf_name = tex_path.stem + ".pdf"
            pdf_path = temp_dir / pdf_name

            logger.debug(f"[PDF编译] 期望PDF文件: {pdf_path}")

            # 记录编译输出
            if process_result.returncode != 0:
                logger.error(f"[PDF编译] {self.config.latex_compiler}返回码: {process_result.returncode}")
                logger.error(f"[PDF编译] 错误输出:\n{process_result.stderr}")
                logger.error(f"[PDF编译] 标准输出:\n{process_result.stdout[-500:]}")
            else:
                logger.info(f"[PDF编译] {self.config.latex_compiler}编译成功，返回码: {process_result.returncode}")

            if pdf_path.exists():
                file_size = pdf_path.stat().st_size
                logger.info(f"[PDF编译] ✓ PDF生成成功: {pdf_path} ({file_size} bytes)")
                return PDFCompileResult(
                    success=True,
                    pdf_path=pdf_path,
                    stdout=process_result.stdout,
                    stderr=process_result.stderr
                )
            else:
                logger.error(f"[PDF编译] PDF文件未生成: {pdf_path}")
                return PDFCompileResult(
                    success=False,
                    error=f"PDF文件未生成",
                    stdout=process_result.stdout,
                    stderr=process_result.stderr
                )

        except subprocess.TimeoutExpired:
            logger.error(f"[PDF编译] 编译超时（>{self.config.timeout}秒）")
            return PDFCompileResult(
                success=False,
                error=f"编译超时"
            )
        except Exception as e:
            logger.error(f"[PDF编译] 编译异常: {e}")
            return PDFCompileResult(
                success=False,
                error=str(e)
            )

    # ==================== 错误诊断 ====================

    def _diagnose_latex_error(self, error_msg: str, stdout: str) -> str:
        """
        诊断LaTeX编译错误类型

        Args:
            error_msg: 错误信息
            stdout: 编译输出

        Returns:
            错误类型：'bracket', 'math_mode', 'overfull', 'missing_number',
                     'missing_item', 'undefined_cmd', 'unknown'
        """
        # 1. 检测item相关错误
        if 'missing \\item' in error_msg.lower() or 'Missing \item' in error_msg:
            return 'missing_item'

        # 2. 检测itemize环境错误
        if '\\begin{itemize}' in error_msg or '\\end{itemize}' in error_msg:
            if 'error' in error_msg.lower():
                return 'missing_item'

        # 3. 检测括号相关错误
        if any(keyword in error_msg for keyword in ['Extra }', 'Extra {',
                                                    'forgotten \\endgroup', 'Missing } inserted']):
            return 'bracket'

        # 4. 检测数学模式错误
        if 'Missing $' in error_msg or 'Display math should end with $$' in error_msg:
            return 'math_mode'

        # 5. 检测内容溢出警告
        if 'Overfull' in stdout or 'Underfull' in stdout:
            return 'overfull'

        # 6. 检测数字缺失错误
        if 'Missing number' in error_msg:
            return 'missing_number'

        # 7. 检测未定义命令
        if 'Undefined control sequence' in error_msg:
            return 'undefined_cmd'

        return 'unknown'

    # ==================== 错误修复方法 ====================

    def _fix_bracket_error(self, tex: str, error_msg: str) -> str:
        """修复括号相关错误"""
        # 提取错误行号
        line_match = re.search(r':(\d+):', error_msg)
        if line_match:
            error_line = int(line_match.group(1))
            lines = tex.split('\n')

            if 0 < error_line <= len(lines):
                problematic_line = lines[error_line - 1]

                # 统计括号数量
                open_braces = problematic_line.count('{')
                close_braces = problematic_line.count('}')

                if close_braces > open_braces:
                    # 多余的}，尝试转义最后一个
                    last_close = problematic_line.rfind('}')
                    lines[error_line - 1] = problematic_line[:last_close] + r'\}' + problematic_line[last_close+1:]
                    logger.info(f"[LaTeX修复] 转义第{error_line}行多余的}}")
                elif open_braces > close_braces:
                    # 缺少}，在行末补上
                    lines[error_line - 1] = problematic_line + '}'
                    logger.info(f"[LaTeX修复] 第{error_line}行补充缺少的}}")

                return '\n'.join(lines)

        # 如果无法定位具体行，使用全局修复
        return self._auto_fix_brackets(tex)

    def _fix_math_mode_error(self, tex: str, error_msg: str) -> str:
        """修复数学模式错误"""
        # 提取错误行号
        line_match = re.search(r':(\d+):', error_msg)
        if line_match:
            error_line = int(line_match.group(1))
            lines = tex.split('\n')

            if 0 < error_line <= len(lines):
                problematic_line = lines[error_line - 1]

                # 检测裸露的^或_
                # 将 字母^数字 转换为 $字母^数字$
                def wrap_exponent(match):
                    return f'${match.group(1)}^{{{match.group(2)}}}$'

                fixed_line = re.sub(r'([a-zA-Z])\^(\d+)', wrap_exponent, problematic_line)

                if fixed_line != problematic_line:
                    lines[error_line - 1] = fixed_line
                    logger.info(f"[LaTeX修复] 第{error_line}行数学模式包裹")
                    return '\n'.join(lines)

        # 全局修复：调用智能净化
        return self._smart_latex_sanitize(tex)

    def _fix_missing_number_error(self, tex: str, error_msg: str) -> str:
        """修复数字缺失错误"""
        # 提取错误行号
        line_match = re.search(r':(\d+):', error_msg)
        if line_match:
            error_line = int(line_match.group(1))
            lines = tex.split('\n')

            if 0 < error_line <= len(lines):
                problematic_line = lines[error_line - 1]
                logger.info(f"[LaTeX修复] 第{error_line}行可能存在数字缺失错误")
                logger.info(f"[LaTeX修复] 错误行内容: {problematic_line[:100]}")

                # 修复1：全角数字转半角
                fullwidth_to_halfwidth = {
                    '０': '0', '１': '1', '２': '2', '３': '3', '４': '4',
                    '５': '5', '６': '6', '７': '7', '８': '8', '９': '9'
                }
                fixed_line = problematic_line
                for full, half in fullwidth_to_halfwidth.items():
                    fixed_line = fixed_line.replace(full, half)

                # 修复2：修复缺失单位的长度（在纯数字后添加pt）
                def add_unit(match):
                    length_cmd = match.group(1)
                    number = match.group(2)
                    if number.strip('-').isdigit():
                        return f'\\setlength{{{length_cmd}}}{{{number}pt}}'
                    return match.group(0)

                fixed_line = re.sub(
                    r'\\setlength\{([^}]+)\}\{(\d+)\}',
                    add_unit,
                    fixed_line
                )

                # 修复3：修复 \setcounter 类似的命令
                def add_counter_unit(match):
                    counter_name = match.group(1)
                    number = match.group(2)
                    for full, half in fullwidth_to_halfwidth.items():
                        number = number.replace(full, half)
                    return f'\\setcounter{{{counter_name}}}{{{number}}}'

                fixed_line = re.sub(
                    r'\\setcounter\{([^}]+)\}\{([^\}]+)\}',
                    add_counter_unit,
                    fixed_line
                )

                # 修复4：修复全角数字在任何数学表达式或命令中
                def fix_fullwidth_in_cmd(match):
                    cmd_name = match.group(1)
                    args = match.group(2)
                    for full, half in fullwidth_to_halfwidth.items():
                        args = args.replace(full, half)
                    return f'\\{cmd_name}{{{args}}}'

                fixed_line = re.sub(
                    r'\\([a-zA-Z]+)\{([^}]*)\}',
                    fix_fullwidth_in_cmd,
                    fixed_line
                )

                if fixed_line != problematic_line:
                    lines[error_line - 1] = fixed_line
                    logger.info(f"[LaTeX修复] 第{error_line}行已修复数字问题")
                    return '\n'.join(lines)

        # 如果无法定位具体行，进行全局修复
        logger.info(f"[LaTeX修复] 执行全局全角数字修复")
        result = tex

        # 全局替换全角数字
        fullwidth_to_halfwidth = {
            '０': '0', '１': '1', '２': '2', '３': '3', '４': '4',
            '５': '5', '６': '6', '７': '7', '８': '8', '９': '9'
        }
        for full, half in fullwidth_to_halfwidth.items():
            result = result.replace(full, half)

        # 全局修复缺失单位的长度
        result = re.sub(
            r'\\setlength\{([^}]+)\}\{(\d+)\}',
            r'\\setlength{\1}{\2pt}',
            result
        )

        if result != tex:
            logger.info(f"[LaTeX修复] 全局修复完成")
        return result

    def _fix_missing_item_error(self, tex: str, error_msg: str) -> str:
        """修复itemize/enumerate环境中的\item缺失错误"""
        # 提取错误行号
        line_match = re.search(r':(\d+):', error_msg)
        error_line = int(line_match.group(1)) if line_match else 0

        lines = tex.split('\n')
        logger.info(f"[LaTeX修复] 第{error_line}行可能存在item错误")

        # 修复1：处理转义的\item (\\item -> \item)
        result_lines = []
        for i, line in enumerate(lines):
            if r'\item' in line and r'\\item' in line:
                fixed_line = line.replace(r'\item', r'\item')
                if fixed_line != line:
                    logger.info(f"[LaTeX修复] 第{i+1}行: 修复转义的\\item")
                    result_lines.append(fixed_line)
                else:
                    result_lines.append(line)
            else:
                result_lines.append(line)

        tex = '\n'.join(result_lines)

        # 修复2：移除空的itemize环境
        tex = re.sub(
            r'\\begin\{itemize\}\s*\\end\{itemize\}',
            '',
            tex
        )

        # 修复3：为没有\item的内容添加\item
        def add_items_to_itemize(match):
            begin_part = match.group(1)
            content = match.group(2)
            end_part = match.group(3)

            if r'\item' in content:
                return match.group(0)

            lines_in_env = [line.strip() for line in content.split('\n') if line.strip()]

            if not lines_in_env:
                return ''

            items = '\n'.join([f'\\item {line}' for line in lines_in_env])
            return f'{begin_part}\n{items}\n{end_part}'

        tex = re.sub(
            r'(\\begin\{itemize\})([\s\S]*?)(\\end\{itemize\})',
            add_items_to_itemize,
            tex
        )

        # 同样处理 enumerate 环境
        tex = re.sub(
            r'(\\begin\{enumerate\})([\s\S]*?)(\\end\{enumerate\})',
            add_items_to_itemize,
            tex
        )

        # 修复4：检测并修复双重转义 \\item -> \item
        tex = tex.replace(r'\\item', r'\item')

        logger.info(f"[LaTeX修复] item错误修复完成")
        return tex

    def _fix_overfull_warning(self, tex: str, stdout: str) -> str:
        """修复内容溢出问题"""
        # 检测溢出的行
        overfull_matches = re.finditer(r'Overfull.*?line (\d+)', stdout)

        fixed_lines = set()
        lines = tex.split('\n')

        for match in overfull_matches:
            error_line = int(match.group(1))
            if error_line in fixed_lines or error_line > len(lines):
                continue

            # 策略1：在溢出行之前查找最近的安全位置插入分页符
            if error_line > 1:
                for i in range(error_line - 1, max(0, error_line - 8), -1):
                    line = lines[i].strip()
                    # 在frame标题或小节标题前分页
                    if '\\section' in line or '\\frametitle' in line or ('\\textbf{' in line and '}' in line):
                        # 避免重复插入
                        if i > 0 and lines[i-1].strip() != '\\newpage':
                            lines.insert(i, '\\newpage')
                            logger.info(f"[LaTeX修复] 在第{i+1}行前插入分页符（解决第{error_line}行溢出）")
                        fixed_lines.add(error_line)
                        break

                # 策略2：如果没找到合适位置，在item之间分页
                if error_line not in fixed_lines:
                    for i in range(error_line - 1, max(0, error_line - 5), -1):
                        line = lines[i].strip()
                        if r'\item' in line:
                            lines.insert(i, '\\newpage')
                            logger.info(f"[LaTeX修复] 在item前插入分页符（解决第{error_line}行溢出）")
                            fixed_lines.add(error_line)
                            break

        return '\n'.join(lines)

    # ==================== 通用修复方法 ====================

    def _auto_fix_brackets(self, text: str) -> str:
        """
        自动修复括号不匹配问题

        策略：
        1. 统计{}括号数量
        2. 在末尾补充缺少的}括号
        """
        open_count = text.count('{')
        close_count = text.count('}')

        if open_count > close_count:
            # 缺少右括号，在末尾补充
            missing = open_count - close_count
            text = text + ('}' * missing)
            logger.info(f"[LaTeX修复] 补充{missing}个右括号")

        elif close_count > open_count:
            # 多余的右括号，尝试转义
            # 从后往前找多余的}并转义
            result = []
            to_escape = close_count - open_count
            escaped = 0

            for char in reversed(text):
                if char == '}' and escaped < to_escape:
                    result.append(r'\}')
                    escaped += 1
                else:
                    result.append(char)

            text = ''.join(reversed(result))
            logger.info(f"[LaTeX修复] 转义{escaped}个右括号")

        return text

    def _smart_latex_sanitize(self, text: str) -> str:
        """
        智能LaTeX内容净化

        处理常见的LaTeX问题：
        1. 数学符号转义
        2. 特殊字符转义
        3. 空白字符规范化
        """
        # 1. 处理数学符号
        math_symbols = {
            '≥': r'$\geq$', '≤': r'$\leq$', '≠': r'$\neq$',
            '≈': r'$\approx$', '∞': r'$\infty$', '√': r'$\sqrt{}$',
        }

        for symbol, replacement in math_symbols.items():
            text = text.replace(symbol, replacement)

        # 2. 处理上标下标
        text = re.sub(r'([a-zA-Z])²', r'\1$^{2}$', text)
        text = re.sub(r'([a-zA-Z])³', r'\1$^{3}$', text)

        # 3. 压缩多余空格
        text = re.sub(r'\n\s*\n\s*\n', '\n\n', text)

        return text


# 便捷函数
async def compile_latex(
    tex_path: Path,
    temp_dir: Path,
    latex_compiler: str = "xelatex",
    max_retries: int = 2
) -> PDFCompileResult:
    """
    便捷函数：编译LaTeX文件

    Args:
        tex_path: LaTeX文件路径
        temp_dir: 临时目录
        latex_compiler: LaTeX编译器路径（默认xelatex）
        max_retries: 最大重试次数

    Returns:
        编译结果
    """
    config = PDFCompilerConfig(latex_compiler=latex_compiler, max_retries=max_retries)
    compiler = PDFCompiler(config)
    return await compiler.compile_with_retry(tex_path, temp_dir)
