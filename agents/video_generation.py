"""
视频生成Agent - 管道式讲解视频生成

这个Agent能够：
1. 接收课程JSON数据，按固定工具链生成视频
2. 依次调用6个阶段工具：预处理→讲解→LaTeX/PDF→帧提取→语音脚本→TTS合成
3. 最终输出完整的讲解视频

使用示例：
    agent = VideoGenerationAgent(tools, llm_client)
    result = await agent.generate_video(course_id="xxx", course_json={...})
"""
import json
import logging
from pathlib import Path
from typing import Optional, Dict, Any, List

from shared.agent.base import BaseAgent

logger = logging.getLogger(__name__)


class VideoGenerationAgent(BaseAgent):
    """
    视频生成Agent

    通过ReAct推理框架驱动的视频生成流程：
    1. 预处理课程内容 → 规范帧
    2. 生成口语化讲解（可选）
    3. 生成LaTeX → 编译PDF
    4. 提取关键帧 → 生成语音脚本
    5. TTS合成 → 视频合成
    """

    def __init__(
        self,
        tools,
        llm_client,
        memory: Optional['MemoryManager'] = None
    ):
        """
        初始化视频生成Agent

        Args:
            tools: 工具管理器（需包含视频生成相关工具）
            llm_client: LLM客户端
            memory: 记忆管理器
        """
        super().__init__(
            name="VideoGenerator",
            description="智能视频生成助手，能够自动完成从课程内容到讲解视频的全流程生成",
            tools=tools,
            memory=memory,
            max_steps=15
        )

        self.llm_client = llm_client

        logger.info(f"[VideoGenAgent] 初始化完成，可用工具: {len(tools.list_tools()) if tools else 0}")

    async def process(self, input_message: str) -> str:
        """处理用户输入（基类抽象方法实现，本Agent主要通过 generate_video 使用）"""
        return f"视频生成Agent已就绪。请使用 generate_video() 方法生成视频。"

    async def generate_video(
        self,
        course_id: str,
        course_json: Dict[str, Any],
        progress_callback=None
    ) -> Dict[str, Any]:
        """
        通过Agent工具链生成视频

        按固定顺序调用注册的工具完成视频生成：
        preprocess → narrate → latex_pdf → images → speech → tts_video

        Args:
            course_id: 课程ID
            course_json: 课程JSON数据
            progress_callback: 进度回调

        Returns:
            生成结果字典
        """
        logger.info(f"[VideoGenAgent] ========== 开始Agent驱动的视频生成 ==========")
        logger.info(f"[VideoGenAgent] 课程ID: {course_id}")
        logger.info(f"[VideoGenAgent] 课程标题: {course_json.get('title', 'N/A')}")

        result = {
            "success": False,
            "course_id": course_id,
            "outputs": {},
            "mode": "agent"
        }

        try:
            # ========== 步骤1: 预处理课程内容 ==========
            if progress_callback:
                progress_callback(5, "正在预处理课程内容...")

            step1 = await self.call_tool(
                "preprocess_frames",
                course_id=course_id,
                course_json=json.dumps(course_json, ensure_ascii=False)
            )

            if not step1.get("success"):
                raise Exception(f"帧预处理失败: {step1.get('error')}")

            logger.info(f"[VideoGenAgent] 步骤1完成: 预处理 {step1.get('frame_count', 0)} 帧")

            if progress_callback:
                progress_callback(15, "帧预处理完成...")

            # ========== 步骤2: 讲解生成 ==========
            step2 = await self.call_tool(
                "generate_narration",
                course_id=course_id
            )

            narration_enabled = step2.get("success", False)
            if narration_enabled:
                logger.info(f"[VideoGenAgent] 步骤2完成: 讲解生成 {step2.get('frame_count', 0)} 帧")
            else:
                logger.info(f"[VideoGenAgent] 步骤2跳过: {step2.get('message', '未启用')}")

            if progress_callback:
                progress_callback(30, "讲解生成完成...")

            # ========== 步骤3: 生成LaTeX并编译PDF ==========
            if progress_callback:
                progress_callback(32, "正在生成 LaTeX 和 PDF...")

            step3 = await self.call_tool(
                "generate_latex_pdf",
                course_id=course_id,
                course_title=course_json.get('title', '课程')
            )

            if not step3.get("success"):
                raise Exception(f"LaTeX/PDF生成失败: {step3.get('error')}")

            pdf_page_count = step3.get("pdf_page_count", 0)
            logger.info(f"[VideoGenAgent] 步骤3完成: PDF已生成, {pdf_page_count} 页")

            if progress_callback:
                progress_callback(60, "PDF 编译完成...")

            # ========== 步骤4: 提取关键帧 ==========
            if progress_callback:
                progress_callback(65, "正在提取关键帧...")

            step4 = await self.call_tool(
                "extract_images",
                course_id=course_id
            )

            if not step4.get("success"):
                raise Exception(f"关键帧提取失败: {step4.get('error')}")

            image_count = step4.get("image_count", 0)
            logger.info(f"[VideoGenAgent] 步骤4完成: 提取 {image_count} 帧")

            if progress_callback:
                progress_callback(75, "关键帧提取完成...")

            # ========== 步骤5: 生成语音脚本 ==========
            if progress_callback:
                progress_callback(78, "正在生成语音脚本...")

            step5 = await self.call_tool(
                "generate_speech_script",
                course_id=course_id,
                course_title=course_json.get('title', '课程'),
                pdf_page_count=pdf_page_count
            )

            if not step5.get("success"):
                raise Exception(f"语音脚本生成失败: {step5.get('error')}")

            scene_count = step5.get("scene_count", 0)
            logger.info(f"[VideoGenAgent] 步骤5完成: {scene_count} 个场景")

            if progress_callback:
                progress_callback(80, "语音脚本生成完成...")

            # ========== 步骤6: TTS与视频合成 ==========
            if progress_callback:
                progress_callback(85, "正在合成视频...")

            step6 = await self.call_tool(
                "tts_and_synthesize",
                course_id=course_id
            )

            if not step6.get("success"):
                raise Exception(f"视频合成失败: {step6.get('error')}")

            logger.info(f"[VideoGenAgent] 步骤6完成: 视频已生成")

            # ========== 完成 ==========
            result["success"] = True
            result["video_path"] = step6.get("video_path", "")
            result["outputs"]["video"] = step6.get("video_path", "")
            result["outputs"]["frames"] = step4.get("frames_path", "")
            result["outputs"]["speech"] = step5.get("speech_path", "")
            result["outputs"]["pdf"] = step3.get("pdf_path", "")
            result["duration"] = step6.get("duration")
            result["total_frames"] = step1.get("frame_count", 0)

            logger.info(f"[VideoGenAgent] ========== 生成完成 ==========")
            logger.info(f"[VideoGenAgent]   - 视频路径: {result['video_path']}")
            logger.info(f"[VideoGenAgent]   - 总帧数: {result['total_frames']}")
            logger.info(f"[VideoGenAgent]   - 时长: {result.get('duration', 'N/A')}")

            if progress_callback:
                progress_callback(100, "生成完成!")

        except Exception as e:
            logger.error(f"[VideoGenAgent] 生成失败: {e}")
            import traceback
            logger.error(traceback.format_exc())

            result["error"] = str(e)

            if progress_callback:
                progress_callback(0, f"生成失败: {str(e)}")

        return result

    def __repr__(self) -> str:
        return f"<VideoGenerationAgent name={self.name} id={self.agent_id}>"
