"""
语音生成器模块

职责：
1. 接收storyboard数据和LaTeX生成结果
2. 根据LaTeX实际帧数调整语音脚本
3. 使用LLM智能扩展旁白
4. 返回结构化结果

设计原则：
- 页数同步：根据LaTeX实际帧数生成对应数量的语音
- LLM扩展：使用专业的扩写提示词，而非简单复用
- 可独立测试
"""

import asyncio
import json
import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Any, Optional

# 使用统一的日志配置
from ..logging_config import get_module_logger
logger = get_module_logger(__name__, "speech_generator")


@dataclass
class SpeechGenerationResult:
    """语音生成结果"""
    success: bool
    script_data: Dict
    total_scenes: int
    expansion_details: List[Dict] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    error: str = ""


class SpeechGenerator:
    """
    语音生成器

    特点：
    1. 接收LaTeX生成结果，实现页数同步
    2. 使用LLM智能扩展旁白
    3. 支持动态场景拆分（s9 → s9, s9a, s9b）
    """

    def __init__(self, llm_client):
        """
        初始化语音生成器

        Args:
            llm_client: LLM客户端实例
        """
        self.llm = llm_client
        # 延迟导入，避免循环依赖
        self._script_generator = None
        logger.info("[SpeechGenerator] 初始化完成")

    @property
    def script_generator(self):
        """延迟加载SpeechScriptGenerator"""
        if self._script_generator is None:
            from .speech_script_generator import SpeechScriptGenerator
            self._script_generator = SpeechScriptGenerator(self.llm)
        return self._script_generator

    async def generate(
        self,
        storyboard: Dict[str, Any],
        latex_result: Any  # LaTeXGenerationResult
    ) -> SpeechGenerationResult:
        """
        生成语音脚本

        Args:
            storyboard: 包含scenes的分镜数据
            latex_result: LaTeX生成结果（包含实际帧数）

        Returns:
            SpeechGenerationResult: 包含语音脚本和元数据的结果
        """
        title = storyboard.get("title", "课程")
        scenes = storyboard.get("scenes", [])

        expected_frames = len(scenes)
        actual_frames = latex_result.actual_frames

        logger.info(f"[SpeechGenerator] ========== 开始生成语音脚本 ==========")
        logger.info(f"[SpeechGenerator] 课程: {title}")
        logger.info(f"[SpeechGenerator] 期望帧数: {expected_frames}, LaTeX实际帧数: {actual_frames}")

        try:
            if actual_frames == expected_frames:
                # 帧数匹配，直接生成
                result = await self._generate_normal(storyboard)
            elif actual_frames < expected_frames:
                # LaTeX实际帧数少于期望帧数 - 异常情况
                logger.error(
                    f"[SpeechGenerator] LaTeX帧数收缩异常: "
                    f"期望{expected_frames}帧，实际{actual_frames}帧"
                )
                return SpeechGenerationResult(
                    success=False,
                    script_data={},
                    total_scenes=0,
                    error=(
                        f"LaTeX实际帧数({actual_frames})少于期望帧数({expected_frames})，"
                        f"无法生成匹配的语音。请检查LaTeX生成结果。"
                    ),
                    warnings=[f"帧数收缩: {expected_frames} → {actual_frames}"]
                )
            else:
                # 帧数扩展（actual_frames > expected_frames）
                result = await self._generate_with_expansion(
                    storyboard,
                    latex_result
                )

            logger.info(f"[SpeechGenerator] ✓ 生成完成，总场景数: {result.total_scenes}")

            # 端到端验证：确保生成的语音场景数与LaTeX帧数匹配
            if result.success and result.total_scenes != actual_frames:
                logger.error(
                    f"[SpeechGenerator] 内部错误：生成的语音场景数({result.total_scenes}) "
                    f"与LaTeX帧数({actual_frames})不匹配"
                )
                return SpeechGenerationResult(
                    success=False,
                    script_data=result.script_data,  # 保留已生成的数据便于调试
                    total_scenes=result.total_scenes,
                    error=(
                        f"内部验证失败：生成的语音场景数({result.total_scenes}) "
                        f"与LaTeX帧数({actual_frames})不匹配"
                    )
                )

            return result

        except Exception as e:
            logger.error(f"[SpeechGenerator] 生成失败: {str(e)}")
            return SpeechGenerationResult(
                success=False,
                script_data={},
                total_scenes=0,
                error=str(e)
            )

    async def _generate_normal(
        self,
        storyboard: Dict[str, Any]
    ) -> SpeechGenerationResult:
        """
        正常模式：帧数匹配，使用LLM扩展生成

        使用现有的SpeechScriptGenerator
        """
        title = storyboard.get("title", "课程")

        # 使用SpeechScriptGenerator生成
        script_result = await self.script_generator.generate(
            title=title,
            storyboard_data=storyboard
        )

        if not script_result.success:
            logger.warning(f"[SpeechGenerator] LLM生成失败，使用回退策略")
            # 回退策略已在script_generator中处理
            warnings = script_result.warnings
        else:
            warnings = []

        # 转换为speech.json格式
        script_data = self._convert_to_speech_format(script_result)

        return SpeechGenerationResult(
            success=True,
            script_data=script_data,
            total_scenes=len(script_data.get("scenes", [])),
            warnings=warnings
        )

    async def _generate_with_expansion(
        self,
        storyboard: Dict[str, Any],
        latex_result: Any
    ) -> SpeechGenerationResult:
        """
        扩展模式：帧数不匹配，智能扩展语音脚本

        策略：
        1. 分析哪些场景可能被拆分
        2. 使用LLM为子场景生成专门的旁白
        3. 生成类似s9a, s9b的子场景ID
        """
        scenes = storyboard.get("scenes", [])
        actual_frames = latex_result.actual_frames
        expected_frames = len(scenes)

        logger.info(f"[SpeechGenerator] 启用扩展模式: {expected_frames} → {actual_frames}")

        # 分析扩展计划
        expansion_plan = self._analyze_expansion(
            scenes,
            actual_frames,
            latex_result.frame_details
        )

        logger.info(f"[SpeechGenerator] 扩展计划: {expansion_plan}")

        # 创建扩展后的storyboard
        expanded_storyboard = self._create_expanded_storyboard(
            storyboard,
            expansion_plan
        )

        # 使用LLM生成扩展后的脚本
        script_result = await self.script_generator.generate(
            title=storyboard.get("title", "课程"),
            storyboard_data=expanded_storyboard
        )

        # 转换格式
        script_data = self._convert_to_speech_format(script_result)

        return SpeechGenerationResult(
            success=True,
            script_data=script_data,
            total_scenes=len(script_data.get("scenes", [])),
            expansion_details=expansion_plan,
            warnings=["语音脚本已扩展以匹配LaTeX实际帧数"]
        )

    def _analyze_expansion(
        self,
        scenes: List[Dict],
        actual_frames: int,
        frame_details: List[str]
    ) -> List[Dict]:
        """
        分析哪些场景需要扩展（改进版）

        返回扩展计划：
        [
            {"scene_id": "s9", "sub_count": 3},  # s9拆分为s9, s9a, s9b
            ...
        ]
        """
        extra_frames = actual_frames - len(scenes)
        if extra_frames <= 0:
            return []

        # 按内容长度排序场景（从长到短）
        scenes_with_length = [
            (s, len(s.get("mainContent", "")))
            for s in scenes
        ]
        scenes_with_length.sort(key=lambda x: x[1], reverse=True)

        expansion_plan = []
        allocated_extra = 0

        # 动态分配额外帧
        for scene, length in scenes_with_length:
            if allocated_extra >= extra_frames:
                break

            # 根据内容长度决定拆分数量
            if length > 1000:
                # 非常长的内容，拆分成3-4个
                sub_count = min(4, extra_frames - allocated_extra + 1)
            elif length > 700:
                # 较长的内容，拆分成2-3个
                sub_count = min(3, extra_frames - allocated_extra + 1)
            elif length > 400:
                # 中等长度，拆分成2个
                sub_count = min(2, extra_frames - allocated_extra + 1)
            else:
                # 短内容，不拆分
                continue

            expansion_plan.append({
                "scene_id": scene.get("sceneID", ""),
                "sub_count": sub_count
            })

            allocated_extra += sub_count - 1  # 原场景占1，其余是额外帧

        # 如果还有未分配的额外帧，分配给最长的场景
        if allocated_extra < extra_frames:
            remaining = extra_frames - allocated_extra

            # 检查是否需要扩展过多（可能表示数据异常）
            if remaining > len(scenes) * 0.5:
                logger.warning(
                    f"[语音扩展] 警告：需要扩展的帧数({remaining})相对于场景数({len(scenes)})过多，"
                    f"可能存在数据异常。强制分配给最长场景。"
                )

            if expansion_plan:
                # 增加第一个拆分场景的sub_count
                expansion_plan[0]["sub_count"] += remaining
                logger.debug(
                    f"[语音扩展] 将剩余{remaining}帧分配给第一个拆分场景: "
                    f"{expansion_plan[0]['scene_id']}"
                )
            else:
                # 没有长场景可拆分，分配到最后一个场景（不理想但必要）
                last_scene = scenes[-1]
                expansion_plan.append({
                    "scene_id": last_scene.get("sceneID", ""),
                    "sub_count": remaining + 1
                })
                logger.warning(
                    f"[语音扩展] 所有场景内容都很短，但必须扩展。"
                    f"强制将最后场景{last_scene.get('sceneID', '')}拆分为{remaining + 1}个"
                )

        # 详细日志：记录每个扩展场景的原因
        if expansion_plan:
            for plan in expansion_plan:
                scene_id = plan["scene_id"]
                sub_count = plan["sub_count"]
                # 找到对应场景的内容长度
                scene_content_length = next(
                    (len(s.get("mainContent", "")) for s in scenes if s.get("sceneID") == scene_id),
                    0
                )
                logger.info(
                    f"[语音扩展] 场景{scene_id} (内容长度: {scene_content_length}字符) "
                    f"将被拆分为{sub_count}个子场景"
                )

        logger.info(f"[语音扩展] 扩展计划: {expansion_plan}")
        return expansion_plan

    def _create_expanded_storyboard(
        self,
        storyboard: Dict,
        expansion_plan: List[Dict]
    ) -> Dict:
        """
        根据扩展计划创建扩展后的storyboard（修复顺序版）

        保持原场景顺序，子场景紧跟父场景
        """
        scenes = storyboard.get("scenes", [])
        expanded_scenes = []

        # 记录需要扩展的场景ID
        expand_ids = {p["scene_id"] for p in expansion_plan}
        sub_counts = {p["scene_id"]: p["sub_count"] for p in expansion_plan}

        for scene in scenes:
            scene_id = scene.get("sceneID", "")

            # 添加原场景
            expanded_scenes.append(scene)

            # 如果需要扩展，添加子场景
            if scene_id in expand_ids:
                sub_count = sub_counts[scene_id]

                for i in range(1, sub_count):
                    sub_id = chr(96 + i)  # a, b, c...
                    sub_scene = scene.copy()
                    sub_scene["sceneID"] = f"{scene_id}{sub_id}"
                    # 子场景标题添加字母后缀（如"例题1a"、"例题1b"）
                    sub_frame_title = sub_scene.get("frameTitle", "")
                    sub_scene["frameTitle"] = f"{sub_frame_title}{sub_id}"
                    expanded_scenes.append(sub_scene)

        return {
            **storyboard,
            "scenes": expanded_scenes,
            "totalSlides": len(expanded_scenes)
        }

    def _convert_to_speech_format(
        self,
        script_result: Any  # SpeechScriptResult
    ) -> Dict:
        """
        将SpeechScriptResult转换为speech.json格式

        格式：
        {
            "scenes": [
                {
                    "frame_id": "s1",
                    "scene_index": 1,
                    "text": "旁白内容",
                    "duration": 12.5
                }
            ],
            "total_duration": 262.5,
            "scene_count": 21
        }
        """
        scenes_data = []
        total_duration = 0

        for scene_id, speech_script in script_result.script_by_scene.items():
            # 合并narration数组为文本
            narration_text = " ".join(speech_script.narration)

            # 估算时长（180字/分钟 = 3字/秒）
            duration = max(2, len(narration_text) / 3)

            # 提取scene_index（从sceneID如s1, s2a中提取）
            # 支持格式: s1, s2a, s2b, scene1, frame1等
            match = re.match(r'[a-z]+(\d+)[a-z]?', scene_id)
            if match:
                scene_index = int(match.group(1))
            else:
                # fallback: 使用当前序号
                scene_index = len(scenes_data) + 1
                logger.debug(
                    f"[格式转换] 无法从scene_id '{scene_id}'提取数字，"
                    f"使用序号{scene_index}"
                )

            scenes_data.append({
                "frame_id": scene_id,
                "scene_index": scene_index,
                "text": narration_text,
                "duration": duration
            })

            total_duration += duration

        # 按scene_index排序
        scenes_data.sort(key=lambda x: x["scene_index"])

        # 更新scene_index为实际序号
        for i, scene in enumerate(scenes_data, 1):
            scene["scene_index"] = i

        return {
            "scenes": scenes_data,
            "total_duration": total_duration,
            "scene_count": len(scenes_data)
        }

    def update_durations_from_audio(
        self,
        script_data: Dict,
        audio_results: List[Any]
    ) -> Dict:
        """
        使用实际音频时长更新脚本数据（任务11：精确字幕时序）

        Args:
            script_data: 原始脚本数据（包含估算时长）
            audio_results: TTS音频结果列表（包含实际时长）

        Returns:
            更新后的脚本数据（使用实际时长）
        """
        logger.info("[SpeechGenerator] ========== 更新音频时长 ==========")

        # 创建scene_id到音频结果的映射
        audio_map = {}
        for audio_result in audio_results:
            if hasattr(audio_result, 'scene_id'):
                audio_map[audio_result.scene_id] = audio_result
            elif isinstance(audio_result, dict):
                audio_map[audio_result.get('scene_id')] = audio_result

        # 更新每个场景的时长
        scenes = script_data.get('scenes', [])
        total_actual_duration = 0
        updated_count = 0

        for scene in scenes:
            frame_id = scene.get('frame_id', '')

            if frame_id in audio_map:
                audio_result = audio_map[frame_id]

                # 获取实际时长
                if hasattr(audio_result, 'duration'):
                    actual_duration = audio_result.duration
                elif isinstance(audio_result, dict):
                    actual_duration = audio_result.get('duration', scene.get('duration', 0))
                else:
                    continue

                old_duration = scene.get('duration', 0)

                # 只在有实际时长时更新
                if actual_duration > 0:
                    scene['duration'] = actual_duration
                    scene['estimated_duration'] = old_duration  # 保留估算值用于对比
                    total_actual_duration += actual_duration
                    updated_count += 1

                    logger.debug(
                        f"[SpeechGenerator] {frame_id}: 时长更新 "
                        f"{old_duration:.2f}秒 → {actual_duration:.2f}秒"
                    )

        # 更新总时长
        script_data['total_duration'] = total_actual_duration

        logger.info(f"[SpeechGenerator] ✓ 时长更新完成: {updated_count}/{len(scenes)} 个场景")
        logger.info(f"[SpeechGenerator]   - 总时长: {total_actual_duration:.1f}秒")

        return script_data


# =============================================================================
# 便捷函数
# =============================================================================

async def generate_speech(
    llm_client,
    storyboard: Dict[str, Any],
    latex_result: Any
) -> SpeechGenerationResult:
    """
    生成语音脚本的便捷函数

    Args:
        llm_client: LLM客户端实例
        storyboard: 分镜数据
        latex_result: LaTeX生成结果

    Returns:
        SpeechGenerationResult: 生成结果
    """
    generator = SpeechGenerator(llm_client)
    return await generator.generate(storyboard, latex_result)
