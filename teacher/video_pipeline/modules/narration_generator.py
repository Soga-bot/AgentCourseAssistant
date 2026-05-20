"""
语音讲解生成器 - 将书面内容转换为自然口语讲解

核心功能：
1. 将书面数学内容转换为适合语音讲解的口语文本
2. 正确处理数学术语发音（角ABC → 角 A B C）
3. 区分运算符上下文（正负号 vs 加减运算）
4. 保持内容准确性，只改变表达方式

位置：在帧预处理之后、LaTeX生成之前调用
"""

import re
import logging
import asyncio
from typing import List, Dict, Any, Optional
from dataclasses import dataclass

# 导入共享的 LLM 客户端
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))

from shared.llm_client import LLMClient, LLMConfig, LLMRequest, LLMResponse

logger = logging.getLogger(__name__)


@dataclass
class NarrationResult:
    """讲解生成结果"""
    success: bool
    narration: str
    original: str
    frame_id: str
    error: Optional[str] = None


class NarrationGenerator:
    """
    语音讲解生成器

    使用 LLM 将书面内容转换为自然口语讲解
    """

    # 系统提示词 - 强调准确性和数学术语发音规则
    SYSTEM_PROMPT = """你是一位专业的数学课程讲解员。你的任务是将数学课件的书面内容转换为适合语音讲解的自然口语。

## 核心原则

1. **准确性优先**：绝不能改变原意，不能增加或删除任何知识点
2. **自然口语化**：将书面语转为适合朗读的口语，添加自然的过渡词
3. **数学术语正确发音**：严格遵循下方的发音规则

## 数学术语发音规则（必须严格遵守）

### 1. 几何符号
- "∠ABC" → "角 A B C"（字母间必须加空格，读作"角 A B C"）
- "△ABC" → "三角形 A B C"（字母间加空格）
- "AB"（线段）→ "线段 A B"（字母间加空格）
- "AB⊥CD" → "A B 垂直于 C D"
- "AB∥CD" → "A B 平行于 C D"

### 2. 运算符（根据上下文区分）
- **正负号**（表示数的性质）：如 "+5" 或 "-3" 读作 "正五" 或 "负三"
- **加减运算**（表示运算）：如 "3+5" 读作 "3 加 5"，"5-3" 读作 "5 减 3"
- 判断方法：如果符号在数字前面表示正负，如果在两个数之间表示运算

### 3. 分数和除法
- "a/b" 或 "a÷b" → "a 分之 b" 或 "a 除以 b"
- "½" → "二分之一"

### 4. 等式和不等式
- "a=b" → "a 等于 b"
- "a≠b" → "a 不等于 b"
- "a>b" → "a 大于 b"
- "a<b" → "a 小于 b"
- "a≥b" → "a 大于等于 b"
- "a≤b" → "a 小于等于 b"

### 5. 特殊符号
- "x²" → "x 的平方"
- "x³" → "x 的立方"
- "√x" → "根号 x"
- "³√x" → "三次根号 x"
- "π" → "派"（不是"圆周率"）
- "∞" → "无穷大"
- "∴" → "所以"
- "∵" → "因为"

### 6. 字母和变量
- 单个字母变量必须空开读："设 x=5" → "设 x 等于 5"
- 多字母变量逐字母读："解方程 ax+b=0" → "解方程 a x 加 b 等于 0"

### 7. 集合符号
- "∈" → "属于"
- "∉" → "不属于"
- "⊂" → "包含于"
- "∪" → "并集"
- "∩" → "交集"
- "∅" → "空集"

### 8. 其他数学表达
- "f(x)" → "函数 f x" 或 "f 关于 x 的函数"
- "lim" → "极限"
- "∑" → "求和"
- "∫" → "积分"

## 转换示例

输入: "有理数包括正整数、0、负整数。"
输出: "有理数包括正整数、零、和负整数。"

输入: "已知∠ABC=90°，求证△ABC是直角三角形。"
输出: "已知角 A B C 等于九十度，求证三角形 A B C 是直角三角形。"

输入: "计算：(-3)+(+5)-(-2)"
输出: "计算：负三加正五减负二"

输入: "若|x|=5，则x=±5"
输出: "若 x 的绝对值等于五，则 x 等于正负五"

## 输出要求

1. 直接输出转换后的口语文本，不要加任何解释或标记
2. 保持原文的段落结构
3. 保留必要的标点符号（句末的句号、问号等）
4. 数字保持原样，不要转成中文数字（如 "5" 不要转成 "五"，但 "-5" 读作 "负五"）"""

    def __init__(self, llm_config: Optional[LLMConfig] = None):
        """
        初始化讲解生成器

        Args:
            llm_config: LLM 配置，如果为 None 则使用默认配置
        """
        self.llm_config = llm_config or LLMConfig()
        self.llm_client = LLMClient(self.llm_config)

        logger.info("[NarrationGenerator] 初始化完成")
        logger.info(f"[NarrationGenerator]   - LLM 模型: {self.llm_config.model}")

    async def generate_narration(
        self,
        frame_id: str,
        title: str,
        content: str,
        frame_type: str
    ) -> NarrationResult:
        """
        为单个帧生成讲解文本

        Args:
            frame_id: 帧ID
            title: 帧标题
            content: 帧内容
            frame_type: 帧类型

        Returns:
            NarrationResult 对象
        """
        # 构建用户提示
        user_prompt = self._build_user_prompt(title, content, frame_type)

        try:
            # 调用 LLM
            response = await self.llm_client.generate(
                system_prompt=self.SYSTEM_PROMPT,
                user_prompt=user_prompt,
                temperature=0.1,  # 低温度保证稳定性
                max_tokens=2000
            )

            if response.success:
                narration = response.content.strip()

                # 后处理：确保数学术语正确
                narration = self._post_process(narration)

                logger.info(f"[NarrationGenerator] 帧 {frame_id} 讲解生成成功")
                logger.debug(f"[NarrationGenerator]   原文: {content[:50]}...")
                logger.debug(f"[NarrationGenerator]   讲解: {narration[:50]}...")

                return NarrationResult(
                    success=True,
                    narration=narration,
                    original=content,
                    frame_id=frame_id
                )
            else:
                logger.error(f"[NarrationGenerator] 帧 {frame_id} LLM 调用失败: {response.error}")
                # 失败时返回原文的简单处理版本
                fallback = self._fallback_convert(content)
                return NarrationResult(
                    success=False,
                    narration=fallback,
                    original=content,
                    frame_id=frame_id,
                    error=response.error
                )

        except Exception as e:
            logger.error(f"[NarrationGenerator] 帧 {frame_id} 生成异常: {e}")
            fallback = self._fallback_convert(content)
            return NarrationResult(
                success=False,
                narration=fallback,
                original=content,
                frame_id=frame_id,
                error=str(e)
            )

    async def generate_for_frames(
        self,
        frames: List[Any],
        batch_size: int = 5,
        progress_callback: Optional[callable] = None
    ) -> List[Any]:
        """
        为多个帧批量生成讲解

        Args:
            frames: Frame 对象列表
            batch_size: 并发批处理大小
            progress_callback: 进度回调函数 callback(current, total, frame_id)

        Returns:
            更新了 narration_hint 字段的 Frame 列表
        """
        total = len(frames)
        logger.info(f"[NarrationGenerator] 开始为 {total} 帧生成讲解")

        results = []
        for i in range(0, total, batch_size):
            batch = frames[i:i+batch_size]

            # 并发生成
            tasks = [
                self.generate_narration(
                    frame_id=f.id,
                    title=f.title,
                    content=f.content,
                    frame_type=f.frame_type
                )
                for f in batch
            ]

            batch_results = await asyncio.gather(*tasks)

            # 更新帧的 narration_hint
            for frame, result in zip(batch, batch_results):
                frame.narration_hint = result.narration
                results.append(result)

                if progress_callback:
                    progress_callback(i + batch.index(frame) + 1, total, frame.id)

            logger.info(f"[NarrationGenerator] 批次 {i//batch_size + 1} 完成 ({min(i+batch_size, total)}/{total})")

            # 批次间延迟，避免 API 限流
            if i + batch_size < total:
                await asyncio.sleep(1.0)

        success_count = sum(1 for r in results if r.success)
        logger.info(f"[NarrationGenerator] 全部完成: {success_count}/{total} 成功")

        return frames

    def _build_user_prompt(self, title: str, content: str, frame_type: str) -> str:
        """构建用户提示"""
        # 根据帧类型添加上下文
        type_context = {
            "intro": "这是课程的导入部分，用于引起学生兴趣。",
            "objectives": "这是学习目标部分，列出本节课要掌握的内容。",
            "concept": "这是知识点详解，是课程的核心内容。",
            "example_q": "这是例题的题目部分。",
            "example_s": "这是例题的解答步骤。",
            "example_m": "这是例题的方法总结。",
            "warning": "这是易错点提醒，强调容易出错的地方。",
            "practice": "这是随堂练习题。",
            "summary": "这是知识框架总结。",
            "extend": "这是课后拓展内容。"
        }

        context = type_context.get(frame_type, "")

        prompt = f"""请将以下数学课件内容转换为适合语音讲解的口语文本。

## 内容类型
{context}

## 标题
{title}

## 内容
{content}

## 要求
1. 保持内容完整性，不遗漏任何信息
2. 严格遵循数学术语发音规则
3. 输出自然的口语讲解文本"""

        return prompt

    def _post_process(self, narration: str) -> str:
        """
        后处理：确保数学术语正确

        这是一个安全检查，修正 LLM 可能遗漏的规则
        """
        # 确保角符号后的字母有空格
        narration = re.sub(
            r'角([A-Z])([A-Z])([A-Z])',
            r'角 \1 \2 \3',
            narration
        )
        narration = re.sub(
            r'三角形([A-Z])([A-Z])([A-Z])',
            r'三角形 \1 \2 \3',
            narration
        )

        # 清理多余空格
        narration = re.sub(r' +', ' ', narration)

        return narration.strip()

    def _fallback_convert(self, content: str) -> str:
        """
        降级转换：当 LLM 不可用时使用规则转换

        基于规则的简单转换，保证基本可用
        """
        text = content

        # 清理 LaTeX 标记
        text = re.sub(r'\\[a-zA-Z]+\{[^}]*\}', '', text)
        text = re.sub(r'\\[a-zA-Z]+', '', text)
        text = re.sub(r'[{}$\\]', '', text)

        # 基本数学符号转换
        replacements = [
            ('∠', '角 '),
            ('△', '三角形 '),
            ('⊥', ' 垂直于 '),
            ('∥', ' 平行于 '),
            ('≠', ' 不等于 '),
            ('≥', ' 大于等于 '),
            ('≤', ' 小于等于 '),
            ('≈', ' 约等于 '),
            ('∞', ' 无穷大 '),
            ('π', ' 派 '),
            ('√', ' 根号 '),
            ('²', ' 的平方'),
            ('³', ' 的立方'),
            ('°', ' 度'),
            ('∴', ' 所以 '),
            ('∵', ' 因为 '),
            ('÷', ' 除以 '),
            ('×', ' 乘以 '),
        ]

        for old, new in replacements:
            text = text.replace(old, new)

        # 处理等号（确保前后有空格）
        text = re.sub(r'\s*=\s*', ' 等于 ', text)

        # 清理多余空格
        text = re.sub(r' +', ' ', text)

        return text.strip()


# ========== 便捷函数 ==========

async def generate_narrations(
    frames: List[Any],
    llm_config: Optional[LLMConfig] = None,
    progress_callback: Optional[callable] = None
) -> List[Any]:
    """
    为帧列表生成讲解的便捷函数

    Args:
        frames: Frame 对象列表
        llm_config: LLM 配置
        progress_callback: 进度回调

    Returns:
        更新了 narration_hint 的 Frame 列表
    """
    generator = NarrationGenerator(llm_config)
    return await generator.generate_for_frames(frames, progress_callback=progress_callback)
