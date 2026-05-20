"""
学习助教Agent - 直接面向学生的智能辅导

这个Agent能够：
1. 理解学生的问题
2. 分析学生的知识薄弱点
3. 从课程库中检索相关知识点
4. 生成针对性的讲解
5. 跟踪学习进度

使用示例：
    agent = LearningTutorAgent(tools, llm_client, memory, student_id="student_001")
    response = await agent.process("我不理解什么是勾股定理")
"""
import logging
from typing import Optional, List, Dict, Any
from shared.agent.base import BaseAgent
from shared.agent.react import ReActLoop

logger = logging.getLogger(__name__)


class LearningTutorAgent(BaseAgent):
    """
    学习助教Agent

    能力：
    1. 理解学生的问题（自然语言输入）
    2. 分析学生的知识薄弱点
    3. 从课程库中检索相关知识点
    4. 生成针对性的讲解
    5. 跟踪学习进度
    """

    # 问题类型分类
    QUESTION_TYPES = {
        "概念理解": [
            "什么是", "什么意思", "解释", "定义", "含义",
            "概念", "怎么理解", "是什么"
        ],
        "解题方法": [
            "怎么做", "怎么做题", "怎么做", "怎么解",
            "怎么求", "方法", "怎么做"
        ],
        "错题分析": [
            "为什么错了", "错在哪里", "错哪了",
            "为什么不对", "错的原因"
        ],
        "知识点关联": [
            "和什么有关", "和什么联系", "和什么相似",
            "和什么不同", "区别"
        ]
    }

    def __init__(
        self,
        tools,
        llm_client,
        memory: Optional['MemoryManager'] = None,
        student_id: Optional[str] = None,
        course_id: Optional[str] = None,
        chapter_id: Optional[str] = None
    ):
        """
        初始化学习助教Agent

        Args:
            tools: 工具管理器
            llm_client: LLM客户端
            memory: 记忆管理器
            student_id: 学生ID（可选）
            course_id: 课程ID（可选，用于课程内答疑）
            chapter_id: 章节ID（可选，用于课程内答疑）
        """
        super().__init__(
            name="LearningTutor",
            description="智能学习助教，帮助学生理解数学概念、解答疑问、巩固知识",
            tools=tools,
            memory=memory,
            max_steps=20
        )

        self.llm_client = llm_client
        self.react_loop = ReActLoop(self, llm_client)
        self.student_id = student_id
        self.course_id = course_id
        self.chapter_id = chapter_id

        # 将个性化讲解方法注册为ReAct可调用的工具
        self._register_personalized_explanation_tool()

        logger.info(f"[LearningTutor] 初始化完成，学生ID: {student_id or 'N/A'}，课程: {course_id or 'N/A'}")

    async def initialize(self):
        """
        显式初始化Agent

        加载学生的历史记录（错题、学习进度等）

        这个方法应该在创建Agent后立即调用，确保历史数据已加载
        """
        if self.student_id and self.memory:
            await self._load_student_history()
            logger.info(f"[LearningTutor] 初始化完成，历史数据已加载")

    async def _load_student_history(self):
        """加载学生的学习历史"""
        # 加载学习进度（如果有相关工具）
        if self.tools and self.tools.has_tool("get_student_progress"):
            try:
                progress = await self.call_tool("get_student_progress", student_id=self.student_id)
                self.remember("progress", progress)
                logger.info(f"[LearningTutor] 加载了学习进度")
            except Exception as e:
                logger.warning(f"[LearningTutor] 加载学习进度失败: {e}")

    def _register_personalized_explanation_tool(self):
        """将个性化讲解方法包装并注册为ReAct可调用的工具"""
        if not self.tools:
            logger.warning("[LearningTutor] 无ToolManager，跳过注册个性化讲解工具")
            return

        agent_self = self  # 闭包捕获self

        async def personalized_explanation(
            question: str,
            weak_points: str = ""
        ) -> Dict[str, Any]:
            """
            根据学生的薄弱点和学习进度生成个性化讲解

            Args:
                question: 学生的问题
                weak_points: 学生薄弱点，用逗号分隔（可选）
            """
            points = [p.strip() for p in weak_points.split(",") if p.strip()] if weak_points else None
            try:
                result = await agent_self.generate_personalized_explanation(question, points)
                return {"success": True, "explanation": result}
            except Exception as e:
                return {"success": False, "error": str(e)}

        self.tools.register_from_function(
            personalized_explanation,
            name="personalized_explanation",
            description="生成个性化讲解，根据学生的薄弱点和学习进度调整讲解方式。适用于需要详细、针对性讲解的场景。"
        )
        logger.info("[LearningTutor] 已注册个性化讲解工具")

    async def process(self, input_message: str) -> str:
        """
        处理学生的问题

        输入示例：
        - "我不理解什么是勾股定理"
        - "这道题怎么做：已知直角三角形两边是3和4，求斜边"
        - "我总是搞不清全等三角形的判定条件"

        Args:
            input_message: 学生的问题

        Returns:
            Agent的响应
        """
        logger.info(f"[LearningTutor] 处理学生问题: {input_message[:100]}...")

        # 如果有课程上下文，将其注入到输入消息中
        if self.course_id:
            course_context = f"[当前学习上下文: 课程{self.course_id}"
            if self.chapter_id:
                course_context += f", 章节{self.chapter_id}"
            course_context += "。请结合当前学习内容回答学生的问题。] "
            input_message = course_context + input_message

        # 分析问题类型
        question_type = self._classify_question(input_message)
        logger.info(f"[LearningTutor] 问题类型: {question_type}")

        # 存储问题到记忆
        self.remember("last_question", {
            "content": input_message,
            "type": question_type,
            "timestamp": self.state.messages[-1].timestamp if self.state.messages else None
        })

        # 使用ReAct循环处理，将问题分类结果和工具使用引导注入ReAct上下文
        try:
            response = await self.react_loop.run(
                input_message,
                extra_context={
                    "question_type": question_type,
                    "tool_guidance": (
                        "当问题类型为「概念理解」或「错题分析」时，"
                        "优先使用 personalized_explanation 工具生成个性化讲解；"
                        "当需要查询教材知识点时，使用 query_knowledge_base 工具。"
                    )
                }
            )

            # 记录本次交互
            self.remember("interaction_count", (self.recall("interaction_count") or 0) + 1)

            return response
        except Exception as e:
            logger.error(f"[LearningTutor] 处理失败: {e}")
            return f"抱歉，处理过程中出现错误：{str(e)}"

    def _classify_question(self, question: str) -> str:
        """
        分类问题类型

        Args:
            question: 问题内容

        Returns:
            问题类型
        """
        for q_type, keywords in self.QUESTION_TYPES.items():
            for keyword in keywords:
                if keyword in question:
                    return q_type

        return "一般问题"

    async def generate_personalized_explanation(
        self,
        question: str,
        weak_points: List[str] = None
    ) -> str:
        """
        生成个性化讲解

        考虑学生的薄弱点，调整讲解方式

        Args:
            question: 问题
            weak_points: 薄弱点列表

        Returns:
            个性化讲解内容
        """
        weakness_context = ""
        if weak_points:
            weakness_context = f"\n注意：学生在以下方面存在困难：{', '.join(weak_points)}"

        # 查询学习进度
        progress = self.recall("progress")
        level_context = ""
        if progress:
            level_context = f"\n当前学习进度：{progress.get('current_chapter', '未知')}"

        prompt = f"""作为一个耐心的初中数学老师，请详细解释以下问题：

问题：{question}{weakness_context}{level_context}

要求：
1. 用简单易懂的语言解释，避免过于学术化
2. 结合1-2个具体例子帮助理解
3. 强调容易出错的地方（如果相关）
4. 给出记忆口诀或技巧（如果适用）
5. 控制在200字以内
"""

        try:
            response = await self.llm_client.generate(
                system_prompt="你是一位有经验的初中数学老师，擅长用简单易懂的方式讲解数学概念，鼓励学生思考。",
                user_prompt=prompt
            )

            if response.success:
                return response.content
            else:
                return "抱歉，讲解生成失败，请稍后再试。"

        except Exception as e:
            logger.error(f"[LearningTutor] 讲解生成失败: {e}")
            return "抱歉，讲解生成失败，请稍后再试。"

    def get_student_summary(self) -> Dict:
        """
        获取学生学习情况摘要

        Returns:
            学习情况摘要
        """
        return {
            "student_id": self.student_id,
            "interaction_count": self.recall("interaction_count") or 0,
            "last_question": self.recall("last_question"),
            "mistakes_count": len(self.recall("mistakes") or []),
            "current_progress": self.recall("progress"),
            "memory_keys": self.memory.get_all_keys(self.agent_id) if self.memory else []
        }

    def __repr__(self) -> str:
        return f"<LearningTutorAgent name={self.name} id={self.agent_id} student={self.student_id}>"
