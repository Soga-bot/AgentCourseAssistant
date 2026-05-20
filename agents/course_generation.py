"""
课程生成Agent - 管道式课程内容生成

这个Agent能够：
1. 根据学生水平调整生成策略
2. 生成课程内容并校验质量
3. 记录生成结果到记忆

使用示例：
    agent = CourseGenerationAgent(tools, llm_client, memory)
    result = await agent.generate_with_strategy(
        version="renjiao_v1", grade="七年级上册",
        chapter_id="c1_youshu", student_level="中等巩固"
    )

====================================
架构关系
====================================

CourseGenerationAgent(BaseAgent)
    └── ToolManager    # 工具注册与调度（generate_course_content 等）
            └── CourseGenerator  # 底层课程生成器
"""
import logging
import re
from typing import Optional, Dict, Any
from shared.agent.base import BaseAgent

logger = logging.getLogger(__name__)


class CourseGenerationAgent(BaseAgent):
    """
    课程生成Agent

    能力：
    1. 理解教师的生成需求（自然语言输入）
    2. 自主查询知识库获取章节信息
    3. 根据学生水平调整生成策略
    4. 生成课程内容并校验质量
    5. 失败时自动调整参数重试
    """

    # 学情等级配置表
    # - example_count: 每个知识点对应的例题数量（基础少而精，培优多而深）
    # - detail_level:  讲解详细程度
    #     high    = 逐步讲解，适合基础薄弱学生，每一步都有详细说明
    #     medium  = 适度讲解，适合中等学生，关键步骤给出说明
    #     advanced = 简明拓展，适合培优学生，侧重思路拓展与变式训练
    STUDENT_LEVEL_CONFIG = {
        # ---- 三个标准学情等级 ----
        "基础薄弱": {"example_count": 3, "detail_level": "high"},
        "中等巩固": {"example_count": 4, "detail_level": "medium"},
        "培优拓展": {"example_count": 5, "detail_level": "advanced"},
        # ---- 别名兼容 ----
        # WHY: 用户输入可能使用不同表述（如"基础"而非"基础薄弱"），
        #      通过别名映射让 _get_generation_strategy() 的模糊匹配能命中对应配置
        "基础": {"example_count": 3, "detail_level": "high"},      # "基础薄弱"的简写别名
        "中等": {"example_count": 4, "detail_level": "medium"},    # "中等巩固"的简写别名
        "困难": {"example_count": 3, "detail_level": "high"},      # 学习困难等同于基础薄弱，需要更多基础练习
        "优等": {"example_count": 5, "detail_level": "advanced"},  # "培优拓展"的简写别名
    }

    def __init__(
        self,
        tools,
        llm_client,
        memory: Optional['MemoryManager'] = None
    ):
        """
        初始化课程生成Agent

        Args:
            tools: 工具管理器
            llm_client: LLM客户端
            memory: 记忆管理器
        """
        super().__init__(
            name="CourseGenerator",
            description="智能课程生成助手，能够根据需求生成高质量的数学课程内容",
            tools=tools,
            memory=memory,
            max_steps=15  # WHY: 课程生成可能需要多轮工具调用（查询知识库、生成内容、校验质量、重试等），15步给足够的决策空间
        )

        self.llm_client = llm_client

        logger.info(f"[CourseGenAgent] 初始化完成，可用工具: {len(tools.list_tools()) if tools else 0}")

    async def process(self, input_message: str) -> str:
        """处理用户输入（基类抽象方法实现，本Agent主要通过 generate_with_strategy 使用）"""
        return f"课程生成Agent已就绪。请使用 generate_with_strategy() 方法生成课程。"

    async def generate_with_strategy(
        self,
        version: str,
        grade: str,
        chapter_id: str,
        student_level: str = "中等巩固",
        purpose: str = "学生自学",
        task_id: str = "",
        progress_callback=None
    ) -> Dict:
        """
        使用智能策略生成课程（策略直调模式）

        按固定流水线执行：生成内容 → 校验 → 记录记忆
        不经过 ReAct 循环，适用于参数已明确、流程固定的场景

        Args:
            version: 教材版本（如"人教版"）
            grade: 年级（如"七年级上册"）
            chapter_id: 章节ID
            student_level: 学生水平
            purpose: 用途
            task_id: 任务ID（用于进度追踪）
            progress_callback: 进度回调函数 callback(progress, message)

        Returns:
            生成结果字典，包含 content_dict（完整课程内容）和 validation（校验结果）
        """
        logger.info(f"[CourseGenAgent] 使用策略生成课程")
        logger.info(f"  Version: {version}, Grade: {grade}")
        logger.info(f"  Chapter: {chapter_id}, Level: {student_level}")

        # 获取生成策略
        strategy = self._get_generation_strategy(student_level)
        logger.info(f"  策略: {strategy}")

        # 将 progress_callback 写入 ToolManager 共享状态，供工具内部读取
        if hasattr(self.tools, '_course_gen_state'):
            self.tools._course_gen_state["progress_callback"] = progress_callback

        # ==============================
        # 步骤1: 生成课程内容
        # ==============================
        # 知识库查询由底层 CourseGenerator.generate() 内部自动完成，无需重复调用
        if self.tools and self.tools.has_tool("generate_course_content"):
            gen_result = await self.call_tool(
                "generate_course_content",
                version=version,
                grade=grade,
                chapter_id=chapter_id,
                student_level=student_level,
                purpose=purpose,
                task_id=task_id
            )

            if not gen_result.get("success"):
                return {
                    "success": False,
                    "error": "生成失败",
                    "message": f"课程内容生成失败: {gen_result.get('error', '未知错误')}"
                }

            logger.info(f"  内容生成成功: {gen_result.get('title', 'N/A')}")
        else:
            logger.warning("[CourseGenAgent] 没有generate_course_content工具")
            return {
                "success": False,
                "error": "工具缺失",
                "message": "generate_course_content工具未配置"
            }

        # ==============================
        # 步骤2: 校验内容
        # ==============================
        content_dict = gen_result.get("content_dict", {})
        validation = None
        if content_dict and self.tools and self.tools.has_tool("validate_content"):
            validation = await self.call_tool(
                "validate_content",
                content=content_dict
            )
            logger.info(f"  内容校验完成: valid={validation.get('is_valid', 'N/A')}")

        # ==============================
        # 步骤3: 记录到记忆
        # ==============================
        generation_record = {
            "version": version,
            "grade": grade,
            "chapter_id": chapter_id,
            "student_level": student_level,
            "purpose": purpose,
            "result": gen_result,
            "strategy": strategy
        }

        self.remember("last_generation", generation_record)
        logger.info("[CourseGenAgent] 生成记录已保存到记忆")

        return {
            "success": True,
            "title": gen_result.get("title"),
            "grade": gen_result.get("grade"),
            "chapter": gen_result.get("chapter"),
            "sections": gen_result.get("sections", []),
            "section_count": gen_result.get("section_count", 0),
            "content_dict": content_dict,
            "strategy": strategy,
            "validation": validation
        }

    def _get_generation_strategy(self, student_level: str) -> Dict:
        """
        获取生成策略

        根据学生水平返回对应的生成参数

        Args:
            student_level: 学生水平描述

        Returns:
            策略字典
        """
        # 标准化学情描述
        for key, config in self.STUDENT_LEVEL_CONFIG.items():
            if key in student_level:
                return config.copy()

        # 默认使用中等巩固
        logger.warning(f"[CourseGenAgent] 未知的学情描述: {student_level}，使用默认策略")
        return self.STUDENT_LEVEL_CONFIG["中等巩固"].copy()

    def parse_generation_request(self, input_message: str) -> Dict[str, Any]:
        """
        解析生成请求

        从自然语言输入中提取生成参数

        Args:
            input_message: 用户输入

        Returns:
            解析出的参数字典
        """
        params = {
            "version": "人教版",  # 默认值
            "grade": "",
            "chapter": "",
            "chapter_id": "",
            "student_level": "中等巩固",
            "purpose": "学生自学"
        }

        # 解析教材版本
        versions = ["人教版", "北师大版", "苏科版", "沪科版", "冀教版"]
        for v in versions:
            if v in input_message:
                params["version"] = v
                break

        # 解析年级
        grade_patterns = [
            r"([七八九]年级[上下]册)",
            r"(\d[上下]册)",
            r"第([一二三四五六七八九])章",
        ]
        for pattern in grade_patterns:
            match = re.search(pattern, input_message)
            if match:
                grade_match = match.group(1) if match.lastindex >= 1 else match.group(0)
                params["grade"] = grade_match
                break

        # 解析学情
        for level in self.STUDENT_LEVEL_CONFIG.keys():
            if level in input_message:
                params["student_level"] = level
                break

        # 尝试提取章节名称/ID
        # 常见章节关键词
        chapter_keywords = [
            "有理数", "整式的加减", "一元一次方程", "图形认识初步",
            "相交线", "平行线", "平面直角坐标系", "三角形",
            "二元一次方程组", "不等式", "数据的收集", "全等三角形",
            "轴对称", "实数", "一次函数", "整式的乘除", "因式分解",
            "分式", "反比例函数", "勾股定理", "四边形", "数据分析",
            "二次根式", "一元二次方程", "图形的旋转", "圆", "概率",
            "二次函数", "相似", "锐角三角函数", "投影"
        ]

        for keyword in chapter_keywords:
            if keyword in input_message:
                params["chapter"] = keyword
                break

        logger.debug(f"[CourseGenAgent] 解析参数: {params}")
        return params

    def get_available_tools(self) -> list:
        """
        获取可用的工具列表

        Returns:
            工具名称列表
        """
        if self.tools:
            return [tool.name for tool in self.tools.list_tools()]
        return []

    def __repr__(self) -> str:
        return f"<CourseGenerationAgent name={self.name} id={self.agent_id}>"
