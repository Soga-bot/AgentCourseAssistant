"""
帧预处理器 - 将 course.json 转换为规范帧

[开发历史] 早期简化版视频流水线（simple_pipeline.py）的配套模块，
用于将课程JSON转换为规范帧数据结构。后续视频管道改用 CourseToVideoMapper 方案后不再使用。
[已弃用 - 2026] 仅被 simple_pipeline.py 引用，无其他外部调用，保留作存档。

核心思想：
1. 按语义边界拆分内容
2. 估算每段内容的渲染高度
3. 超过容量的继续拆分
4. 输出规范帧列表（每帧保证不溢出）

特点：
- 纯规则处理，0次LLM调用
- 预计算高度，保证不溢出
- 语义边界优先，分页合理
"""

import re
import logging
from typing import Dict, List, Any, Tuple
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class Frame:
    """规范帧数据结构"""
    id: str                    # 帧ID（s1, s2, s3...）
    title: str               # 帧标题
    content: str              # 帧内容（已处理，保证不溢出）
    frame_type: str            # 帧类型
    section_source: str        # 来源section名称
    narration_hint: str = ""   # 语音提示（可选）


class FramePreprocessor:
    """
    帧预处理器

    将 course.json 的 sections 转换为规范帧列表
    每个帧保证不溢出
    """

    # ========== 页面容量配置 ==========
    # Beamer 标准页面容量（128mm × 96mm，12pt 字体）
    PAGE_CAPACITY_LINES = 12      # 内容行数（预留3行余量）
    CHARS_PER_LINE = 27          # 每行约27个中文字符

    # 内容类型成本系数（相对于纯文本的额外占用）
    CONTENT_COST = {
        "formula": 1.5,      # 公式占用更多空间
        "block_title": 1.0,   # block 标题占1行
        "list_item": 1.0,     # 列表项
        "empty_line": 0.5,    # 空行
    }

    # Section 类型到帧类型的映射
    SECTION_TYPE_MAP = {
        "导入": "intro",
        "学习目标": "objectives",
        "知识点详解": "concept",
        "典例精讲": "example",
        "易错点": "warning",
        "随堂小测": "practice",
        "知识框架": "summary",
        "课后拓展": "extend"
    }

    def __init__(self):
        self.frame_counter = 0
        logger.info("[FramePreprocessor] 初始化完成")
        logger.info(f"[FramePreprocessor] 页面容量: {self.PAGE_CAPACITY_LINES} 行")

    def preprocess(self, course_json: Dict) -> List[Frame]:
        """
        预处理主流程

        Args:
            course_json: course.json 的内容

        Returns:
            规范帧列表
        """
        self.frame_counter = 0
        frames = []

        sections = course_json.get("sections", {})
        if not sections:
            logger.warning("[FramePreprocessor] sections 为空")
            return frames

        logger.info(f"[FramePreprocessor] 开始处理 {len(sections)} 个 sections")

        # 按 section 顺序处理
        section_order = ["导入", "学习目标", "知识点详解", "典例精讲",
                        "易错点", "随堂小测", "知识框架", "课后拓展"]

        for section_name in section_order:
            if section_name not in sections:
                continue

            content = sections[section_name]
            if not content or not content.strip():
                continue

            section_frames = self._process_section(section_name, content)
            frames.extend(section_frames)

        logger.info(f"[FramePreprocessor] 预处理完成: {len(frames)} 帧")
        return frames

    def _process_section(self, section_name: str, content: str) -> List[Frame]:
        """按 section 类型处理"""
        frame_type = self.SECTION_TYPE_MAP.get(section_name, "concept")

        if frame_type == "intro":
            return self._process_simple_section(section_name, content, "intro")

        elif frame_type == "objectives":
            return self._process_simple_section(section_name, content, "objectives")

        elif frame_type == "concept":
            return self._process_concept_section(section_name, content)

        elif frame_type == "example":
            return self._process_example_section(section_name, content)

        elif frame_type == "warning":
            return self._process_warning_section(section_name, content)

        elif frame_type == "practice":
            return self._process_practice_section(section_name, content)

        elif frame_type == "summary":
            return self._process_summary_section(section_name, content)

        elif frame_type == "extend":
            return self._process_simple_section(section_name, content, "extend")

        else:
            return self._process_simple_section(section_name, content, "concept")

    def _process_simple_section(self, section_name: str, content: str,
                                  frame_type: str) -> List[Frame]:
        """处理简单 section（不拆分或简单拆分）"""
        frames = []

        # 估算高度
        height = self._estimate_height(content)

        if height <= self.PAGE_CAPACITY_LINES:
            # 不需要拆分
            frame = self._create_frame(section_name, content, frame_type,
                                        section_source=section_name)
            frames.append(frame)
        else:
            # 需要拆分
            split_contents = self._split_long_content(content, height)
            for i, split_content in enumerate(split_contents):
                sub_title = f"{section_name}（{i+1}）" if len(split_contents) > 1 else section_name
                frame = self._create_frame(sub_title, split_content, frame_type,
                                           section_source=section_name)
                frames.append(frame)

        return frames

    def _process_concept_section(self, section_name: str, content: str) -> List[Frame]:
        """处理知识点详解 - 按【小标题】拆分"""
        frames = []

        # 按【一】【二】等小标题拆分
        pattern = r'【([一二三四五六七八九十]+)[、\.]([^【]+)'
        matches = list(re.finditer(pattern, content))

        if not matches:
            # 没有小标题，作为整体处理
            return self._process_simple_section(section_name, content, "concept")

        # 按小标题拆分
        start = 0
        for i, match in enumerate(matches):
            end = match.start()
            if start < end:
                part = content[start:end].strip()
                if part:
                    part_frames = self._process_concept_part(part, i + 1)
                    frames.extend(part_frames)
            start = end

        # 最后一段
        if start < len(content):
            part = content[start:].strip()
            if part:
                part_frames = self._process_concept_part(part, len(matches) + 1)
                frames.extend(part_frames)

        return frames

    def _process_concept_part(self, content: str, index: int) -> List[Frame]:
        """处理单个知识点部分"""
        frames = []

        # 提取标题
        title_match = re.match(r'【([一二三四五六七八九十]+)[、\.](.+?)】', content)
        if title_match:
            title = title_match.group(2).strip()
        else:
            title = f"知识点{index}"

        # 估算高度
        height = self._estimate_height(content)

        if height <= self.PAGE_CAPACITY_LINES:
            frame = self._create_frame(title, content, "concept", section_source="知识点详解")
            frames.append(frame)
        else:
            # 需要拆分
            split_contents = self._split_long_content(content, height)
            for i, split_content in enumerate(split_contents):
                sub_title = f"{title}（{i+1}）" if len(split_contents) > 1 else title
                frame = self._create_frame(sub_title, split_content, "concept", section_source="知识点详解")
                frames.append(frame)

        return frames

    def _process_example_section(self, section_name: str, content: str) -> List[Frame]:
        """处理典例精讲 - 按例题拆分，每例题拆3帧"""
        frames = []

        # 按【例题1】【例题2】拆分
        pattern = r'【例题\d+】'
        examples = re.split(pattern, content)

        # 第一个可能是空的
        examples = [e.strip() for e in examples if e.strip()]

        if not examples:
            return self._process_simple_section(section_name, content, "example")

        for i, example in enumerate(examples):
            example_frames = self._process_single_example(example, i + 1)
            frames.extend(example_frames)

        return frames

    def _process_single_example(self, content: str, index: int) -> List[Frame]:
        """处理单个例题 - 固定拆3帧"""
        frames = []

        # 提取各部分
        parts = self._extract_example_parts(content)

        # 第1帧：题目
        if parts.get("question"):
            frame = self._create_frame(
                f"典例精讲{index} - 题目",
                parts["question"],
                "example_q",
                section_source="典例精讲"
            )
            frames.append(frame)

        # 第2帧：步骤
        if parts.get("steps"):
            frame = self._create_frame(
                f"典例精讲{index} - 解答",
                parts["steps"],
                "example_s",
                section_source="典例精讲"
            )
            frames.append(frame)

        # 第3帧：总结
        if parts.get("summary"):
            frame = self._create_frame(
                f"典例精讲{index} - 总结",
                parts["summary"],
                "example_m",
                section_source="典例精讲"
            )
            frames.append(frame)

        return frames

    def _extract_example_parts(self, content: str) -> Dict[str, str]:
        """提取例题的各部分"""
        parts = {}

        # 提取题目
        q_match = re.search(r'【题目】(.+?)(?=【|$)', content, re.DOTALL)
        if q_match:
            parts["question"] = q_match.group(1).strip()
        else:
            # 尝试其他格式
            lines = content.split('\n')
            if lines:
                parts["question"] = lines[0] if '【' in lines[0] else content[:200]

        # 提取步骤
        s_match = re.search(r'【完整步骤】(.+?)(?=【|$)', content, re.DOTALL)
        if s_match:
            parts["steps"] = s_match.group(1).strip()
        else:
            # 尝试提取思路引导和步骤
            all_steps = re.search(r'【思路引导】(.+)', content, re.DOTALL)
            if all_steps:
                parts["steps"] = all_steps.group(1).strip()

        # 提取总结
        m_match = re.search(r'【方法总结】(.+?)(?=【|$)', content, re.DOTALL)
        if m_match:
            parts["summary"] = m_match.group(1).strip()
        else:
            # 尝试提取易错提醒
            warning = re.search(r'【易错提醒】(.+)', content, re.DOTALL)
            if warning:
                parts["summary"] = warning.group(1).strip()

        return parts

    def _process_warning_section(self, section_name: str, content: str) -> List[Frame]:
        """处理易错点 - 每个易错点1帧"""
        frames = []

        # 按易错点1、易错点2拆分
        pattern = r'易错点\d+[：:]'
        warnings = re.split(pattern, content)
        warnings = [w.strip() for w in warnings if w.strip()]

        if not warnings:
            return self._process_simple_section(section_name, content, "warning")

        for i, warning in enumerate(warnings):
            # 估算高度
            height = self._estimate_height(warning)

            if height <= self.PAGE_CAPACITY_LINES:
                frame = self._create_frame(
                    f"易错点{i+1}",
                    warning,
                    "warning",
                    section_source="易错点"
                )
                frames.append(frame)
            else:
                # 拆分
                split_contents = self._split_long_content(warning, height)
                for j, split_content in enumerate(split_contents):
                    frame = self._create_frame(
                        f"易错点{i+1}（{j+1}）",
                        split_content,
                        "warning",
                        section_source="易错点"
                    )
                    frames.append(frame)

        return frames

    def _process_practice_section(self, section_name: str, content: str) -> List[Frame]:
        """处理随堂小测 - 每2题1帧"""
        frames = []

        # 按练习题1、练习题2拆分
        pattern = r'练习题\d+[：:]'
        questions = re.split(pattern, content)
        questions = [q.strip() for q in questions if q.strip()]

        if not questions:
            return self._process_simple_section(section_name, content, "practice")

        # 每2题1帧
        for i in range(0, len(questions), 2):
            batch = questions[i:i+2]
            batch_content = "\n\n".join([f"练习题{j+1}: {q}" for j, q in enumerate(batch)])

            # 估算高度
            height = self._estimate_height(batch_content)

            if height <= self.PAGE_CAPACITY_LINES:
                frame = self._create_frame(
                    f"随堂小测（{i//2+1}）",
                    batch_content,
                    "practice",
                    section_source="随堂小测"
                )
                frames.append(frame)
            else:
                # 拆分
                split_contents = self._split_long_content(batch_content, height)
                for j, split_content in enumerate(split_contents):
                    frame = self._create_frame(
                        f"随堂小测（{i//2+1}-{j+1}）",
                        split_content,
                        "practice",
                        section_source="随堂小测"
                    )
                    frames.append(frame)

        return frames

    def _process_summary_section(self, section_name: str, content: str) -> List[Frame]:
        """处理知识框架"""
        # 知识框架通常不拆分
        return self._process_simple_section(section_name, content, "summary")

    # ========== 核心方法：高度估算和内容拆分 ==========

    def _estimate_height(self, content: str) -> int:
        """
        估算内容渲染高度（行数）

        采用保守估算策略：
        - 纯文本：1字符 = 1/27 行
        - 公式：1字符 = 1.5/27 行
        - 列表项：1项 = 1行
        """
        if not content:
            return 0

        lines = 0
        content_lines = content.split('\n')

        for line in content_lines:
            line = line.strip()
            if not line:
                lines += 0.5  # 空行
                continue

            # 检测公式（包含 $ 或 LaTeX 命令）
            if '$' in line or '\\' in line or '{' in line:
                # 公式行，占用更多空间
                char_count = len(line)
                lines += max(1, char_count / (self.CHARS_PER_LINE / 1.5))
            elif re.match(r'^[①②③④⑤⑥⑦⑧⑨⑩]', line) or re.match(r'^\d+[\.、）]', line):
                # 列表项
                lines += 1
            else:
                # 普通文本
                char_count = len(line)
                lines += max(1, char_count / self.CHARS_PER_LINE)

        return int(lines) + 1  # 加1行余量

    def _split_long_content(self, content: str, estimated_height: int) -> List[str]:
        """
        拆分超长内容

        策略：
        1. 按段落拆分
        2. 每段估算高度
        3. 合并到接近容量上限
        """
        # 按双换行或单换行拆分段落
        paragraphs = re.split(r'\n\s*\n', content)
        paragraphs = [p.strip() for p in paragraphs if p.strip()]

        if len(paragraphs) <= 1:
            # 只有一段，按句子拆分
            return self._split_by_sentences(content)

        # 按段落合并
        result = []
        current = ""
        current_height = 0

        for para in paragraphs:
            para_height = self._estimate_height(para)

            if current_height + para_height <= self.PAGE_CAPACITY_LINES:
                current += ("\n\n" if current else "") + para
                current_height += para_height
            else:
                if current:
                    result.append(current)
                current = para
                current_height = para_height

        if current:
            result.append(current)

        return result if result else [content]

    def _split_by_sentences(self, content: str) -> List[str]:
        """按句子拆分"""
        # 按句号、问号、感叹号拆分
        sentences = re.split(r'([。！？])', content)

        # 重新组合（保留标点）
        combined = []
        for i in range(0, len(sentences) - 1, 2):
            if i + 1 < len(sentences):
                combined.append(sentences[i] + sentences[i + 1])
            else:
                combined.append(sentences[i])

        if not combined:
            return [content]

        # 合并到容量上限
        result = []
        current = ""
        current_height = 0

        for sentence in combined:
            sent_height = self._estimate_height(sentence)

            if current_height + sent_height <= self.PAGE_CAPACITY_LINES:
                current += sentence
                current_height += sent_height
            else:
                if current:
                    result.append(current)
                current = sentence
                current_height = sent_height

        if current:
            result.append(current)

        return result if result else [content]

    # ========== 工具方法 ==========

    def _create_frame(self, title: str, content: str, frame_type: str,
                      section_source: str = "") -> Frame:
        """创建帧"""
        self.frame_counter += 1

        return Frame(
            id=f"s{self.frame_counter}",
            title=title,
            content=content.strip(),
            frame_type=frame_type,
            section_source=section_source
        )

    def frames_to_dict(self, frames: List[Frame]) -> List[Dict]:
        """转换为字典格式（用于JSON输出）"""
        return [
            {
                "id": f.id,
                "title": f.title,
                "content": f.content,
                "frameType": f.frame_type,
                "sectionSource": f.section_source,
                "narrationHint": f.narration_hint
            }
            for f in frames
        ]

    def frames_from_dict(self, frames_data: List[Dict]) -> List[Frame]:
        """从字典格式恢复帧对象"""
        return [
            Frame(
                id=d.get("id", ""),
                title=d.get("title", ""),
                content=d.get("content", ""),
                frame_type=d.get("frameType", "concept"),
                section_source=d.get("sectionSource", ""),
                narration_hint=d.get("narrationHint", "")
            )
            for d in frames_data
        ]

    def get_stats(self, frames: List[Frame]) -> Dict[str, Any]:
        """获取统计信息"""
        type_counts = {}
        for f in frames:
            type_counts[f.frame_type] = type_counts.get(f.frame_type, 0) + 1

        return {
            "total_frames": len(frames),
            "type_distribution": type_counts,
            "avg_content_length": sum(len(f.content) for f in frames) / len(frames) if frames else 0
        }


# ========== 便捷函数 ==========

def preprocess_course_to_frames(course_json: Dict) -> List[Dict]:
    """
    便捷函数：预处理 course.json 为帧列表

    Args:
        course_json: course.json 的内容

    Returns:
        帧字典列表
    """
    preprocessor = FramePreprocessor()
    frames = preprocessor.preprocess(course_json)
    return preprocessor.frames_to_dict(frames)
