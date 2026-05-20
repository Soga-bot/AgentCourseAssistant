# -*- coding: utf-8 -*-
"""
分镜预处理模块（阶段2.5）

位置：分镜设计后、LaTeX生成前
职责：将分镜的原始内容预处理为LaTeX友好的结构化数据

目标：
1. 减轻LaTeX生成LLM的认知负荷（~50%）
2. 用规则引擎处理可预见的转换（比LLM更可靠）
3. 为LLM提供结构化的输入数据
"""

import re
import logging
from typing import Dict, List, Optional, Any
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


@dataclass
class PreprocessedScene:
    """预处理后的场景数据"""
    scene_id: str
    frame_title: str
    slide_type: str
    # 预处理后的内容
    content_blocks: List[Dict] = field(default_factory=list)  # 结构化的内容块
    # LaTeX环境建议
    suggested_environments: List[str] = field(default_factory=list)
    # 预标记
    needs_math_mode: bool = False
    has_complex_structure: bool = False
    estimated_height: float = 0.0  # 估算的内容行数
    # 原始数据（保留用于调试）
    original_content: str = ""
    original_narration: str = ""


@dataclass
class PreprocessResult:
    """预处理结果"""
    success: bool = False
    preprocessed_scenes: List[PreprocessedScene] = field(default_factory=list)
    batch_suggestion: int = 2  # 建议的batch大小
    total_height_estimate: float = 0.0  # 估算的总行数
    warnings: List[str] = field(default_factory=list)
    statistics: Dict[str, Any] = field(default_factory=dict)


class StoryboardPreprocessor:
    """
    分镜预处理器

    核心原则：
    1. 规则优先：所有确定性转换都用规则处理
    2. 结构化输出：为LLM提供清晰的内容结构
    3. 保守估算：宁可多分页也不要溢出
    """

    # ==================== 符号转换规则 ====================
    # Unicode → LaTeX 符号映射
    UNICODE_TO_LATEX: Dict[str, str] = {
        # 数学符号
        '∠': r'$\\angle$',
        '△': r'$\\triangle$',
        '⊙': r'$\\odot$',
        '∥': r'$\\parallel$',
        '⊥': r'$\\perp$',
        '°': r'$^\\circ$',
        '≌': r'$\\cong$',
        '∽': r'$\\sim$',
        '∈': r'$\\in$',
        '∪': r'$\\cup$',
        '∩': r'$\\cap$',
        '±': r'$\\pm$',
        '√': r'$\\sqrt{}$',
        '∑': r'$\\sum$',
        '∏': r'$\\prod$',
        '∞': r'$\\infty$',
        '≠': r'$\\neq$',
        '≤': r'$\\le$',
        '≥': r'$\\ge$',
        '÷': r'$\\div$',
        '×': r'$\\times$',

        # 上标字符
        'ⁿ': '^n', '¹': '^1', '²': '^2', '³': '^3', '⁴': '^4',
        '⁵': '^5', '⁶': '^6', '⁷': '^7', '⁸': '^8', '⁹': '^9',
        '⁰': '^0', '⁺': '^+', '⁻': '^-',

        # 下标字符
        '₀': '_0', '₁': '_1', '₂': '_2', '₃': '_3', '₄': '_4',
        '₅': '_5', '₆': '_6', '₇': '_7', '₈': '_8', '₉': '_9',

        # 圆圈数字
        '①': '(1)', '②': '(2)', '③': '(3)', '④': '(4)', '⑤': '(5)',
        '⑥': '(6)', '⑦': '(7)', '⑧': '(8)', '⑨': '(9)', '⑩': '(10)',
    }

    # 全角字符转换
    FULLWIDTH_TO_HALFWIDTH: Dict[str, str] = {
        '（': '(', '）': ')',
        '「': '(', '」': ')',
        '【': '[', '】': ']',
        '，': ',', '：': ':', '；': ';',
        '！': '!', '？': '?',
    }

    # ==================== 内容块类型映射 ====================
    # 根据slide_type和内容关键词推断LaTeX环境
    CONTENT_TYPE_MAPPING = {
        # 定义类 → block
        'definition': 'block',
        'theorem': 'block',

        # 例题类 → exampleblock
        'example': 'exampleblock',
        'practice': 'itemize',

        # 警告类 → alertblock
        'warning': 'alertblock',
        'alert': 'alertblock',

        # 总结类 → block
        'summary': 'block',
        'conclusion': 'block',
    }

    def __init__(self):
        """初始化预处理器"""
        self.stats = {
            'scenes_processed': 0,
            'symbols_converted': 0,
            'blocks_created': 0,
            'math_mode_suggestions': 0,
        }

    async def preprocess(
        self,
        storyboard: Dict[str, Any],
        target_batch_size: int = 2
    ) -> PreprocessResult:
        """
        预处理分镜数据

        Args:
            storyboard: 原始分镜数据
            target_batch_size: 目标批次大小

        Returns:
            PreprocessResult
        """
        logger.info("[预处理] ========== 开始预处理分镜数据 ==========")
        logger.info(f"[预处理] 目标批次大小: {target_batch_size}")

        result = PreprocessResult()
        scenes = storyboard.get('scenes', [])

        if not scenes:
            result.success = False
            result.warnings.append("分镜数据为空")
            return result

        logger.info(f"[预处理] 待处理场景数: {len(scenes)}")

        # 处理每个场景
        for scene_data in scenes:
            preprocessed = self._preprocess_scene(scene_data)
            result.preprocessed_scenes.append(preprocessed)
            result.total_height_estimate += preprocessed.estimated_height

        # 计算批次建议
        result.batch_suggestion = self._calculate_batch_size(
            len(scenes),
            result.total_height_estimate,
            target_batch_size
        )

        # 生成统计信息
        result.statistics = self.stats.copy()
        result.statistics['average_height'] = (
            result.total_height_estimate / len(scenes) if scenes else 0
        )

        result.success = True

        logger.info(f"[预处理] ========== 预处理完成 ==========")
        logger.info(f"[预处理] 处理场景: {len(result.preprocessed_scenes)}")
        logger.info(f"[预处理] 符号转换: {self.stats['symbols_converted']}次")
        logger.info(f"[预处理] 创建内容块: {self.stats['blocks_created']}个")
        logger.info(f"[预处理] 建议批次大小: {result.batch_suggestion}")
        logger.info(f"[预处理] 估算总行数: {result.total_height_estimate:.1f}")

        return result

    def _preprocess_scene(self, scene_data: Dict) -> PreprocessedScene:
        """预处理单个场景"""
        scene_id = scene_data.get('sceneID', '')
        slide_type = scene_data.get('slideType', 'concept')
        raw_title = scene_data.get('frameTitle', '')
        main_content = scene_data.get('mainContent', '')
        narration = scene_data.get('narration', '')

        # 步骤0: 清理和优化标题（移除分页标记和冗余词）
        clean_title = self._clean_frame_title(raw_title)

        processed = PreprocessedScene(
            scene_id=scene_id,
            frame_title=clean_title,
            slide_type=slide_type,
            original_content=main_content,
            original_narration=narration
        )

        # 步骤1: 符号预转换
        content_after_symbols = self._convert_symbols(main_content)

        # 步骤1.5: 清理分页标记（从内容中移除(1/2)(1/2)等）
        content_after_cleanup = self._clean_pagination_markers(content_after_symbols)

        # 步骤2: 结构化分析
        content_blocks = self._analyze_content_structure(
            content_after_cleanup,
            slide_type
        )
        processed.content_blocks = content_blocks

        # 步骤3: LaTeX环境建议
        processed.suggested_environments = self._suggest_environments(
            slide_type,
            content_blocks
        )

        # 步骤4: 高度估算
        processed.estimated_height = self._estimate_content_height(
            content_blocks,
            slide_type
        )

        # 步骤5: 检测数学模式需求
        processed.needs_math_mode = self._needs_math_mode(content_after_cleanup)

        # 步骤6: 检测复杂结构
        processed.has_complex_structure = self._has_complex_structure(content_blocks)

        # 更新统计
        self.stats['scenes_processed'] += 1
        self.stats['blocks_created'] += len(content_blocks)

        return processed

    def _convert_symbols(self, text: str) -> str:
        """转换Unicode符号为LaTeX"""
        result = text
        conversions = 0

        # Unicode符号转换
        for unicode_char, latex_replacement in self.UNICODE_TO_LATEX.items():
            if unicode_char in result:
                result = result.replace(unicode_char, latex_replacement)
                conversions += 1

        # 全角字符转换
        for fullwidth, halfwidth in self.FULLWIDTH_TO_HALFWIDTH.items():
            if fullwidth in result:
                result = result.replace(fullwidth, halfwidth)
                conversions += 1

        self.stats['symbols_converted'] += conversions
        return result

    def _analyze_content_structure(
        self,
        content: str,
        slide_type: str
    ) -> List[Dict]:
        """
        分析内容结构

        返回结构化的内容块列表：
        [
            {
                'type': 'definition' | 'property' | 'example' | 'alert' | 'summary' | 'list',
                'title': '标题',
                'content': '内容',
                'needs_bold': True/False
            }
        ]
        """
        blocks = []

        # 检测【】标记的结构化内容
        pattern = r'【(.+?)】([^【]*?(?=【|$))'
        matches = re.findall(pattern, content)

        if matches:
            for title, block_content in matches:
                block_type = self._infer_block_type(title, slide_type)
                blocks.append({
                    'type': block_type,
                    'title': title.strip(),
                    'content': block_content.strip(),
                    'needs_bold': True
                })
        else:
            # 没有明确结构，作为单个块处理
            blocks.append({
                'type': self._infer_block_type('', slide_type),
                'title': '',
                'content': content.strip(),
                'needs_bold': False
            })

        return blocks

    def _infer_block_type(self, title: str, slide_type: str) -> str:
        """推断内容块类型"""
        title_lower = title.lower()

        # 根据标题关键词推断
        if any(kw in title for kw in ['定义', '定理', '概念']):
            return 'definition'
        elif any(kw in title for kw in ['例', '典例', '练习']):
            return 'example'
        elif any(kw in title for kw in ['易错', '注意', '提醒', '警告']):
            return 'alert'
        elif any(kw in title for kw in ['总结', '小结', '结论']):
            return 'summary'
        elif any(kw in title for kw in ['性质', '公式', '方法']):
            return 'property'
        else:
            # 根据slide_type推断
            return self.CONTENT_TYPE_MAPPING.get(slide_type, 'content')

    def _suggest_environments(
        self,
        slide_type: str,
        content_blocks: List[Dict]
    ) -> List[str]:
        """建议LaTeX环境"""
        environments = []

        # 根据内容块类型建议环境
        for block in content_blocks:
            block_type = block['type']

            if block_type == 'definition':
                environments.append('block')
            elif block_type == 'example':
                environments.append('exampleblock')
            elif block_type == 'alert':
                environments.append('alertblock')
            elif block_type == 'summary':
                environments.append('block')
            elif block_type == 'property':
                # 性质列表可以用block+itemize
                environments.append('block')
            elif slide_type == 'practice':
                environments.append('itemize')

        # 如果没有明确的block建议，添加默认
        if not environments:
            if slide_type in ['intro', 'concept']:
                environments.append('itemize')
            else:
                environments.append('block')

        return environments

    # ==================== 每页可容纳内容标准（基于LaTeX实际渲染数据）====================
    # 每页最大容量：1行标题 + 15行内容 + 行间距
    MAX_TITLE_LINES = 1          # frame标题行数
    MAX_CONTENT_LINES = 15       # 内容最大行数
    MAX_WIDTH_CHARS = 27         # 最大宽度（字符数）

    def _estimate_content_height(
        self,
        content_blocks: List[Dict],
        slide_type: str
    ) -> float:
        """
        估算内容行数（基于LaTeX实际渲染数据）

        每页最大容量：
        - 高度：1行标题 + 15行内容 + 行间距
        - 宽度：27字符
        """
        total_lines = 0

        # frame标题（固定1行）
        total_lines += self.MAX_TITLE_LINES

        for block in content_blocks:
            content = block['content']
            title = block.get('title', '')

            # block标题（1行）
            if title:
                total_lines += 1

            # 内容行数（基于宽度27字符）
            char_count = len(content)
            estimated_lines = max(1, (char_count + self.MAX_WIDTH_CHARS - 1) // self.MAX_WIDTH_CHARS)
            total_lines += estimated_lines

        # 行间距（每个block额外增加0.5行间距）
        total_lines += len(content_blocks) * 0.5

        # 最大可用行数
        max_lines = self.MAX_TITLE_LINES + self.MAX_CONTENT_LINES

        # 如果超过最大行数，标记警告
        if total_lines > max_lines:
            logger.warning(
                f"[分页检测] {slide_type} 内容溢出: "
                f"估算 {total_lines:.1f} 行，可用 {max_lines} 行"
            )

        return total_lines

    def _needs_math_mode(self, content: str) -> bool:
        """检测是否需要数学模式"""
        math_indicators = [
            r'\$', r'\\frac', r'\\sqrt', r'\\sum', r'\\prod',
            r'^', '_', '≤', '≥', '≠', '√', '∑', '∏', '∞'
        ]
        return any(indicator in content for indicator in math_indicators)

    def _has_complex_structure(self, content_blocks: List[Dict]) -> bool:
        """检测是否有复杂结构"""
        return len(content_blocks) > 2 or any(
            block['type'] in ['definition', 'example', 'alert']
            for block in content_blocks
        )

    def _calculate_batch_size(
        self,
        total_scenes: int,
        total_height: float,
        target_size: int
    ) -> int:
        """
        计算建议的批次大小（基于LaTeX实际渲染数据）

        策略：
        - 默认使用target_size（建议为2）
        - 如果内容非常简单（行数少），可以增加到3
        - 如果内容很复杂，保持为2或降至1
        """
        max_lines = self.MAX_TITLE_LINES + self.MAX_CONTENT_LINES  # 16行
        avg_lines = total_height / total_scenes if total_scenes > 0 else 0

        if avg_lines < max_lines * 0.4:  # 少于40%（约6.4行）
            # 内容简单，可以适当增加
            return min(target_size + 1, 3)
        elif avg_lines > max_lines * 0.8:  # 超过80%（约12.8行）
            # 内容复杂，减少批次大小
            return max(target_size - 1, 1)
        else:
            return target_size

    def _clean_frame_title(self, title: str) -> str:
        """
        清理frame标题

        移除：
        1. 分页标记，如 ](1/2)、](1/2)(1/2)、]($\frac{1}{2}$) 等
        2. "题目"等冗余词
        3. 限制长度为20字符
        """
        if not title:
            return title

        clean_title = title

        # 移除分页标记：](xxx) 格式，包括LaTeX数学格式
        # 处理多种分页标记格式：
        # - ](1/2)           → 简单分数
        # - ]($\frac{1}{2}$) → LaTeX分数
        # - ](1/2)(1/2)      → 多个标记
        # - ]($\frac{1}{2}$)($\frac{1}{2}$) → LaTeX多个标记
        # - ]($\frac{1}{2}$)(1) → 混合格式

        # 策略：先移除LaTeX格式的分页标记 ]($...$)
        # 使用更宽松的正则，匹配 ]( 后跟任意内容直到 )
        while r'\](' in clean_title:
            # 找到 ]( 的位置
            start_idx = clean_title.find(r'\](')
            if start_idx == -1:
                break
            # 从 ]( 开始，逐个字符匹配，找到匹配的 )
            depth = 0
            end_idx = -1
            i = start_idx + 2  # 跳过 ](
            while i < len(clean_title):
                if clean_title[i] == '(':
                    depth += 1
                elif clean_title[i] == ')':
                    if depth == 0:
                        end_idx = i
                        break
                    depth -= 1
                i += 1
            if end_idx != -1:
                clean_title = clean_title[:start_idx] + clean_title[end_idx + 1:]
            else:
                break

        # 移除"题目"等冗余词（标题本身就有"例题1"，再加"题目"就重复了）
        clean_title = re.sub(r'题目[:：]', '', clean_title)

        # 限制长度（避免标题过长溢出）
        if len(clean_title) > 20:
            clean_title = clean_title[:20]

        return clean_title.strip()

    def _clean_pagination_markers(self, content: str) -> str:
        """
        清理内容中的分页标记

        移除如 (1/2)(1/2)、(1/2)(2/2)、](1/2)、($\frac{1}{2}$)($\frac{1}{2}$) 等分页标记
        这些标记是LLM之前尝试分页时留下的，但现在我们用规则分页，所以不需要它们
        """
        if not content:
            return content

        clean_content = content

        # 移除各种分页标记格式
        # 1. LaTeX数学格式：($\frac{1}{2}$)($\frac{1}{2}$) 等
        #    匹配 ($...$)($...$) 或类似格式
        clean_content = re.sub(r'\(\s*\$[^$]*\$\s*\)\s*\(\s*\$[^$]*\$\s*\)', '', clean_content)

        # 2. 简单括号格式：(1/2)(1/2)、(1/3)(2/3)(3/3) 等
        #    匹配连续的括号对，内部包含数字和斜杠
        clean_content = re.sub(r'\(\d+/\d+\)\s*\(\d+/\d+\)', '', clean_content)
        clean_content = re.sub(r'\(\d+/\d+\)\s*\(\d+/\d+\)\s*\(\d+/\d+\)', '', clean_content)

        # 3. 单个分页标记：(1/2)、(2/2)、(1/3) 等
        clean_content = re.sub(r'\(\d+/\d+\)', '', clean_content)

        # 4. 混合格式：($\frac{1}{2}$)(1) 等
        clean_content = re.sub(r'\(\s*\$[^$]*\$\s*\)\s*\(\d+\)', '', clean_content)

        # 5. 移除残留的 ](...) 格式标记
        while r'\](' in clean_content:
            start_idx = clean_content.find(r'\](')
            if start_idx == -1:
                break
            depth = 0
            end_idx = -1
            i = start_idx + 2
            while i < len(clean_content):
                if clean_content[i] == '(':
                    depth += 1
                elif clean_content[i] == ')':
                    if depth == 0:
                        end_idx = i
                        break
                    depth -= 1
                i += 1
            if end_idx != -1:
                clean_content = clean_content[:start_idx] + clean_content[end_idx + 1:]
            else:
                break

        # 清理多余的空格
        clean_content = re.sub(r'\s+', ' ', clean_content).strip()

        return clean_content

    def get_latex_generation_hints(self) -> str:
        """
        生成LaTeX生成的提示信息

        这些信息将添加到LaTeX生成的prompt中，
        告诉LLM预处理已经做了什么
        """
        return f"""
# 预处理已完成（减轻LLM压力）

以下场景内容已经过预处理：
1. ✅ Unicode符号已转换为LaTeX命令（∠→\\angle, ²→^2等）
2. ✅ 全角字符已转换为半角
3. ✅ 内容结构已分析并标记
4. ✅ LaTeX环境已建议

**LLM只需要**：
- 根据预标记的结构生成对应的LaTeX环境
- 使用建议的block/exampleblock/alertblock/itemize
- 保持数学符号在$...$中

**无需处理的转换**：
- ❌ 不需要转换Unicode符号（已完成）
- ❌ 不需要转换全角字符（已完成）
- ❌ 不需要分析内容结构（已完成）
"""
