"""
阶段0：智能难度判断模块（动态帧数版本）

使用 LLM 分析课程内容复杂度，动态计算最佳帧数

职责：
1. 分析课程内容的复杂度
2. 根据知识点数量、内容深度、教学目标直接计算最佳帧数
3. 提供分析理由和建议
4. 支持规则回退（LLM失败时）
"""

import asyncio
import re
import json
import logging
from typing import Dict, List, Optional
from dataclasses import dataclass

# 使用统一的日志配置
from ..logging_config import get_module_logger
logger = get_module_logger(__name__, "difficulty_judge")


@dataclass
class DifficultyAnalysis:
    """难度分析结果（动态帧数版本）"""
    frame_count: int           # 动态计算的帧数（4-15帧）
    confidence: float           # 置信度 0-1
    reasoning: str              # 判断理由
    knowledge_points_count: int # 识别的知识点数量
    estimated_duration: int     # 建议总时长（秒）
    suggested_stages: List[str] # 建议的教学阶段


class IntelligentDifficultyJudge:
    """
    智能难度判断器（动态帧数版本）

    使用 LLM 分析课程内容复杂度，直接计算最佳帧数

    设计原则：
    1. LLM优先：优先使用LLM进行动态计算
    2. 规则回退：LLM失败时使用公式计算
    3. 缓存支持：避免重复分析相同内容
    """

    # 动态帧数计算提示词模板
    DYNAMIC_FRAMES_ANALYSIS_PROMPT = """# 角色
你是课程内容分析专家，擅长评估教学内容的复杂度并计算最佳讲解帧数。

# 核心原则
**教学效果优先** - 根据实际内容量和复杂度计算最合适的帧数，不局限于固定选项。

# 课程内容分析
标题：{title}
内容长度：{content_length} 字符
内容预览：{content_preview}

# 帧数计算公式

## 基础帧数（必选帧）
1. 标题页：1帧
2. 学习目标：1帧
3. 课堂小结：1帧

## 知识点讲解帧（动态）
- 每个独立知识点需要1-2帧
- 复杂知识点可以拆分为2-3帧
- 公式推导或证明需要2-3帧

## 情境导入帧（可选）
- 如果有生活实例或问题引入：1帧
- 如果是直接概念讲解：0帧

## 例题示范帧（动态）
- 有例题时：1-3帧（根据例题数量和复杂度）
- 无例题时：0帧

## 方法总结帧（可选）
- 需要总结解题方法或技巧：1帧
- 无需特殊方法：0帧

# 计算示例

## 示例1：简单概念（4-5帧）
知识点：1个（如"认识函数"）
计算：基础3帧 + 知识点1帧 + 情境0帧 + 例题0帧 + 总结0帧 = 4帧

## 示例2：中等内容（7-9帧）
知识点：2-3个（如"直线、射线、线段的区别"）
计算：基础3帧 + 知识点3帧 + 情境1帧 + 例题1帧 + 总结0帧 = 8帧

## 示例3：复杂内容（10-13帧）
知识点：4-6个（如"三角形全等判定方法"）
计算：基础3帧 + 知识点6帧 + 情境1帧 + 例题2帧 + 总结1帧 = 13帧

# 分析要点

## 1. 知识点数量统计
- 统计内容中包含的核心知识点数量
- 区分：概念、性质、应用应分别计算

## 2. 内容深度评估
- 是否需要详细推导？（需要更多帧）
- 是否需要多个角度讲解？（需要更多帧）
- 是否需要大量示例说明？（需要更多帧）

## 3. 学科特征调整
- **几何课程**：图形分析通常需要额外帧
- **函数课程**：图像和性质展示需要额外帧
- **代数课程**：计算类相对简洁
- **统计课程**：数据解读需要额外帧

## 4. 帧数范围限制
- 最小：4帧（基础3帧 + 1个知识点）
- 最大：15帧（避免视频过长影响学习效果）
- 推荐：5-12帧（最佳学习时长范围）

# 输出格式（严格JSON）
```json
{{
  "knowledge_points_count": 知识点数量（整数）,
  "frame_count": 计算得出的帧数（4-15之间的整数）,
  "frame_breakdown": {{
    "basic_frames": 3,
    "knowledge_frames": 数字,
    "intro_frames": 数字,
    "example_frames": 数字,
    "summary_frames": 数字
  }},
  "confidence": 0.0-1.0,
  "reasoning": "一句话说明帧数计算理由",
  "estimated_duration": 秒数,
  "suggested_stages": ["导入", "新知", "应用", "总结"]
}}
```

⚠️ 重要：
- frame_count必须是4-15之间的整数
- reasoning简要说明计算过程（如"3个知识点+1个例题=7帧"）
- frame_breakdown展示帧数构成
- 确保JSON完整，不要被截断

请分析课程内容并计算最佳帧数：
"""

    def __init__(self, llm_client, max_tokens: int = 2000):
        """
        初始化难度判断器

        Args:
            llm_client: LLM客户端实例
            max_tokens: 最大token数（默认2000）
        """
        self.llm_client = llm_client
        self.max_tokens = max_tokens
        self._cache = {}  # 缓存已分析的内容
        logger.info("[DifficultyJudge] 初始化完成（动态帧数模式），max_tokens=%d", max_tokens)

    def _get_cache_key(self, title: str, content: str) -> str:
        """生成缓存键"""
        normalized = re.sub(r'\s+', '', title + content)[:100]
        return normalized

    async def analyze_difficulty(
        self,
        title: str,
        content: str,
        use_cache: bool = True,
        quick_mode: bool = False
    ) -> DifficultyAnalysis:
        """
        分析课程难度并计算动态帧数

        Args:
            title: 课程标题
            content: 课程内容
            use_cache: 是否使用缓存
            quick_mode: 快速模式（仅用于向后兼容）

        Returns:
            DifficultyAnalysis: 分析结果
        """
        # 检查缓存
        cache_key = self._get_cache_key(title, content)
        if use_cache and cache_key in self._cache:
            logger.info("[DifficultyJudge] 使用缓存的难度结果")
            return self._cache[cache_key]

        # 内容预览（取前800字符，更多上下文有助于准确计算）
        content_preview = content[:800] if len(content) > 800 else content
        if len(content) > 800:
            content_preview += "...（共{}字符）".format(len(content))

        prompt = self.DYNAMIC_FRAMES_ANALYSIS_PROMPT.format(
            title=title[:100],
            content_length=len(content),
            content_preview=content_preview
        )

        try:
            from shared.llm_client import LLMRequest

            request = LLMRequest(
                messages=[{"role": "user", "content": prompt}],
                temperature=0.0,  # 难度判断需要确定性
                max_tokens=self.max_tokens
            )

            logger.info("[DifficultyJudge] 使用 LLM 动态计算帧数...")

            response = await self.llm_client.call(request)

            if not response.success:
                logger.error("[DifficultyJudge] LLM 调用失败: %s", response.error)
                return self._fallback_calculation(title, content)

            # 解析JSON响应
            result = self._parse_json_response(response.content)

            # 缓存结果
            if use_cache:
                self._cache[cache_key] = result

            logger.info("[DifficultyJudge] 分析完成: %d帧", result.frame_count)
            logger.info("[DifficultyJudge]   知识点数: %d", result.knowledge_points_count)
            logger.info("[DifficultyJudge]   理由: %s", result.reasoning)

            return result

        except Exception as e:
            logger.error("[DifficultyJudge] 分析异常: %s", str(e))
            return self._fallback_calculation(title, content)

    def _parse_json_response(self, response: str) -> DifficultyAnalysis:
        """解析JSON响应"""
        try:
            # 清理响应
            response = response.strip()
            if response.startswith("```"):
                response = response.split("```")[1]
                if response.startswith("json"):
                    response = response[4:]

            # 提取JSON
            data = self._extract_json(response)
            if not data:
                return self._create_default_analysis()

            # 解析帧数
            frame_count = data.get("frame_count", 8)
            knowledge_points_count = data.get("knowledge_points_count", 0)

            # 验证帧数范围
            if not isinstance(frame_count, int):
                frame_count = int(frame_count) if str(frame_count).isdigit() else 8

            # 限制帧数在4-15之间
            frame_count = max(4, min(15, frame_count))

            # 解析帧构成
            breakdown = data.get("frame_breakdown", {})
            if not isinstance(breakdown, dict):
                breakdown = {}

            # 构建理由
            reasoning = data.get("reasoning", "")
            if not reasoning:
                # 从breakdown生成理由
                basic = breakdown.get("basic_frames", 3)
                knowledge = breakdown.get("knowledge_frames", frame_count - 3)
                reasoning = f"基础{basic}帧 + 知识点{knowledge}帧 = {frame_count}帧"

            return DifficultyAnalysis(
                frame_count=frame_count,
                confidence=data.get("confidence", 0.8),
                reasoning=reasoning,
                knowledge_points_count=knowledge_points_count,
                estimated_duration=data.get("estimated_duration", frame_count * 15),
                suggested_stages=data.get("suggested_stages", ["导入", "新知", "应用", "总结"])
            )

        except Exception as e:
            logger.warning("[DifficultyJudge] JSON解析失败: %s", e)
            return self._create_default_analysis()

    def _extract_json(self, response: str) -> Optional[Dict]:
        """从内容中提取JSON"""
        try:
            return json.loads(response)
        except json.JSONDecodeError:
            # 尝试提取大括号内容
            match = re.search(r'\{.*\}', response, re.DOTALL)
            if match:
                try:
                    return json.loads(match.group(0))
                except:
                    pass
            return None

    def _create_default_analysis(self) -> DifficultyAnalysis:
        """创建默认分析结果"""
        return DifficultyAnalysis(
            frame_count=8,
            confidence=0.5,
            reasoning="使用默认帧数",
            knowledge_points_count=0,
            estimated_duration=120,
            suggested_stages=["导入", "新知", "应用", "总结"]
        )

    def _fallback_calculation(self, title: str, content: str) -> DifficultyAnalysis:
        """
        回退计算：基于规则公式动态计算帧数

        当 LLM 失败时使用
        """
        logger.info("[DifficultyJudge] 使用规则公式计算帧数")

        # 基础帧数
        basic_frames = 3  # 标题页、学习目标、课堂小结

        # 统计知识点数量（基于段落和标题）
        text = (title + "\n" + content).lower()

        # 知识点标识模式
        knowledge_patterns = [
            r'第.+点|第.+个',  # 第一点、第二个等
            r'[、,，]?\d+[、,，]',  # 1.、2.等
            r'知识点|概念|定义|性质|特点|定理|公式',  # 知识点相关词
        ]

        knowledge_points_count = 0
        for pattern in knowledge_patterns:
            matches = len(re.findall(pattern, text))
            knowledge_points_count += matches

        # 如果没有找到明确的知识点，按段落估算
        if knowledge_points_count == 0:
            paragraphs = [p for p in content.split('\n\n') if p.strip()]
            knowledge_points_count = max(2, min(6, len(paragraphs)))

        # 限制知识点数量范围
        knowledge_points_count = max(1, min(8, knowledge_points_count))

        # 计算知识点讲解帧（每个知识点1-2帧）
        knowledge_frames = knowledge_points_count

        # 判断是否需要情境导入帧
        intro_keywords = ["生活", "实例", "问题", "引入", "情境"]
        intro_frames = 1 if any(kw in text for kw in intro_keywords) else 0

        # 判断是否需要例题示范帧
        example_keywords = ["例题", "示范", "练习", "应用题", "题目"]
        example_frames = 1 if any(kw in text for kw in example_keywords) else 0

        # 判断是否需要方法总结帧
        summary_method_keywords = ["方法", "技巧", "步骤", "注意", "总结"]
        summary_frames = 1 if any(kw in text for kw in summary_method_keywords) and knowledge_points_count >= 3 else 0

        # 计算总帧数
        frame_count = basic_frames + knowledge_frames + intro_frames + example_frames + summary_frames

        # 限制帧数在4-15之间
        frame_count = max(4, min(15, frame_count))

        # 根据内容长度微调
        content_length = len(content)
        if content_length > 3000 and frame_count < 10:
            frame_count = min(15, frame_count + 2)
        elif content_length < 500 and frame_count > 6:
            frame_count = max(4, frame_count - 2)

        # 构建理由
        reasoning_parts = []
        reasoning_parts.append(f"基础{basic_frames}帧")
        if knowledge_frames > 0:
            reasoning_parts.append(f"知识点{knowledge_frames}帧")
        if intro_frames > 0:
            reasoning_parts.append(f"导入{intro_frames}帧")
        if example_frames > 0:
            reasoning_parts.append(f"例题{example_frames}帧")
        if summary_frames > 0:
            reasoning_parts.append(f"总结{summary_frames}帧")
        reasoning = " + ".join(reasoning_parts) + f" = {frame_count}帧"

        return DifficultyAnalysis(
            frame_count=frame_count,
            confidence=0.7,  # 规则计算置信度
            reasoning=reasoning,
            knowledge_points_count=knowledge_points_count,
            estimated_duration=frame_count * 15,
            suggested_stages=self._generate_suggested_stages(frame_count, intro_frames, example_frames)
        )

    def _generate_suggested_stages(self, frame_count: int, intro_frames: int, example_frames: int) -> List[str]:
        """根据帧数构成生成建议的教学阶段"""
        stages = []

        if intro_frames > 0:
            stages.append("导入")

        stages.append("新知")

        if example_frames > 0:
            stages.append("应用")

        stages.append("总结")

        return stages

    def clear_cache(self):
        """清空缓存"""
        self._cache.clear()
        logger.info("[DifficultyJudge] 缓存已清空")


# =============================================================================
# 便捷函数
# =============================================================================

async def analyze_frame_count(
    llm_client,
    title: str,
    content: str
) -> DifficultyAnalysis:
    """
    分析课程并计算最佳帧数的便捷函数

    Args:
        llm_client: LLM客户端实例
        title: 课程标题
        content: 课程内容

    Returns:
        DifficultyAnalysis: 分析结果，包含动态计算的帧数
    """
    judge = IntelligentDifficultyJudge(llm_client)
    return await judge.analyze_difficulty(title, content)
