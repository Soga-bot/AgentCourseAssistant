"""
分镜生成模块（阶段2）

基于结构化内容生成教学分镜
专门负责基于结构化内容生成教学分镜

职责：
1. 基于阶段1的知识点结果设计教学流程
2. 为每个知识点生成详细的分镜帧
3. 确定每帧的slideType和内容
4. 判断是否需要图示
5. 不考虑JSON格式，专注于教学逻辑
"""

import re
import json
import logging
from typing import Dict, List, Optional, Any
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


@dataclass
class StoryboardScene:
    """单帧分镜数据结构"""
    scene_id: str                 # 场景ID（s1, s2, s3...）
    frame_title: str              # 帧标题
    main_content: str             # 主要内容（完整，不省略）
    narration: str                # 旁白讲解
    slide_type: str               # 类型（title/objectives/intro/concept/example/summary/practice）
    needs_diagram: bool = False   # 是否需要图示
    diagram_spec: Dict = field(default_factory=dict)  # 图示规格
    stage: str = ""               # 教学阶段（导入/新知/应用/总结）
    is_extended: bool = False     # 是否为扩展帧


@dataclass
class StoryboardGenerationResult:
    """分镜生成结果"""
    success: bool
    title: str = ""
    total_slides: int = 0
    estimated_duration: str = ""
    teaching_flow: List[str] = field(default_factory=list)
    scenes: List[StoryboardScene] = field(default_factory=list)
    error: str = ""
    validation_warnings: List[str] = field(default_factory=list)


class StoryboardGenerationExpert:
    """
    分镜生成专家

    设计原则：
    1. 职责单一：只负责分镜设计，不处理内容理解
    2. 基于结构化输入：使用阶段1的知识点结果
    3. 教学逻辑：按照教学流程设计帧序列
    4. 内容完整：确保每帧都有实质性内容
    """

    # 分镜生成提示词
    GENERATION_PROMPT = """# 角色
你是课程分镜设计专家，擅长将结构化的课程内容转化为详细的教学视频分镜。

# 任务
基于课程内容分析结果，生成 {target_frames} 帧的教学分镜。

# 输入：课程内容分析结果
{understanding_result}

# 教学流程设计原则

## 标准教学流程（8-9帧版本）
1. **s1 标题页**（title）：课程标题展示
2. **s2 学习目标**（objectives）：展示学习目标
3. **s3 情境导入**（intro）：生活实例或问题引入
4. **s4-s{concept_end} 新知呈现**（concept）：每个知识点1-2帧
5. **例题示范**（example）：1-2帧（如有例题内容）
6. **课堂小结**（summary）：总结回顾

## 简化教学流程（6帧版本）
1. **s1 标题页**（title）
2. **s2 学习目标**（objectives）
3. **s3-s{concept_end} 新知呈现**（concept）：每个知识点1帧
4. **小结**（summary）

## 扩展教学流程（12帧以上版本）
1. **s1 标题页**（title）
2. **s2 学习目标**（objectives）
3. **s3 情境导入**（intro）
4. **s4-s{concept_end} 新知呈现**（concept）：每个知识点1-2帧
5. **例题示范**（example）：2-3帧
6. **方法总结**（practice）：解题方法或技巧
7. **巩固练习**（practice）：练习题
8. **课堂小结**（summary）：总结回顾

# 每帧内容要求

## mainContent（幻灯片内容）
⚠️ **禁止占位符**：
- 禁止：mainContent为"本知识点包含以下内容：基本概念和定义..."
- 禁止：使用"..."、"等"、"之类"省略内容

✅ **完整内容应包含**：
- 概念帧：定义 + 性质 + 特点（用\\begin{{itemize}}...\\end{{itemize}}列表格式）
- 应用帧：实例 + 方法 + 步骤
- 例题帧：题目 + 分析 + 解答
- 总结帧（重要）：必须详细包含：
  1. 知识点回顾：列出所有核心概念、定理、公式（写完整内容）
  2. 运算法则：写出具体的运算规则和方法步骤
  3. 易混点提醒：指出容易混淆的概念和常见错误
  4. 使用\\begin{{itemize}}格式组织，每个要点都要展开详细说明

## narration（旁白讲解）
- 使用"我们"、"同学们"营造互动感
- 口语化讲解，体现思维过程
- 逐步展开，不要跳跃推理
- 长度：每帧50-150字

## slideType（帧类型）
- title：标题页
- objectives：学习目标
- intro：情境导入
- concept：新知呈现（知识点讲解）
- example：例题示范
- practice：巩固练习
- summary：课堂小结

# 图示需求判断

根据course_type和知识点内容判断是否需要图示：

## 几何课程（geometry）
- **需要图示**：涉及图形、角度、位置关系
- **图示类型**：geometry（基本图形）、triangle_aux（带辅助线的三角形）

## 函数课程（function）
- **需要图示**：涉及函数、图像
- **图示类型**：function_plot（函数图像）、function_multi（多函数对比）

## 统计课程（statistics）
- **需要图示**：涉及数据、图表
- **图示类型**：chart（统计图表）、histogram（直方图）

## 代数课程（algebra）
- **一般不需要图示**（除非涉及几何意义）

# 图示规格格式（精简版）
```json
{{
  "type": "图示类型（geometry/function_plot/chart）",
  "title": "图示标题",
  "具体参数根据类型而定": "..."
}}
```

## 常用图示类型及参数

### geometry - 基本几何图形
{{
  "type": "geometry",
  "shape": "triangle",
  "vertices": [[0,0], [4,0], [2,3]],
  "labels": ["A", "B", "C"],
  "title": "三角形ABC"
}}

### function_plot - 函数图像
{{
  "type": "function_plot",
  "function": "x^2",
  "xRange": [-3, 3],
  "yRange": [-1, 10],
  "title": "二次函数图像"
}}

### chart - 统计图表
{{
  "type": "chart",
  "chartType": "bar",
  "data": {{"categories": ["A", "B"], "values": [10, 20]}},
  "title": "统计图"
}}

# 输出格式（严格JSON）
```json
{{
  "title": "课程标题",
  "totalSlides": 帧数,
  "estimatedDuration": "约X分X秒",
  "teachingFlow": ["导入", "新知", "应用", "总结"],
  "scenes": [
    {{
      "sceneID": "s1",
      "frameTitle": "帧标题",
      "mainContent": "完整内容（禁止占位符）",
      "narration": "旁白讲解",
      "slideType": "title",
      "needsDiagram": false,
      "stage": "导入"
    }},
    {{
      "sceneID": "s3",
      "frameTitle": "知识点标题",
      "mainContent": "完整知识点内容（列表格式）",
      "narration": "详细讲解...",
      "slideType": "concept",
      "needsDiagram": true,
      "diagramSpec": {{
        "type": "geometry",
        "shape": "triangle",
        "vertices": [[0,0], [4,0], [2,3]],
        "labels": ["A", "B", "C"],
        "title": "三角形示例"
      }},
      "stage": "新知"
    }}
  ]
}}
```

# ⚠️ 强制要求
1. **每帧mainContent必须完整**：禁止占位符，禁止省略号
2. **narration必须详细**：每帧50-150字的口语化讲解
3. **needsDiagram和diagramSpec匹配**：needsDiagram=true时必须提供有效diagramSpec
4. **slideType准确**：按照教学流程正确标记每帧类型

请基于课程内容分析结果生成详细的分镜：
"""

    def __init__(self, llm_client, max_tokens: int = 8000):
        """
        初始化分镜生成专家

        Args:
            llm_client: LLM客户端实例
            max_tokens: 最大token数（默认8000，确保输出完整）
        """
        self.llm_client = llm_client
        self.max_tokens = max_tokens
        logger.info("[StoryboardGeneration] 初始化完成，max_tokens=%d", max_tokens)

    async def generate(
        self,
        title: str,
        understanding_result: Any,
        original_content: str = ""
    ) -> StoryboardGenerationResult:
        """
        生成分镜

        Args:
            title: 课程标题
            understanding_result: 阶段1的内容理解结果（ContentUnderstandingResult）
            original_content: 原始课程内容（用于验证）

        Returns:
            StoryboardGenerationResult: 分镜生成结果
        """
        logger.info("[StoryboardGeneration] ========== 开始生成分镜 ==========")
        logger.info("[StoryboardGeneration] 课程标题: %s", title)
        logger.info("[StoryboardGeneration] 课程类型: %s", understanding_result.course_type)
        logger.info("[StoryboardGeneration] 知识点数: %d", len(understanding_result.knowledge_points))

        # 确定目标帧数
        target_frames = self._determine_target_frames(understanding_result)
        logger.info("[StoryboardGeneration] 目标帧数: %d", target_frames)

        # 构建理解结果JSON字符串
        understanding_json = self._serialize_understanding_result(understanding_result)

        # 构建提示词
        prompt = self.GENERATION_PROMPT.format(
            understanding_result=understanding_json,
            target_frames=target_frames
        )

        try:
            # 调用LLM生成分镜
            logger.info("[StoryboardGeneration] 调用 LLM 生成分镜...")

            from shared.llm_client import LLMRequest
            request = LLMRequest(
                messages=[{"role": "user", "content": prompt}],
                temperature=0.1,  # 低温度确保稳定
                max_tokens=self.max_tokens
            )

            response = await self.llm_client.call(request)

            if not response.success:
                logger.error("[StoryboardGeneration] LLM 调用失败: %s", response.error)
                return self._create_fallback_result(title, understanding_result, response.error)

            # 解析响应
            storyboard_data = self._parse_json_response(response.content)

            if not storyboard_data:
                logger.error("[StoryboardGeneration] JSON 解析失败")
                logger.debug("[StoryboardGeneration] 原始响应: %s", response.content[:500])
                return self._create_fallback_result(title, understanding_result, "JSON解析失败")

            # 验证分镜质量
            validation = self._validate_storyboard(storyboard_data, understanding_result)

            # 构建结果
            scenes = self._parse_scenes(storyboard_data.get("scenes", []))

            result = StoryboardGenerationResult(
                success=validation["valid"],
                title=storyboard_data.get("title", title),
                total_slides=len(scenes),
                estimated_duration=storyboard_data.get("estimatedDuration", ""),
                teaching_flow=storyboard_data.get("teachingFlow", []),
                scenes=scenes,
                validation_warnings=validation["warnings"]
            )

            logger.info("[StoryboardGeneration] ✓ 分镜生成完成")
            logger.info("[StoryboardGeneration]   - 总帧数: %d", result.total_slides)
            logger.info("[StoryboardGeneration]   - 需要图示: %d 帧", sum(1 for s in scenes if s.needs_diagram))

            if not validation["valid"]:
                logger.warning("[StoryboardGeneration] 验证警告: %s", "; ".join(validation["warnings"]))

            return result

        except Exception as e:
            logger.error("[StoryboardGeneration] 生成异常: %s", str(e))
            import traceback
            logger.debug("[StoryboardGeneration] 异常堆栈: %s", traceback.format_exc()[:500])
            return self._create_fallback_result(title, understanding_result, str(e))

    def _serialize_understanding_result(self, result: Any) -> str:
        """将内容理解结果序列化为JSON字符串"""
        # 将KnowledgePoint对象转为字典
        knowledge_points = []
        for kp in result.knowledge_points:
            kp_dict = {
                "name": kp.name,
                "content": kp.content,
                "category": kp.category,
                "key_theorems": kp.key_theorems,
                "needs_diagram": kp.needs_diagram,
                "diagram_type": kp.diagram_type
            }
            knowledge_points.append(kp_dict)

        understanding_dict = {
            "course_type": result.course_type,
            "objectives": result.objectives,
            "knowledge_points": knowledge_points,
            "teaching_structure": result.teaching_structure
        }

        return json.dumps(understanding_dict, ensure_ascii=False, indent=2)

    def _determine_target_frames(self, understanding_result: Any) -> int:
        """根据知识点数量确定目标帧数"""
        kp_count = len(understanding_result.knowledge_points)

        if kp_count <= 2:
            return 6
        elif kp_count <= 4:
            return 8
        else:
            return min(12, kp_count + 4)

    def _parse_json_response(self, response: str) -> Optional[Dict]:
        """解析JSON响应"""
        try:
            # 尝试直接解析
            return json.loads(response)
        except json.JSONDecodeError:
            # 尝试提取JSON代码块
            match = re.search(r'```json\s*(.*?)\s*```', response, re.DOTALL)
            if match:
                return json.loads(match.group(1))
            # 尝试提取大括号内容
            match = re.search(r'\{.*\}', response, re.DOTALL)
            if match:
                return json.loads(match.group(0))
            return None

    def _parse_scenes(self, scenes_data: List[Dict]) -> List[StoryboardScene]:
        """解析场景数据"""
        scenes = []
        for scene_data in scenes_data:
            scene = StoryboardScene(
                scene_id=scene_data.get("sceneID", ""),
                frame_title=scene_data.get("frameTitle", ""),
                main_content=scene_data.get("mainContent", ""),
                narration=scene_data.get("narration", ""),
                slide_type=scene_data.get("slideType", "concept"),
                needs_diagram=scene_data.get("needsDiagram", False),
                diagram_spec=scene_data.get("diagramSpec", {}),
                stage=scene_data.get("stage", ""),
                is_extended=scene_data.get("isExtended", False)
            )
            scenes.append(scene)
        return scenes

    # ========== 阶段2.1: 内容长度检测 ==========
    def _check_scene_length(self, scene: StoryboardScene) -> dict:
        """
        检查场景内容长度（阶段2.1实现）

        Args:
            scene: 待检测的场景

        Returns:
            检测结果字典: {
                'length': int,           # 内容字符数
                'needs_split': bool,    # 是否需要拆分
                'reason': str,          # 拆分原因
                'metrics': dict         # 详细指标
            }
        """
        content = scene.main_content

        # 基础指标
        char_count = len(content)
        line_count = content.count('\n') + 1
        item_count = content.count('\\item')
        has_itemize = '\\begin{itemize}' in content

        # 配置阈值（可调整）
        THRESHOLD = {
            'max_chars': 800,           # 最大字符数
            'max_lines': 20,            # 最大行数
            'max_items': 5,             # 最大列表项数
        }

        # 判断是否需要拆分
        reasons = []
        needs_split = False

        if char_count > THRESHOLD['max_chars']:
            needs_split = True
            reasons.append(f"内容过长({char_count}字符 > {THRESHOLD['max_chars']}阈值)")

        if line_count > THRESHOLD['max_lines']:
            needs_split = True
            reasons.append(f"行数过多({line_count}行 > {THRESHOLD['max_lines']}阈值)")

        if item_count > THRESHOLD['max_items']:
            needs_split = True
            reasons.append(f"列表项过多({item_count}项 > {THRESHOLD['max_items']}阈值)")

        return {
            'length': char_count,
            'needs_split': needs_split,
            'reason': '; '.join(reasons) if reasons else '',
            'metrics': {
                'char_count': char_count,
                'line_count': line_count,
                'item_count': item_count,
                'has_itemize': has_itemize,
            }
        }

    def _validate_storyboard(
        self,
        storyboard_data: Dict,
        understanding_result: Any
    ) -> Dict[str, Any]:
        """验证分镜质量"""
        warnings = []

        # 检查场景数量
        scenes = storyboard_data.get("scenes", [])
        if len(scenes) == 0:
            warnings.append("未生成任何场景")
            return {"valid": False, "warnings": warnings}

        # 检查占位符
        placeholder_patterns = [
            "本知识点包含以下内容",
            "基本概念和定义",
            "重要性质和特点",
            "应用场景和实例",
            "注意事项和易错点"
        ]

        placeholder_count = 0
        concept_count = 0

        for scene in scenes:
            slide_type = scene.get("slideType", "")
            content = scene.get("mainContent", "")

            if slide_type == "concept":
                concept_count += 1
                if any(pattern in content for pattern in placeholder_patterns):
                    placeholder_count += 1
                    warnings.append(f"场景{scene.get('sceneID')}包含占位符")

        # 检查narration长度
        for scene in scenes:
            narration = scene.get("narration", "")
            if len(narration) < 30:
                warnings.append(f"场景{scene.get('sceneID')}的narration过短")

        # 检查图示配置
        for scene in scenes:
            needs_diagram = scene.get("needsDiagram", False)
            diagram_spec = scene.get("diagramSpec", {})
            if needs_diagram and not diagram_spec:
                warnings.append(f"场景{scene.get('sceneID')}需要图示但diagramSpec为空")

        # 计算占位符比例
        if concept_count > 0:
            placeholder_ratio = placeholder_count / concept_count
            if placeholder_ratio > 0.3:
                warnings.append(f"占位符比例过高: {placeholder_ratio*100:.1f}%")

        return {
            "valid": len(warnings) == 0,
            "warnings": warnings
        }

    # ========== 阶段2.3: 后处理验证和报告 ==========
    def _validate_and_report(self, storyboard: StoryboardGenerationResult) -> dict:
        """
        验证storyboard质量并生成报告（阶段2.3实现）

        此函数只检测，不修改，用于了解当前storyboard的质量状况

        Args:
            storyboard: 待检测的storyboard

        Returns:
            检测报告: {
                'total_scenes': int,
                'oversized_scenes': list,
                'recommendations': list,
                'summary': str
            }
        """
        scenes = storyboard.scenes
        oversized_scenes = []
        recommendations = []

        # 逐个检测场景
        for scene in scenes:
            check_result = self._check_scene_length(scene)

            if check_result['needs_split']:
                oversized_scenes.append({
                    'scene_id': scene.scene_id,
                    'frame_title': scene.frame_title,
                    'length': check_result['length'],
                    'reason': check_result['reason'],
                    'metrics': check_result['metrics']
                })

        # 生成建议
        if oversized_scenes:
            recommendations.append(f"发现{len(oversized_scenes)}个过长的场景，建议拆分")

            for scene_info in oversized_scenes:
                scene_id = scene_info['scene_id']
                length = scene_info['length']
                recommendations.append(f"  - {scene_id}: {length}字符 ({scene_info['reason']})")

        else:
            recommendations.append("所有场景长度都在合理范围内")

        # 生成总结
        summary = (
            f"[Storyboard检测] 总帧数: {len(scenes)}\n"
            f"[Storyboard检测] 过长帧: {len(oversized_scenes)}\n"
        )

        if oversized_scenes:
            summary += f"[Storyboard检测] 建议: {len(oversized_scenes)}个场景需要拆分\n"
            for scene_info in oversized_scenes[:3]:  # 最多显示3个
                summary += f"  - {scene_info['scene_id']}: {scene_info['length']}字符\n"
            if len(oversized_scenes) > 3:
                summary += f"  ... 还有{len(oversized_scenes)-3}个\n"
        else:
            summary += "[Storyboard检测] ✓ 所有帧长度正常，无需拆分\n"

        # 输出日志
        logger.info(summary)
        print(summary)

        return {
            'total_scenes': len(scenes),
            'oversized_scenes': oversized_scenes,
            'recommendations': recommendations,
            'summary': summary
        }

    def _create_fallback_result(
        self,
        title: str,
        understanding_result: Any,
        error: str
    ) -> StoryboardGenerationResult:
        """创建回退分镜"""
        logger.warning("[StoryboardGeneration] 使用回退策略")

        scenes = []
        scene_idx = 1

        # s1 标题页
        scenes.append(StoryboardScene(
            scene_id=f"s{scene_idx}",
            frame_title=title,
            main_content=title,
            narration=f"同学们好，今天我们学习{title}",
            slide_type="title",
            stage="导入"
        ))
        scene_idx += 1

        # s2 学习目标
        if understanding_result.objectives:
            objectives_content = "\\begin{itemize}\n"
            for obj in understanding_result.objectives[:3]:
                objectives_content += f"\\item {obj}\n"
            objectives_content += "\\end{itemize}"

            scenes.append(StoryboardScene(
                scene_id=f"s{scene_idx}",
                frame_title="学习目标",
                main_content=objectives_content,
                narration="让我们看看今天的学习目标",
                slide_type="objectives",
                stage="导入"
            ))
            scene_idx += 1

        # 知识点帧
        for kp in understanding_result.knowledge_points[:6]:
            # 检查是否需要添加图示
            needs_diagram = kp.needs_diagram
            diagram_spec = {}

            if needs_diagram and kp.diagram_type:
                diagram_spec = self._create_default_diagram_spec(kp.diagram_type, kp.name)

            scenes.append(StoryboardScene(
                scene_id=f"s{scene_idx}",
                frame_title=kp.name,
                main_content=kp.content,
                narration=f"我们来看{kp.name}的相关内容",
                slide_type="concept",
                needs_diagram=needs_diagram,
                diagram_spec=diagram_spec,
                stage="新知"
            ))
            scene_idx += 1

        # 总结帧
        scenes.append(StoryboardScene(
            scene_id=f"s{scene_idx}",
            frame_title="课堂小结",
            main_content="本节课我们学习了核心知识点和方法",
            narration="同学们，今天我们一起学习了这些内容",
            slide_type="summary",
            stage="总结"
        ))

        return StoryboardGenerationResult(
            success=False,
            title=title,
            total_slides=len(scenes),
            estimated_duration=f"约{len(scenes)*30}秒",
            teaching_flow=["导入", "新知", "总结"],
            scenes=scenes,
            error=error
        )

    def _create_default_diagram_spec(self, diagram_type: str, title: str) -> Dict:
        """创建默认图示规格"""
        if diagram_type == "geometry":
            return {
                "type": "geometry",
                "shape": "triangle",
                "vertices": [[0, 0], [4, 0], [2, 3]],
                "labels": ["A", "B", "C"],
                "title": title
            }
        elif diagram_type == "function_plot":
            return {
                "type": "function_plot",
                "function": "x^2",
                "xRange": [-3, 3],
                "yRange": [-1, 10],
                "title": title
            }
        elif diagram_type == "chart":
            return {
                "type": "chart",
                "chartType": "bar",
                "data": {"categories": ["A", "B"], "values": [10, 20]},
                "title": title
            }
        else:
            return {}
