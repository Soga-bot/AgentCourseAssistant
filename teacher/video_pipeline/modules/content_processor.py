"""
内容处理模块

负责课程内容的智能重组、格式转换和质量检查
包括：
- 智能内容重组（将长段落转换为结构化列表）
- 内容完整性检查（检测和修复空内容）
- 关键词加粗
- LaTeX 格式转换
"""

import re
import logging
from typing import Dict, List, Any

logger = logging.getLogger(__name__)


class ContentProcessor:
    """内容处理器

    职责：
    1. 智能重组长段落为结构化列表
    2. 检测并修复空内容
    3. 自动加粗关键词
    4. LaTeX 格式转换
    """

    @staticmethod
    def ensure_content_completeness(title: str, content: str, scene: dict) -> str:
        """确保内容完整性，检测并修复空内容（轻量级兜底）

        注意：这是最后的兜底机制，主要依赖storyboard生成时保证内容质量
        """
        if not content:
            content = ""

        content_stripped = content.strip()

        # 根据场景类型确定最低字数要求
        # 注意：scene字典中使用 "stage" 作为键名，不是 "slideType"
        slide_type = scene.get("slideType", scene.get("stage", ""))

        # 如果slide_type为空，尝试从标题推断
        if not slide_type:
            slide_type = ContentProcessor._infer_slide_type_from_title(title)

        min_length_requirements = {
            "title": 0,
            "objectives": 50,
            "intro": 50,
            "concept": 100,
            "example": 80,
            "practice": 60,
            "summary": 40,
        }
        min_length = min_length_requirements.get(slide_type, 50)

        # 检查内容是否足够
        if content_stripped and len(content_stripped) >= min_length:
            return content

        # 内容不足，记录警告并返回最小填充
        logger.warning(f"[内容完整性] 内容不足警告: 标题='{title}', 类型='{slide_type}', "
                   f"实际={len(content_stripped)}, 要求>={min_length}")

        # 最小填充：仅添加警告信息，不生成复杂内容
        if not content_stripped:
            placeholder = f"[内容生成异常：{title}的内容为空，请检查storyboard生成过程]"
        else:
            placeholder = content_stripped
            while len(placeholder) < min_length:
                placeholder += f" [注：{title}内容长度不足，应由LLM重新生成]"

        return placeholder

    @staticmethod
    def _infer_slide_type_from_title(title: str) -> str:
        """从标题推断幻灯片类型

        当scene字典中没有stage字段时，根据标题关键词推断类型
        """
        title_lower = title.lower()

        # 定义关键词映射
        type_keywords = {
            "title": ["标题", "title", "课程", "chapter"],
            "objectives": ["学习目标", "目标", "objectives", "本节课"],
            "intro": ["导入", "情境", "引言", "introduction", "生活中的", "现象"],
            "concept": ["知识点", "详解", "讲解", "说明", "概念", "定义", "性质", "core", "原理", "分类", "关系"],
            "example": ["例题", "example", "示范", "典型", "精讲"],
            "practice": ["练习", "习题", "exercise", "巩固", "随堂", "测试"],
            "summary": ["小结", "总结", "summary", "回顾", "课堂总结", "课程总结", "归纳"]
        }

        # 按优先级检查（从具体到一般）
        for slide_type, keywords in type_keywords.items():
            if any(keyword in title or keyword.lower() in title_lower for keyword in keywords):
                return slide_type

        # 默认为概念讲解类型
        return "concept"


    @staticmethod
    def intelligently_restructure_content(content: str) -> str:
        """智能重组内容：将长段落拆分为结构化列表

        处理策略：
        1. 检测长段落（超过80字），尝试智能分段
        2. 识别关键句型（定义、分类、性质等）
        3. 转换为要点列表
        4. 保留关键词加粗标记
        """
        if not content:
            return content

        # 如果内容已经是列表格式，直接返回
        lines = content.split('\n')
        if any(line.strip().startswith(('- ', '• ', '1.', '2.', '3.', '4.', '5.', '一、', '二、', '三、'))
               for line in lines):
            return content

        # 长度检查：如果内容不超过80字，保持原样
        if len(content) <= 80:
            return content

        # 智能分段策略
        result_parts = []

        # 按句子分割（保留分隔符）
        sentences = re.split(r'(。[！？；]|\.\s+|\!\s+|\?\s+|;\s+)', content)

        # 重组句子（因为分割会丢失分隔符）
        full_sentences = []
        for i in range(0, len(sentences) - 1, 2):
            if i + 1 < len(sentences):
                full_sentences.append(sentences[i] + sentences[i + 1])
            else:
                full_sentences.append(sentences[i])

        # 分类句子
        definition_sentence = None  # 定义句
        category_sentences = []     # 分类句
        property_sentences = []     # 性质句
        example_sentences = []      # 例句
        other_sentences = []        # 其他

        for sentence in full_sentences:
            if not sentence.strip():
                continue

            # 识别定义句
            if any(keyword in sentence for keyword in ['是指', '定义为', '就是', '叫做', '叫做']):
                definition_sentence = sentence
            # 识别分类句（包含"分为"、"包括"、"有"等）
            elif any(keyword in sentence for keyword in ['分为', '包括', '有：', '有:', '两类', '三种']):
                category_sentences.append(sentence)
            # 识别性质句（包含"基本事实"、"性质"、"定理"等）
            elif any(keyword in sentence for keyword in ['基本事实', '性质', '定理', '公理', '特点是']):
                property_sentences.append(sentence)
            # 识别例句（包含"比如"、"例如"、"如"等）
            elif any(keyword in sentence for keyword in ['比如', '例如', '如：', '如:', '譬如']):
                example_sentences.append(sentence)
            else:
                other_sentences.append(sentence)

        # 构建结构化输出
        if definition_sentence:
            # 提取并加粗关键概念
            result_parts.append(ContentProcessor._bold_keywords(definition_sentence))

        if category_sentences:
            for sent in category_sentences:
                # 尝试提取分类项
                items = ContentProcessor._extract_list_items(sent)
                if items:
                    result_parts.extend([f"- {item}" for item in items])
                else:
                    result_parts.append(f"- {ContentProcessor._bold_keywords(sent)}")

        if property_sentences:
            for sent in property_sentences:
                result_parts.append(f"- {ContentProcessor._bold_keywords(sent)}")

        if example_sentences:
            for sent in example_sentences:
                result_parts.append(f"- {ContentProcessor._bold_keywords(sent)}")

        if other_sentences:
            for sent in other_sentences:
                result_parts.append(f"- {ContentProcessor._bold_keywords(sent)}")

        # 如果没有成功重组，返回原内容
        if len(result_parts) <= 1:
            return content

        return '\n'.join(result_parts)

    @staticmethod
    def _bold_keywords(text: str) -> str:
        """返回原文本（移除 LaTeX 加粗，避免转义问题）"""
        return text

    @staticmethod
    def _extract_list_items(sentence: str) -> list:
        """从句子中提取列表项

        例如："分为直线、射线、线段三类" -> ["直线", "射线", "线段"]
        """
        items = []

        # 匹配 "分为A、B、C" 或 "包括A、B、C" 等模式
        patterns = [
            r'分为(.+?)等',
            r'包括(.+?)等',
            r'分为(.+)$',
            r'包括(.+)$',
            r'有：?(.+?)[。！？]$',
        ]

        for pattern in patterns:
            match = re.search(pattern, sentence)
            if match:
                content = match.group(1)
                # 按顿号、逗号分隔
                items = [item.strip() for item in re.split(r'[、,，]', content)]
                break

        return [item for item in items if item and len(item) > 1]

    @staticmethod
    def convert_to_latex(content: str) -> str:
        """将内容转换为LaTeX格式

        处理包括：
        - 过滤 Markdown 标题 (# ## ###)
        - 转换列表为 LaTeX itemize
        - 转换数学符号
        - 修复：避免在列表中间关闭itemize环境导致嵌套错误
        - 修复：确保itemize环境总是成对出现
        """
        if not content:
            return ""

        lines = content.split('\n')
        latex_lines = []
        itemize_mode = False
        itemize_content = []

        def is_list_item(line: str) -> bool:
            """检查是否是列表项"""
            line = line.strip()
            return bool(line.startswith('- ') or line.startswith('• ') or re.match(r'^\d+[.、]', line))

        def has_more_list_items_ahead(current_index: int, all_lines: list) -> bool:
            """检查后面是否还有更多列表项"""
            for i in range(current_index + 1, len(all_lines)):
                if is_list_item(all_lines[i]):
                    return True
            return False

        try:
            for i, line in enumerate(lines):
                line = line.strip()
                if not line:
                    continue

                # 过滤 Markdown 标题 (# ## ### #### 等)
                if re.match(r'^#{1,6}\s+', line):
                    # 跳过 Markdown 标题行，不将其插入 LaTeX 文档
                    # 这些标题在 beamer 中会作为 frame title 显示
                    continue

                if is_list_item(line):
                    if not itemize_mode:
                        itemize_mode = True
                        itemize_content = []

                    if line.startswith('- '):
                        itemize_content.append(f"\\item {line[2:]}")
                    elif line.startswith('• '):
                        itemize_content.append(f"\\item {line[2:]}")
                    else:
                        # 移除数字前缀
                        clean_line = re.sub(r'^\d+[.、]\s*', '', line)
                        itemize_content.append(f"\\item {clean_line}")
                else:
                    # 非列表行
                    if itemize_mode:
                        # 检查后面是否还有更多列表项
                        has_more = has_more_list_items_ahead(i, lines)

                        if has_more and line:
                            # 后面还有列表项，将当前行也转为item（保持itemize连续）
                            itemize_content.append(f"\\item {ContentProcessor._convert_math_notation(line)}")
                        else:
                            # 后面没有更多列表项，关闭itemize
                            if itemize_content:  # 只有当有内容时才输出itemize
                                latex_lines.append("\\begin{itemize}")
                                latex_lines.extend(itemize_content)
                                latex_lines.append("\\end{itemize}")
                            # 无论是否有内容，都重置模式
                            itemize_mode = False
                            itemize_content = []

                            # 添加当前非列表行
                            converted_line = ContentProcessor._convert_math_notation(line)
                            latex_lines.append(converted_line)
                    else:
                        # 不在itemize模式中，直接添加
                        converted_line = ContentProcessor._convert_math_notation(line)
                        latex_lines.append(converted_line)

            # 处理最后仍在itemize模式的情况
            if itemize_mode:
                # 只有当itemize_content不为空时才输出itemize环境
                if itemize_content:
                    latex_lines.append("\\begin{itemize}")
                    latex_lines.extend(itemize_content)
                    latex_lines.append("\\end{itemize}")
                # 如果itemize_content为空，记录警告但不输出
                elif itemize_mode:
                    import logging
                    logger = logging.getLogger(__name__)
                    logger.warning("[convert_to_latex] itemize_mode为True但itemize_content为空，跳过输出itemize环境")

            return "\n".join(latex_lines)

        except Exception as e:
            # 发生异常时记录错误并返回空字符串
            import logging
            logger = logging.getLogger(__name__)
            logger.error(f"[convert_to_latex] 转换异常: {e}, content长度={len(content)}")
            return ""

    @staticmethod
    def _convert_math_notation(text: str) -> str:
        """转换内容为安全的 LaTeX 格式，转义特殊字符

        只转义最常见的问题字符：
        - _ 下划线（最常见，导致编译错误）
        - % 百分号（注释字符）
        - & 符号（表格/分隔符）
        # 不转义 {} 以支持 LaTeX 命令如 \textbf{}
        """
        # 只转义最必要的特殊字符
        char_map = {
            '_': r'\_',
            '%': r'\%',
            '&': r'\&',
            '$': r'\$',
        }

        for char, escaped in char_map.items():
            text = text.replace(char, escaped)

        return text

    @staticmethod
    def process_for_tts(text: str) -> str:
        """
        处理文本便于TTS朗读
        适配通用课程生成（不仅仅是数学几何）

        将符号转换为中文，确保TTS正确朗读
        """
        # 几何符号（数学课程用）
        geometric_replacements = {
            '∠': ' 角 ',
            '△': ' 三角形 ',
            '⊙': ' 圆 ',
            '⊥': ' 垂直于 ',
            '∥': ' 平行于 ',
            '≌': ' 全等于 ',
            '∽': ' 相似于 ',
        }

        # 比较符号（通用课程用）
        comparison_replacements = {
            '≤': ' 小于等于 ',
            '≥': ' 大于等于 ',
            '≠': ' 不等于 ',
            '≈': ' 约等于 ',
        }

        # 其他符号（通用课程用）
        other_replacements = {
            '±': ' 正负 ',
            '∞': ' 无穷大 ',
            '∫': ' 积分 ',
            '∑': ' 求和 ',
            '∏': ' 求积 ',
            '√': ' 根号 ',
            '²': ' 的平方 ',
            '³': ' 的立方 ',
        }

        # 合并所有替换规则
        all_replacements = {}
        all_replacements.update(geometric_replacements)
        all_replacements.update(comparison_replacements)
        all_replacements.update(other_replacements)

        # 应用替换
        for old, new in all_replacements.items():
            text = text.replace(old, new)

        return text
