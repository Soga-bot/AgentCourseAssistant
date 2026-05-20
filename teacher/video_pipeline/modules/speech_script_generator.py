"""
阶段3：语音脚本生成器（Speech Script Generator）

根据分镜数据扩写口语化讲解
根据分镜数据扩写口语化讲解

职责：
1. 接收分镜JSON数据
2. 将narration扩写为详细TTS脚本
3. 确保英文数学符号格式正确
4. 生成每个场景的语音文本
"""

import asyncio
import json
import logging
import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Any
from pathlib import Path

# 使用统一的日志配置
from ..logging_config import get_module_logger
logger = get_module_logger(__name__, "speech_script_generator")


@dataclass
class SpeechScript:
    """单场景语音脚本"""
    scene_id: str
    stage_title: str
    sub_stage: str = ""
    narration: List[str] = field(default_factory=list)
    question: str = ""
    key_points_summary: List[str] = field(default_factory=list)


@dataclass
class SpeechScriptResult:
    """语音脚本生成结果"""
    success: bool
    video_title: str = ""
    total_slides: int = 0
    script_by_scene: Dict[str, SpeechScript] = field(default_factory=dict)
    error: str = ""
    warnings: List[str] = field(default_factory=list)


@dataclass
class NarrationSpec:
    """旁白规格（根据内容复杂度确定）"""
    min_chars: int  # 最少字符数
    max_chars: int  # 最多字符数
    segments: int  # 分几段
    detail_level: str  # 详细程度: simple/medium/complex
    reasoning: str  # 规格说明


class SpeechScriptGenerator:
    """
    语音脚本生成器

    设计原则：
    1. 职责单一：只负责脚本生成
    2. 口语化：使用自然口语，适合TTS
    3. 符号规范：英文数学符号添加空格
    4. 节奏控制：合理控制每段长度
    """

    # 语音脚本生成提示词（完整保留，不精简）
    SPEECH_PROMPT_TEMPLATE = """# 角色
你是顶级教育内容创作者，擅长将结构化大纲转化为生动口语化讲解。

# 核心原则
**自然口语** - 让TTS输出听起来像真实老师讲解，而不是机器朗读。

# 任务
将教学大纲扩写为详细TTS脚本，共 {frame_count} 个场景。

# 输入数据
课程标题：{title}
分镜数据：{video_meta_json}

# 扩写规则

## 1. 严格对应
必须为 {scene_ids} 每个场景生成内容，不能遗漏。

## 2. narration扩写
- **简单帧**（6帧版本的s1-s6）：扩展为2-3段，每段40-70字，步骤更详细
- **扩展帧**（9/12帧版本的sXa/sXb）：聚焦子主题，深度展开
- **必须使用"我们"**作为主语，营造互动感
- **自然口语**，严禁"首先/其次/最后"等机械表达
- **逐步展开**，体现思维过程

## 3. 英文数学符号格式规范（重要，必须执行）
连续的英文大写字母必须在字母之间添加空格，确保TTS正确朗读：

- **角度符号**：∠BAC 必须写为 "∠B A C"（读作 B-A-C，不是 办克）
- **三角形符号**：△ABC 必须写为 "△A B C"
- **圆符号**：⊙O 必须写为 "⊙ O"
- **点标记**：点AB、点CD 必须写为 "点 A B"、"点 C D"
- **连续字母**：任何连续的2-6个英文大写字母都要加空格分隔

示例：
- "连接AB和CD" → "连接 A B 和 C D"
- "在△ABC中，∠BAC=60°" → "在 △A B C 中，∠B A C = 60度"
- "圆O的半径" → "圆 O 的半径"

## 4. question优化
- 只在关键节点提问（如概念引入、步骤转换、检验理解处）
- 多数场景无需提问，保持讲解连贯性
- 提问应该是开放式的，引发思考

## 5. keyPoints重组
- 总结性陈述句，不是要点列表
- 体现该场景的核心收获

## 6. 节奏控制
- 不要每个场景都提问
- 在学生需要思考或检验理解时才提问
- 保持讲解的连贯性和流畅性

# 输出格式（严格JSON）
```json
{{
  "videoTitle": "吸引人标题（<=20字）",
  "totalSlides": {frame_count},
  "scriptByScene": {{
    "{first_scene_id}": {{
      "stageTitle": "复制原stage",
      "subStage": "子阶段名（扩展帧）",
      "narration": ["口语化旁白段1", "口语化旁白段2"],
      "question": "自然口语提问（非必要可为空字符串）",
      "keyPointsSummary": ["总结要点1", "总结要点2"]
    }}
  }}
}}
```

⚠️ 重要：
- narration是数组，包含多段旁白
- question为空字符串时不是null，是""
- keyPointsSummary是总结性陈述，不是要点列表
- 英文数学符号必须添加空格

请生成详细的语音脚本：
"""

    # ========== 内容复杂度分析配置 ==========
    # 复杂度阈值配置
    COMPLEXITY_THRESHOLDS = {
        'simple': {
            'max_score': 5,
            'min_chars': 80,
            'max_chars': 150,
            'segments': 2,
            'description': '简单内容：简洁讲解，突出重点'
        },
        'medium': {
            'max_score': 10,
            'min_chars': 120,
            'max_chars': 250,
            'segments': 3,
            'description': '中等复杂：详细讲解，逐步展开'
        },
        'complex': {
            'max_score': 999,  # 无上限
            'min_chars': 180,
            'max_chars': 400,
            'segments': 4,
            'description': '复杂内容：深度讲解，细致分析'
        }
    }

    def __init__(self, llm_client, max_tokens: int = 4000):
        """
        初始化语音脚本生成器

        Args:
            llm_client: LLM客户端实例
            max_tokens: 最大token数（默认4000）
        """
        self.llm_client = llm_client
        self.max_tokens = max_tokens
        logger.info("[SpeechScriptGenerator] 初始化完成，max_tokens=%d", max_tokens)

    # ========== 内容复杂度分析（任务9：内容详细度自适应）==========

    def _analyze_scene_complexity(self, scene: Dict) -> Dict:
        """
        分析场景内容复杂度

        考虑因素：
        1. 内容长度
        2. 数学公式数量
        3. 步骤/解题过程数量
        4. 列表项数量
        5. 幻灯片类型

        Args:
            scene: 场景数据字典

        Returns:
            复杂度分析结果: {
                'score': int,          # 复杂度分数
                'level': str,          # simple/medium/complex
                'factors': dict,       # 各因素得分
                'reasoning': str       # 分析说明
            }
        """
        content = scene.get("mainContent", "")
        slide_type = scene.get("slideType", "")
        stage = scene.get("stage", "")

        # 初始化复杂度因素
        factors = {
            'content_length': 0,
            'formula_count': 0,
            'step_count': 0,
            'item_count': 0,
            'type_bonus': 0
        }

        # 1. 内容长度得分
        char_count = len(content)
        if char_count > 300:
            factors['content_length'] = 3
        elif char_count > 150:
            factors['content_length'] = 2
        elif char_count > 50:
            factors['content_length'] = 1

        # 2. 数学公式数量
        # 检测LaTeX公式：$...$ 或 \(...\) 或 \[...\]
        formula_patterns = [r'\$[^$]+\$', r'\\\(.*?\\\)', r'\\\[.*?\\\]']
        formula_count = 0
        for pattern in formula_patterns:
            formula_count += len(re.findall(pattern, content))
        factors['formula_count'] = min(formula_count, 3)

        # 3. 步骤/解题过程
        # 检测"步骤"、"解："、"证明"、"因为"、"所以"
        step_keywords = ['步骤', '解：', '证明', '因为', '所以', '第一步', '第二步',
                         '首先', '其次', '最后', '于是', '因此']
        step_count = sum(1 for keyword in step_keywords if keyword in content)
        factors['step_count'] = min(step_count, 3)

        # 4. 列表项数量
        item_count = content.count('\\item')
        factors['item_count'] = min(item_count, 2)

        # 5. 幻灯片类型加成
        # summary, example, practice通常需要更详细的讲解
        type_bonus_map = {
            'summary': 2,
            'example': 2,
            'practice': 1,
            'concept': 1,
            'intro': 0,
            'objectives': 0,
            'title': 0
        }
        factors['type_bonus'] = type_bonus_map.get(slide_type, 0)

        # 计算总分
        total_score = sum(factors.values())

        # 确定复杂度级别
        if total_score <= self.COMPLEXITY_THRESHOLDS['simple']['max_score']:
            level = 'simple'
        elif total_score <= self.COMPLEXITY_THRESHOLDS['medium']['max_score']:
            level = 'medium'
        else:
            level = 'complex'

        # 生成分析说明
        reasoning_parts = []
        if factors['content_length'] > 0:
            reasoning_parts.append(f"内容长度{char_count}字")
        if factors['formula_count'] > 0:
            reasoning_parts.append(f"包含{formula_count}个公式")
        if factors['step_count'] > 0:
            reasoning_parts.append(f"{step_count}个步骤关键词")
        if factors['item_count'] > 0:
            reasoning_parts.append(f"{item_count}个列表项")
        if factors['type_bonus'] > 0:
            reasoning_parts.append(f"类型({slide_type})加成")

        reasoning = f"复杂度{total_score}分({level})：" + "、".join(reasoning_parts) if reasoning_parts else f"简单内容，复杂度{total_score}分"

        logger.debug(f"[SpeechScriptGenerator] 场景{scene.get('sceneID')}复杂度分析: {reasoning}")

        return {
            'score': total_score,
            'level': level,
            'factors': factors,
            'reasoning': reasoning
        }

    def _get_narration_spec_for_scene(self, scene: Dict) -> NarrationSpec:
        """
        根据场景内容获取合适的narration规格

        Args:
            scene: 场景数据字典

        Returns:
            NarrationSpec: 旁白规格
        """
        # 分析复杂度
        complexity = self._analyze_scene_complexity(scene)
        level = complexity['level']

        # 获取对应级别的配置
        config = self.COMPLEXITY_THRESHOLDS[level]

        # 获取slide_type用于微调
        slide_type = scene.get("slideType", "")

        # 特殊类型微调
        min_chars = config['min_chars']
        max_chars = config['max_chars']
        segments = config['segments']

        # summary类型需要更多内容
        if slide_type == 'summary':
            min_chars += 50
            max_chars += 100
            segments += 1

        # title/objectives类型可以少一些
        if slide_type in ['title', 'objectives']:
            min_chars = max(30, min_chars - 30)
            max_chars = max(60, max_chars - 50)
            segments = max(1, segments - 1)

        spec = NarrationSpec(
            min_chars=min_chars,
            max_chars=max_chars,
            segments=segments,
            detail_level=level,
            reasoning=f"{complexity['reasoning']}；建议{segments}段，每段{min_chars}-{max_chars//segments}字"
        )

        logger.info(f"[SpeechScriptGenerator] {scene.get('sceneID')}({slide_type}): {spec.reasoning}")

        return spec

    def _generate_scene_specs_instruction(self, scenes: List[Dict]) -> str:
        """
        生成每个场景的narration规格说明（用于LLM提示词）

        Args:
            scenes: 场景列表

        Returns:
            格式化的规格说明字符串
        """
        lines = ["# 各场景narration规格说明", ""]
        lines.append("根据每个场景的内容复杂度，生成对应详细程度的narration：")
        lines.append("")

        for scene in scenes:
            scene_id = scene.get("sceneID", "s1")
            slide_type = scene.get("slideType", "")
            frame_title = scene.get("frameTitle", "")

            # 获取规格
            spec = self._get_narration_spec_for_scene(scene)

            # 格式化说明
            lines.append(f"**{scene_id} ({slide_type}) - {frame_title}**")
            lines.append(f"- 复杂度级别：{spec.detail_level}")
            lines.append(f"- narration总长度：{spec.min_chars}-{spec.max_chars}字")
            lines.append(f"- 分{spec.segments}段讲解，每段约{spec.min_chars//spec.segments}-{spec.max_chars//spec.segments}字")
            lines.append(f"- 说明：{spec.reasoning}")
            lines.append("")

        lines.append("⚠️ 请严格按照上述规格为每个场景生成narration，确保：")
        lines.append("1. 总长度在指定范围内")
        lines.append("2. 分段数量符合要求")
        lines.append("3. 复杂内容要更详细，简单内容要简洁")
        lines.append("")

        return "\n".join(lines)

    async def generate(
        self,
        title: str,
        storyboard_data: Dict,
        original_content: str = ""
    ) -> SpeechScriptResult:
        """
        生成语音脚本

        Args:
            title: 课程标题
            storyboard_data: 分镜JSON数据
            original_content: 原始课程内容（可选）

        Returns:
            SpeechScriptResult: 语音脚本生成结果
        """
        logger.info("[SpeechScriptGenerator] ========== 开始生成语音脚本 ==========")
        logger.info("[SpeechScriptGenerator] 课程标题: %s", title)

        scenes = storyboard_data.get('scenes', [])
        frame_count = len(scenes)

        if frame_count == 0:
            logger.error("[SpeechScriptGenerator] 分镜数据为空")
            return SpeechScriptResult(
                success=False,
                error="分镜数据为空"
            )

        # 生成scene_id列表
        scene_ids = [s.get('sceneID', f's{i+1}') for i, s in enumerate(scenes)]
        first_scene_id = scene_ids[0] if scene_ids else 's1'

        try:
            from shared.llm_client import LLMRequest

            # 生成各场景narration规格说明（基于内容复杂度）
            scene_specs = self._generate_scene_specs_instruction(scenes)

            # 构建提示词（添加场景规格说明）
            prompt = self.SPEECH_PROMPT_TEMPLATE.format(
                title=title[:50],
                frame_count=frame_count,
                scene_ids=str(scene_ids),
                first_scene_id=first_scene_id,
                video_meta_json=json.dumps(storyboard_data, ensure_ascii=False, indent=2)[:5000]
            )

            # 在扩写规则后添加场景规格说明
            # 在"# 输出格式"之前插入
            prompt = prompt.replace(
                "# 输出格式（严格JSON）",
                f"{scene_specs}\n# 输出格式（严格JSON）"
            )

            request = LLMRequest(
                messages=[{"role": "user", "content": prompt}],
                temperature=0.1,  # 教育讲解需要准确性
                max_tokens=self.max_tokens
            )

            logger.info("[SpeechScriptGenerator] 调用 LLM 生成脚本...")

            response = await self.llm_client.call(request)

            if not response.success:
                logger.error("[SpeechScriptGenerator] LLM 调用失败: %s", response.error)
                return self._create_fallback_result(title, storyboard_data)

            # 解析脚本
            result = self._parse_script_result(response.content, title, frame_count)

            logger.info("[SpeechScriptGenerator] ✓ 脚本生成完成")
            logger.info("[SpeechScriptGenerator]   - 总场景数: %d", len(result.script_by_scene))

            return result

        except Exception as e:
            logger.error("[SpeechScriptGenerator] 生成异常: %s", str(e))
            import traceback
            logger.debug("[SpeechScriptGenerator] 异常堆栈: %s", traceback.format_exc()[:500])
            return self._create_fallback_result(title, storyboard_data)

    def _parse_script_result(self, content: str, title: str, expected_frames: int) -> SpeechScriptResult:
        """解析脚本结果"""
        try:
            # 清理响应
            content = content.strip()
            if content.startswith('```json'):
                content = content.split('```json')[1].split('```')[0]
            elif content.startswith('```'):
                content = content.split('```')[1].split('```')[0]
            content = content.strip()

            # 解析JSON
            data = json.loads(content)

            video_title = data.get('videoTitle', title)
            script_by_scene = {}

            # 解析每个场景的脚本
            for scene_id, script_data in data.get('scriptByScene', {}).items():
                # 获取narration列表并格式化每个元素
                narration_list = script_data.get('narration', [])
                formatted_narration = []

                for narration_text in narration_list:
                    # 对每个narration应用数学符号格式化
                    formatted_text = self._format_math_symbols(narration_text)
                    formatted_narration.append(formatted_text)

                speech_script = SpeechScript(
                    scene_id=scene_id,
                    stage_title=script_data.get('stageTitle', ''),
                    sub_stage=script_data.get('subStage', ''),
                    narration=formatted_narration,
                    question=script_data.get('question', ''),
                    key_points_summary=script_data.get('keyPointsSummary', [])
                )
                script_by_scene[scene_id] = speech_script

            return SpeechScriptResult(
                success=True,
                video_title=video_title,
                total_slides=expected_frames,
                script_by_scene=script_by_scene
            )

        except Exception as e:
            logger.warning("[SpeechScriptGenerator] JSON解析失败: %s", e)
            # 使用回退策略
            return self._create_fallback_result(title, {})

    def _create_fallback_result(self, title: str, storyboard_data: Dict) -> SpeechScriptResult:
        """创建回退脚本结果"""
        logger.warning("[SpeechScriptGenerator] 使用回退策略")

        script_by_scene = {}

        # 从分镜数据直接提取
        scenes = storyboard_data.get('scenes', [])

        for scene in scenes:
            scene_id = scene.get('sceneID', 's1')
            stage = scene.get('stage', 'concept')
            narration = scene.get('narration', '我们来看这帧内容')

            # 应用英文符号格式化
            narration = self._format_math_symbols(narration)

            # 简单分段
            if len(narration) > 100:
                # 按句号分段
                segments = re.split(r'[。！？]', narration)
                segments = [s.strip() + '。' for s in segments if s.strip()]
            else:
                segments = [narration]

            speech_script = SpeechScript(
                scene_id=scene_id,
                stage_title=stage,
                narration=segments,
                question='',
                key_points_summary=[]
            )
            script_by_scene[scene_id] = speech_script

        return SpeechScriptResult(
            success=len(script_by_scene) > 0,
            video_title=title,
            total_slides=len(script_by_scene),
            script_by_scene=script_by_scene,
            warnings=['使用回退策略生成的脚本']
        )

    def _format_math_symbols(self, text: str) -> str:
        """
        格式化数学符号，使其适合TTS朗读

        使用 MathSymbolReader 进行完整处理，包括：
        - 负数：-3 → 负三
        - 省略乘号：2x → 2乘以x
        - 幂运算：x² → x的平方
        - 括号：a(b+1) → a乘以括号b加1括号
        - 绝对值：|x| → x的绝对值
        - 根号：√x → x的算术平方根
        - 角度/三角形符号：∠ABC → 角A B C
        """
        try:
            # 导入 MathSymbolReader
            from shared.math_symbol_reader import MathSymbolReader

            # 使用 MathSymbolReader 进行处理
            processed, rules_applied = MathSymbolReader.process(text)

            # 记录应用了哪些规则（用于调试）
            if rules_applied:
                logger.debug(f"[SpeechScriptGenerator] 应用数学符号规则: {rules_applied}")

            return processed

        except ImportError:
            logger.warning("[SpeechScriptGenerator] 无法导入 MathSymbolReader，使用简化格式化")
            # 回退到原始的简单格式化
            return self._format_math_symbols_simple(text)

    def _format_math_symbols_simple(self, text: str) -> str:
        """简化版数学符号格式化（回退方案）"""
        # 替换角度符号
        text = re.sub(r'∠([A-Z]+)', lambda m: '角' + ' '.join(m.group(1)), text)

        # 替换三角形符号
        text = re.sub(r'△([A-Z]+)', lambda m: '三角形' + ' '.join(m.group(1)), text)

        # 替换度数符号
        text = text.replace('°', '度')

        # 替换连续的英文大写字母
        text = re.sub(r'(?<![角三角形])([A-Z]{2,6})(?=[^A-Z]|$)', lambda m: ' '.join(m.group(1)), text)

        return text

    def save_script_to_file(self, result: SpeechScriptResult, output_path: str) -> bool:
        """保存脚本到文件"""
        try:
            output = Path(output_path)
            output.parent.mkdir(parents=True, exist_ok=True)

            with open(output, 'w', encoding='utf-8') as f:
                f.write(f"# {result.video_title}\n\n")

                for scene_id in sorted(result.script_by_scene.keys()):
                    script = result.script_by_scene[scene_id]
                    f.write(f"## {scene_id}: {script.stage_title}\n")
                    if script.sub_stage:
                        f.write(f"({script.sub_stage})\n")
                    f.write("\n")

                    for i, narration in enumerate(script.narration, 1):
                        f.write(f"{i}. {narration}\n")

                    if script.question:
                        f.write(f"\n提问: {script.question}\n")

                    if script.key_points_summary:
                        f.write(f"\n要点: ")
                        f.write(" ".join(script.key_points_summary))
                        f.write("\n")

                    f.write("\n" + "-" * 50 + "\n\n")

            logger.info("[SpeechScriptGenerator] 脚本已保存: %s", output_path)
            return True

        except Exception as e:
            logger.error("[SpeechScriptGenerator] 保存脚本失败: %s", e)
            return False


# =============================================================================
# 便捷函数
# =============================================================================

async def generate_speech_script(
    llm_client,
    title: str,
    storyboard_data: Dict
) -> SpeechScriptResult:
    """
    生成语音脚本的便捷函数

    Args:
        llm_client: LLM客户端实例
        title: 课程标题
        storyboard_data: 分镜JSON数据

    Returns:
        SpeechScriptResult: 语音脚本生成结果
    """
    generator = SpeechScriptGenerator(llm_client)
    return await generator.generate(title, storyboard_data)
