"""
排版设计专家（Layout Designer）

职责：
1. 格式化内容（itemize、LaTeX等）
2. 决定子场景分页（超过2题、超过350字）
3. 设计图示规格（diagramSpec）
4. 视觉动作标注（visualActions）

输入：
- ContentGenerator输出的内容帧列表

输出：最终格式化的帧列表（可用于LaTeX生成）
"""

import asyncio
import json
import logging
import re
from dataclasses import dataclass
from typing import Dict, List, Optional, Any
from shared.llm_client import LLMClient, LLMRequest
from .content_generator import ContentFrame
from .storyboard_designer import StoryboardFrame, StoryboardDesignResult

logger = logging.getLogger(__name__)


class LayoutDesigner:
    """
    排版设计专家

    专注职责：
    1. 格式化内容为LaTeX/结构化格式
    2. 处理子场景分页规则
    3. 生成图示规格
    4. 添加视觉动作标注

    不涉及：
    - 内容创作（由ContentGenerator处理）
    - 教学流程规划（由TeachingFlowDesigner处理）
    """

    def __init__(self, llm_client: LLMClient = None):
        self.llm_client = llm_client
        logger.info("[LayoutDesigner] 初始化完成")

    async def design_layout(
        self,
        content_frames: List[ContentFrame],
        course_type: str = ""
    ) -> StoryboardDesignResult:
        """
        为内容帧应用排版设计

        Args:
            content_frames: ContentGenerator输出的内容帧列表
            course_type: 课程类型（用于判断是否需要图示）

        Returns:
            StoryboardDesignResult: 最终格式化的故事板
        """
        logger.info("[LayoutDesigner] ========== 开始排版设计 ==========")
        logger.info("[LayoutDesigner] 待排版帧数: %d", len(content_frames))

        final_frames = []

        for content_frame in content_frames:
            # 格式化内容
            formatted_frame = await self._format_single_frame(content_frame, course_type)

            # 检查是否需要分页
            split_frames = self._check_and_split_frame(formatted_frame)
            final_frames.extend(split_frames)

        logger.info("[LayoutDesigner] ✓ 排版完成，最终帧数: %d", len(final_frames))

        return StoryboardDesignResult(
            success=True,
            frames=final_frames,
            total_frames=len(final_frames)
        )

    async def _format_single_frame(
        self,
        content_frame: ContentFrame,
        course_type: str
    ) -> StoryboardFrame:
        """格式化单个帧"""
        # 格式化mainContent
        formatted_content = self._format_content(content_frame.main_content, content_frame.slide_type)

        # 决定是否需要图示
        needs_diagram, diagram_spec = self._decide_diagram(
            content_frame,
            course_type,
            formatted_content
        )

        # 生成视觉动作
        visual_actions = self._generate_visual_actions(content_frame, formatted_content)

        # 创建StoryboardFrame
        return StoryboardFrame(
            scene_id=content_frame.scene_id,
            stage=content_frame.stage,
            frame_title=content_frame.frame_title,
            main_content=formatted_content,
            narration=content_frame.narration,
            key_points=content_frame.key_points or [],
            visual_actions=visual_actions,
            needs_diagram=needs_diagram,
            diagram_spec=diagram_spec,
            duration_hint=self._estimate_duration(formatted_content)
        )

    def _format_content(self, content: str, slide_type: str) -> str:
        """格式化内容"""
        # 如果已经是LaTeX格式，直接返回
        if '\\begin{' in content or '\\item' in content:
            return content

        # 根据slide_type决定格式
        if slide_type == 'objectives':
            # 学习目标：转为itemize列表
            if not content.startswith('\\begin{itemize}'):
                lines = [line.strip() for line in content.split('\n') if line.strip()]
                items = [f"\\item {line}" for line in lines]
                return "\\begin{itemize}\n" + "\n".join(items) + "\n\\end{itemize}"

        elif slide_type == 'concept':
            # 概念讲解：转为结构化列表
            if '：' in content or ':' in content:
                lines = content.split('\n')
                formatted_lines = []
                for line in lines:
                    line = line.strip()
                    if line:
                        if '：' in line or ':' in line:
                            # 转为item格式
                            formatted_lines.append(f"\\item {line}")
                        else:
                            formatted_lines.append(line)
                if formatted_lines and not formatted_lines[0].startswith('\\item'):
                    formatted_lines.insert(0, "\\begin{itemize}")
                    formatted_lines.append("\\end{itemize}")
                return "\n".join(formatted_lines)
            else:
                # 简单内容，加itemize包装
                return f"\\begin{{itemize}}\n\\item {content}\n\\end{{itemize}}"

        elif slide_type == 'practice':
            # 练习题：保持原有格式，确保换行
            return content

        elif slide_type == 'summary':
            # 小结：转为itemize列表
            if not content.startswith('\\begin{itemize}'):
                lines = [line.strip() for line in content.split('\n') if line.strip()]
                items = [f"\\item {line}" for line in lines]
                return "\\begin{itemize}\n" + "\n".join(items) + "\n\\end{itemize}"

        # 默认：直接返回
        return content

    def _decide_diagram(
        self,
        content_frame: ContentFrame,
        course_type: str,
        formatted_content: str
    ) -> tuple[bool, Dict]:
        """决定是否需要图示，并生成规格"""
        # 几何课程总是需要图示
        if course_type == 'geometry':
            return True, self._create_geometry_diagram_spec(content_frame)

        # 函数课程需要图示
        if course_type == 'function':
            return True, self._create_function_diagram_spec(content_frame)

        # 检查内容中的关键词
        diagram_keywords = ['图形', '图像', '坐标', '三角形', '函数', '图表']
        needs_diagram = any(kw in content_frame.main_content or kw in content_frame.frame_title
                           for kw in diagram_keywords)

        if needs_diagram:
            return True, self._create_default_diagram_spec(content_frame)

        return False, {}

    def _create_geometry_diagram_spec(self, content_frame: ContentFrame) -> Dict:
        """创建几何图示规格"""
        return {
            "type": "geometry",
            "title": content_frame.frame_title,
            "shape": "triangle",  # 默认三角形
            "parameters": {}
        }

    def _create_function_diagram_spec(self, content_frame: ContentFrame) -> Dict:
        """创建函数图示规格"""
        return {
            "type": "function_plot",
            "title": content_frame.frame_title,
            "function": "x^2",  # 默认二次函数
            "xRange": [-5, 5],
            "yRange": [-5, 10]
        }

    def _create_default_diagram_spec(self, content_frame: ContentFrame) -> Dict:
        """创建默认图示规格"""
        return {
            "type": "chart",
            "title": content_frame.frame_title
        }

    def _generate_visual_actions(
        self,
        content_frame: ContentFrame,
        formatted_content: str
    ) -> List[str]:
        """生成视觉动作标注"""
        actions = []

        # 根据slide_type生成默认视觉动作
        if content_frame.slide_type == 'concept':
            # 概念帧：高亮关键词
            if content_frame.key_points:
                for kp in content_frame.key_points[:2]:
                    actions.append(f"HIGHLIGHT:{kp}")

        elif content_frame.slide_type == 'example':
            # 例题帧：标注解答步骤
            actions.append("TYPE:例题分析")
            actions.append("RED:关键步骤")

        elif content_frame.slide_type == 'practice':
            # 练习帧：标注题目类型
            actions.append("TYPE:练习题")

        elif content_frame.slide_type == 'summary':
            # 小结帧：标注要点回顾
            actions.append("TYPE:要点回顾")

        return actions

    def _estimate_duration(self, content: str) -> int:
        """估算帧时长（秒）"""
        # 基于内容长度估算
        char_count = len(content)
        base_duration = 20
        extra_duration = min(char_count // 50, 40)
        return base_duration + extra_duration

    def _check_and_split_frame(self, frame: StoryboardFrame) -> List[StoryboardFrame]:
        """检查帧是否需要分页，如果需要则拆分"""
        frames = [frame]

        # 规则1：practice类型，超过2道题需要分页
        if frame.stage == 'practice':
            question_count = self._count_questions(frame.main_content)
            if question_count > 2:
                logger.info(
                    f"[LayoutDesigner] {frame.scene_id}有{question_count}道题，需要分页"
                )
                frames = self._split_practice_frame(frame, question_count)

        # 规则2：concept类型，超过350字需要分页
        elif frame.stage in ['concept', 'example']:
            chinese_chars = len(re.sub(r'\\[a-zA-Z{}$^_\\]+', '', frame.main_content))
            if chinese_chars > 350:
                logger.info(
                    f"[LayoutDesigner] {frame.scene_id}有{chinese_chars}字，需要分页"
                )
                frames = self._split_long_content_frame(frame, chinese_chars)

        return frames

    def _count_questions(self, content: str) -> int:
        """统计题目数量"""
        # 匹配题目标记
        patterns = [
            r'\n\d+\.\s',  # 1. 2. 3.
            r'\n[①②③④⑤⑥⑦⑧⑨⑩]\s',  # 圆圈数字
            r'\n基础题|中等题|提升题',  # 题型标记
            r'题目：',  # 题目标记
        ]
        count = 0
        for pattern in patterns:
            matches = re.findall(pattern, content)
            count += len(matches)
        return max(count, content.count('（'))

    def _split_practice_frame(
        self,
        frame: StoryboardFrame,
        question_count: int
    ) -> List[StoryboardFrame]:
        """拆分练习帧"""
        questions_per_frame = 2
        sub_frames = []

        # 简单按字符数拆分（实际应该按题目结构）
        content_lines = frame.main_content.split('\n')
        current_content = []
        current_question_count = 0
        sub_index = 0

        for line in content_lines:
            current_content.append(line)

            # 检测是否是新题目
            if re.match(r'^\d+\.\s', line) or re.match(r'^[①②③④⑤⑥⑦⑧⑨⑩]\s', line):
                current_question_count += 1

            # 达到题目数量限制，创建子帧
            if current_question_count >= questions_per_frame:
                sub_id = chr(97 + sub_index)  # a, b, c

                sub_frame = StoryboardFrame(
                    scene_id=f"{frame.scene_id}{sub_id}",
                    stage=frame.stage,
                    frame_title=f"{frame.frame_title}（{sub_index+1}）",
                    main_content='\n'.join(current_content),
                    narration=f"{frame.narration}（第{sub_index+1}部分）",
                    key_points=frame.key_points,
                    visual_actions=frame.visual_actions,
                    needs_diagram=frame.needs_diagram,
                    diagram_spec=frame.diagram_spec,
                    duration_hint=frame.duration_hint
                )
                sub_frames.append(sub_frame)

                # 重置
                current_content = []
                current_question_count = 0
                sub_index += 1

        # 处理剩余内容
        if current_content:
            sub_id = chr(97 + sub_index)
            sub_frame = StoryboardFrame(
                scene_id=f"{frame.scene_id}{sub_id}",
                stage=frame.stage,
                frame_title=f"{frame.frame_title}（{sub_index+1}）",
                main_content='\n'.join(current_content),
                narration=f"{frame.narration}（第{sub_index+1}部分）",
                key_points=frame.key_points,
                visual_actions=frame.visual_actions,
                needs_diagram=frame.needs_diagram,
                diagram_spec=frame.diagram_spec,
                duration_hint=frame.duration_hint
            )
            sub_frames.append(sub_frame)

        return sub_frames

    def _split_long_content_frame(
        self,
        frame: StoryboardFrame,
        char_count: int
    ) -> List[StoryboardFrame]:
        """拆分长内容帧"""
        # 简单按itemize拆分
        sub_frames = []

        if '\\begin{itemize}' in frame.main_content:
            # 提取所有item
            items = re.findall(r'\\item\s+([^\n]+)', frame.main_content)

            # 每个子场景最多3个item
            items_per_frame = 3
            sub_index = 0

            for i in range(0, len(items), items_per_frame):
                chunk_items = items[i:i+items_per_frame]
                sub_id = chr(97 + sub_index)

                chunk_content = "\\begin{itemize}\n"
                for item in chunk_items:
                    chunk_content += f"\\item {item}\n"
                chunk_content += "\\end{itemize}"

                sub_frame = StoryboardFrame(
                    scene_id=f"{frame.scene_id}{sub_id}",
                    stage=frame.stage,
                    frame_title=f"{frame.frame_title}（{i//items_per_frame+1}）",
                    main_content=chunk_content,
                    narration=f"{frame.narration}（第{i//items_per_frame+1}部分）",
                    key_points=frame.key_points,
                    visual_actions=frame.visual_actions,
                    needs_diagram=frame.needs_diagram,
                    diagram_spec=frame.diagram_spec,
                    duration_hint=frame.duration_hint
                )
                sub_frames.append(sub_frame)
                sub_index += 1

        return sub_frames if sub_frames else [frame]
