"""
阶段1C：格式转换专家（Format Converter）

格式转换专家模块
将故事板设计结果转换为标准JSON格式

职责：
1. 接收故事板设计结果
2. 转换为标准JSON格式
3. 确保格式符合下游系统要求
4. 验证JSON结构完整性

更新说明：
- 添加 LLM 辅助转换回退机制
- 改进 JSON 提取方法
- 支持更灵活的数据结构
- 温度设为 0.0 确保稳定输出
"""

import asyncio
import json
import logging
import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Any

# 使用统一的日志配置
from ..logging_config import get_module_logger
logger = get_module_logger(__name__, "format_converter")


@dataclass
class FormatResult:
    """格式转换结果"""
    success: bool
    json_data: Dict = field(default_factory=dict)
    error: str = ""
    validation_warnings: List[str] = field(default_factory=list)


class FormatConverter:
    """
    格式转换专家

    设计原则：
    1. 职责单一：只负责格式转换
    2. 优先直接转换：无需LLM即可转换
    3. LLM辅助：仅在必要时使用
    4. 验证完整性：确保输出符合要求
    """

    # LLM 格式修正提示词（用于辅助转换）
    FORMAT_FIX_PROMPT = """# 角色
你是JSON格式修正专家，负责将非标准格式转换为标准JSON。

# 任务
将提供的帧内容转换为严格符合JSON格式的输出。

# =====================================================================
# 输出格式要求
# =====================================================================

请输出以下JSON结构：

```json
{{
  "title": "视频标题",
  "totalSlides": 帧数,
  "estimatedDuration": "预计秒数",
  "teachingFlow": ["导入", "新知", "应用", "总结"],
  "scenes": [
    {{
      "sceneID": "scene_id",
      "stage": "阶段",
      "subStage": "子阶段",
      "frameTitle": "标题",
      "mainContent": "主要内容",
      "narration": "旁白内容",
      "socraticQuestion": "问题内容",
      "keyPoints": ["要点1", "要点2"],
      "equations": ["公式"],
      "visualActions": ["TYPE:视觉描述"],
      "needsDiagram": false,
      "diagramSpec": {{}},
      "durationHint": 30,
      "isExtended": false
    }}
  ]
}}
```

# 格式要求：
1. sceneID必须使用指定序列: {scene_ids}
2. narration必须包含"我们"
3. socraticQuestion为空字符串时不是null
4. keyPoints/equations/visualActions都是数组
5. durationHint为整数
6. isExtended为布尔值
7. needsDiagram为布尔值
8. diagramSpec为字典对象
9. 所有字符串用双引号
10. 无注释，无markdown标记

# =====================================================================
# 待转换内容
# =====================================================================

{frames_content}

请输出纯JSON（无markdown标记）：
"""

    def __init__(self, llm_client=None):
        """
        初始化格式转换专家

        Args:
            llm_client: LLM客户端实例（可选，用于辅助修正）
        """
        self.llm_client = llm_client
        logger.info("[FormatConverter] 初始化完成")

    async def convert_async(
        self,
        storyboard: Any,
        title: str,
        understanding_result: Any = None
    ) -> FormatResult:
        """
        转换为标准JSON格式（异步版本，支持LLM回退）

        Args:
            storyboard: 故事板设计结果
            title: 课程标题
            understanding_result: 内容理解结果（可选）

        Returns:
            FormatResult: 格式转换结果
        """
        logger.info("[FormatConverter] ========== 开始格式转换 ==========")

        try:
            # 优先使用直接转换（更快更可靠）
            json_data = self._direct_convert(storyboard, title)

            # 验证转换结果
            expected_frames = storyboard.total_frames if hasattr(storyboard, 'total_frames') else len(json_data.get('scenes', []))
            validation = self._validate_json(json_data, expected_frames)

            logger.info("[FormatConverter] ✓ 直接转换成功")
            logger.info("[FormatConverter]   - 总帧数: %d", len(json_data.get('scenes', [])))

            if validation['warnings']:
                logger.warning("[FormatConverter] 验证警告: %s", '; '.join(validation['warnings']))

            return FormatResult(
                success=True,
                json_data=json_data,
                validation_warnings=validation['warnings']
            )

        except Exception as e:
            logger.warning("[FormatConverter] 直接转换失败，尝试LLM辅助: %s", str(e)[:60])
            # 回退到LLM辅助转换
            if self.llm_client:
                return await self._llm_convert(storyboard, title, understanding_result)
            else:
                logger.error("[FormatConverter] 无LLM客户端，转换失败")
                return FormatResult(
                    success=False,
                    error=str(e)
                )

    def convert(
        self,
        storyboard: Any,
        title: str,
        understanding_result: Any = None
    ) -> FormatResult:
        """
        转换为标准JSON格式（同步版本）

        Args:
            storyboard: 故事板设计结果
            title: 课程标题
            understanding_result: 内容理解结果（可选）

        Returns:
            FormatResult: 格式转换结果
        """
        logger.info("[FormatConverter] ========== 开始格式转换 ==========")

        try:
            # 优先使用直接转换（更快更可靠）
            json_data = self._direct_convert(storyboard, title)

            # 验证转换结果
            expected_frames = storyboard.total_frames if hasattr(storyboard, 'total_frames') else len(json_data.get('scenes', []))
            validation = self._validate_json(json_data, expected_frames)

            logger.info("[FormatConverter] ✓ 格式转换完成")
            logger.info("[FormatConverter]   - 总帧数: %d", len(json_data.get('scenes', [])))

            if validation['warnings']:
                logger.warning("[FormatConverter] 验证警告: %s", '; '.join(validation['warnings']))

            return FormatResult(
                success=True,
                json_data=json_data,
                validation_warnings=validation['warnings']
            )

        except Exception as e:
            logger.error("[FormatConverter] 转换失败: %s", str(e))
            return FormatResult(
                success=False,
                error=str(e)
            )

    def _direct_convert(
        self,
        storyboard: Any,
        title: str
    ) -> Dict:
        """直接转换（无LLM）"""

        # 获取帧列表
        if hasattr(storyboard, 'frames'):
            frames = storyboard.frames
            total_frames = storyboard.total_frames
        elif isinstance(storyboard, list):
            frames = storyboard
            total_frames = len(frames)
        else:
            # 可能是旧的StoryboardGenerationResult
            frames = storyboard.scenes if hasattr(storyboard, 'scenes') else []
            total_frames = len(frames)

        # 转换场景
        scenes = []
        for i, frame in enumerate(frames):
            scene = self._convert_frame(frame, i)
            scenes.append(scene)

        # 计算总时长
        total_duration = sum(s.get('durationHint', 30) for s in scenes)

        return {
            'title': title,
            'totalSlides': total_frames,
            'estimatedDuration': f'{total_duration}秒',
            'teachingFlow': ['导入', '新知', '应用', '总结'],
            'scenes': scenes
        }

    def _convert_frame(self, frame: Any, index: int) -> Dict:
        """转换单帧"""
        # 支持多种数据结构
        if hasattr(frame, 'scene_id'):
            # StoryboardFrame
            scene_id = frame.scene_id
            stage = frame.stage
            sub_stage = frame.sub_stage if hasattr(frame, 'sub_stage') else ''
            frame_title = frame.frame_title
            main_content = frame.main_content if hasattr(frame, 'main_content') else ''
            narration = frame.narration
            key_points = frame.key_points if hasattr(frame, 'key_points') else []
            visual_actions = frame.visual_actions if hasattr(frame, 'visual_actions') else []
            needs_diagram = frame.needs_diagram if hasattr(frame, 'needs_diagram') else False
            diagram_spec = frame.diagram_spec if hasattr(frame, 'diagram_spec') else {}
            is_extended = frame.is_extended if hasattr(frame, 'is_extended') else False
        elif hasattr(frame, 'sceneID'):
            # 可能是StoryboardScene（旧格式）
            scene_id = frame.sceneID
            stage = frame.slide_type
            sub_stage = ''
            frame_title = frame.frame_title
            main_content = frame.main_content
            narration = frame.narration
            key_points = []
            visual_actions = []
            needs_diagram = frame.needs_diagram
            diagram_spec = frame.diagram_spec
            is_extended = frame.is_extended if hasattr(frame, 'is_extended') else False
        elif isinstance(frame, dict):
            # 字典格式
            scene_id = frame.get('scene_id', frame.get('sceneID', f's{index + 1}'))
            stage = frame.get('stage', frame.get('slide_type', 'concept'))
            sub_stage = frame.get('sub_stage', frame.get('subStage', ''))
            frame_title = frame.get('frame_title', frame.get('frameTitle', f'帧{index + 1}'))
            main_content = frame.get('main_content', frame.get('mainContent', ''))
            narration = frame.get('narration', '')
            key_points = frame.get('key_points', frame.get('keyPoints', []))
            visual_actions = frame.get('visual_actions', frame.get('visualActions', []))
            needs_diagram = frame.get('needs_diagram', frame.get('needsDiagram', False))
            diagram_spec = frame.get('diagram_spec', frame.get('diagramSpec', {}))
            is_extended = frame.get('is_extended', frame.get('isExtended', False))
        else:
            # 默认值
            scene_id = f's{index + 1}'
            stage = 'concept'
            sub_stage = ''
            frame_title = f'帧{index + 1}'
            main_content = ''
            narration = ''
            key_points = []
            visual_actions = []
            needs_diagram = False
            diagram_spec = {}
            is_extended = False

        # 确保narration包含"我们"
        if narration and "我们" not in narration and "咱" not in narration:
            narration = "我们" + narration

        # 映射slideType
        slide_type = self._map_slide_type(stage)

        return {
            'sceneID': scene_id,
            'stage': slide_type,
            'subStage': sub_stage,
            'frameTitle': frame_title,
            'mainContent': main_content,
            'narration': narration,
            'socraticQuestion': '',
            'keyPoints': key_points if isinstance(key_points, list) else [],
            'equations': [],
            'visualActions': visual_actions if isinstance(visual_actions, list) else [],
            'needsDiagram': needs_diagram,
            'diagramSpec': diagram_spec if isinstance(diagram_spec, dict) else {},
            'durationHint': 30,
            'isExtended': is_extended
        }

    def _map_slide_type(self, stage: str) -> str:
        """映射slideType到标准格式"""
        stage_lower = stage.lower()

        # 标准映射
        type_mapping = {
            'title': 'title',
            'objectives': 'objectives',
            'objective': 'objectives',
            'intro': 'intro',
            'introduction': 'intro',
            'concept': 'concept',
            'concepts': 'concept',
            'example': 'example',
            'practice': 'practice',
            'summary': 'summary',
            'conclusion': 'summary'
        }

        return type_mapping.get(stage_lower, 'concept')

    async def _llm_convert(
        self,
        storyboard: Any,
        title: str,
        understanding_result: Any = None
    ) -> FormatResult:
        """
        使用LLM辅助转换（回退机制）

        温度设为 0.0 确保稳定输出
        """
        try:
            # 获取帧列表
            if hasattr(storyboard, 'frames'):
                frames = storyboard.frames
                total_frames = storyboard.total_frames
            elif isinstance(storyboard, list):
                frames = storyboard
                total_frames = len(frames)
            else:
                frames = storyboard.scenes if hasattr(storyboard, 'scenes') else []
                total_frames = len(frames)

            # 生成 scene_id 序列
            scene_ids = [f"s{i+1}" for i in range(total_frames)]

            # 构建帧内容描述
            frames_text = ""
            for i, frame in enumerate(frames):
                # 提取帧信息
                if hasattr(frame, 'scene_id'):
                    scene_id = frame.scene_id
                    stage = frame.stage
                    sub_stage = getattr(frame, 'sub_stage', '')
                    frame_title = frame.frame_title
                    main_content = getattr(frame, 'main_content', '')
                    narration = frame.narration
                    key_points = getattr(frame, 'key_points', [])
                    visual_actions = getattr(frame, 'visual_actions', [])
                elif hasattr(frame, 'sceneID'):
                    scene_id = frame.sceneID
                    stage = frame.slide_type
                    sub_stage = ''
                    frame_title = frame.frame_title
                    main_content = frame.main_content
                    narration = frame.narration
                    key_points = []
                    visual_actions = []
                elif isinstance(frame, dict):
                    scene_id = frame.get('scene_id', frame.get('sceneID', f's{i+1}'))
                    stage = frame.get('stage', frame.get('slide_type', 'concept'))
                    sub_stage = frame.get('sub_stage', frame.get('subStage', ''))
                    frame_title = frame.get('frame_title', frame.get('frameTitle', f'帧{i+1}'))
                    main_content = frame.get('main_content', frame.get('mainContent', ''))
                    narration = frame.get('narration', '')
                    key_points = frame.get('key_points', frame.get('keyPoints', []))
                    visual_actions = frame.get('visual_actions', frame.get('visualActions', []))
                else:
                    continue

                frames_text += f"""
帧{i + 1} (sceneID: {scene_ids[i] if i < len(scene_ids) else f's{i+1}'}):
- 阶段: {stage}
- 子阶段: {sub_stage}
- 标题: {frame_title}
- 内容: {main_content[:100] if main_content else '无'}
- 旁白: {narration[:100] if narration else '无'}
- 要点: {' | '.join(key_points[:3]) if key_points else '无'}
- 视觉: {' | '.join(visual_actions[:2]) if visual_actions else '无'}
"""

            # 构建提示词
            prompt = self.FORMAT_FIX_PROMPT.format(
                scene_ids=str(scene_ids),
                frames_content=frames_text[:8000]  # 限制长度
            )

            # 调用 LLM（温度 0.0 确保稳定输出）
            from shared.llm_client import LLMRequest
            request = LLMRequest(
                messages=[{"role": "user", "content": prompt}],
                temperature=0.0,  # 温度 0.0 确保稳定输出
                max_tokens=16000
            )

            response = await self.llm_client.call(request)

            if not response.success:
                logger.error("[FormatConverter] LLM辅助转换失败: %s", response.error)
                # 最后回退到直接转换
                json_data = self._direct_convert(storyboard, title)
                return FormatResult(success=True, json_data=json_data)

            # 提取 JSON
            json_data = self._extract_json(response.content)

            if json_data:
                logger.info("[FormatConverter] ✓ LLM辅助转换成功")
                return FormatResult(success=True, json_data=json_data)
            else:
                logger.warning("[FormatConverter] LLM输出无法解析为JSON，回退到直接转换")
                json_data = self._direct_convert(storyboard, title)
                return FormatResult(success=True, json_data=json_data)

        except Exception as e:
            logger.error("[FormatConverter] LLM辅助转换异常: %s", str(e))
            # 最终回退到直接转换
            try:
                json_data = self._direct_convert(storyboard, title)
                return FormatResult(success=True, json_data=json_data)
            except Exception as e2:
                return FormatResult(success=False, error=f"LLM转换失败: {str(e)}, 直接转换也失败: {str(e2)}")

    def _extract_json(self, content: str) -> Optional[Dict]:
        """
        从内容中提取JSON

        支持多种格式：
        - 纯 JSON
        - ```json ... ``` 代码块
        - ``` ... ``` 代码块
        - 混合文本中的 JSON 对象
        """
        if not content:
            return None

        # 移除 markdown 标记
        content = content.strip()
        if content.startswith('```json'):
            content = content[7:]
        if content.startswith('```'):
            content = content[3:]
        if content.endswith('```'):
            content = content[:-3]
        content = content.strip()

        # 尝试直接解析
        try:
            return json.loads(content)
        except json.JSONDecodeError:
            pass

        # 尝试从混合文本中提取 JSON 对象
        start = content.find('{')
        end = content.rfind('}')
        if start >= 0 and end > start:
            try:
                return json.loads(content[start:end + 1])
            except json.JSONDecodeError:
                pass

        # 尝试提取数组
        start = content.find('[')
        end = content.rfind(']')
        if start >= 0 and end > start:
            try:
                return json.loads(content[start:end + 1])
            except json.JSONDecodeError:
                pass

        logger.warning("[FormatConverter] 无法从内容中提取有效JSON")
        return None

    def _validate_json(self, json_data: Dict, expected_frames: int) -> Dict:
        """验证JSON结构完整性"""
        warnings = []

        # 检查必需字段
        required_fields = ['title', 'totalSlides', 'scenes']
        for field in required_fields:
            if field not in json_data:
                warnings.append(f"缺少必需字段: {field}")

        # 检查场景数量
        scenes = json_data.get('scenes', [])
        if len(scenes) == 0:
            warnings.append("未生成任何场景")
        elif len(scenes) != expected_frames:
            warnings.append(f"场景数量不匹配: 预期{expected_frames}, 实际{len(scenes)}")

        # 检查每个场景的必需字段
        for i, scene in enumerate(scenes):
            if not isinstance(scene, dict):
                warnings.append(f"场景{i+1}不是字典类型")
                continue

            required_scene_fields = ['sceneID', 'frameTitle', 'mainContent', 'narration']
            for field in required_scene_fields:
                if field not in scene:
                    warnings.append(f"场景{i+1}缺少字段: {field}")

            # 检查内容完整性
            if scene.get('mainContent') and len(scene.get('mainContent', '')) < 10:
                warnings.append(f"场景{scene.get('sceneID', i+1)}的mainContent过短")

            if scene.get('narration') and len(scene.get('narration', '')) < 10:
                warnings.append(f"场景{scene.get('sceneID', i+1)}的narration过短")

            # 检查图示配置
            if scene.get('needsDiagram') and not scene.get('diagramSpec'):
                warnings.append(f"场景{scene.get('sceneID', i+1)}需要图示但diagramSpec为空")

        return {
            'valid': len(warnings) == 0,
            'warnings': warnings
        }


# =============================================================================
# 便捷函数
# =============================================================================

def convert_to_json(
    storyboard: Any,
    title: str,
    understanding_result: Any = None
) -> Dict:
    """
    转换为JSON格式的便捷函数（同步版本）

    Args:
        storyboard: 故事板设计结果
        title: 课程标题
        understanding_result: 内容理解结果（可选）

    Returns:
        Dict: JSON数据
    """
    converter = FormatConverter()
    result = converter.convert(storyboard, title, understanding_result)

    if result.success:
        return result.json_data
    else:
        # 返回默认格式
        return {
            'title': title,
            'totalSlides': 0,
            'estimatedDuration': '0秒',
            'teachingFlow': [],
            'scenes': []
        }


async def convert_to_json_async(
    storyboard: Any,
    title: str,
    understanding_result: Any = None,
    llm_client=None
) -> Dict:
    """
    转换为JSON格式的便捷函数（异步版本，支持LLM回退）

    Args:
        storyboard: 故事板设计结果
        title: 课程标题
        understanding_result: 内容理解结果（可选）
        llm_client: LLM客户端实例（用于辅助修正）

    Returns:
        Dict: JSON数据
    """
    converter = FormatConverter(llm_client=llm_client)
    result = await converter.convert_async(storyboard, title, understanding_result)

    if result.success:
        return result.json_data
    else:
        # 返回默认格式
        return {
            'title': title,
            'totalSlides': 0,
            'estimatedDuration': '0秒',
            'teachingFlow': [],
            'scenes': []
        }
