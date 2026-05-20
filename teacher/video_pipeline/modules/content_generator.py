"""
内容生成专家（Content Generator）

职责：
1. 为每个帧结构生成具体内容（mainContent）
2. 为每个帧生成讲解语音（narration）
3. 为每个帧生成核心要点（keyPoints）

输入：
- TeachingFlowDesigner输出的帧结构列表
- 原始课程内容

输出：填充了内容的帧列表
"""

import asyncio
import json
import logging
from dataclasses import dataclass
from typing import Dict, List, Optional, Any
from shared.llm_client import LLMClient, LLMRequest
from .teaching_flow_designer import FrameStructure

logger = logging.getLogger(__name__)


@dataclass
class ContentFrame:
    """包含具体内容的帧"""
    scene_id: str
    frame_title: str
    stage: str
    slide_type: str
    main_content: str = ""
    narration: str = ""
    key_points: List[str] = None

    def __post_init__(self):
        if self.key_points is None:
            self.key_points = []


@dataclass
class ContentGenerationResult:
    """内容生成结果"""
    success: bool
    frames: List[ContentFrame] = None
    total_frames: int = 0
    error: str = ""

    def __post_init__(self):
        if self.frames is None:
            self.frames = []


class ContentGenerator:
    """
    内容生成专家

    专注职责：
    1. 为每帧生成具体的mainContent
    2. 为每帧生成narration讲解
    3. 为每帧生成keyPoints要点

    不涉及：
    - 排版格式（由LayoutDesigner处理）
    - 子场景分页（由LayoutDesigner处理）
    """

    # 温度设置：低温度保证稳定性，但允许少量变化
    TEMPERATURE = 0.1
    MAX_TOKENS = 4000  # 需要生成较多内容

    def __init__(self, llm_client: LLMClient):
        self.llm_client = llm_client
        logger.info("[ContentGenerator] 初始化完成")

    async def generate_content(
        self,
        frame_structures: List[FrameStructure],
        title: str,
        understanding_result: Any
    ) -> ContentGenerationResult:
        """
        为帧结构生成具体内容

        Args:
            frame_structures: TeachingFlowDesigner输出的帧结构列表
            title: 课程标题
            understanding_result: 内容理解结果

        Returns:
            ContentGenerationResult: 内容生成结果
        """
        logger.info("[ContentGenerator] ========== 开始生成内容 ==========")
        logger.info("[ContentGenerator] 需要生成内容的帧数: %d", len(frame_structures))

        # 序列化理解结果
        understanding_json = self._serialize_understanding_result(understanding_result)

        # 分批生成（避免单次生成过多内容）
        batch_size = 3
        all_frames = []

        for i in range(0, len(frame_structures), batch_size):
            batch = frame_structures[i:i + batch_size]
            logger.info("[ContentGenerator] 正在生成批次 %d-%d...", i+1, min(i+batch_size, len(frame_structures)))

            batch_result = await self._generate_batch(batch, title, understanding_json)
            if not batch_result.success:
                logger.error("[ContentGenerator] 批次生成失败: %s", batch_result.error)
                # 使用回退内容继续
                batch_frames = self._create_fallback_frames(batch, understanding_result)
            else:
                batch_frames = batch_result.frames

            all_frames.extend(batch_frames)

        logger.info("[ContentGenerator] ✓ 内容生成完成，共 %d 帧", len(all_frames))

        return ContentGenerationResult(
            success=True,
            frames=all_frames,
            total_frames=len(all_frames)
        )

    async def _generate_batch(
        self,
        batch: List[FrameStructure],
        title: str,
        understanding_json: str
    ) -> ContentGenerationResult:
        """生成一批帧的内容"""
        # 构建提示词
        prompt = self._build_batch_prompt(batch, title, understanding_json)

        # 调用LLM
        try:
            request = LLMRequest(
                messages=[{"role": "user", "content": prompt}],
                temperature=self.TEMPERATURE,
                max_tokens=self.MAX_TOKENS
            )

            response = await self.llm_client.call(request)

            if not response.success:
                return ContentGenerationResult(
                    success=False,
                    error=f"LLM调用失败: {response.error}"
                )

            # 解析结果
            return self._parse_batch_result(response.content, batch)

        except Exception as e:
            logger.error("[ContentGenerator] 批次生成异常: %s", str(e))
            return ContentGenerationResult(
                success=False,
                error=f"生成异常: {str(e)}"
            )

    def _build_batch_prompt(
        self,
        batch: List[FrameStructure],
        title: str,
        understanding_json: str
    ) -> str:
        """构建批次提示词"""
        frames_info = "\n".join([
            f"- {f.scene_id}: {f.frame_title} ({f.slide_type}) - {f.description}"
            for f in batch
        ])

        # 构建scene_id列表用于JSON输出
        scene_ids = [f.scene_id for f in batch]

        return rf"""# 任务
你是一位专业的教学内容创作者。为以下教学帧生成详细的幻灯片内容和语音讲解。

# 课程信息
课程标题：{title}

# 课程内容分析（参考此内容生成）
```json
{understanding_json}
```

# 需要生成内容的帧（共{len(batch)}个）
{frames_info}

# ⚠️ 重要要求

## 内容完整性
1. **禁止使用占位符**如"..."、"略"、"待补充"等
2. **每帧内容必须完整**，至少150字
3. **根据课程内容分析中的实际知识点生成**，不要编造
4. **必须包含具体的例子、公式、步骤**

## 各类型帧的具体要求

### title（标题帧）
- mainContent: 课程标题 + 副标题（如果有）
- narration: 欢迎语，介绍课程主题（30-50字）
- keyPoints: 提取2-3个关键词

### objectives（学习目标）
- mainContent: 使用\\begin{{itemize}}...\\end{{itemize}}格式，列出4-6个学习目标
- narration: 介绍学习目标的重要性（50-80字）
- keyPoints: 核心学习目标

### concept（概念讲解）
- mainContent: 详细讲解，包含定义、性质、特点、公式等，使用\\begin{{itemize}}格式
- narration: 详细讲解概念，逐步展开（100-150字）
- keyPoints: 3-5个核心要点

### example（例题讲解）
- mainContent: 完整例题，包含题目、思路引导、完整步骤、答案、易错提醒五个部分
- 题目部分用粗体显示
- 解答步骤用编号列表
- 标题使用frameTitle，不要在标题中包含题目内容
- narration: 引导思考，逐步讲解解题过程（100-150字）
- keyPoints: 解题要点（3-5个）

### example_continue（例题续页）
- mainContent: 继续上一题，包含完整步骤、答案、易错提醒
- 解答步骤用编号列表
- 标题使用frameTitle（如"例题1（续）"）
- narration: 继续讲解解题过程（80-120字）
- keyPoints: 解题要点（2-3个）

### practice（练习题）
- mainContent: 完整题目 + 选项/解答步骤
- narration: 读题提示和答案说明（80-120字）
- keyPoints: 题目考查点

### summary（课堂小结）
- mainContent: 使用\\begin{{itemize}}总结核心要点
- narration: 回顾总结，强调重点（80-100字）
- keyPoints: 3-5个总结要点

# 输出格式
请严格按照以下JSON格式输出（不要添加任何其他文字）：

```json
{{
  "frames": [
    {{
      "scene_id": "{scene_ids[0] if len(scene_ids) > 0 else 's1'}",
      "mainContent": "详细内容（至少150字，使用LaTeX格式）",
      "narration": "详细讲解（50-150字）",
      "keyPoints": ["要点1", "要点2", "要点3"]
    }}{',' if len(scene_ids) > 1 else ''}
    {f'{{"scene_id": "{scene_ids[1] if len(scene_ids) > 1 else "s2"}", "mainContent": "...", "narration": "...", "keyPoints": ["..."]}}' if len(scene_ids) > 1 else ''}
  ]
}}
```

⚠️ 注意：
1. 必须输出有效的JSON格式
2. mainContent必须详细完整，至少150字
3. narration要详细讲解，不是简单重复标题
4. 使用LaTeX格式（如\\begin{{itemize}}、\\item等）

请生成内容：
"""

    def _parse_batch_result(
        self,
        content: str,
        batch: List[FrameStructure]
    ) -> ContentGenerationResult:
        """解析批次生成结果（JSON格式）"""
        frames = []

        try:
            # 清理响应，提取JSON
            content = content.strip()

            # 移除markdown代码块标记
            if content.startswith('```json'):
                content = content.split('```json')[1].split('```')[0]
            elif content.startswith('```'):
                content = content.split('```')[1].split('```')[0]
            content = content.strip()

            # 解析JSON
            data = json.loads(content)

            # 提取frames数组
            frames_data = data.get('frames', [])

            if not frames_data:
                raise ValueError("JSON中没有frames数组")

            # 为每个frame创建ContentFrame
            for frame_data in frames_data:
                scene_id = frame_data.get('scene_id', '')

                # 找到对应的FrameStructure
                frame_struct = None
                for fs in batch:
                    if fs.scene_id == scene_id:
                        frame_struct = fs
                        break

                if not frame_struct:
                    logger.warning("[ContentGenerator] 未找到对应的FrameStructure: %s", scene_id)
                    continue

                # 提取内容
                main_content = frame_data.get('mainContent', '')
                narration = frame_data.get('narration', '')
                key_points = frame_data.get('keyPoints', [])

                # 验证内容长度
                if len(main_content) < 50:
                    logger.warning(
                        "[ContentGenerator] %s mainContent过短: %d字（建议>=100字）",
                        scene_id, len(main_content)
                    )
                    # 使用fallback内容
                    main_content = self._generate_fallback_content(frame_struct)

                if len(narration) < 20:
                    logger.warning(
                        "[ContentGenerator] %s narration过短: %d字",
                        scene_id, len(narration)
                    )
                    narration = f"让我们来学习{frame_struct.frame_title}。{frame_struct.description}"

                # 创建ContentFrame
                frame = ContentFrame(
                    scene_id=frame_struct.scene_id,
                    frame_title=frame_struct.frame_title,
                    stage=frame_struct.stage,
                    slide_type=frame_struct.slide_type,
                    main_content=main_content,
                    narration=narration,
                    key_points=key_points if isinstance(key_points, list) else []
                )
                frames.append(frame)

            if not frames:
                raise ValueError("未能解析出任何有效帧")

            logger.info("[ContentGenerator] 成功解析 %d 帧", len(frames))
            return ContentGenerationResult(
                success=True,
                frames=frames,
                total_frames=len(frames)
            )

        except json.JSONDecodeError as e:
            logger.error("[ContentGenerator] JSON解析失败: %s", str(e))
            logger.debug("[ContentGenerator] 原始内容: %s", content[:500])
            return ContentGenerationResult(
                success=False,
                error=f"JSON解析失败: {str(e)}"
            )
        except Exception as e:
            logger.warning("[ContentGenerator] 解析失败: %s", str(e))
            return ContentGenerationResult(
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
                "category": kp.category,
                "key_theorems": kp.key_theorems
            }
            knowledge_points.append(kp_dict)

        understanding_dict = {
            "course_type": result.course_type,
            "objectives": result.objectives,
            "knowledge_points": knowledge_points
        }

        return json.dumps(understanding_dict, ensure_ascii=False, indent=2)

    def _generate_fallback_content(self, frame_struct: FrameStructure) -> str:
        """为单个帧生成回退内容（详细版）"""
        slide_type = frame_struct.slide_type
        title = frame_struct.frame_title
        desc = frame_struct.description

        if slide_type == 'title':
            return f"\\centering\n\\Large \\textbf{{{title}}}\n\n\\normalsize\n\\vspace{{1cm}}\n课程讲解"

        elif slide_type == 'objectives':
            return f"""\\begin{{itemize}}
\\item 理解{title}的核心概念
\\item 掌握{title}的基本性质
\\item 能够运用{title}解决相关问题
\\item 提升{title}的应用能力
\\end{{itemize}}"""

        elif slide_type == 'concept':
            return f"""\\begin{{itemize}}
\\item \\textbf{{{title}}}的定义和特征
\\item {title}的核心要点：{desc}
\\item {title}的相关性质和定理
\\item {title}的应用场景
\\item 常见问题和注意事项
\\end{{itemize}}"""

        elif slide_type == 'example':
            # 智能处理例题标题：提取例题编号，将题目内容移到正文
            import re
            display_title = title
            problem_content = desc

            # 如果title包含冒号，提取冒号前的部分作为标题
            if '：' in title or ':' in title:
                # 优先使用中文冒号分隔
                if '：' in title:
                    parts = title.split('：', 1)
                else:
                    parts = title.split(':', 1)

                if len(parts) == 2:
                    display_title = parts[0].strip()
                    # 如果desc为空或很简短，使用冒号后的内容作为题目
                    if not desc or len(desc) < 10:
                        problem_content = parts[1].strip()

            # 方案B2+B1: 使用换行控制，标签后加换行，内容另起一行
            return f"""\\textbf{{{display_title}}}

\\vspace{{0.3cm}}

\\textbf{{\\u3010题目\\u3011}}\\;
{problem_content}

\\vspace{{0.3cm}}

\\textbf{{\\u3010思路引导\\u3011}}\\;
仔细分析题目条件，运用相关知识和方法求解。

\\vspace{{0.3cm}}

\\textbf{{\\u3010完整步骤\\u3011}}\\;
\\begin{{enumerate}}
\\item 分析题目，明确已知条件和求解目标
\\item 运用相关知识和方法进行求解
\\item 验证答案的正确性
\\end{{enumerate}}

\\vspace{{0.3cm}}

\\textbf{{\\u3010答案\\u3011}}\\;
略"""

        elif slide_type == 'example_continue':
            # 例题续页：只显示完整步骤、答案、易错提醒
            # 方案B2+B1: 使用换行控制
            return f"""\\textbf{{{title}}}

\\vspace{{0.3cm}}

\\textbf{{\\u3010完整步骤\\u3011}}\\;
\\begin{{enumerate}}
\\item 分析题目，明确已知条件和求解目标
\\item 运用相关知识和方法进行求解
\\item 验证答案的正确性
\\end{{enumerate}}

\\vspace{{0.3cm}}

\\textbf{{\\u3010答案\\u3011}}\\;
略

\\vspace{{0.3cm}}

\\textbf{{\\u3010易错提醒\\u3011}}\\;
解题时要注意细节，避免常见错误。"""

        elif slide_type == 'practice':
            return f"""\\textbf{{练习题}}

\\vspace{{0.3cm}}

{desc}

\\vspace{{0.3cm}}

\\textbf{{提示：}}运用所学知识，仔细分析题目条件，选择合适的方法进行解答。"""

        elif slide_type == 'summary':
            return f"""\\begin{{itemize}}
\\item {title}的核心概念和定义
\\item 主要知识点：{desc}
\\item 重要结论和方法
\\item 需要注意的问题
\\end{{itemize}}

\\vspace{{0.5cm}}

通过本节课的学习，我们应该掌握{title}的基本概念和应用方法，并在实际练习中加以运用。"""

        else:
            return f"\\textbf{{{title}}}\\n\n{desc}"

    def _create_fallback_frames(
        self,
        batch: List[FrameStructure],
        understanding_result: Any
    ) -> List[ContentFrame]:
        """创建回退内容帧（详细版）"""
        frames = []

        kp_dict = {kp.name: kp.content for kp in understanding_result.knowledge_points}

        for fs in batch:
            # 生成详细内容
            main_content = self._generate_fallback_content(fs)

            # 生成详细讲解
            if fs.slide_type == 'title':
                narration = f"同学们好，今天我们要学习的是{fs.frame_title}。通过这节课，希望大家能够掌握相关知识和技能。"
            elif fs.slide_type == 'objectives':
                obj_list = "、".join(understanding_result.objectives[:3])
                narration = f"在学习{fs.frame_title}之前，我们先来了解一下本节课的学习目标。主要包括{obj_list}等方面。"
            elif fs.slide_type == 'concept':
                content = kp_dict.get(fs.frame_title, fs.description)
                narration = f"现在我们来学习{fs.frame_title}。{content}这是非常重要的知识点，大家要仔细理解。"
            elif fs.slide_type == 'example':
                narration = f"让我们通过一个例题来深入理解{fs.frame_title}。请大家先思考一下如何解答，然后再看详细的解题过程。"
            elif fs.slide_type == 'practice':
                narration = f"现在轮到大家练习了。请仔细阅读题目，运用刚才学到的知识来解决这个问题。完成后可以参考答案。"
            elif fs.slide_type == 'summary':
                narration = f"今天我们学习了{fs.frame_title}的相关知识。让我们回顾一下重点内容，加深理解和记忆。"
            else:
                narration = f"让我们来看看{fs.frame_title}。{fs.description}"

            frame = ContentFrame(
                scene_id=fs.scene_id,
                frame_title=fs.frame_title,
                stage=fs.stage,
                slide_type=fs.slide_type,
                main_content=main_content,
                narration=narration,
                key_points=[fs.frame_title, fs.slide_type]
            )
            frames.append(frame)

        return frames
