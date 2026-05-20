"""
教学流程规划专家（Teaching Flow Designer）

职责：
1. 分析课程内容，决定教学流程
2. 决定教什么、按什么顺序教
3. 决定分几帧、每帧的类型
4. 不涉及具体内容生成

输出：帧结构列表（sceneID, frameTitle, stage, slideType）
"""

import asyncio
import json
import logging
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Any
from shared.llm_client import LLMClient, LLMRequest

logger = logging.getLogger(__name__)


@dataclass
class FrameStructure:
    """帧结构定义（不含具体内容）"""
    scene_id: str
    frame_title: str
    stage: str              # title, objectives, concept, practice, summary, etc.
    slide_type: str         # title, intro, concept, example, practice, warning, summary, extend
    description: str = ""   # 该帧的目的说明
    keywords: List[str] = field(default_factory=list)  # 关键词/知识点


@dataclass
class TeachingFlowResult:
    """教学流程规划结果"""
    success: bool
    frames: List[FrameStructure] = field(default_factory=list)
    total_frames: int = 0
    rationale: str = ""  # 规划理由
    error: str = ""


class TeachingFlowDesigner:
    """
    教学流程规划专家

    专注职责：
    1. 分析课程内容
    2. 规划教学流程
    3. 决定帧数和类型
    4. 不生成具体内容
    """

    # 温度设置：低温度保证稳定性
    TEMPERATURE = 0.0
    MAX_TOKENS = 2000  # 输出只需要结构，不需要太多tokens

    # 教学流程模板
    FLOW_TEMPLATES = {
        "standard_9": """标准9帧流程：
1. s1 - 标题页 (title)
2. s2 - 学习目标 (objectives)
3. s3 - 情境导入 (intro)
4. s4-s6 - 知识点详解 (concept) - 每个知识点1-2帧
5. s7 - 例题示范 (example)
6. s8 - 巩固练习 (practice)
7. s9 - 课堂小结 (summary)""",
    }

    def __init__(self, llm_client: LLMClient):
        self.llm_client = llm_client
        logger.info("[TeachingFlowDesigner] 初始化完成")

    async def design_flow(
        self,
        title: str,
        understanding_result: Any,
        target_frames: int = 9
    ) -> TeachingFlowResult:
        """
        规划教学流程

        Args:
            title: 课程标题
            understanding_result: 内容理解结果（来自ContentUnderstanding）
            target_frames: 目标帧数

        Returns:
            TeachingFlowResult: 流程规划结果
        """
        logger.info("[TeachingFlowDesigner] ========== 开始规划教学流程 ==========")
        logger.info("[TeachingFlowDesigner] 课程: %s, 目标帧数: %d", title, target_frames)

        # 序列化理解结果
        understanding_json = self._serialize_understanding_result(understanding_result)

        # 构建提示词
        prompt = self._build_prompt(title, understanding_json, target_frames)

        # 调用LLM
        try:
            request = LLMRequest(
                messages=[{"role": "user", "content": prompt}],
                temperature=self.TEMPERATURE,
                max_tokens=self.MAX_TOKENS
            )

            response = await self.llm_client.call(request)

            if not response.success:
                logger.error("[TeachingFlowDesigner] LLM调用失败: %s", response.error)
                return self._create_fallback_result(title, understanding_result, target_frames, response.error)

            # 解析结果
            result = self._parse_result(response.content, title)

            if result.success:
                logger.info("[TeachingFlowDesigner] ✓ 流程规划完成")
                logger.info("[TeachingFlowDesigner]   - 规划帧数: %d", result.total_frames)
                for frame in result.frames:
                    logger.debug("[TeachingFlowDesigner]   - %s: %s (%s)",
                               frame.scene_id, frame.frame_title, frame.slide_type)

            return result

        except Exception as e:
            logger.error("[TeachingFlowDesigner] 规划异常: %s", str(e))
            return self._create_fallback_result(title, understanding_result, target_frames, str(e))

    def _build_prompt(
        self,
        title: str,
        understanding_json: str,
        target_frames: int
    ) -> str:
        """构建提示词"""
        return f"""# 任务
规划课程的教学流程，决定分几帧、每帧讲什么。

# 输入信息
课程标题：{title}

目标帧数：{target_frames}帧

课程内容分析：
```json
{understanding_json}
```

# 标准教学流程参考
{self.FLOW_TEMPLATES.get("standard_9", "")}

# 规划要求
1. 根据课程内容知识点的数量和复杂度，调整帧数分配
2. 知识点较多时，可以为每个知识点分配1-2帧
3. 有例题时，单独分配example帧
4. 有练习题时，单独分配practice帧
5. 确保包含：标题页、学习目标、课堂小结

# 输出格式
请按以下格式输出教学流程：

```
规划理由：[简要说明为什么这样规划帧数和类型]

s1|标题页|title|课程标题展示
s2|学习目标|objectives|展示本节课的学习目标
s3|情境导入|intro|[具体主题]|从生活实例引入
s4|知识点1详解|concept|[具体知识点名称]
...
s9|课堂小结|summary|总结回顾本节课内容
```

格式说明：
- 格式：sceneID|帧标题|stage|slide_type|描述
- stage可选：title, objectives, intro, concept, example, practice, summary, extend
- slide_type可选：title, intro, concept, example, practice, warning, summary, extend

请直接输出教学流程规划，不要包含其他内容。"""

    def _parse_result(self, content: str, title: str) -> TeachingFlowResult:
        """解析LLM输出"""
        frames = []
        rationale = ""

        try:
            lines = content.strip().split('\n')

            for line in lines:
                line = line.strip()

                # 提取规划理由
                if line.startswith("规划理由："):
                    rationale = line.split("：", 1)[-1].strip()
                    continue

                # 解析帧结构
                if '|' in line and not line.startswith('#'):
                    parts = [p.strip() for p in line.split('|')]

                    if len(parts) >= 4:
                        scene_id = parts[0]
                        frame_title = parts[1]
                        stage = parts[2]
                        slide_type = parts[3] if len(parts) > 3 else stage
                        description = parts[4] if len(parts) > 4 else ""

                        # 规范化
                        if slide_type not in ['title', 'intro', 'concept', 'example',
                                             'practice', 'warning', 'summary', 'extend']:
                            slide_type = stage

                        frame = FrameStructure(
                            scene_id=scene_id,
                            frame_title=frame_title,
                            stage=stage,
                            slide_type=slide_type,
                            description=description
                        )
                        frames.append(frame)

            if not frames:
                raise ValueError("未能解析出任何帧结构")

            return TeachingFlowResult(
                success=True,
                frames=frames,
                total_frames=len(frames),
                rationale=rationale
            )

        except Exception as e:
            logger.warning("[TeachingFlowDesigner] 解析失败: %s", str(e))
            return TeachingFlowResult(
                success=False,
                error=f"解析失败: {str(e)}"
            )

    def _serialize_understanding_result(self, result: Any) -> str:
        """将内容理解结果序列化为JSON字符串"""
        knowledge_points = []
        for kp in result.knowledge_points:
            kp_dict = {
                "name": kp.name,
                "content": kp.content,
                "category": kp.category
            }
            knowledge_points.append(kp_dict)

        understanding_dict = {
            "course_type": result.course_type,
            "objectives": result.objectives,
            "knowledge_points": knowledge_points
        }

        return json.dumps(understanding_dict, ensure_ascii=False, indent=2)

    def _create_fallback_result(
        self,
        title: str,
        understanding_result: Any,
        target_frames: int,
        error: str
    ) -> TeachingFlowResult:
        """创建回退结果"""
        logger.warning("[TeachingFlowDesigner] 使用回退流程")

        frames = []

        # s1 标题页
        frames.append(FrameStructure(
            scene_id="s1",
            frame_title=title,
            stage="title",
            slide_type="title",
            description="课程标题展示"
        ))

        # s2 学习目标
        frames.append(FrameStructure(
            scene_id="s2",
            frame_title="学习目标",
            stage="objectives",
            slide_type="objectives",
            description="展示学习目标"
        ))

        # 知识点帧
        kp_count = min(len(understanding_result.knowledge_points), target_frames - 3)
        for i, kp in enumerate(understanding_result.knowledge_points[:kp_count]):
            frames.append(FrameStructure(
                scene_id=f"s{i+3}",
                frame_title=kp.name,
                stage="concept",
                slide_type="concept",
                description=f"讲解{kp.name}",
                keywords=[kp.name]
            ))

        # 最后一帧：小结
        frames.append(FrameStructure(
            scene_id=f"s{len(frames)+1}",
            frame_title="课堂小结",
            stage="summary",
            slide_type="summary",
            description="总结回顾"
        ))

        return TeachingFlowResult(
            success=True,
            frames=frames,
            total_frames=len(frames),
            rationale=f"回退流程（{error}）"
        )
