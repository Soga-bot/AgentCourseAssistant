"""
分页模块数据结构定义

这个模块定义了专门分页功能所需的输入输出格式
"""

from typing import List, Dict, Any, TypedDict
from dataclasses import dataclass, field


@dataclass
class FrameMapping:
    """单个frame的映射信息"""
    original_scene_id: str  # 原始scene ID（如"s5"）
    frame_num: int  # 这是第几个分页（从1开始）
    total_frames: int  # 总共分了多少页
    frame_title: str  # 分页后的标题（如"典例精讲1（1/3）"）
    original_title: str  # 原始标题（如"典例精讲1"）
    content_summary: str  # 内容摘要（用于语音生成，80-150字）
    full_content: str  # 完整的frame内容（LaTeX代码）


@dataclass
class PaginationResult:
    """分页结果"""
    latex: str  # 分页后的完整LaTeX代码
    frame_mappings: List[FrameMapping]  # 每个frame的映射信息
    stats: Dict[str, Any]  # 统计信息

    def __post_init__(self):
        """初始化后处理"""
        if self.stats is None:
            self.stats = {}


@dataclass
class PaginationRequest:
    """分页请求"""
    latex: str  # 待分页的LaTeX代码
    scenes: List[Dict[str, Any]]  # 场景列表，用于获取scene ID和标题
    options: Dict[str, Any] = field(default_factory=dict)  # 可选配置


# 分页配置选项
PAGINATION_CONFIG = {
    # 典例精讲类：固定拆分为3页
    'example_split': {
        'enabled': True,
        'frames_per_example': 3,
        'structure': ['题目+思路引导', '完整步骤', '易错提醒+方法总结']
    },

    # 随堂练习类：按题目数量拆分
    'exercise_split': {
        'enabled': True,
        'questions_per_frame': 2,  # 每帧2题
        'use_frametitle': True  # 使用\frametitle保留原标题
    },

    # 课堂小结类：按section拆分
    'summary_split': {
        'enabled': True,
        'sections_per_frame': 2,  # 每帧2个section
        'use_frametitle': True
    },

    # 易错点提醒类：按数量拆分
    'warning_split': {
        'enabled': True,
        'min_items_to_split': 3,  # 至少3个才拆分
        'target_frames': 2
    },

    # 通用配置
    'general': {
        'max_chars_per_frame': 800,  # 单帧最大字符数
        'min_chars_per_frame': 100,  # 单帧最小字符数
        'preserve_semantic': True,  # 保持语义完整性
        'add_frametitle': True  # 分页后添加\frametitle
    }
}


# 分页类型的枚举
class PaginationType:
    """分页类型"""
    EXAMPLE = "example"  # 典例精讲
    EXERCISE = "exercise"  # 随堂练习
    SUMMARY = "summary"  # 课堂小结
    WARNING = "warning"  # 易错点提醒
    CONCEPT = "concept"  # 概念讲解（新增）
    NONE = "none"  # 不分页


def detect_pagination_type(frame_title: str, frame_content: str) -> str:
    """
    检测frame应该使用哪种分页类型

    Args:
        frame_title: frame标题
        frame_content: frame内容

    Returns:
        PaginationType常量
    """
    title_lower = frame_title.lower()
    content_lower = frame_content.lower()

    # 优先级从高到低
    if '典例精讲' in title_lower or '典例精讲' in content_lower:
        return PaginationType.EXAMPLE

    if '随堂练习' in title_lower or '练习' in title_lower:
        return PaginationType.EXERCISE

    if '课堂小结' in title_lower or '小结' in title_lower:
        return PaginationType.SUMMARY

    if '易错点' in title_lower or '易错' in title_lower:
        return PaginationType.WARNING

    # 新增：概念讲解识别
    # 检测是否包含多个概念（使用顿号、逗号、空格等分隔符）
    concept_separators = ['、', '与', '及', '或', ',', ' ']
    has_multiple_concepts = any(sep in frame_title for sep in concept_separators[:-1])  # 排除空格
    # 检测关键词：数轴、相反数、绝对值、有理数、无理数等概念词
    concept_keywords = ['数轴', '相反数', '绝对值', '有理数', '无理数', '科学记数法',
                       '乘方', '开方', '平方根', '立方根', '运算', '法则', '定律']
    has_concept_keywords = sum(1 for kw in concept_keywords if kw in frame_title) >= 2

    # 概念讲解类：标题包含多个概念 或 包含概念组合
    if (has_multiple_concepts or has_concept_keywords) and not any(
        kw in title_lower for kw in ['封面', '导入', '目标', '小结', '练习', '精讲', '易错']
    ):
        return PaginationType.CONCEPT

    return PaginationType.NONE


def extract_frame_blocks(latex: str) -> List[Dict[str, str]]:
    r"""
    从LaTeX中提取所有frame块

    支持两种格式：
    1. \\begin{frame}{标题}\\n内容\\end{frame}
    2. \\begin{frame}\\n\\frametitle{标题}\\n内容\\end{frame}

    Returns:
        List of {
            'title': str,
            'content': str,
            'full_latex': str,  # 包含\begin{frame}...\end{frame}的完整代码
            'scene_id': str     # SceneID（如果存在）
        }
    """
    import re

    frames = []

    # 匹配两种frame格式
    # 格式1: \begin{frame}{标题}\n内容\end{frame}
    # 格式2: \begin{frame}\n\frametitle{标题}\n内容\end{frame}
    # 使用非贪婪匹配，避免跨越多个frame
    pattern = r'\\begin\{frame\}(?:\{([^\}]+)\})?\s*\n((?:\\frametitle\{[^\}]+\}\s*\n)?)(.*?)\\end\{frame\}'

    for match in re.finditer(pattern, latex, re.DOTALL):
        group1 = match.group(1) or ""  # 标题（格式1）
        group2 = match.group(2) or ""   # \frametitle行（格式2）
        content = match.group(3) or ""
        full_latex = match.group(0)

        # 确定标题：优先使用group1（格式1），否则从group2中提取（格式2）
        title = group1.strip()
        if not title and group2:
            # 从\frametitle{...}中提取标题
            frametitle_match = re.search(r'\\frametitle\{([^\}]+)\}', group2)
            if frametitle_match:
                title = frametitle_match.group(1).strip()

        # 提取SceneID
        scene_id = None
        scene_id_match = re.search(r'% SceneID:\s*(\S+)', full_latex)
        if scene_id_match:
            scene_id = scene_id_match.group(1)

        frames.append({
            'title': title,
            'content': content.strip(),
            'full_latex': full_latex,
            'scene_id': scene_id
        })

    return frames
