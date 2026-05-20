"""
课程内容理解模块（阶段1）

课程内容结构化理解与知识点提取
专门负责课程内容的结构化理解和知识点提取

职责：
1. 理解课程内容的整体结构
2. 提取核心知识点列表
3. 分析知识点之间的逻辑关系
4. 识别课程类型（几何/代数/函数/统计等）
5. 不考虑分镜格式，专注于内容理解
"""

import re
import json
import logging
from typing import Dict, List, Optional, Any
from dataclasses import dataclass, field

# 使用统一的日志配置
from ..logging_config import get_module_logger
logger = get_module_logger(__name__, "content_understanding")


@dataclass
class KnowledgePoint:
    """知识点数据结构"""
    name: str                    # 知识点名称（如"直线、射线、线段的区别"）
    content: str                 # 详细内容（完整保留，不省略）
    category: str = ""           # 类别（概念/性质/应用/例题）
    key_theorems: List[str] = field(default_factory=list)  # 涉及的定理/公式
    needs_diagram: bool = False  # 是否需要图示
    diagram_type: str = ""       # 图示类型（如geometry, function_plot）


@dataclass
class ContentUnderstandingResult:
    """内容理解结果"""
    success: bool
    course_type: str = ""         # 课程类型（geometry/algebra/function/statistics/general）
    objectives: List[str] = field(default_factory=list)      # 学习目标
    knowledge_points: List[KnowledgePoint] = field(default_factory=list)  # 知识点列表
    teaching_structure: Dict = field(default_factory=dict)     # 教学结构建议
    error: str = ""
    raw_content: str = ""          # 原始内容（用于验证完整性）
    compression_ratio: float = 1.0  # 压缩比（原始/结构化）


class ContentUnderstandingExpert:
    """
    课程内容理解专家

    设计原则：
    1. 职责单一：只负责内容理解，不关心分镜格式
    2. 输出结构化：提取的知识点可直接用于分镜生成
    3. 内容完整：确保所有重要信息不被遗漏
    4. 类型感知：根据课程类型采用不同的理解策略
    """

    # 课程内容理解提示词
    UNDERSTANDING_PROMPT = """# 角色
你是课程内容分析专家，专门负责理解和结构化课程内容。

# 核心原则
**内容完整性优先** - 确保所有知识点都被提取，不得遗漏或省略。

# 课程类型识别
根据内容特征识别课程类型：
- **几何课程**：涉及图形、角度、线段、三角形、圆等几何概念
- **代数课程**：涉及方程、不等式、因式分解、整式运算等
- **函数课程**：涉及函数、图像、性质、解析式等
- **统计课程**：涉及数据、图表、概率、统计量等
- **通用课程**：跨学科或综合性内容

# 任务分析要求

## 1. 学习目标提取
- 从课程内容中识别明确的学习目标
- 如果内容中未明确说明，根据知识点推断合理的学习目标
- 目标应该是具体可测的（如"理解XXX的概念"而非"学习XXX"）

## 2. 知识点提取原则
- **完整性**：每个知识点必须包含完整的定义、性质、应用
- **独立性**：知识点之间界限清晰，避免重复
- **层次性**：按照逻辑顺序排列（从基础到应用）
- **可讲授性**：每个知识点可以独立成为一帧或一组帧的内容

## 3. 知识点内容要求

⚠️ **绝对禁止（违规将导致重新生成）**：
- 禁止使用"..."表示省略
- 禁止用"等"、"之类"、"等等"、"省略"代替具体内容
- 禁止用"包括..."、"如..."等不完整表述
- 每个knowledge_point的content字段必须完整详细

✅ **完整内容应包含（必须全部展开）**：
- 概念/定义（是什么）- 必须完整表述，不能只写"...的定义"
- 性质/特点（有什么特点）- 列出所有主要性质，不能用"...等性质"
- 应用/实例（如何应用）- 给出具体例子，不能用"...等实例"
- 注意事项/易错点（需要注意什么）- 列出关键注意点

⚠️ **最低字数要求**：
- 每个知识点content字段至少80字
- 如果内容不足80字，说明信息不完整，需要补充

## 4. 图示需求判断
根据知识点特征判断是否需要图示：
- **几何课程**：涉及图形、角度、位置关系时需要geometry类型图示
- **函数课程**：涉及函数、图像时需要function_plot类型图示
- **统计课程**：涉及数据、图表时需要chart/histogram类型图示
- **代数课程**：一般不需要图示，除非涉及几何意义

# 输出格式（严格JSON）

```json
{{
  "course_type": "课程类型（geometry/algebra/function/statistics/general）",
  "objectives": [
    "学习目标1",
    "学习目标2",
    "学习目标3"
  ],
  "knowledge_points": [
    {{
      "name": "知识点名称（简短明确，如'直线、射线、线段的定义'）",
      "content": "完整详细的知识点内容（禁止用...省略，必须包含定义、性质、应用等完整信息）",
      "category": "类别（concept性质/application应用/example例题/summary总结）",
      "key_theorems": ["涉及的定理1", "涉及的定理2"],
      "needs_diagram": true/false,
      "diagram_type": "图示类型（如geometry、function_plot、chart，如果不需要则为空字符串）"
    }}
  ],
  "teaching_structure": {{
    "suggested_frames": "建议帧数（如6-9帧）",
    "flow_sequence": ["导入", "概念1", "概念2", "应用", "总结"],
    "key_transitions": ["从概念1到概念2的过渡方式", "从概念到应用的过渡方式"]
  }}
}}
```

# ⚠️ 强制要求
1. **content字段必须完整**：禁止用"..."、"等"、"之类"省略内容
2. **知识点数量适中**：建议3-6个知识点，每个知识点内容详细
3. **图示类型准确**：根据course_type选择合适的图示类型
4. **逻辑顺序正确**：知识点应按照教学逻辑排列（从基础到应用）

# 当前任务
课程标题：{title}
课程内容（{content_length}字符）：
{content}

请分析课程内容并输出结构化信息：
"""

    def __init__(self, llm_client, max_tokens: int = 16000):
        """
        初始化内容理解专家

        Args:
            llm_client: LLM客户端实例
            max_tokens: 最大token数（默认16000，确保输出完整）
        """
        self.llm_client = llm_client
        self.max_tokens = max_tokens
        logger.info("[ContentUnderstanding] 初始化完成，max_tokens=%d", max_tokens)

    async def understand(
        self,
        title: str,
        content: str,
        force_course_type: Optional[str] = None
    ) -> ContentUnderstandingResult:
        """
        理解课程内容

        Args:
            title: 课程标题
            content: 课程内容（完整内容，不截断）
            force_course_type: 强制指定课程类型（可选）

        Returns:
            ContentUnderstandingResult: 内容理解结果
        """
        logger.info("[ContentUnderstanding] ========== 开始分析课程内容 ==========")
        logger.info("[ContentUnderstanding] 课程标题: %s", title)
        logger.info("[ContentUnderstanding] 内容长度: %d 字符", len(content))

        # 如果内容很短，可以直接使用
        if len(content) <= 1000:
            logger.info("[ContentUnderstanding] 内容较短，直接使用原始内容")
            return self._create_simple_result(title, content, force_course_type)

        # 构建提示词
        prompt = self.UNDERSTANDING_PROMPT.format(
            title=title,
            content=content,
            content_length=len(content)
        )

        try:
            # 调用LLM进行内容理解
            logger.info("[ContentUnderstanding] 调用 LLM 进行内容分析...")

            from shared.llm_client import LLMRequest
            request = LLMRequest(
                messages=[{"role": "user", "content": prompt}],
                temperature=0.0,  # 低温度确保稳定
                max_tokens=self.max_tokens
            )

            response = await self.llm_client.call(request)

            if not response.success:
                logger.error("[ContentUnderstanding] LLM 调用失败: %s", response.error)
                return self._create_fallback_result(title, content, response.error)

            # 解析响应
            result_data = self._parse_json_response(response.content)

            if not result_data:
                logger.error("[ContentUnderstanding] JSON 解析失败")
                logger.debug("[ContentUnderstanding] 原始响应: %s", response.content[:500])
                return self._create_fallback_result(title, content, "JSON解析失败")

            # 验证完整性
            validation = self._validate_understanding(result_data, title, content)
            if not validation["valid"]:
                logger.warning("[ContentUnderstanding] 验证警告: %s", validation["warnings"])
                # 检测省略标记问题，强制重新生成
                invalid_kps = self._find_ellipsis_knowledge_points(result_data.get("knowledge_points", []))
                if invalid_kps:
                    logger.warning("[ContentUnderstanding] 检测到%d个知识点包含省略标记，强制重新生成", len(invalid_kps))
                    result_data = await self._regenerate_knowledge_points(
                        result_data, invalid_kps, title, content
                    )

            # 构建结果
            result = ContentUnderstandingResult(
                success=True,
                course_type=result_data.get("course_type", force_course_type or "general"),
                objectives=result_data.get("objectives", []),
                knowledge_points=self._parse_knowledge_points(result_data.get("knowledge_points", [])),
                teaching_structure=result_data.get("teaching_structure", {}),
                raw_content=content,
                compression_ratio=len(content) / len(response.content)
            )

            logger.info("[ContentUnderstanding] ✓ 分析完成")
            logger.info("[ContentUnderstanding]   - 课程类型: %s", result.course_type)
            logger.info("[ContentUnderstanding]   - 学习目标: %d 个", len(result.objectives))
            logger.info("[ContentUnderstanding]   - 知识点: %d 个", len(result.knowledge_points))
            logger.info("[ContentUnderstanding]   - 压缩比: %.2f", result.compression_ratio)

            return result

        except Exception as e:
            logger.error("[ContentUnderstanding] 分析异常: %s", str(e))
            import traceback
            logger.debug("[ContentUnderstanding] 异常堆栈: %s", traceback.format_exc()[:500])
            return self._create_fallback_result(title, content, str(e))

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

    def _parse_knowledge_points(self, points_data: List[Dict]) -> List[KnowledgePoint]:
        """解析知识点数据"""
        knowledge_points = []
        for point_data in points_data:
            kp = KnowledgePoint(
                name=point_data.get("name", ""),
                content=point_data.get("content", ""),
                category=point_data.get("category", "concept"),
                key_theorems=point_data.get("key_theorems", []),
                needs_diagram=point_data.get("needs_diagram", False),
                diagram_type=point_data.get("diagram_type", "")
            )
            knowledge_points.append(kp)
        return knowledge_points

    def _validate_understanding(
        self,
        result_data: Dict,
        title: str,
        original_content: str
    ) -> Dict[str, Any]:
        """验证内容理解结果的完整性"""
        warnings = []

        # 检查知识点数量
        knowledge_points = result_data.get("knowledge_points", [])
        if len(knowledge_points) == 0:
            warnings.append("未提取到任何知识点")
        elif len(knowledge_points) < 2:
            warnings.append("知识点数量过少，可能内容不完整")

        # 检查是否有省略标记
        for kp in knowledge_points:
            content = kp.get("content", "")
            if "..." in content or "等" in content or "之类" in content:
                warnings.append(f"知识点'{kp.get('name', '')}'包含省略标记")

        # 检查内容长度比例
        total_content_length = sum(len(kp.get("content", "")) for kp in knowledge_points)
        if total_content_length < len(original_content) * 0.3:
            warnings.append("提取的内容长度过短，可能信息丢失")

        return {
            "valid": len(warnings) == 0,
            "warnings": "; ".join(warnings)
        }

    def _create_simple_result(
        self,
        title: str,
        content: str,
        force_course_type: Optional[str]
    ) -> ContentUnderstandingResult:
        """为短内容创建简单结果"""
        # 简单的课程类型推断
        course_type = force_course_type or self._infer_course_type(title, content)

        # 简单的知识点提取
        knowledge_point = KnowledgePoint(
            name=title,
            content=content,
            category="concept",
            needs_diagram=self._should_add_diagram(course_type, content)
        )

        return ContentUnderstandingResult(
            success=True,
            course_type=course_type,
            objectives=["理解" + title],
            knowledge_points=[knowledge_point],
            teaching_structure={"suggested_frames": "3-4帧"},
            raw_content=content
        )

    def _create_fallback_result(
        self,
        title: str,
        content: str,
        error: str
    ) -> ContentUnderstandingResult:
        """创建回退结果"""
        logger.warning("[ContentUnderstanding] 使用回退策略")

        # 按段落分割内容作为知识点
        paragraphs = [p.strip() for p in content.split('\n\n') if p.strip()]
        knowledge_points = []

        for i, para in enumerate(paragraphs[:6]):  # 最多6个知识点
            kp = KnowledgePoint(
                name=f"知识点{i+1}",
                content=para,
                category="concept"
            )
            knowledge_points.append(kp)

        return ContentUnderstandingResult(
            success=False,
            course_type="general",
            objectives=["理解课程核心内容"],
            knowledge_points=knowledge_points,
            teaching_structure={"suggested_frames": str(len(knowledge_points) + 2) + "帧"},
            error=error,
            raw_content=content
        )

    def _infer_course_type(self, title: str, content: str) -> str:
        """推断课程类型"""
        text = (title + " " + content).lower()

        # 几何关键词
        geometry_keywords = ["角", "三角形", "圆", "直线", "射线", "线段", "垂直", "平行",
                          "全等", "相似", "对称", "旋转", "平移", "几何"]
        # 函数关键词
        function_keywords = ["函数", "图像", "坐标", "定义域", "值域", "单调", "奇偶",
                          "二次函数", "一次函数", "反比例"]
        # 统计关键词
        statistics_keywords = ["数据", "平均", "中位数", "众数", "方差", "概率", "统计",
                             "图表", "抽样", "分布"]
        # 代数关键词
        algebra_keywords = ["方程", "不等式", "因式分解", "整式", "分式", "根式", "运算"]

        if any(kw in text for kw in geometry_keywords):
            return "geometry"
        elif any(kw in text for kw in function_keywords):
            return "function"
        elif any(kw in text for kw in statistics_keywords):
            return "statistics"
        elif any(kw in text for kw in algebra_keywords):
            return "algebra"
        else:
            return "general"

    def _should_add_diagram(self, course_type: str, content: str) -> bool:
        """判断是否需要图示"""
        if course_type in ["geometry", "function"]:
            return True
        return False


    def _find_ellipsis_knowledge_points(self, knowledge_points: List[Dict]) -> List[int]:
        """查找包含省略标记的知识点索引
        
        Returns:
            List[int]: 包含省略标记的知识点索引列表
        """
        invalid_indices = []
        ellipsis_markers = ['...', '等', '之类', '等等', '省略']
        
        for idx, kp in enumerate(knowledge_points):
            kp_content = kp.get('content', '')
            if any(marker in kp_content for marker in ellipsis_markers):
                invalid_indices.append(idx)
                logger.warning("[ContentUnderstanding] 知识点'%s'包含省略标记", kp.get('name', f'索引{idx}'))
        
        return invalid_indices

    async def _regenerate_knowledge_points(
        self,
        result_data: Dict,
        invalid_indices: List[int],
        title: str,
        original_content: str
    ) -> Dict:
        """重新生成包含省略标记的知识点
        
        Args:
            result_data: 原始结果数据
            invalid_indices: 需要重新生成的知识点索引
            title: 课程标题
            original_content: 原始内容
            
        Returns:
            Dict: 更新后的结果数据
        """
        from shared.llm_client import LLMRequest
        
        knowledge_points = result_data.get('knowledge_points', [])
        
        for idx in invalid_indices:
            if idx >= len(knowledge_points):
                continue
                
            kp = knowledge_points[idx]
            kp_name = kp.get('name', f'知识点{idx + 1}')
            
            logger.info("[ContentUnderstanding] 重新生成知识点: %s", kp_name)
            
            # 构建重新生成的提示词
            regenerate_prompt = f"""请为以下知识点生成完整详细的内容，**绝对禁止**使用省略标记。

## 课程标题
{title}

## 原始内容（参考）
{original_content[:1000]}

## 需要重新生成的知识点
名称：{kp_name}

⚠️ **强制要求**：
1. **禁止使用**省略号（...）、"等"、"之类"、"等等"、"省略"等标记
2. 必须完整展开所有内容，包括：
   - 定义的完整表述
   - 性质的详细列表
   - 具体的例子和说明
   - 关键要点逐条说明
3. 内容长度至少100字
4. 使用列表格式组织要点

请按照以下JSON格式输出（仅输出JSON，不要其他文字）：
{{
  "name": "{kp_name}",
  "content": "[完整的知识点内容，不包含任何省略标记]",
  "category": "concept"
}}
"""

            try:
                request = LLMRequest(
                    messages=[{"role": "user", "content": regenerate_prompt}],
                    temperature=0.1,  # 重新生成也需要准确性
                    max_tokens=16000
                )
                
                response = await self.llm_client.call(request)
                if response.success:
                    # 尝试解析JSON
                    try:
                        import json
                        regenerated_kp = json.loads(response.content)
                        if regenerated_kp.get('content'):
                            knowledge_points[idx] = regenerated_kp
                            logger.info("[ContentUnderstanding] ✓ 知识点'%s'重新生成完成", kp_name)
                    except json.JSONDecodeError:
                        logger.warning("[ContentUnderstanding] 知识点'%s'重新生成JSON解析失败", kp_name)
                else:
                    logger.warning("[ContentUnderstanding] 知识点'%s'重新生成失败: %s", kp_name, response.error)
                    
            except Exception as e:
                logger.error("[ContentUnderstanding] 知识点'%s'重新生成异常: %s", kp_name, str(e))
        
        # 更新结果数据
        result_data['knowledge_points'] = knowledge_points
        return result_data
