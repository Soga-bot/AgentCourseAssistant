"""
轻量分镜映射器 - CourseToVideoMapper

采用混合模式:
- 规则映射: 快速生成分镜结构
- LLM优化: 优化讲解词和标题

【智能分页核心策略】
本模块采用"语义边界智能拆分"策略，而非"原子块不切割"：

1. 语义完整性优先：
   - 在逻辑边界处拆分（题目|思路|步骤|答案）
   - 每个拆分后的单元保持相对完整的语义

2. 容量适配强制要求：
   - Beamer单帧容量有限（224pt≈10-15行）
   - 超出必须拆分，否则内容溢出

3. 帧间连贯性保障：
   - 自动添加【续下页】【接上页】导航标记
   - 观众即使翻页也能理解内容延续

4. 差异化处理：
   - 简单例题（≤3步）：保持完整，不拆分
   - 复杂例题（≥6步）：语义边界拆分，保持连贯

【为什么不采用"原子块不切割"？】
- Beamer物理限制：单帧容量有限，长内容必须拆分
- 语义连贯性：合理拆分比内容溢出更可接受
- 观众体验：帧间导航标记能弥补拆分带来的理解障碍

注意: 必须提供 LLM 客户端
"""

import re
import logging
import time
from typing import Dict, List, Any, Optional
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class LightweightScene:
    """轻量级场景数据"""
    sceneID: str
    frameTitle: str
    mainContent: str
    narration: str
    slideType: str
    needsDiagram: bool
    diagramSpec: Dict = None


class CourseToVideoMapper:
    """
    课程内容到视频分镜的轻量级映射器

    采用混合模式:
    - 规则映射: 快速生成分镜结构
    - LLM优化: 优化讲解词和标题

    特点:
    - 基于规则的直接映射
    - 保留分镜作为中间层的优势
    - LLM质量提升

    【智能分页机制】
    本类实现"语义边界智能拆分"策略：

    1. 拆分原则：
       - 语义边界优先（题目|思路|步骤|答案）
       - 容量适配强制（224pt阈值）
       - 帧间连贯保障（导航标记）

    2. 场景类型差异化处理：
       - intro/objective/extend/summary: 小板块，尽量保持完整
       - example/warning/practice: 按语义单元分组拆分
       - concept: 按子知识点边界拆分

    3. 质量保障：
       - 占位符清理
       - 碎片合并（10行阈值）
       - 质量评分（4维验证）

    注意:
    - 初始化时 llm_client 参数可选
    - 但调用 map_to_storyboard() 时必须已配置 LLM 客户端，否则抛出 RuntimeError
    """

    # section 类型到帧类型的映射
    SECTION_FRAME_MAPPING = {
        "导入": "intro",
        "学习目标": "objective",  # 新增
        "知识点详解": "concept",
        "典例精讲": "example",
        "易错点": "warning",
        "随堂小测": "practice",
        "知识框架": "summary",
        "课后拓展": "extend"
    }

    # 帧类型到中文名称的映射
    FRAME_TYPE_NAMES = {
        "title": "标题页",
        "intro": "情境导入",
        "objective": "学习目标",
        "concept": "知识点讲解",
        "example": "例题示范",
        "example_continue": "例题续页",
        "warning": "易错点提醒",
        "practice": "随堂练习",
        "summary": "课堂小结",
        "extend": "课后拓展"
    }

    # ========== 智能分页规则配置 ==========
    # 从 latex_generator.py 迁移的分页规则
    PAGINATION_RULES = {
        'example': {
            'enabled': True,
            'split_parts': 3,  # 固定拆分为3页
            'structure': ['题目+思路引导', '完整步骤', '易错提醒+方法总结']
        },
        'exercise': {
            'enabled': True,
            'questions_per_page': 2  # 每页2题
        },
        'summary': {
            'enabled': True,
            'sections_per_page': 2  # 每页2个section
        },
        'warning': {
            'enabled': True,
            'min_items_to_split': 3,  # 至少3个item才拆分
            'target_frames': 2  # 拆分为2页
        }
    }

    # ========== 页面容量标准（LaTeX Beamer 实际渲染数据） ==========
    # 统一标准：所有内容拆分、分页检查都必须基于此标准
    #
    # 基础数据：
    #   - 每页标准：1行标题 + 15行内容 = 16行
    #   - 每行标准：27字符（中文字符，基于12pt字体）
    #   - 行高标准：14pt/行（12pt字体 + 1.2倍行距）
    #
    # 计算：
    #   页面字符容量 = 16行 × 27字符/行 = 432字符
    #   页面高度 = 16行 × 14pt/行 = 224pt
    #
    # 内容拆分阈值 = 页面容量 × 0.8（考虑block标题、公式密度、行间距）
    #                 = 432 × 0.8 ≈ 350字符
    #
    # 为什么要0.8系数：
    #   - block环境标题占用空间
    #   - 公式比普通文本占用更多空间
    #   - itemize/enumerate环境有额外缩进
    #   - 行间距和垂直间距
    #
    # 历史问题：
    #   - 旧代码使用800字符阈值，是页面容量的1.85倍
    #   - 导致内容溢出（页面爆满）和过度拆分并存
    #
    MAX_LINES_PER_PAGE = 16           # 最大行数（1标题 + 15内容）
    MAX_CHARS_PER_LINE = 27           # 每行最大字符数
    LINE_HEIGHT_PT = 14               # 每行高度（pt）
    MAX_CHARS_PER_PAGE = 432          # 页面字符容量 = 16 × 27
    SAFE_HEIGHT_LIMIT_PT = 224        # 页面高度 = 16 × 14
    CONTENT_SPLIT_THRESHOLD = 350     # 内容拆分阈值 = 432 × 0.8

    # ========== 2025-04-03 分页优化配置 ==========
    MAX_RECURSION_DEPTH_GLOBAL = 3    # 全局最大递归深度
    MAX_SUBSCENES_PER_ORIGINAL = 5    # 单个场景最多拆5份（防止场景爆炸）
    PRIMARY_HEIGHT_THRESHOLD = 224    # 主阈值（页面高度）
    SECONDARY_HEIGHT_THRESHOLD = 201.6  # 次阈值 = 224 × 0.9（高不确定性场景使用）

    # ========== 分页指标收集（类级别，跨实例共享） ==========
    _pagination_metrics = {
        'estimate_vs_actual': [],      # (估算高度, 实际高度)
        'split_quality_scores': [],    # 质量评分
        'overflow_incidents': 0,       # 溢出次数
        'placeholder_detected': 0,     # 占位符检测次数
        'retry_count': [],             # 重试次数
        'pagination_triggers': [],     # 拆分触发原因统计
        'scene_counts': [],            # 场景数量统计
    }

    def __init__(self, llm_client=None):
        """
        初始化映射器

        Args:
            llm_client: LLM客户端，用于优化讲解词和标题

        Note:
            虽然 llm_client 参数可选，但在调用 map_to_storyboard() 时必须提供 LLM 客户端
        """
        self.scenes = []
        self.scene_counter = 0
        self.llm_client = llm_client
        self.use_llm = llm_client is not None

    async def map_to_storyboard(
        self,
        course_json: Dict,
        progress_callback: Optional[callable] = None
    ) -> Dict:
        """
        将 course.json 映射为标准分镜格式（默认使用混合模式）

        混合模式（规则映射 + LLM优化）

        Args:
            course_json: course.json 的内容
            progress_callback: 进度回调

        Returns:
            优化后的标准分镜 JSON

        Raises:
            RuntimeError: 如果没有提供 LLM 客户端
        """
        if not self.use_llm:
            raise RuntimeError(
                "混合模式需要 LLM 客户端。"
                "请确保系统已配置 LLM 客户端后再试。"
            )

        # 直接使用混合模式
        logger.info(f"[分镜映射] 使用混合模式（规则映射 + LLM优化）")
        return await self.map_to_storyboard_hybrid(course_json, progress_callback)

    def _map_to_storyboard_hybrid_internal(self, course_json: Dict) -> Dict:
        """
        混合模式内部方法：基于规则生成分镜结构（供LLM优化使用）

        Args:
            course_json: course.json 的内容

        Returns:
            标准分镜 JSON
        """
        self.scenes = []
        self.scene_counter = 0

        title = course_json.get("title", "课程")
        chapter = course_json.get("chapter", "")
        grade = course_json.get("grade", "")
        sections = course_json.get("sections", {})

        logger.info(f"[混合模式-规则] 开始映射: {title}")
        logger.info(f"[混合模式-规则] 章节信息: {grade} {chapter}")
        logger.info(f"[混合模式-规则] 发现 {len(sections)} 个section")

        # 1. 创建标题页
        self._add_title_scene(title, grade, chapter)

        # 2. 遍历 sections
        for section_name, section_content in sections.items():
            frame_type = self.SECTION_FRAME_MAPPING.get(section_name, "concept")

            logger.info(f"[混合模式-规则] 处理section: {section_name} → {frame_type}")

            if frame_type == "intro":
                self._add_intro_scene(section_name, section_content)

            elif frame_type == "objective":
                self._add_objective_scene(section_name, section_content)

            elif frame_type == "concept":
                self._add_concept_scenes(section_name, section_content)

            elif frame_type == "example":
                self._add_example_scenes(section_name, section_content)

            elif frame_type == "warning":
                self._add_warning_scene(section_name, section_content)

            elif frame_type == "practice":
                self._add_practice_scene(section_name, section_content)

            elif frame_type == "summary":
                self._add_summary_scene(section_name, section_content)

            elif frame_type == "extend":
                self._add_extend_scene(section_name, section_content)

        # 3. 组装分镜（添加详细的场景统计日志）
        logger.info(f"[分镜统计] 总场景数: {len(self.scenes)}")
        logger.info(f"[分镜统计] 场景分布:")
        for i, scene in enumerate(self.scenes, 1):
            logger.info(f"  场景{i}: {scene.frameTitle} ({scene.slideType})")

        # 转换为字典并清理内容
        scene_dicts = [self._scene_to_dict(s) for s in self.scenes]
        scene_dicts = self._cleanup_scene_content(scene_dicts)

        storyboard = {
            "title": title,
            "totalSlides": len(scene_dicts),
            "estimatedDuration": f"约{len(scene_dicts) * 0.5:.1f}分钟",
            "scenes": scene_dicts
        }

        logger.info(f"[混合模式-规则] 映射完成: {len(self.scenes)}帧")
        return storyboard

    async def map_to_storyboard_hybrid(
        self,
        course_json: Dict,
        progress_callback: Optional[callable] = None
    ) -> Dict:
        """
        混合模式: 规则映射 + 统一智能分页 + LLM优化

        步骤:
        1. 使用规则生成分镜结构
        2. 统一智能分页（类型感知 + LLM语义拆分）
        3. 使用LLM优化讲解词和标题

        Args:
            course_json: course.json 的内容
            progress_callback: 进度回调

        Returns:
            优化后的标准分镜 JSON

        Raises:
            RuntimeError: 如果没有提供 LLM 客户端
        """
        if not self.use_llm:
            raise RuntimeError(
                "混合模式需要 LLM 客户端。"
                "请确保系统已配置 LLM 客户端后再试。"
            )

        logger.info(f"[混合模式] 开始混合映射...")

        # 步骤1: 规则映射
        if progress_callback:
            progress_callback(10, "正在生成分镜结构...")

        storyboard = self._map_to_storyboard_hybrid_internal(course_json)

        logger.info(f"[混合模式] 规则映射完成: {len(storyboard['scenes'])}帧")

        # 步骤2: 统一智能分页（类型感知 + LLM语义拆分）
        if progress_callback:
            progress_callback(20, "正在进行智能分页...")

        storyboard = await self._apply_intelligent_pagination_unified(
            storyboard=storyboard,
            course_json=course_json,
            progress_callback=progress_callback
        )

        # 步骤3: LLM优化
        if progress_callback:
            progress_callback(40, "正在优化讲解词和标题...")

        optimized_storyboard = await self._optimize_with_llm(
            storyboard=storyboard,
            course_json=course_json,
            progress_callback=progress_callback
        )

        if progress_callback:
            progress_callback(100, "分镜优化完成")

        logger.info(f"[混合模式] 混合映射完成: {len(optimized_storyboard['scenes'])}帧")
        return optimized_storyboard

    async def _apply_intelligent_pagination_unified(
        self,
        storyboard: Dict,
        course_json: Dict,
        progress_callback: Optional[callable] = None
    ) -> Dict:
        """
        统一智能分页入口（2025-03-31 合并重构）

        职责：
        1. 遍历所有场景，使用 _should_paginate 判断是否需要拆分
        2. _should_paginate 已包含场景类型感知的差异化触发条件
        3. 需要拆分的场景调用 _llm_semantic_split_for_pagination
        4. 递归检查拆分后的子场景

        场景类型处理策略：
        - intro/objective/extend: 不拆分
        - concept: >432字符时LLM语义拆分
        - example: 基于复杂度判断（简单/中等/复杂）
        - warning: ≥3个易错点拆2页
        - practice: ≥3题时每2题一页
        - summary: ≥5个要点时每2个section一页

        Args:
            storyboard: 当前分镜
            course_json: 课程JSON（保留参数兼容性）
            progress_callback: 进度回调

        Returns:
            分页后的分镜
        """
        scenes = storyboard.get('scenes', [])
        if not scenes:
            return storyboard

        paginated_scenes = []
        pagination_count = 0

        # 【2025-04-03】递归拆分：使用全局配置的递归深度
        MAX_RECURSION_DEPTH = self.MAX_RECURSION_DEPTH_GLOBAL

        async def recursive_paginate(scenes_to_check, depth=0, parent_base_scene_id=None):
            """递归分页函数

            Args:
                scenes_to_check: 待检查的场景列表
                depth: 当前递归深度
                parent_base_scene_id: 父场景的基础ID（不含字母后缀），用于统计子场景数

            Returns:
                分页后的场景列表
            """
            if depth > MAX_RECURSION_DEPTH:
                logger.warning(f"[递归分页] 达到最大递归深度({MAX_RECURSION_DEPTH})，停止拆分")
                return scenes_to_check

            result_scenes = []
            local_count = 0
            subscene_counter = {}  # 统计每个原始场景的子场景数

            for scene in scenes_to_check:
                scene_type = scene.get('slideType', '')
                scene_id = scene.get('sceneID', '')

                # 提取场景的基础ID（去掉字母后缀，如 s19a → s19）
                base_scene_id = self._extract_base_scene_id(scene_id)

                # 检查子场景数量限制
                if parent_base_scene_id and base_scene_id == parent_base_scene_id:
                    subscene_counter[base_scene_id] = subscene_counter.get(base_scene_id, 0) + 1
                    if subscene_counter[base_scene_id] > self.MAX_SUBSCENES_PER_ORIGINAL:
                        logger.warning(f"[分页限制] {base_scene_id} 已达最大子场景数({self.MAX_SUBSCENES_PER_ORIGINAL})，停止拆分")
                        result_scenes.append(scene)
                        continue
                elif parent_base_scene_id is None and depth > 0:
                    # 首次进入递归，设置父场景基础ID
                    parent_base_scene_id = base_scene_id
                    subscene_counter[base_scene_id] = 1

                # 检查是否需要分页
                should_split, split_reason = self._should_paginate(scene, scene_type)
                if should_split:
                    logger.info(f"[递归分页] 深度={depth}: 拆分场景 {scene_id} ({scene_type}) - 原因: {split_reason}")
                    local_count += 1

                    # 调用LLM语义拆分
                    split_scenes = await self._llm_semantic_split_for_pagination(scene, scene_type)

                    # 递归检查拆分后的子场景
                    if split_scenes and depth < MAX_RECURSION_DEPTH:
                        logger.info(f"[递归分页] 深度={depth}: 检查{len(split_scenes)}个子场景")
                        checked_scenes = await recursive_paginate(
                            split_scenes,
                            depth + 1,
                            parent_base_scene_id or base_scene_id
                        )
                        result_scenes.extend(checked_scenes)
                    else:
                        result_scenes.extend(split_scenes)
                else:
                    result_scenes.append(scene)

            if local_count > 0:
                logger.info(f"[递归分页] 深度={depth}: 拆分了{local_count}个场景")

            return result_scenes

        # 开始递归分页
        paginated_scenes = await recursive_paginate(scenes)

        # 【2025-04-03】清理占位符和不规范LaTeX（后处理）
        paginated_scenes = self._cleanup_scene_content(paginated_scenes)
        logger.info(f"[智能分页] 清理内容后: {len(paginated_scenes)}个场景")

        # 【2025-04-03】合并碎片场景（后处理）
        paginated_scenes = self._merge_tiny_scenes(paginated_scenes, min_lines=10)
        logger.info(f"[智能分页] 合并碎片后: {len(paginated_scenes)}个场景")

        if len(paginated_scenes) != len(scenes):
            # 更新分镜统计
            storyboard['scenes'] = paginated_scenes
            storyboard['totalSlides'] = len(paginated_scenes)
            storyboard['estimatedDuration'] = f"约{len(paginated_scenes) * 0.5:.1f}分钟"
            logger.info(f"[智能分页] 完成: 递归分页后总场景数: {len(paginated_scenes)} (原始{len(scenes)})")
        else:
            logger.info(f"[智能分页] 没有场景需要分页")

        return storyboard

    async def _optimize_with_llm(
        self,
        storyboard: Dict,
        course_json: Dict,
        progress_callback: Optional[callable] = None
    ) -> Dict:
        """
        使用LLM优化分镜的讲解词和标题

        优化内容:
        - 讲解词: 转换为自然教学语言
        - 标题: 提取更具体的知识点名称
        """
        from shared.llm_client import LLMRequest, LLMResponse

        scenes = storyboard.get("scenes", [])
        if not scenes:
            return storyboard

        # 准备场景摘要（优化前几帧）
        scenes_summary = []
        max_optimize = min(len(scenes), 8)  # 最多优化8帧

        for i in range(max_optimize):
            scene = scenes[i]
            scenes_summary.append(f"""
{i+1}. 场景ID: {scene['sceneID']}
   类型: {scene['slideType']}
   当前标题: {scene['frameTitle']}
   当前讲解词: {scene['narration'][:80]}...
""")

        # 构建提示词
        course_title = course_json.get("title", "")

        prompt = f"""# 任务
你是一位经验丰富的初中数学教师，需要优化课程视频的分镜脚本。

# 课程信息
标题: {course_title}

# 当前分镜（需要优化）
{chr(10).join(scenes_summary)}

# 优化要求
1. **讲解词优化**:
   - 转换为自然的教学语言，使用"同学们"、"接下来"、"注意"等教学用语
   - 语气亲切自然，适合TTS朗读
   - 保持内容准确，只优化表达方式
   - 控制在120字以内

2. **标题优化**:
   - 提取知识点的具体名称
   - 简洁明了，6-12字
   - 避免使用"知识点1"这样的通用标题

# 输出格式（纯JSON，不要其他内容）
```json
{{
  "optimized_scenes": [
    {{
      "sceneID": "s1",
      "optimizedTitle": "优化后的标题",
      "optimizedNarration": "优化后的讲解词"
    }},
    {{
      "sceneID": "s2",
      "optimizedTitle": "优化后的标题",
      "optimizedNarration": "优化后的讲解词"
    }}
  ]
}}
```

请开始优化:"""

        # 调用LLM
        try:
            request = LLMRequest(
                messages=[{"role": "user", "content": prompt}],
                temperature=0.1,
                max_tokens=16000
            )

            logger.info(f"[混合模式] 调用LLM优化 {max_optimize} 帧分镜...")
            response: LLMResponse = await self.llm_client.call(request)

            if not response.success:
                logger.error(f"[混合模式] LLM优化失败: {response.error}")
                return storyboard

            # 解析响应
            from shared.utils import extract_json

            result = extract_json(response.content)
            if not result or "optimized_scenes" not in result:
                logger.warning("[混合模式] LLM响应解析失败，返回原始分镜")
                return storyboard

            # 应用优化结果
            optimized_scenes_dict = {s["sceneID"]: s for s in result["optimized_scenes"]}

            for scene in storyboard["scenes"]:
                scene_id = scene["sceneID"]
                if scene_id in optimized_scenes_dict:
                    opt = optimized_scenes_dict[scene_id]
                    # 更新标题和讲解词
                    optimized_title = opt.get("optimizedTitle", scene["frameTitle"])
                    # 确保标题简洁
                    scene["frameTitle"] = self._ensure_concise_title(optimized_title, scene.get("slideType", ""))
                    scene["narration"] = opt.get("optimizedNarration", scene["narration"])

            logger.info(f"[混合模式] LLM优化完成: {len(optimized_scenes_dict)}/{len(scenes)} 帧已优化")
            return storyboard

        except Exception as e:
            logger.error(f"[混合模式] LLM优化异常: {e}")
            # 出错时返回原始分镜
            return storyboard

    def _add_title_scene(self, title: str, grade: str, chapter: str):
        """添加标题页"""
        self.scene_counter += 1
        scene = LightweightScene(
            sceneID=f"s{self.scene_counter}",
            frameTitle=title,
            mainContent=f"{grade}\n{chapter}",
            narration=f"同学们好，今天我们来学习{chapter}。",
            slideType="title",
            needsDiagram=False
        )
        self.scenes.append(scene)
        logger.debug(f"[轻量分镜] 添加标题页: s{self.scene_counter}")

    def _add_intro_scene(self, name: str, content: str):
        """添加导入帧"""
        self.scene_counter += 1
        scene = LightweightScene(
            sceneID=f"s{self.scene_counter}",
            frameTitle="情境导入",
            mainContent=self._format_content(content),
            narration=self._extract_narration(content, max_length=150),
            slideType="intro",
            needsDiagram=False
        )
        self.scenes.append(scene)
        logger.debug(f"[轻量分镜] 添加导入帧: s{self.scene_counter}")

    def _add_objective_scene(self, name: str, content: str):
        """添加学习目标帧"""
        self.scene_counter += 1
        scene = LightweightScene(
            sceneID=f"s{self.scene_counter}",
            frameTitle="学习目标",
            mainContent=self._format_content(content),
            narration=self._extract_narration(content, max_length=150),
            slideType="objective",
            needsDiagram=False
        )
        self.scenes.append(scene)
        logger.debug(f"[轻量分镜] 添加学习目标帧: s{self.scene_counter}")

    def _add_concept_scenes(self, name: str, content: str):
        """
        添加知识点讲解帧（智能分段版）

        改进：
        1. 检测是否有明确子标题（###标记），有就拆分（不设长度限制）
        2. 如果没有子标题但内容过长（>CONTENT_SPLIT_THRESHOLD字），按段落智能分段
        3. 为每个子段落生成独立的narration
        4. 确保每个分段都有完整的讲解
        """
        content_length = len(content)

        # 检测是否有子标题（###标记）
        subsections = self._split_by_subsections(content)

        if len(subsections) > 1:
            # 有明确子标题，进行拆分（不设长度限制）
            logger.info(f"[智能分段] {name} 检测到 {len(subsections)} 个子标题，进行拆分")

            for sub_title, sub_content in subsections:
                self.scene_counter += 1
                scene_id = f"s{self.scene_counter}"

                # 为子内容生成独立的narration
                narration = self._extract_narration_for_subsection(
                    name, sub_title, sub_content, max_length=200
                )

                # 确保标题简洁
                chunk_title = self._ensure_concise_title(f"{name} - {sub_title}" if sub_title else name, "concept")
                scene = LightweightScene(
                    sceneID=scene_id,
                    frameTitle=chunk_title,
                    mainContent=self._format_content(sub_content),
                    narration=narration,
                    slideType="concept",
                    needsDiagram=self._detect_needs_diagram(sub_content)
                )
                self.scenes.append(scene)
                logger.debug(f"[智能分段] 添加子场景: {scene_id}, 标题: {chunk_title}")
        else:
            # 没有子标题，使用单个场景
            self.scene_counter += 1

            # 如果内容过长（超过拆分阈值），需要智能拆分内容
            if content_length > self.CONTENT_SPLIT_THRESHOLD:
                # 尝试按段落智能拆分内容
                content_chunks = self._split_long_content_by_structure(content, max_segments=5)

                if len(content_chunks) > 1:
                    # 内容成功拆分，为每个chunk创建场景
                    # 保存基础场景编号，用于生成子场景ID（如 s4a, s4b）
                    base_scene_num = self.scene_counter

                    for i, chunk in enumerate(content_chunks):
                        if i == 0:
                            # 第一个场景使用原ID
                            scene_id = f"s{base_scene_num}"
                        else:
                            # 后续场景使用字母后缀（s4a, s4b...）
                            self.scene_counter += 1
                            scene_id = f"s{base_scene_num}{chr(96+i)}"

                        # 为每个chunk生成独立的narration
                        chunk_narration = self._extract_narration(chunk, max_length=200)

                        # 提取chunk的标题（从第一行或前50字）
                        raw_chunk_title = self._extract_chunk_title(chunk, name, i+1)
                        # 确保标题简洁
                        chunk_title = self._ensure_concise_title(raw_chunk_title, "concept")

                        scene = LightweightScene(
                            sceneID=scene_id,
                            frameTitle=chunk_title,
                            mainContent=self._format_content(chunk),
                            narration=chunk_narration,
                            slideType="concept",
                            needsDiagram=self._detect_needs_diagram(chunk)
                        )
                        self.scenes.append(scene)
                        logger.debug(f"[智能分段] 添加分段场景: {scene_id}, {chunk_title}")
                else:
                    # 内容无法拆分，保持单个场景
                    # 确保标题简洁
                    concise_title = self._ensure_concise_title(name, "concept")
                    scene = LightweightScene(
                        sceneID=f"s{self.scene_counter}",
                        frameTitle=concise_title,
                        mainContent=self._format_content(content),
                        narration=self._extract_narration(content, max_length=200),
                        slideType="concept",
                        needsDiagram=self._detect_needs_diagram(content)
                    )
                    self.scenes.append(scene)
                    logger.debug(f"[轻量分镜] 添加知识点帧: s{self.scene_counter}, 标题: {concise_title}")
            else:
                # 正常单个场景
                # 确保标题简洁
                concise_title = self._ensure_concise_title(name, "concept")
                scene = LightweightScene(
                    sceneID=f"s{self.scene_counter}",
                    frameTitle=concise_title,
                    mainContent=self._format_content(content),
                    narration=self._extract_narration(content, max_length=150),
                    slideType="concept",
                    needsDiagram=self._detect_needs_diagram(content)
                )
                self.scenes.append(scene)
                logger.debug(f"[轻量分镜] 添加知识点帧: s{self.scene_counter}, 标题: {concise_title}")

    def _clean_example_title(self, name: str) -> str:
        """
        清理例题标题，确保格式简洁

        规则：
        1. 如果包含冒号，只保留冒号前的部分
        2. 如果标题超过12个字，截断到12字
        3. 去除多余空格

        Args:
            name: 原始标题

        Returns:
            清理后的标题
        """
        if not name:
            return "例题"

        # 清理空格
        name = name.strip()

        # 如果包含冒号，只保留冒号前的部分
        if '：' in name:
            name = name.split('：')[0].strip()
        elif ':' in name:
            name = name.split(':')[0].strip()

        # 如果标题超过12个字，截断（保留"例题1"这样的格式）
        if len(name) > 12:
            # 尝试提取"例题X"或"典例精讲X"格式
            import re
            match = re.search(r'(例题|典例精讲)[\d一二三四五六七八九十]+', name)
            if match:
                name = match.group(0)
            else:
                name = name[:12]

        return name

    def _add_example_scenes(self, name: str, content: str):
        """
        添加例题帧（智能分段版，支持续页拆分）

        改进：
        1. 检测是否有多道例题（有明确标记就拆分）
        2. 检测单个例题是否有"===续页==="标记，如有则拆分为2页
        3. 如果有多道题，为每题创建独立场景
        4. 每题生成完整的narration
        5. 清理标题格式（去除题目内容）
        """
        # 清理标题（先使用原有清理方法）
        name = self._clean_example_title(name)
        # 再确保标题简洁（统一处理）
        name = self._ensure_concise_title(name, "example")

        # 首先检查是否有续页标记
        if "===续页===" in content:
            # 单个复杂例题需要拆分为2页
            logger.info(f"[智能分段] {name} 检测到续页标记，进行拆分")
            parts = content.split("===续页===", 1)

            # 第1页：题目+思路引导
            self.scene_counter += 1
            scene_id_1 = f"s{self.scene_counter}"
            scene_1 = LightweightScene(
                sceneID=scene_id_1,
                frameTitle=name,  # 已经被_ensure_concise_title处理过
                mainContent=self._format_content(parts[0].strip()),
                narration=self._extract_narration(parts[0].strip(), max_length=120),
                slideType="example",
                needsDiagram=False
            )
            self.scenes.append(scene_1)
            logger.debug(f"[智能分段] 添加例题第1页: {scene_id_1}")

            # 第2页：完整步骤+答案+易错提醒
            self.scene_counter += 1
            scene_id_2 = f"s{self.scene_counter}"
            # 确保"（续）"标题也简洁
            continue_title = self._ensure_concise_title(f"{name}（续）", "example")
            scene_2 = LightweightScene(
                sceneID=scene_id_2,
                frameTitle=continue_title,
                mainContent=self._format_content(parts[1].strip()),
                narration=self._extract_narration(parts[1].strip(), max_length=100),
                slideType="example_continue",
                needsDiagram=False
            )
            self.scenes.append(scene_2)
            logger.debug(f"[智能分段] 添加例题第2页: {scene_id_2}")
            return

        # 检查是否有多个例题
        examples = self._split_examples(content)

        if len(examples) > 1:
            # 有多个例题，进行拆分（不设长度限制）
            logger.info(f"[智能分段] {name} 检测到 {len(examples)} 道例题，进行拆分")

            for i, (example_title, example_content) in enumerate(examples):
                self.scene_counter += 1
                scene_id = f"s{self.scene_counter}"

                # 为每个例题生成独立的narration
                narration = self._extract_narration_for_example(
                    name, example_title, example_content, i + 1, len(examples)
                )

                # 确保标题简洁
                full_title = f"{name} - {example_title}" if example_title else name
                concise_title = self._ensure_concise_title(full_title, "example")

                scene = LightweightScene(
                    sceneID=scene_id,
                    frameTitle=concise_title,
                    mainContent=self._format_content(example_content),
                    narration=narration,
                    slideType="example",
                    needsDiagram=self._detect_needs_diagram(example_content)
                )
                self.scenes.append(scene)
                logger.debug(f"[智能分段] 添加例题场景: {scene_id}, {concise_title}")
        else:
            # 只有一道例题或无法拆分，保持单个场景
            self.scene_counter += 1
            # 确保标题简洁（name已经被_ensure_concise_title处理过）
            scene = LightweightScene(
                sceneID=f"s{self.scene_counter}",
                frameTitle=name,  # 已经被_ensure_concise_title处理过
                mainContent=self._format_content(content),
                narration=self._extract_narration(content, max_length=200),
                slideType="example",
                needsDiagram=self._detect_needs_diagram(content)
            )
            self.scenes.append(scene)
            logger.debug(f"[轻量分镜] 添加例题帧: s{self.scene_counter}, 标题: {name}")

    def _add_warning_scene(self, name: str, content: str):
        """添加易错点帧"""
        self.scene_counter += 1
        scene = LightweightScene(
            sceneID=f"s{self.scene_counter}",
            frameTitle="易错点提醒",
            mainContent=self._format_content(content),
            narration=self._extract_narration(content, max_length=150),
            slideType="warning",
            needsDiagram=False
        )
        self.scenes.append(scene)
        logger.debug(f"[轻量分镜] 添加易错点帧: s{self.scene_counter}")

    def _add_practice_scene(self, name: str, content: str):
        """添加练习帧"""
        self.scene_counter += 1
        scene = LightweightScene(
            sceneID=f"s{self.scene_counter}",
            frameTitle="随堂练习",
            mainContent=self._format_content(content),
            narration=self._extract_narration(content, max_length=150),
            slideType="practice",
            needsDiagram=False
        )
        self.scenes.append(scene)
        logger.debug(f"[轻量分镜] 添加练习帧: s{self.scene_counter}")

    def _add_summary_scene(self, name: str, content: str):
        """添加总结帧"""
        self.scene_counter += 1
        scene = LightweightScene(
            sceneID=f"s{self.scene_counter}",
            frameTitle="课堂小结",
            mainContent=self._format_content(content),
            narration=self._extract_narration(content, max_length=150),
            slideType="summary",
            needsDiagram=False
        )
        self.scenes.append(scene)
        logger.debug(f"[轻量分镜] 添加总结帧: s{self.scene_counter}")

    def _add_extend_scene(self, name: str, content: str):
        """添加拓展帧"""
        self.scene_counter += 1
        scene = LightweightScene(
            sceneID=f"s{self.scene_counter}",
            frameTitle="课后拓展",
            mainContent=self._format_content(content),
            narration=self._extract_narration(content, max_length=150),
            slideType="extend",
            needsDiagram=False
        )
        self.scenes.append(scene)
        logger.debug(f"[轻量分镜] 添加拓展帧: s{self.scene_counter}")

    # ==================== 智能分页方法 ====================

    def _parse_content_structure(self, content: str) -> Dict[str, int]:
        """
        解析场景内容的结构（2025升级版 - 结构化分析）

        Args:
            content: 场景的mainContent文本

        Returns:
            结构化统计：{
                'steps': 步骤点数量,
                'errors': 易错点数量,
                'examples': 示例数量,
                'formulas': 公式数量,
                'lines': 文本行数
            }
        """
        import re

        # 检测步骤点（中文数字或阿拉伯数字编号）
        steps = len(re.findall(r'[一二三四五六七八九十\d]+[\.\、、]|步骤\s*[一二三四五六七八九十\d]+', content))
        steps += len(re.findall(r'\(\d+\)|步骤\s*\(\d+\)', content))

        # 检测易错点
        errors = len(re.findall(r'易错点|易错提醒|注意|注意点', content))

        # 检测示例
        examples = len(re.findall(r'例如|示例|譬如|比如', content))

        # 检测公式
        formulas = content.count('$') // 2

        # 检测行数
        lines = len([line for line in content.split('\n') if line.strip()])

        return {
            'steps': steps,
            'errors': errors,
            'examples': examples,
            'formulas': formulas,
            'lines': lines
        }

    def _extract_base_scene_id(self, scene_id: str) -> str:
        """
        提取场景的基础ID（去除字母后缀）

        例如：
        - s19 → s19
        - s19a → s19
        - s19ab → s19
        - s19abc → s19

        Args:
            scene_id: 场景ID

        Returns:
            基础场景ID
        """
        import re
        match = re.match(r'(s\d+)', scene_id)
        return match.group(1) if match else scene_id

    def _get_safe_height_limit(self, scene_type: str) -> int:
        """
        根据场景类型获取安全高度限制（基于LaTeX实际渲染数据）

        使用类级别定义的统一页面容量标准

        Args:
            scene_type: 场景类型

        Returns:
            安全高度限制（pt）
        """
        # 引用类级别定义的统一常量
        logger.debug(f"[高度限制] {scene_type} -> {self.SAFE_HEIGHT_LIMIT_PT}pt ({self.MAX_LINES_PER_PAGE}行标准)")
        return self.SAFE_HEIGHT_LIMIT_PT

    def _should_paginate(self, scene: Dict, scene_type: str) -> tuple[bool, str]:
        """
        判断场景是否需要分页（基于精确标准的差异化触发条件）

        Args:
            scene: 场景数据
            scene_type: 场景类型

        Returns:
            (是否需要分页, 触发原因)
        """
        content = scene.get('mainContent', '')
        scene_id = scene.get('sceneID', '')
        frame_title = scene.get('frameTitle', '')

        # 【2025-03-31 升级】基于场景类型的差异化触发条件

        # ============ 不拆分的类型（但需检查高度） ============
        if scene_type in ['intro', 'objective', 'extend']:
            # 【2025-04-04 修复】添加高度检查，防止内容溢出
            estimated_height, safety_mult = self._estimate_content_height_conservative(content)

            if estimated_height > self.PRIMARY_HEIGHT_THRESHOLD:
                # 内容过长，必须拆分以避免溢出
                reason = f"{scene_type}类型内容过长（估算{estimated_height:.1f}pt超过阈值{self.PRIMARY_HEIGHT_THRESHOLD}pt），需拆分"
                logger.warning(f"[智能分页] ⚠️ {scene_id} {reason}，需要分页")
                return True, reason
            else:
                logger.info(f"[智能分页] {scene_id} 类型={scene_type}，高度合适，不拆分")
                return False, None

        # ============ 已拆分过的续页：仍需检查高度 ============
        has_letter_suffix = bool(re.search(r'\d[a-z]$', scene_id))
        if has_letter_suffix:
            # 【2025-04-04 修复】续页也需要检查高度，防止溢出
            estimated_height, safety_mult = self._estimate_content_height_conservative(content)

            if estimated_height > self.PRIMARY_HEIGHT_THRESHOLD:
                # 续页内容过长，需要再次拆分
                reason = f"续页内容过长（估算{estimated_height:.1f}pt超过阈值{self.PRIMARY_HEIGHT_THRESHOLD}pt），需再次拆分"
                logger.warning(f"[智能分页] ⚠️ {scene_id} {reason}，需要分页")
                return True, reason

            logger.debug(f"[智能分页] {scene_id} 续页高度合适（估算{estimated_height:.1f}pt），不再分页")
            return False, None

        # ============ 类型特定的触发条件 ============
        structure = self._parse_content_structure(content)
        logger.info(f"[智能分页] {scene_id} 结构分析: 步骤={structure['steps']}, 易错={structure['errors']}, 示例={structure['examples']}, 公式={structure['formulas']}, 行数={structure['lines']}")

        if scene_type == 'concept':
            # concept：使用保守估算 + 双阈值判断
            # 字符数不可靠（公式、符号占用更多空间）
            estimated_height, safety_mult = self._estimate_content_height_conservative(content)

            # 主判断：保守估算超过主阈值
            if estimated_height > self.PRIMARY_HEIGHT_THRESHOLD:
                reason = f"估算{estimated_height}pt > 主阈值{self.PRIMARY_HEIGHT_THRESHOLD}pt"
                logger.info(f"[智能分页] {scene_id} {reason}")
                return True, reason

            # 次判断：高不确定性场景 + 超过次阈值
            if safety_mult > 1.2 and estimated_height > self.SECONDARY_HEIGHT_THRESHOLD:
                reason = f"估算{estimated_height}pt > 次阈值{self.SECONDARY_HEIGHT_THRESHOLD}pt (不确定系数{safety_mult:.2f})"
                logger.warning(f"[智能分页] {scene_id} {reason}")
                return True, reason

            logger.info(f"[智能分页] {scene_id} 估算{estimated_height}pt，不需要拆分")
            return False, None

        elif scene_type == 'example':
            # example：基于语义边界的智能拆分
            #
            # 【核心原则】
            # 1. 语义完整性优先：在题目|思路|步骤|答案的逻辑边界处拆分
            # 2. 容量适配：每帧必须适配Beamer单页容量（约224pt）
            # 3. 观众体验：即使拆分，也要保证逻辑连贯性
            #
            # 【拆分触发条件】
            # - 步骤数≥6：需要拆分（单帧无法容纳完整解答过程）
            # - 步骤数≥4且公式数≥5：需要拆分（公式占用大量空间）
            # - 简单例题（≤3步、≤2公式）：不拆分，保持语义单元完整

            if structure['steps'] >= 6:
                reason = f"步骤点过多({structure['steps']}个)，需在语义边界拆分"
                logger.warning(f"[智能分页] ⚠️ {scene_id} {reason}，需要分页")
                return True, reason
            if structure['steps'] >= 4 and structure['formulas'] >= 5:
                reason = f"步骤多({structure['steps']})且公式多({structure['formulas']}个)，需在语义边界拆分"
                logger.warning(f"[智能分页] ⚠️ {scene_id} {reason}，需要分页")
                return True, reason
            # 简单例题：保持语义单元完整，不拆分
            logger.info(f"[智能分页] {scene_id} 例题复杂度适中，保持语义单元完整，暂不拆分")
            return False, None

        elif scene_type == 'warning':
            # warning：基于易错点分组的语义边界拆分
            #
            # 【拆分策略】
            # - 易错点≥3个：先估算高度，再决定是否拆分
            # - 简单易错点（≤2个）：保持语义完整，不拆分
            # - 单个易错点内容过长：也要拆分
            if structure['errors'] >= 3:
                # 【优化】先估算高度，再决定拆分方式
                estimated_height, safety_mult = self._estimate_content_height_conservative(content)

                # 主判断：高度超过主阈值
                if estimated_height > self.PRIMARY_HEIGHT_THRESHOLD:
                    reason = f"易错点过多({structure['errors']}个)且估算高度{estimated_height:.1f}pt超过阈值{self.PRIMARY_HEIGHT_THRESHOLD}pt，需按语义分组拆分"
                    logger.warning(f"[智能分页] ⚠️ {scene_id} {reason}，需要分页")
                    return True, reason

                # 次判断：高不确定性场景 + 超过次阈值
                if safety_mult > 1.2 and estimated_height > self.SECONDARY_HEIGHT_THRESHOLD:
                    reason = f"易错点过多({structure['errors']}个)且估算高度{estimated_height:.1f}pt超过次阈值{self.SECONDARY_HEIGHT_THRESHOLD}pt(不确定系数{safety_mult:.2f})，需按语义分组拆分"
                    logger.warning(f"[智能分页] ⚠️ {scene_id} {reason}，需要分页")
                    return True, reason

                # 易错点多但高度未超阈值：仍需拆分（避免单帧易错点过多）
                reason = f"易错点过多({structure['errors']}个，估算高度{estimated_height:.1f}pt)，需按语义分组拆分"
                logger.warning(f"[智能分页] ⚠️ {scene_id} {reason}，需要分页")
                return True, reason

            # 检查步骤数（很多易错点用(1)(2)格式）
            if structure['steps'] >= 3:
                estimated_height, safety_mult = self._estimate_content_height_conservative(content)
                if estimated_height > self.PRIMARY_HEIGHT_THRESHOLD:
                    reason = f"步骤点过多({structure['steps']}个)且估算高度{estimated_height:.1f}pt超过阈值，需按语义分组拆分"
                    logger.warning(f"[智能分页] ⚠️ {scene_id} {reason}，需要分页")
                    return True, reason

            logger.info(f"[智能分页] {scene_id} 易错点数量合适，保持语义完整，不拆分")
            return False, None

        elif scene_type == 'practice':
            # practice：基于题目分组的语义边界拆分
            #
            # 【拆分策略】
            # - 题目≥3道：先估算高度，再决定是否拆分
            # - 简单练习（≤2题）：保持语义完整，不拆分
            # - 单题内容过长：即使题目少也要拆分
            question_count = content.count('\\textbf{')
            if question_count == 0:
                question_count = len(re.findall(r'\d+\.\s+', content))

            if question_count >= 3:
                # 【优化】先估算高度，再决定拆分方式
                estimated_height, safety_mult = self._estimate_content_height_conservative(content)

                # 主判断：高度超过主阈值
                if estimated_height > self.PRIMARY_HEIGHT_THRESHOLD:
                    reason = f"题目过多({question_count}题)且估算高度{estimated_height:.1f}pt超过阈值{self.PRIMARY_HEIGHT_THRESHOLD}pt，需按题分组拆分（每2题一页）"
                    logger.warning(f"[智能分页] ⚠️ {scene_id} {reason}，需要分页")
                    return True, reason

                # 次判断：高不确定性场景 + 超过次阈值
                if safety_mult > 1.2 and estimated_height > self.SECONDARY_HEIGHT_THRESHOLD:
                    reason = f"题目过多({question_count}题)且估算高度{estimated_height:.1f}pt超过次阈值{self.SECONDARY_HEIGHT_THRESHOLD}pt(不确定系数{safety_mult:.2f})，需按题分组拆分"
                    logger.warning(f"[智能分页] ⚠️ {scene_id} {reason}，需要分页")
                    return True, reason

                # 题目多但高度未超阈值：仍需拆分（避免单帧题目过多）
                reason = f"题目过多({question_count}题，估算高度{estimated_height:.1f}pt)，需按题分组拆分（每2题一页）"
                logger.warning(f"[智能分页] ⚠️ {scene_id} {reason}，需要分页")
                return True, reason

            # 题目少但可能单题内容过长：检查高度
            if question_count > 0:
                estimated_height, safety_mult = self._estimate_content_height_conservative(content)
                if estimated_height > self.PRIMARY_HEIGHT_THRESHOLD:
                    reason = f"单题内容过长（估算高度{estimated_height:.1f}pt超过阈值{self.PRIMARY_HEIGHT_THRESHOLD}pt），需拆分"
                    logger.warning(f"[智能分页] ⚠️ {scene_id} {reason}，需要分页")
                    return True, reason

            logger.info(f"[智能分页] {scene_id} 题目数量({question_count}题)和高度合适，保持语义完整，不拆分")
            return False, None

        elif scene_type == 'summary':
            # summary：基于要点分组的语义边界拆分
            #
            # 【拆分策略】
            # - 要点≥5个：先估算高度，再决定是否拆分
            # - 简单小结（≤4个要点）：保持语义完整，不拆分
            # - 单个要点内容过长：也要拆分
            section_count = content.count('\\textbf{')
            if section_count >= 5:
                # 【优化】先估算高度，再决定拆分方式
                estimated_height, safety_mult = self._estimate_content_height_conservative(content)

                # 主判断：高度超过主阈值
                if estimated_height > self.PRIMARY_HEIGHT_THRESHOLD:
                    reason = f"要点过多({section_count}个)且估算高度{estimated_height:.1f}pt超过阈值{self.PRIMARY_HEIGHT_THRESHOLD}pt，需按语义分组拆分"
                    logger.warning(f"[智能分页] ⚠️ {scene_id} {reason}，需要分页")
                    return True, reason

                # 次判断：高不确定性场景 + 超过次阈值
                if safety_mult > 1.2 and estimated_height > self.SECONDARY_HEIGHT_THRESHOLD:
                    reason = f"要点过多({section_count}个)且估算高度{estimated_height:.1f}pt超过次阈值{self.SECONDARY_HEIGHT_THRESHOLD}pt(不确定系数{safety_mult:.2f})，需按语义分组拆分"
                    logger.warning(f"[智能分页] ⚠️ {scene_id} {reason}，需要分页")
                    return True, reason

                # 要点多但高度未超阈值：仍需拆分（避免单帧要点过多）
                reason = f"要点过多({section_count}个，估算高度{estimated_height:.1f}pt)，需按语义分组拆分"
                logger.warning(f"[智能分页] ⚠️ {scene_id} {reason}，需要分页")
                return True, reason

            # 要点少但可能单个要点内容过长：检查高度
            if section_count > 0:
                estimated_height, safety_mult = self._estimate_content_height_conservative(content)
                if estimated_height > self.PRIMARY_HEIGHT_THRESHOLD:
                    reason = f"单个要点内容过长（估算高度{estimated_height:.1f}pt超过阈值{self.PRIMARY_HEIGHT_THRESHOLD}pt），需拆分"
                    logger.warning(f"[智能分页] ⚠️ {scene_id} {reason}，需要分页")
                    return True, reason

            logger.info(f"[智能分页] {scene_id} 要点数量({section_count}个)和高度合适，保持语义完整，不拆分")
            return False, None

        # 默认：不需要分页
        logger.info(f"[智能分页] {scene_id} 类型={scene_type}，不需要拆分")
        return False, None

    def _detect_nesting_depth(self, content: str) -> int:
        """
        检测内容的最深嵌套深度

        Args:
            content: LaTeX内容

        Returns:
            嵌套深度（0-6）
        """
        import re
        max_depth = 0
        current_depth = 0

        for line in content.split('\n'):
            stripped = line.strip()
            # 检测 \begin{itemize} 或 \begin{enumerate}
            if re.search(r'\\begin\{(itemize|enumerate)\}', stripped):
                current_depth += 1
                max_depth = max(max_depth, current_depth)
            # 检测 \end{itemize} 或 \end{enumerate}
            elif re.search(r'\\end\{(itemize|enumerate)\}', stripped):
                current_depth -= 1

        return min(max_depth, 6)  # 限制最大深度为6

    def _classify_example_complexity(self, content: str) -> str:
        """
        判断例题复杂度（本地规则，作为LLM判断的辅助）

        返回: "simple" | "medium" | "complex"

        判断标准：
        - simple: ≤3步、≤2个公式、无嵌套括号
        - medium: 4-6步、3-5个公式、简单嵌套
        - complex: >6步或>5个公式、复杂嵌套
        """
        # 检测步骤数
        steps_count = len(re.findall(r'[①②③④⑤⑥⑦⑧⑧⑨⑩]|(\d+)\.|\(\d+\))', content))
        steps_count += len(re.findall(r'[1-9]\.\s+', content))  # "1. " 格式

        # 检测公式数
        formula_count = content.count('$') // 2

        # 检测嵌套括号
        has_nested_paren = '(+(' in content or '[(' in content
        has_simple_nested = re.search(r'\([^)]+\([^)]+\)', content)  # (a+b)

        # 检测多种运算符
        has_multiple_operations = any(op in content for op in ['+(', '-(', '×(', '÷(', '*('])

        # 判断复杂度
        if formula_count <= 2 and steps_count <= 3 and not has_nested_paren and not has_multiple_operations:
            return "simple"
        elif formula_count <= 5 and steps_count <= 6 and not has_multiple_operations:
            return "medium"
        else:
            return "complex"

    def _ensure_concise_title(self, title: str, scene_type: str = "") -> str:
        """
        确保标题简洁，避免长段落

        规则：
        - 标题最多20个汉字
        - 如果超过长度，智能截取核心内容
        - 移除冗余前缀（如"知识点详解 - "等）

        Args:
            title: 原始标题
            scene_type: 场景类型

        Returns:
            简洁后的标题
        """
        if not title:
            return "标题"

        # 移除常见冗余前缀
        redundant_prefixes = [
            "知识点详解 - ",
            "知识点讲解 - ",
            "概念讲解 - ",
            "详细讲解 - ",
            "知识点 - ",
        ]

        result = title
        for prefix in redundant_prefixes:
            if result.startswith(prefix):
                result = result[len(prefix):]
                logger.debug(f"[简洁标题] 移除前缀 '{prefix}': {title} -> {result}")
                break

        # 移除定义式的长内容（如"定义:仅符号不同的两个数..."）
        # 这类内容应该放在mainContent中，而不是标题
        if "定义:" in result or "性质:" in result:
            # 保留冒号前的核心词
            parts = re.split(r'[:：]', result, 1)
            result = parts[0].strip()
            logger.debug(f"[简洁标题] 移除定义式内容: {title} -> {result}")
        elif len(result) > 20:
            # 检测是否有分隔符，取第一部分
            if ' - ' in result:
                result = result.split(' - ')[0]
            elif '——' in result:
                result = result.split('——')[0]
            elif '_' in result:
                result = result.split('_')[0]
            else:
                # 尝试在句号或逗号处截断
                for sep in ['。', '，', ',', '、', ' ']:
                    if sep in result:
                        result = result.split(sep)[0]
                        break

        # 硬性长度限制：最多20个字符
        max_title_length = 20
        if len(result) > max_title_length:
            truncated = result[:max_title_length]
            logger.warning(f"[简洁标题] ⚠️ 标题过长({len(result)}字符)，截断: {result} -> {truncated}")
            result = truncated

        return result if result else "标题"

    def _estimate_content_height(self, content: str) -> int:
        """
        估算纯文本内容的LaTeX渲染高度（单位：pt）

        2025升级版：基于mainContent纯文本特征估算
        - 行数（主要因素）
        - 字符数
        - 结构元素（编号、公式符号）
        - 层次标记（缩进、括号）
        - block环境额外空间

        Args:
            content: mainContent纯文本内容

        Returns:
            估算高度（pt）
        """
        # 基础行数计算（提高系数以减少溢出）
        lines = [line for line in content.split('\n') if line.strip()]
        line_count = len(lines)
        base_height = line_count * 28  # 每行约28pt（更保守）

        # 字符密度加成（长行需要更多垂直空间）
        # 宽度限制：27字符/行（基于LaTeX实际渲染数据）
        avg_chars_per_line = sum(len(line) for line in lines) / max(line_count, 1)
        if avg_chars_per_line > 27:
            # 长行可能导致换行，增加高度
            density_penalty = (avg_chars_per_line - 27) * 4
        else:
            density_penalty = 0

        # 公式加成（$符号检测）
        formula_count = content.count('$') // 2
        formula_penalty = formula_count * 18  # 每个公式约18pt（提高）

        # 结构元素加成（编号、括号等）
        struct_count = 0
        # 中文数字编号
        struct_count += len(re.findall(r'[一二三四五六七八九十]+[、．.]', content))
        # 阿拉伯数字编号
        struct_count += len(re.findall(r'\d+[、．.)\]]', content))
        # 括号标记
        struct_count += len(re.findall(r'[【\[\(（][^\]\)）]+[】\]\)）]', content))
        struct_penalty = struct_count * 12  # 每个结构元素约12pt（提高）

        # block环境加成（Beamer block有额外padding）
        # 检测可能的block标题（有类似"标题："的格式）
        block_count = content.count('：') + content.count(':')
        block_penalty = block_count * 8  # 每个可能的block增加8pt（提高）

        # 复杂度乘数（内容越多，额外边距越大）
        complexity_factor = 1.0 + (line_count / 100) * 0.3  # 每100行增加30%边距

        # 安全边距
        safety_margin = int(40 * complexity_factor)

        # 总高度
        total_height = int(base_height + density_penalty + formula_penalty + struct_penalty + block_penalty + safety_margin)

        logger.debug(f"[高度估算] 行数={line_count}×28={base_height}pt, 密度+{density_penalty:.0f}pt, 公式+{formula_penalty}pt, 结构+{struct_penalty}pt, block+{block_penalty}pt, 边距+{safety_margin}pt, 总计={total_height}pt")

        return total_height

    def _estimate_content_height_conservative(self, content: str) -> tuple[int, float]:
        """
        保守估算内容高度（倾向高估，避免溢出）

        在基础估算上增加安全系数，使用不确定性检测

        Args:
            content: LaTeX内容

        Returns:
            (估算高度pt, 安全系数)
        """
        # 基础估算
        base_height = self._estimate_content_height(content)

        # 默认安全系数1.3（保守）
        safety_multiplier = 1.3

        # 使用不确定性检测函数
        is_uncertain, uncertainty_reasons = self._has_high_uncertainty(content)

        if is_uncertain:
            # 根据不确定性因素数量加成
            uncertainty_bonus = min(len(uncertainty_reasons) * 0.1, 0.3)  # 最多30%加成
            safety_multiplier += uncertainty_bonus
            logger.debug(f"[保守估算] 检测到高不确定性({len(uncertainty_reasons)}个因素)，加成{uncertainty_bonus:.0%}")

        # 限制最大安全系数为2.0
        safety_multiplier = min(safety_multiplier, 2.0)

        estimated_height = int(base_height * safety_multiplier)

        logger.debug(f"[保守估算] 基础={base_height}pt, 系数={safety_multiplier:.2f}, 估算={estimated_height}pt")

        return estimated_height, safety_multiplier

    def _has_high_uncertainty(self, content: str) -> tuple[bool, list[str]]:
        """
        检测内容是否难以准确估算

        检测7种不确定性模式：
        1. cases环境
        2. 矩阵环境
        3. 嵌套分数
        4. 可变尺寸图片
        5. 多行公式对齐
        6. 堆叠符号
        7. 花括号标注

        Args:
            content: LaTeX内容

        Returns:
            (是否高不确定性, 不确定性原因列表)
        """
        import re

        reasons = []

        # Uncertainty detection patterns
        UNCERTAINTY_PATTERNS = {
            r'\\begin\{cases\}': 'cases_env',
            r'\\begin\{(pmatrix|matrix|bmatrix|vmatrix)\}': 'matrix_env',
            r'\\frac\{[^}]*\\frac': 'nested_fraction',
            r'\\includegraphics\[scale=': 'scalable_image',
            r'\\begin\{align\}': 'multiline_formula',
            r'\\stackrel': 'stacked_symbol',
            r'\\underbrace': 'brace_annotation',
            r'\\overbrace': 'brace_annotation',
            r'\\begin\{array\}': 'array_env',
            r'\\sqrt\{[^}]*\\sqrt': 'nested_sqrt',
        }

        for pattern, desc in UNCERTAINTY_PATTERNS.items():
            if re.search(pattern, content):
                reasons.append(desc)

        # Special detection: long paragraphs without line breaks (possibly dense formulas)
        lines = content.split('\n')
        long_lines = [l for l in lines if len(l) > 80]
        if len(long_lines) > len(lines) * 0.3 and len(content) > 800:
            reasons.append('long_paragraph_no_break')

        # Special detection: unknown LaTeX environments
        known_envs = {
            'itemize', 'enumerate', 'frame', 'block', 'alertblock',
            'exampleblock', 'columns', 'column', 'center', 'flushleft',
            'flushright', 'verbatim', 'quote', 'quotation'
        }
        all_envs = set(re.findall(r'\\begin\{([^}]+)\}', content))
        unknown_envs = all_envs - known_envs
        if unknown_envs:
            reasons.append(f'unknown_env: {", ".join(unknown_envs)}')

        # 判断是否高不确定性
        is_uncertain = len(reasons) >= 2 or any('未知' in r for r in reasons)

        if is_uncertain:
            logger.debug(f"[不确定性检测] 检测到{len(reasons)}个不确定性因素: {reasons}")

        return is_uncertain, reasons

    def _validate_split_quality(self, original_scene: Dict, sub_scenes: list[Dict]) -> tuple[bool, float, list[str]]:
        """
        验证拆分质量

        检查项：
        1. 占位符检测
        2. 内容完整性（子场景总长度不应少于原内容的90%）
        3. 子场景数量合理性（2-5个）
        4. 每个子场景有合理长度（5-25行）

        Args:
            original_scene: 原始场景
            sub_scenes: 拆分后的子场景列表

        Returns:
            (是否通过验证, 质量分数0-1, 问题列表)
        """
        original_content = original_scene.get('mainContent', '')
        issues = []
        score = 1.0

        # 检查1：占位符检测
        placeholder_keywords = ["待补充", "待填充", "待定", "占位", "SceneID:", "内容待补充", "本页内容"]
        for scene in sub_scenes:
            content = scene.get('mainContent', '')
            for keyword in placeholder_keywords:
                if keyword in content:
                    scene_id = scene.get('sceneID', '')
                    issues.append(f"{scene_id}: 包含占位符 '{keyword}'")
                    score -= 0.4

        # 检查2：内容完整性（子场景总长度不应少于原内容的90%）
        total_sub_length = sum(len(s.get('mainContent', '')) for s in sub_scenes)
        original_length = len(original_content)
        if original_length > 0:
            completion_ratio = total_sub_length / original_length
            if completion_ratio < 0.9:
                issues.append(f"内容损失过多: 原{original_length}字符 → 子{total_sub_length}字符 ({completion_ratio:.1%})")
                score -= 0.2

        # 检查3：子场景数量合理性
        sub_scenes_count = len(sub_scenes)
        if sub_scenes_count < 1:
            issues.append(f"子场景数过少: {sub_scenes_count}个")
            score -= 0.1
        elif sub_scenes_count > 5:
            issues.append(f"子场景数过多: {sub_scenes_count}个")
            score -= 0.1

        # 检查4：每个子场景有合理长度
        for scene in sub_scenes:
            content_lines = self._count_content_lines(scene.get('mainContent', ''))
            scene_id = scene.get('sceneID', '')
            if content_lines < 5:
                issues.append(f"{scene_id}: 内容过短({content_lines}行)")
                score -= 0.15
            elif content_lines > 25:
                issues.append(f"{scene_id}: 内容过长({content_lines}行)")
                score -= 0.05

        # 确保分数在0-1之间
        score = max(0.0, min(1.0, score))

        is_valid = score >= 0.6

        if not is_valid:
            logger.warning(f"[质量验证] 失败(得分{score:.2f}): {issues}")
        else:
            logger.info(f"[质量验证] 通过(得分{score:.2f})")

        return is_valid, score, issues

    def _count_content_lines(self, content: str) -> int:
        """
        计算内容的实际行数（非空行）

        Args:
            content: 场景内容

        Returns:
            非空行数
        """
        return len([line for line in content.split('\n') if line.strip()])

    def _merge_scenes(self, scenes_to_merge: list[Dict]) -> Dict:
        """
        合并多个场景为一个

        Args:
            scenes_to_merge: 待合并的场景列表

        Returns:
            合并后的场景
        """
        if not scenes_to_merge:
            return None

        if len(scenes_to_merge) == 1:
            return scenes_to_merge[0]

        first = scenes_to_merge[0]

        # 合并内容
        merged_content = []
        for i, scene in enumerate(scenes_to_merge):
            if i > 0:
                merged_content.append('\n\n')  # 场景间分隔
            merged_content.append(scene.get('mainContent', ''))

        # 合并标题
        merged_title = '、'.join(
            s.get('frameTitle', '') for s in scenes_to_merge if s.get('frameTitle')
        )

        # 合并讲解词
        narrations = [s.get('narration', '') for s in scenes_to_merge if s.get('narration')]
        merged_narration = '。'.join(narrations)
        if merged_narration and not merged_narration.endswith('。'):
            merged_narration += '。'

        merged = {
            'sceneID': first.get('sceneID', ''),
            'frameTitle': merged_title,
            'mainContent': ''.join(merged_content),
            'narration': merged_narration,
            'slideType': first.get('slideType', 'concept'),
            'needsDiagram': any(s.get('needsDiagram', False) for s in scenes_to_merge),
        }

        return merged

    def _cleanup_scene_content(self, scenes: list[Dict]) -> list[Dict]:
        """
        清理场景内容中的占位符和不规范内容

        清理内容：
        1. 规范化LaTeX命令：使用ContentConverter.normalize_latex_commands()
        2. 移除占位符：待补充、待填充、【场景ID】、【标题】、【内容】等
        3. 移除重复内容

        Args:
            scenes: 场景列表

        Returns:
            清理后的场景列表
        """
        import re
        from .content_converter import ContentConverter

        converter = ContentConverter()

        # 占位符模式（包括旧格式和新格式）
        placeholder_patterns = [
            r'【场景ID】.*?\n【标题】.*?\n【内容】.*?(?=\n\n|【场景ID】|$)',
            r'【\n*\n*SceneID:.*?\n*标题.*?\n*内容.*?\n*【?',
            r'【\n*SceneID:.*?】',
            r'SceneID:.*?\n标题.*?\n内容.*?\n',
            r'【.*?待补充.*?】',
            r'【.*?待填充.*?】',
            r'【.*?占位.*?】',
            r'【\s*$',  # 单独的【开头
        ]

        cleaned_scenes = []
        stats = {'latex_normalized': 0, 'placeholders_removed': 0, 'duplicates_removed': 0}

        for scene in scenes:
            content = scene.get('mainContent', '')
            title = scene.get('frameTitle', '')
            narration = scene.get('narration', '')

            # 1. 规范化LaTeX命令（使用ContentConverter）
            original_content = content
            content = converter.normalize_latex_commands(content)
            title = converter.normalize_latex_commands(title)
            if content != original_content:
                stats['latex_normalized'] += 1

            # 2. 移除占位符（包括LLM模仿输出的格式）
            original_content = content
            for pattern in placeholder_patterns:
                content = re.sub(pattern, '', content, flags=re.DOTALL)
                title = re.sub(pattern, '', title, flags=re.DOTALL)
            if content != original_content:
                stats['placeholders_removed'] += 1

            # 3. 移除内容重复（检测连续重复的段落）
            lines = content.split('\n')
            unique_lines = []
            prev_line = None
            duplicate_count = 0
            for line in lines:
                if line.strip() and line == prev_line:
                    duplicate_count += 1
                    continue
                unique_lines.append(line)
                prev_line = line
            content = '\n'.join(unique_lines)
            if duplicate_count > 0:
                stats['duplicates_removed'] += duplicate_count

            # 4. 清理多余空行和首尾空格
            content = re.sub(r'\n{3,}', '\n\n', content)
            content = content.strip()
            title = title.strip()

            # 更新场景
            scene['mainContent'] = content
            scene['frameTitle'] = title
            scene['narration'] = narration

            # 如果清理后内容为空，记录警告
            if not content:
                logger.warning(f"[内容清理] 场景 {scene.get('sceneID')} 清理后内容为空")

            cleaned_scenes.append(scene)

        # 记录清理统计
        logger.info(f"[内容清理] LaTeX规范化: {stats['latex_normalized']}, "
                   f"占位符移除: {stats['placeholders_removed']}, "
                   f"重复移除: {stats['duplicates_removed']}")

        return cleaned_scenes

    def _merge_tiny_scenes(self, scenes: list[Dict], min_lines: int = 10) -> list[Dict]:
        """
        合并过小的子场景，避免碎片化

        Args:
            scenes: 场景列表
            min_lines: 最小行数阈值（默认10行）

        Returns:
            合并后的场景列表
        """
        if not scenes:
            return scenes

        merged = []
        buffer = []
        buffer_lines = 0

        for scene in scenes:
            content_lines = self._count_content_lines(scene.get('mainContent', ''))

            if content_lines < min_lines:
                # 碎片：加入缓冲区
                buffer.append(scene)
                buffer_lines += content_lines

                if buffer_lines >= min_lines:
                    # 缓冲区达标，合并
                    merged_scene = self._merge_scenes(buffer)
                    if merged_scene:
                        merged.append(merged_scene)
                        logger.info(f"[合并碎片] {len(buffer)}个小场景合并为1个({buffer_lines}行)")
                    buffer = []
                    buffer_lines = 0
            else:
                # 正常场景：先处理缓冲区，再添加当前场景
                if buffer:
                    # 缓冲区有内容，先合并
                    if buffer_lines >= min_lines // 2:
                        # 缓冲区内容足够多，合并
                        merged_scene = self._merge_scenes(buffer)
                        if merged_scene:
                            merged.append(merged_scene)
                            logger.info(f"[合并碎片] 缓冲区合并({len(buffer)}个场景, {buffer_lines}行)")
                    else:
                        # 缓冲区太少，可能需要丢弃或强制合并
                        logger.warning(f"[合并碎片] 缓冲区过小({len(buffer)}个场景, {buffer_lines}行)，强制合并")
                        merged_scene = self._merge_scenes(buffer)
                        if merged_scene:
                            merged.append(merged_scene)
                    buffer = []
                    buffer_lines = 0
                merged.append(scene)

        # 处理剩余缓冲区
        if buffer:
            buffer_lines = sum(self._count_content_lines(s.get('mainContent', '')) for s in buffer)
            if buffer_lines >= min_lines // 2:
                merged_scene = self._merge_scenes(buffer)
                if merged_scene:
                    merged.append(merged_scene)
                    logger.warning(f"[合并碎片] 剩余缓冲区合并({len(buffer)}个场景, {buffer_lines}行)")
            else:
                logger.warning(f"[合并碎片] 丢弃过小碎片({len(buffer)}个场景, {buffer_lines}行)")

        return merged

    async def _llm_semantic_split_for_pagination(
        self,
        scene: Dict,
        scene_type: str
    ) -> List[Dict]:
        """
        使用LLM进行语义拆分（用于分页）

        Args:
            scene: 原始场景
            scene_type: 场景类型

        Returns:
            拆分后的场景列表
        """
        from shared.llm_client import LLMRequest, LLMResponse
        from shared.utils import extract_json

        scene_id = scene.get('sceneID', '')
        frame_title = scene.get('frameTitle', '')
        content = scene.get('mainContent', '')

        logger.info(f"[智能分页] 拆分场景: {scene_id} - {frame_title} ({scene_type})")

        # 构建分页prompt
        prompt = self._build_pagination_prompt(scene_id, frame_title, content, scene_type)

        try:
            request = LLMRequest(
                messages=[{"role": "user", "content": prompt}],
                temperature=0.1,
                max_tokens=16000
            )

            response: LLMResponse = await self.llm_client.call(request)

            if not response.success:
                logger.warning(f"[智能分页] LLM调用失败: {response.error}")
                return [scene]

            # 解析响应
            result = extract_json(response.content)
            if not result or 'frames' not in result:
                logger.warning("[智能分页] LLM响应格式错误，返回原场景")
                return [scene]

            # 【2025-03-31】对于example类型，检查是否需要拆分
            if scene_type == 'example' and 'need_split' in result:
                if result['need_split'] == False:
                    # LLM判断不需要拆分，返回原场景
                    complexity = result.get('complexity', 'unknown')
                    logger.info(f"[智能分页] {scene_id} LLM判断为{complexity}例题，不需要拆分")
                    return [scene]
                # need_split = True，继续正常拆分流程

            # 转换为场景格式
            split_scenes = []
            frames_data = result['frames']
            # 优化：避免重复的正则匹配
            scene_num_match = re.search(r'\d+', scene_id)
            base_scene_num = int(scene_num_match.group()) if scene_num_match else 1

            for i, frame_data in enumerate(frames_data):
                frame_content = frame_data.get('content', '').strip()

                # 【新增】跳过空帧，避免创建无内容的场景
                if not frame_content:
                    logger.debug(f"[智能分页] 跳过空帧 {i+1}")
                    continue

                if i == 0:
                    new_scene_id = scene_id
                else:
                    # 使用字母后缀：s9a, s9b, s9c
                    new_scene_id = f"s{base_scene_num}{chr(96+i)}"

                split_scene = {
                    'sceneID': new_scene_id,
                    'frameTitle': frame_data.get('frame_title', frame_title),
                    'mainContent': frame_content,
                    'narration': self._extract_narration(frame_content, max_length=150),
                    'slideType': scene_type,
                    'needsDiagram': scene.get('needsDiagram', False)
                }
                split_scenes.append(split_scene)
                logger.info(f"[智能分页] 创建场景: {new_scene_id} - {frame_data.get('frame_title', frame_title)}")

            logger.info(f"[智能分页] 拆分完成: {len(split_scenes)}个场景")

            # 【2025-04-04】清理LLM输出中的占位符
            split_scenes = self._cleanup_scene_content(split_scenes)

            # 【2025-04-04】添加帧间导航标记
            split_scenes = self._add_navigation_markers(split_scenes, scene_type)

            # 【2025-04-04】质量验证
            is_valid, score, issues = self._validate_split_quality(scene, split_scenes)

            if not is_valid:
                logger.warning(f"[智能分页] 质量验证失败，返回原场景")
                return [scene]

            return split_scenes

        except Exception as e:
            logger.error(f"[智能分页] 异常: {e}")
            return [scene]

    def _add_navigation_markers(
        self,
        scenes: List[Dict],
        scene_type: str
    ) -> List[Dict]:
        """
        为拆分后的场景添加帧间导航标记

        对于被拆分的内容，添加【续下页】和【接上页】标记，
        帮助观众理解内容的延续性。

        Args:
            scenes: 拆分后的场景列表
            scene_type: 场景类型

        Returns:
            添加了导航标记的场景列表
        """
        if len(scenes) <= 1:
            return scenes

        marked_scenes = []

        for i, scene in enumerate(scenes):
            content = scene.get('mainContent', '')
            scene_id = scene.get('sceneID', '')

            # 第一帧：添加【续下页】标记
            if i == 0 and len(scenes) > 1:
                # 检查是否已有导航标记
                if '【续下页】' not in content and r'\textbf{【续下页】}' not in content:
                    content = content.rstrip() + '\n\n' + r'\textbf{【续下页】}'
                    logger.debug(f"[导航标记] {scene_id} 添加【续下页】")

            # 中间帧：添加【接上页】和【续下页】标记
            elif 0 < i < len(scenes) - 1:
                # 添加【接上页】
                if '【接上页】' not in content and r'\textbf{【接上页】}' not in content:
                    content = r'\textbf{【接上页】}}' + '\n\n' + content

                # 添加【续下页】
                if '【续下页】' not in content and r'\textbf{【续下页】}' not in content:
                    content = content.rstrip() + '\n\n' + r'\textbf{【续下页】}'

                logger.debug(f"[导航标记] {scene_id} 添加【接上页】和【续下页】")

            # 最后一帧：只添加【接上页】标记
            elif i == len(scenes) - 1 and len(scenes) > 1:
                if '【接上页】' not in content and r'\textbf{【接上页】}' not in content:
                    content = r'\textbf{【接上页】}}' + '\n\n' + content
                    logger.debug(f"[导航标记] {scene_id} 添加【接上页】")

            # 更新场景内容
            scene['mainContent'] = content
            marked_scenes.append(scene)

        logger.info(f"[导航标记] 为{len(marked_scenes)}个场景添加了帧间导航标记")
        return marked_scenes

    def _build_pagination_prompt(
        self,
        scene_id: str,
        frame_title: str,
        content: str,
        scene_type: str
    ) -> str:
        """
        构建分页prompt（基于场景类型的差异化策略）

        Args:
            scene_id: 场景ID
            frame_title: 帧标题
            content: 内容
            scene_type: 场景类型

        Returns:
            分页prompt
        """
        # 只对以下类型使用LLM拆分：example（其他类型用规则拆分）
        if scene_type == 'example':
            return f"""# 任务
判断以下例题的复杂度，并决定是否需要拆分以及拆分成几页。

【核心原则】
1. 语义边界拆分：在题目|思路|步骤|答案的逻辑边界处拆分
2. 帧间连贯性：使用导航标记帮助观众理解内容延续
3. 容量适配：每帧内容必须适配Beamer单页容量（约10-15行）

# 原始内容
【场景ID】{scene_id}
【标题】{frame_title}
【内容】
{content}

# 复杂度判断标准
- **简单例题**：≤3步、≤2个公式、无嵌套括号 → 不拆分，1页
- **中等例题**：4-6步、3-5个公式、或简单嵌套 → 拆分为2页
- **复杂例题**：>6步或>5个公式、或复杂嵌套运算 → 拆分为3页

# 检测要点
- 步骤数：统计 ①②③ 或 1.2.3. 或 (1)(2)(3) 等标记
- 公式数：统计 $...$ 的数量
- 嵌套运算：检测 (+、[嵌套等

# 拆分方案（含帧间导航标记）

**1页（简单）**：
题目 + 思路 + 步骤 + 答案 + 易错提醒

**2页（中等）**：
  - frame1：题目 + 思路引导（不含解答步骤）
    → 结尾标记：\\textbf{{【续下页】}}
  - frame2：\\textbf{{【接上页】}} + 完整步骤 + 答案 + 易错提醒

**3页（复杂）**：
  - frame1：题目 + 思路引导（不含解答步骤）
    → 结尾标记：\\textbf{{【续下页】}}
  - frame2：\\textbf{{【接上页】}} + 步骤（前半部分）
    → 结尾标记：\\textbf{{【续下页】}}
  - frame3：\\textbf{{【接上页】}} + 步骤（后半部分）+ 答案 + 易错提醒

# 输出格式
**简单例题（不拆分）**：
```json
{{
  "need_split": false,
  "complexity": "simple",
  "frames": [
    {{"frame_num": 1, "frame_title": "{frame_title}", "content": "原内容"}}
  ]
}}
```

**中等例题（拆分2页）**：
```json
{{
  "need_split": true,
  "complexity": "medium",
  "split_count": 2,
  "frames": [
    {{"frame_num": 1, "frame_title": "{frame_title}", "content": "【题目】...\\n\\n【思路引导】...\\n\\n\\textbf{{【续下页】}}"}},
    {{"frame_num": 2, "frame_title": "{frame_title}", "content": "\\textbf{{【接上页】}}\\n\\n【完整步骤】...\\n\\n【答案】...\\n\\n【易错提醒】..."}}
  ]
}}
```

**复杂例题（拆分3页）**：
```json
{{
  "need_split": true,
  "complexity": "complex",
  "split_count": 3,
  "frames": [
    {{"frame_num": 1, "frame_title": "{frame_title}", "content": "【题目】...\\n\\n【思路引导】...\\n\\n\\textbf{{【续下页】}}"}},
    {{"frame_num": 2, "frame_title": "{frame_title}", "content": "\\textbf{{【接上页】}}\\n\\n【完整步骤】（步骤1-4）...\\n\\n\\textbf{{【续下页】}}"}},
    {{"frame_num": 3, "frame_title": "{frame_title}", "content": "\\textbf{{【接上页】}}\\n\\n【完整步骤】（步骤5-7）...\\n\\n【答案】...\\n\\n【易错提醒】..."}}
  ]
}}
```

请先判断复杂度，再决定是否拆分以及拆分成几页。

---

【强制性输出约束 - 必须遵守】
1. **禁止占位符**：绝对禁止输出"待补充"、"待填充"、"待定"、"占位"、"内容待补充"、"本页内容"等
2. **内容完整性**：每个子场景必须包含完整的教学逻辑（引入→展开→总结）
3. **合理推断**：如果原内容在某方面不够详细，用合理的教学推断补全，而非留空
4. **逻辑递进**：子场景之间必须有清晰的逻辑递进关系，禁止简单机械截断
5. **长度控制**：每个子场景的内容长度应在8-20行之间（约200-500字符）

【输出前自检】
在输出JSON前，请检查：
- [ ] 是否有任何形式的占位符？如有，重新生成
- [ ] 每个子场景是否有完整的起承转合？如有残缺，补充完整
- [ ] 子场景之间的过渡是否自然？如生硬，调整拆分点

【违规处理】
如果输出包含占位符或不完整内容，将被视为无效输出，系统将自动重试。"""

        elif scene_type == 'practice':
            return f"""# 任务
将以下随堂练习内容每2题拆分为一页

# 原始内容
【场景ID】{scene_id}
【标题】{frame_title}
【内容】
{content}

# 拆分要求
- 每2题为一页
- 每页包含完整的题目、答案、解析

# 输出格式
```json
{{
  "frames": [
    {{"frame_num": 1, "frame_title": "{frame_title}（1/2）", "content": "第1-2题的内容"}},
    {{"frame_num": 2, "frame_title": "{frame_title}（2/2）", "content": "剩余题目的内容"}}
  ]
}}
```

请开始拆分:

---

【强制性输出约束 - 必须遵守】
1. **禁止占位符**：绝对禁止输出"待补充"、"待填充"、"待定"、"占位"、"内容待补充"、"本页内容"等
2. **内容完整性**：每个子场景必须包含完整的题目、答案、解析
3. **合理推断**：如果原内容缺少解析部分，用合理的教学推断补全
4. **题目数量保证**：确保所有题目都被包含，不遗漏任何题目

【输出前自检】
- [ ] 是否有任何形式的占位符？
- [ ] 所有题目是否都包含在内？
- [ ] 每个题目是否有完整的答案和解析？

【违规处理】
占位符或不完整内容将导致系统自动重试。"""

        elif scene_type == 'summary':
            return f"""# 任务
将以下课堂小结内容每2个section拆分为一页

# 原始内容
【场景ID】{scene_id}
【标题】{frame_title}
【内容】
{content}

# 拆分要求
- 每2个section为一页
- 保持每个section的完整性

# 输出格式
```json
{{
  "frames": [
    {{"frame_num": 1, "frame_title": "{frame_title}（1/2）", "content": "前2个section的内容"}},
    {{"frame_num": 2, "frame_title": "{frame_title}（2/2）", "content": "剩余section的内容"}}
  ]
}}
```

请开始拆分:

---

【强制性输出约束 - 必须遵守】
1. **禁止占位符**：绝对禁止输出"待补充"、"待填充"、"待定"、"占位"、"内容待补充"、"本页内容"等
2. **内容完整性**：每个小结要点必须完整，不得截断
3. **保持逻辑性**：section之间的逻辑关系必须清晰
4. **数量保证**：确保所有小结要点都被包含

【输出前自检】
- [ ] 是否有任何形式的占位符？
- [ ] 所有要点是否都包含在内？
- [ ] section之间的逻辑是否连贯？

【违规处理】
占位符或不完整内容将导致系统自动重试。"""

        elif scene_type == 'warning':
            return f"""# 任务
将以下易错点提醒内容拆分为2页

# 原始内容
【场景ID】{scene_id}
【标题】{frame_title}
【内容】
{content}

# 拆分要求
- 按item数量平均分配
- 保持每个item的完整性

# 输出格式
```json
{{
  "frames": [
    {{"frame_num": 1, "frame_title": "{frame_title}（1/2）", "content": "前半部分item的内容"}},
    {{"frame_num": 2, "frame_title": "{frame_title}（2/2）", "content": "后半部分item的内容"}}
  ]
}}
```

请开始拆分:

---

【强制性输出约束 - 必须遵守】
1. **禁止占位符**：绝对禁止输出"待补充"、"待填充"、"待定"、"占位"、"内容待补充"、"本页内容"等
2. **内容完整性**：每个易错点必须包含完整的错误原因和正确做法
3. **保持实用性**：易错提醒必须具有实际指导意义

【输出前自检】
- [ ] 是否有任何形式的占位符？
- [ ] 所有易错点是否都包含在内？
- [ ] 每个易错点是否有完整的说明？

【违规处理】
占位符或不完整内容将导致系统自动重试。"""

        elif scene_type == 'concept':
            # 【2025-04-04 新增】支持concept类型的语义拆分
            return f"""# 任务
将以下概念讲解内容按知识单元（block）拆分为多页

【核心原则】
1. **语义边界拆分**：按照独立的block（知识单元）拆分，每个block保持完整
2. **帧间连贯性**：使用导航标记帮助观众理解内容延续
3. **容量适配**：每帧内容必须适配Beamer单页容量（约2-3个block）

# 原始内容
【场景ID】{scene_id}
【标题】{frame_title}
【内容】
{content}

# 拆分策略
concept类型通常包含多个独立的block（如：定义、性质、方法等），按以下规则拆分：
- **2-3个block/页**：保持每页内容适中
- **优先级排序**：核心定义和基础性质放在前面
- **block完整性**：每个block保持完整，不截断

# 拆分方案示例

**2页方案**：
  - frame1：前2个block（定义、基本性质）
    → 结尾标记：\\textbf{{【续下页】}}
  - frame2：\\textbf{{【接上页】}} + 剩余block（推广、应用）

**3页方案**：
  - frame1：第1个block（核心定义）
    → 结尾标记：\\textbf{{【续下页】}}
  - frame2：\\textbf{{【接上页】}} + 第2-3个block（性质、方法）
    → 结尾标记：\\textbf{{【续下页】}}
  - frame3：\\textbf{{【接上页】}} + 剩余block（推广、应用）

# 输出格式
```json
{{
  "need_split": true,
  "frames": [
    {{"frame_num": 1, "frame_title": "{frame_title}（1/2）", "content": "前2个block的完整内容...\\n\\n\\textbf{{【续下页】}}"}},
    {{"frame_num": 2, "frame_title": "{frame_title}（2/2）", "content": "\\textbf{{【接上页】}}\\n\\n剩余block的完整内容..."}}
  ]
}}
```

【强制性输出约束 - 必须遵守】
1. **禁止占位符**：绝对禁止输出任何形式的占位符
2. **内容完整性**：每个block必须完整，不能在block中间截断
3. **逻辑连贯性**：block之间的逻辑关系必须清晰
4. **导航标记**：系统会自动添加【续下页】和【接上页】标记

【输出前自检】
- [ ] 是否有任何形式的占位符？
- [ ] 每个block是否完整？
- [ ] block之间的逻辑是否连贯？

【违规处理】
占位符或不完整内容将导致系统自动重试。"""

        elif scene_type in ['intro', 'objective', 'extend']:
            # 【2025-04-04 新增】支持intro/objective/extend类型的语义拆分
            return f"""# 任务
将以下{frame_title}内容按语义边界拆分为多页

【核心原则】
1. 语义边界拆分：在逻辑节点处拆分（如不同主题之间）
2. 帧间连贯性：使用导航标记帮助观众理解内容延续
3. 容量适配：每帧内容必须适配Beamer单页容量（约10-15行）

# 原始内容
【场景ID】{scene_id}
【标题】{frame_title}
【内容】
{content}

# 拆分策略
对于intro（导入）类型：
- 优先按照不同主题拆分（如：生活实例 → 引入负数 → 有理数概念）
- 每个主题保持相对完整
- 避免把相关联的内容硬性拆开

对于objective（学习目标）类型：
- 按照目标维度拆分（知识与技能 → 过程与方法 → 情感态度）
- 每个维度保持完整

对于extend（拓展）类型：
- 按照拓展主题数量拆分
- 每个拓展主题独立成页

# 输出格式
```json
{{
  "frames": [
    {{"frame_num": 1, "frame_title": "{frame_title}（1/2）", "content": "第一部分内容"}},
    {{"frame_num": 2, "frame_title": "{frame_title}（2/2）", "content": "第二部分内容"}}
  ]
}}
```

【强制性输出约束 - 必须遵守】
1. **禁止占位符**：绝对禁止输出任何形式的占位符
2. **内容完整性**：每个拆分部分必须包含完整的语义单元
3. **逻辑连贯性**：拆分点必须选在逻辑边界，不能随意截断
4. **导航标记**：系统会自动添加【续下页】和【接上页】标记

【输出前自检】
- [ ] 是否有任何形式的占位符？
- [ ] 拆分点是否在逻辑边界？
- [ ] 每个部分是否语义完整？

【违规处理】
占位符或不完整内容将导致系统自动重试。"""

        else:
            # 不应该进入这里（intro/objective/extend/concept已经在_should_paginate中处理）
            logger.error(f"[智能分页] {scene_id} 未知类型 {scene_type} 的拆分请求，返回原内容")
            return f"""# 任务
以下内容不需要拆分，直接返回原内容。

# 原始内容
【场景ID】{scene_id}
【标题】{frame_title}
【内容】
{content}

# 输出格式
```json
{{
  "frames": [
    {{"frame_num": 1, "frame_title": "{frame_title}", "content": "原内容"}}
  ]
}}
```

请直接返回原内容，不要拆分。

---

【强制性输出约束 - 必须遵守】
1. **禁止占位符**：绝对禁止输出任何形式的占位符
2. **内容完整性**：必须返回完整的内容，不得有任何截断或省略"""

    # ==================== 辅助方法 ====================

    def _split_by_subsections(self, content: str) -> List[tuple]:
        """
        按子标题拆分内容

        检测标记:
        1. ### 子标题, ## 子标题
        2. 中文数字标题：一、xxx；二、xxx；（1）xxx 等
        3. 阿拉伯数字标题：1. xxx；2. xxx 等
        4. 内联过渡词: 首先其次是然后接着最后等
        """
        # 优先级1: 尝试 ### 拆分
        parts = re.split(r'###\s+', content)
        if len(parts) > 1:
            result = []
            # 处理第一个部分（可能是"一、xxx"这样的初始标题）
            if parts[0].strip():
                first_part = parts[0].strip()
                # 提取第一行作为标题
                lines = first_part.split('\n', 1)
                if len(lines) == 2:
                    result.append((lines[0].strip(), lines[1]))
                else:
                    result.append(("", first_part))
            # 处理后续的 ### 标题部分
            for part in parts[1:]:
                lines = part.split('\n', 1)
                if len(lines) == 2:
                    result.append((lines[0].strip(), lines[1]))
                else:
                    result.append(("", part))
            return result

        # 优先级2: 尝试 ## 拆分
        parts = re.split(r'##\s+', content)
        if len(parts) > 1:
            result = []
            # 处理第一个部分
            if parts[0].strip():
                first_part = parts[0].strip()
                lines = first_part.split('\n', 1)
                if len(lines) == 2:
                    result.append((lines[0].strip(), lines[1]))
                else:
                    result.append(("", first_part))
            # 处理后续的 ## 标题部分
            for part in parts[1:]:
                lines = part.split('\n', 1)
                if len(lines) == 2:
                    result.append((lines[0].strip(), lines[1]))
                else:
                    result.append(("", part))
            return result

        # 优先级3: 尝试中文数字标题拆分（一、xxx；二、xxx；三、xxx 等）
        # 匹配：一、二、三、四、五、六、七、八、九、十、十一、十二...
        chinese_num_pattern = r'([一二三四五六七八九十]+(?:百千万)?、[^\n]{1,50})'
        chinese_num_matches = list(re.finditer(chinese_num_pattern, content))

        if len(chinese_num_matches) >= 2:  # 至少2个标题才拆分
            result = []
            # 处理第一个标题之前的内容（如果有）
            if chinese_num_matches[0].start() > 0:
                before_first = content[:chinese_num_matches[0].start()].strip()
                if before_first:
                    result.append(("", before_first))

            # 处理每个标题及其内容
            for i in range(len(chinese_num_matches)):
                title = chinese_num_matches[i].group(1).strip()
                start = chinese_num_matches[i].end()
                end = chinese_num_matches[i + 1].start() if i + 1 < len(chinese_num_matches) else len(content)
                section_content = content[start:end].strip()
                result.append((title, section_content))

            return result

        # 优先级4: 尝试阿拉伯数字标题拆分（1. xxx；2. xxx；（1）xxx 等）
        # 匹配：1. xxx；2. xxx；（1）xxx；（2）xxx
        arabic_num_pattern = r'(?:^|\n)\s*((?:\(\d+\)|\d+)[.、:：]\s*[^\n]{1,50})'
        arabic_num_matches = list(re.finditer(arabic_num_pattern, content, re.MULTILINE))

        if len(arabic_num_matches) >= 2:  # 至少2个标题才拆分
            result = []
            # 处理第一个标题之前的内容（如果有）
            if arabic_num_matches[0].start() > 0:
                before_first = content[:arabic_num_matches[0].start()].strip()
                if before_first:
                    result.append(("", before_first))

            # 处理每个标题及其内容
            for i in range(len(arabic_num_matches)):
                title = arabic_num_matches[i].group(1).strip()
                start = arabic_num_matches[i].end()
                end = arabic_num_matches[i + 1].start() if i + 1 < len(arabic_num_matches) else len(content)
                section_content = content[start:end].strip()
                result.append((title, section_content))

            return result

        # 优先级5: 尝试内联过渡词拆分（首先、其次、然后、接着、最后、另外、此外、接下来）
        # 这些词通常在段落开头或句首，后面跟着一个主题
        # 匹配模式：句首/标点后 + 过渡词 + 逗号(可选)
        transition_pattern = r'(?:^|[，。；！？]\s*)(首先|其次|然后|接着|最后|另外|此外|接下来|再有)，?'
        transition_matches = list(re.finditer(transition_pattern, content))

        if len(transition_matches) >= 2:  # 至少2个过渡词才使用这种拆分
            result = []
            # 获取第一个过渡词之前的内容
            first_match = transition_matches[0]
            before_first = content[:first_match.start()].strip()
            if before_first:
                # 提取第一句话作为标题
                title_match = re.match(r'^([^。；！？\n]{0,30})', before_first)
                if title_match:
                    result.append((title_match.group(1), before_first))
                else:
                    result.append(("", before_first))

            # 获取每两个过渡词之间的内容
            for i in range(len(transition_matches)):
                start = transition_matches[i].end()
                end = transition_matches[i + 1].start() if i + 1 < len(transition_matches) else len(content)
                section_content = content[start:end].strip()

                # 提取过渡词和后面的关键词作为标题
                current_transition = transition_matches[i].group(1)  # 修改：使用group(1)
                # 提取该部分的主题（通常是过渡词后的前几个字）
                title_match = re.match(r'^([^，。；！？\n]{0,15})', section_content)
                if title_match:
                    title = f"{current_transition}，{title_match.group(1)}"
                else:
                    title = current_transition

                result.append((title, section_content))

            return result

        return []

        # 尝试 ## 拆分
        parts = re.split(r'##\s+', content)
        if len(parts) > 1:
            result = []
            # 处理第一个部分
            if parts[0].strip():
                first_part = parts[0].strip()
                lines = first_part.split('\n', 1)
                if len(lines) == 2:
                    result.append((lines[0].strip(), lines[1]))
                else:
                    result.append(("", first_part))
            # 处理后续的 ## 标题部分
            for part in parts[1:]:
                lines = part.split('\n', 1)
                if len(lines) == 2:
                    result.append((lines[0].strip(), lines[1]))
                else:
                    result.append(("", part))
            return result

        # 尝试内联过渡词拆分（首先、其次、然后、接着、最后、另外、此外、接下来）
        # 这些词通常在段落开头或句首，后面跟着一个主题
        # 匹配模式：句首/标点后 + 过渡词 + 逗号(可选)
        transition_pattern = r'(?:^|[，。；！？]\s*)(首先|其次|然后|接着|最后|另外|此外|接下来|再有)，?'
        transition_matches = list(re.finditer(transition_pattern, content))

        if len(transition_matches) >= 2:  # 至少2个过渡词才使用这种拆分
            result = []
            # 获取第一个过渡词之前的内容
            first_match = transition_matches[0]
            before_first = content[:first_match.start()].strip()
            if before_first:
                # 提取第一句话作为标题
                title_match = re.match(r'^([^。；！？\n]{0,30})', before_first)
                if title_match:
                    result.append((title_match.group(1), before_first))
                else:
                    result.append(("", before_first))

            # 获取每两个过渡词之间的内容
            for i in range(len(transition_matches)):
                start = transition_matches[i].end()
                end = transition_matches[i + 1].start() if i + 1 < len(transition_matches) else len(content)
                section_content = content[start:end].strip()

                # 提取过渡词和后面的关键词作为标题
                current_transition = transition_matches[i].group(1)  # 修改：使用group(1)
                # 提取该部分的主题（通常是过渡词后的前几个字）
                title_match = re.match(r'^([^，。；！？\n]{0,15})', section_content)
                if title_match:
                    title = f"{current_transition}，{title_match.group(1)}"
                else:
                    title = current_transition

                result.append((title, section_content))

            return result

        return []

    def _split_examples(self, content: str) -> List[tuple]:
        """
        拆分例题

        检测标记:
        - 【典例X】
        - 【例X】
        - ### 例X

        注意：标题只返回"例X"格式，不包含题目内容
        """
        examples = []

        # 按多种模式拆分
        patterns = [
            r'【典例(\d+)】',
            r'【例题?(\d+)】',
            r'###\s*例题?\s*(\d+)',
            r'例\s*(\d+)[:：]'
        ]

        # 先尝试 【典例X】 或 【例X】
        for pattern in patterns[:3]:
            matches = list(re.finditer(pattern, content))
            if len(matches) >= 2:  # 至少2个例题才使用这种拆分
                parts = re.split(pattern, content)
                for i in range(1, len(parts), 2):
                    if i + 1 < len(parts):
                        example_num = parts[i]
                        example_content = parts[i + 1]
                        # 【修改】标题只保留"例X"格式，不提取题目内容
                        title = f"例{example_num}"
                        examples.append((title, example_content))
                return examples

        # 尝试按编号列表拆分: 1. xxx  2. xxx
        numbered_pattern = r'(?:^|\n)\s*(\d+)\.\s+([^\n]+(?:\n(?!\s*\d+\.)[^\n]*)*)'
        numbered_matches = list(re.finditer(numbered_pattern, content, re.MULTILINE))
        if len(numbered_matches) >= 2:
            for match in numbered_matches:
                num = match.group(1)
                ex_content = match.group(2).strip()
                examples.append((f"例{num}", ex_content))
            return examples

        # 都没有，返回整个内容作为一个例题
        examples.append(("例题", content))
        return examples

    def _split_long_content_by_structure(self, content: str, max_segments: int = 5) -> List[str]:
        """
        按内容结构智能拆分长文本

        策略：
        1. 检测中文数字标题（一、xxx；二、xxx）
        2. 检测阿拉伯数字标题（1. xxx；2. xxx）
        3. 按段落拆分（空行分隔）

        Args:
            content: 要拆分的内容
            max_segments: 最多分成几段

        Returns:
            拆分后的内容段列表
        """
        # 策略1: 检测中文数字标题
        chinese_num_pattern = r'(?:^|\n)\s*([一二三四五六七八九十]+、[^\n]+(?:\n(?!\s*[一二三四五六七八九十]+、)[^\n]*)*)'
        chinese_matches = list(re.finditer(chinese_num_pattern, content, re.MULTILINE))

        if len(chinese_matches) >= 2:
            chunks = []
            for match in chinese_matches:
                chunks.append(match.group(1).strip())
            return chunks[:max_segments]

        # 策略2: 检测阿拉伯数字标题
        arabic_num_pattern = r'(?:^|\n)\s*(\(\d+\)|\d+)[.、:：]\s*[^\n]+(?:\n(?!\s*(?:\(\d+\)|\d+)[.、:：])[^\n]*)*'
        arabic_matches = list(re.finditer(arabic_num_pattern, content, re.MULTILINE))

        if len(arabic_matches) >= 2:
            chunks = []
            for match in arabic_matches:
                chunks.append(match.group(0).strip())
            return chunks[:max_segments]

        # 策略3: 按段落拆分（空行分隔）
        paragraphs = [p.strip() for p in content.split('\n\n') if p.strip()]
        if len(paragraphs) > 1:
            # 计算每段应该包含多少个段落
            chunk_size = max(1, len(paragraphs) // max_segments)
            chunks = []
            for i in range(0, len(paragraphs), chunk_size):
                chunk = '\n\n'.join(paragraphs[i:i + chunk_size])
                chunks.append(chunk)
            return chunks

        # 无法拆分，返回原内容
        return [content]

    def _extract_chunk_title(self, chunk: str, base_name: str, index: int) -> str:
        """
        从内容块中提取标题

        Args:
            chunk: 内容块
            base_name: 基础名称
            index: 块索引

        Returns:
            提取的标题
        """
        # 尝试提取第一行作为标题
        lines = chunk.strip().split('\n', 1)
        if lines:
            first_line = lines[0].strip()
            # 检查是否是标题格式（简短且可能包含标点）
            if len(first_line) < 50 and first_line:
                # 清理LaTeX标记
                clean_title = re.sub(r'\\textbf\{([^}]+)\}', r'\1', first_line)
                clean_title = re.sub(r'[{}$\\]', '', clean_title)
                if clean_title:
                    return f"{base_name}·{clean_title[:30]}"

        # 无法提取标题，使用序号
        return f"{base_name}（{index}）"

    def _smart_split_paragraphs(self, paragraphs: List[str], max_per_frame: int = 3) -> List[List[str]]:
        """
        智能拆分段落

        每帧最多 max_per_frame 个段落，但尽量保持语义完整
        """
        if len(paragraphs) <= max_per_frame:
            return [paragraphs]

        chunks = []
        current_chunk = []

        for para in paragraphs:
            current_chunk.append(para)
            if len(current_chunk) >= max_per_frame:
                chunks.append(current_chunk)
                current_chunk = []

        if current_chunk:
            chunks.append(current_chunk)

        return chunks

    def _format_content(self, content: str) -> str:
        """
        格式化内容为 LaTeX

        处理:
        - 列表标记 → itemize
        - 加粗 → textbf
        - 公式保持不变
        - 分页标记 → newpage
        """
        if not content:
            return ""

        # 处理分页标记 ===分页===
        if "===分页===" in content:
            parts = content.split("===分页===")
            formatted_parts = []
            for i, part in enumerate(parts):
                if part.strip():  # 处理非空部分
                    # 格式化这部分内容
                    formatted_part = self._format_single_part(part.strip())
                    formatted_parts.append(formatted_part)
                    # 如果不是最后一部分，添加分页命令
                    if i < len(parts) - 1:
                        formatted_parts.append("\\newpage")
            return '\n'.join(formatted_parts)

        # 没有分页标记，直接格式化
        return self._format_single_part(content)

    def _format_single_part(self, content: str) -> str:
        """
        格式化单个内容部分（不包含分页标记）

        增强格式化：
        - 列表标记 → itemize
        - 内联过渡词 → itemize（首先、其次、然后、接着、最后等）
        - 加粗标记 → textbf
        - 关键词强调 → alert
        - 段落结构优化
        """
        if not content:
            return ""

        # 先处理加粗和强调标记
        content = self._format_emphasis(content)

        # 检测是否有列表
        has_list = bool(re.search(r'^\s*[-•·]\s+', content, re.MULTILINE))

        if has_list:
            # 转换为 LaTeX itemize
            lines = content.split('\n')
            latex_lines = ["\\begin{itemize}"]
            for line in lines:
                list_match = re.match(r'^\s*[-•·]\s+(.+)', line)
                if list_match:
                    item_content = list_match.group(1)
                    # 处理列表项内的加粗和强调
                    item_content = self._format_inline_emphasis(item_content)
                    latex_lines.append(f"  \\item {item_content}")
                elif line.strip():
                    # 非列表行保持原样
                    latex_lines.append(line)
            latex_lines.append("\\end{itemize}")
            return '\n'.join(latex_lines)

        # 检测是否有内联过渡词模式（首先...其次...然后...）
        # 这种模式应该转换为itemize以便于分页
        transition_pattern = r'[，。；！？]\s*(首先|其次|然后|接着|最后|另外|此外|接下来)，?'
        transition_matches = list(re.finditer(transition_pattern, content))

        if len(transition_matches) >= 2:
            # 转换为 itemize 格式
            items = []

            # 获取第一个过渡词之前的内容作为引导语
            if transition_matches:
                intro = content[:transition_matches[0].start()].strip()
                if intro:
                    items.append(("引导", intro))

            # 获取每两个过渡词之间的内容
            for i in range(len(transition_matches)):
                start = transition_matches[i].end()
                end = transition_matches[i + 1].start() if i + 1 < len(transition_matches) else len(content)
                section_content = content[start:end].strip()

                # 使用过渡词作为列表项标题
                transition = transition_matches[i].group(1)
                items.append((transition, section_content))

            if len(items) >= 2:
                # 生成 itemize 格式
                latex_lines = ["\\begin{itemize}"]
                for item_title, item_content in items:
                    # 处理内容中的加粗和强调
                    item_content = self._format_inline_emphasis(item_content)
                    latex_lines.append(f"  \\item \\textbf{{{item_title}：}}{item_content}")
                latex_lines.append("\\end{itemize}")
                return '\n'.join(latex_lines)

        # 没有列表，处理段落结构
        return self._format_paragraphs(content)

    def _format_emphasis(self, content: str) -> str:
        """
        处理内容中的加粗和强调标记

        支持格式：
        - **文本** → \\textbf{文本}
        - 【重点】文本 → \\textbf{文本}
        - 重要：文本 → \\alert{重要：}文本
        """
        # 处理 **文本** 格式
        content = re.sub(r'\*\*([^*]+)\*\*', r'\\textbf{\1}', content)

        # 处理 【重点】文本 或 【注意】文本
        content = re.sub(r'【(重点|注意|关键)】([^【\n]+)', r'\\textbf{\1：\2}', content)

        # 处理 "重要：", "关键：" 等开头的强调词
        content = re.sub(r'(重要|关键|核心|重点)[：:]\s*([^\n]{0,50})', r'\\alert{\1：}\2', content)

        return content

    def _format_inline_emphasis(self, content: str) -> str:
        """
        处理行内加粗和强调（用于列表项等）
        """
        # 处理 **文本**
        content = re.sub(r'\*\*([^*]+)\*\*', r'\\textbf{\1}', content)

        # 处理括号内的强调
        content = re.sub(r'（([^（）]{0,20}）)', r'(\\textbf{\1})', content)

        return content

    def _format_paragraphs(self, content: str) -> str:
        """
        格式化段落内容

        处理：
        - 识别段落分隔
        - 添加适当的间距
        - 处理行内强调
        """
        if not content:
            return ""

        # 处理行内强调
        content = self._format_inline_emphasis(content)

        # 按段落分割（空行或明显的段落标记）
        paragraphs = re.split(r'\n\s*\n|[。！？]\s*\n', content)

        formatted_paragraphs = []
        for para in paragraphs:
            para = para.strip()
            if para:
                # 检测是否是标题（开头有编号或中文数字）
                if re.match(r'^[一二三四五六七八九十\d]+[、.．\s]', para):
                    # 短标题格式化
                    formatted_paragraphs.append(f"\\textbf{{{para}}}")
                else:
                    # 普通段落
                    formatted_paragraphs.append(para)

        # 用段落分隔符连接
        return '\n\n'.join(formatted_paragraphs)

    def _extract_narration(self, content: str, max_length: int = 200) -> str:
        """
        从内容中提取讲解词

        策略:
        1. 取前 max_length 个字符
        2. 在句号处截断，保持完整
        3. 添加省略号（如果被截断）
        4. 如果内容为空，返回默认讲解词
        """
        if not content:
            # 返回默认讲解词，避免 TTS 因空文本失败
            return "同学们，这个知识点很重要，请仔细听讲。"

        # 清理内容
        # 先处理换行符后的标点符号，避免"。，"这样的错误
        clean_content = re.sub(r'\n+([，。！？；、])', r'\1', content)  # 换行+标点 → 只保留标点
        clean_content = re.sub(r'\n+', '，', clean_content)  # 其他换行转逗号
        clean_content = re.sub(r'\s+', ' ', clean_content)  # 合并空格
        clean_content = clean_content.strip()

        if len(clean_content) <= max_length:
            return clean_content

        # 尝试在句号处截断
        truncated = clean_content[:max_length]
        last_period = truncated.rfind('。')

        if last_period > max_length // 2:  # 句号位置合理
            return truncated[:last_period + 1]

        return truncated + "..."

    def _extract_narration_for_subsection(
        self, section_name: str, sub_title: str, sub_content: str, max_length: int = 200
    ) -> str:
        """
        为子章节生成讲解词

        Args:
            section_name: 主章节名称
            sub_title: 子标题
            sub_content: 子内容
            max_length: 最大长度

        Returns:
            生成的讲解词
        """
        if not sub_content:
            return f"我们来看{sub_title}的相关内容。"

        # 提取子内容的关键信息
        clean_content = self._clean_content_for_narration(sub_content)

        # 生成讲解词模板
        if sub_title:
            narration = f"关于{sub_title}，{clean_content[:max_length-20]}"
        else:
            narration = clean_content[:max_length]

        # 在句号处截断
        if len(narration) > max_length:
            last_period = narration.rfind('。')
            if last_period > max_length // 2:
                narration = narration[:last_period + 1]
            else:
                narration = narration[:max_length] + "..."

        return narration

    def _extract_multi_narration(
        self, name: str, content: str, max_segments: int = 3
    ) -> List[str]:
        """
        将长内容拆分为多段讲解词

        Args:
            name: 章节名称
            content: 内容文本
            max_segments: 最多分段数

        Returns:
            讲解词列表
        """
        narrations = []

        # 清理内容
        clean_content = self._clean_content_for_narration(content)

        # 按段落拆分
        paragraphs = re.split(r'[。\n]+', clean_content)
        paragraphs = [p.strip() for p in paragraphs if p.strip()]

        if len(paragraphs) <= max_segments:
            # 段落数量足够，每段一个讲解
            for para in paragraphs:
                narrations.append(para)
        else:
            # 段落太多，需要合并
            chunk_size = len(paragraphs) // max_segments + 1
            for i in range(0, len(paragraphs), chunk_size):
                chunk = paragraphs[i:i + chunk_size]
                combined = "。".join(chunk)
                if combined and not combined.endswith('。'):
                    combined += '。'
                narrations.append(combined[:200])

        return narrations

    def _extract_narration_for_example(
        self, section_name: str, example_title: str, example_content: str, index: int, total: int
    ) -> str:
        """
        为例题生成讲解词

        Args:
            section_name: 章节名称
            example_title: 例题标题
            example_content: 例题内容
            index: 当前例题序号
            total: 总例题数

        Returns:
            生成的讲解词
        """
        # 清理例题内容
        clean_content = self._clean_content_for_narration(example_content)

        # 提取题目部分（如果有【题目】标记）
        question_match = re.search(r'【.*?题.*?】(.{0,150}?)(?=【|$)', clean_content)
        if question_match:
            question_text = question_match.group(1).strip()
            narration = f"来看{example_title}：{question_text}"
        else:
            # 直接取前100字作为题目
            question_text = clean_content[:100]
            narration = f"来看{example_title}：{question_text}"

        # 如果有答案，提示学生思考
        if "答案" in clean_content or "解：" in clean_content:
            narration += "，大家先思考一下。"

        # 限制长度
        if len(narration) > 180:
            last_period = narration.rfind('。')
            if last_period > 100:
                narration = narration[:last_period + 1]
            else:
                narration = narration[:180] + "..."

        return narration

    def _clean_content_for_narration(self, content: str) -> str:
        """
        清理内容用于生成讲解词

        处理：
        - 移除 LaTeX 命令
        - 移除公式符号
        - 合并换行
        """
        if not content:
            return ""

        # 移除 LaTeX 命令
        clean = re.sub(r'\\[a-zA-Z]+({[^}]*})?', '', content)
        clean = re.sub(r'[{}$]', '', clean)

        # 处理换行符
        clean = re.sub(r'\n+([，。！？；、])', r'\1', clean)
        clean = re.sub(r'\n+', '，', clean)
        clean = re.sub(r'\s+', ' ', clean)

        return clean.strip()

    def _detect_needs_diagram(self, content: str) -> bool:
        """
        检测内容是否需要图示

        检测关键词:
        - 函数类: 函数、图像、坐标、抛物线
        - 几何类: 三角形、圆形、证明、垂直、平行
        - 统计类: 图表、统计、分布、柱状图
        """
        diagram_keywords = {
            # 函数类
            "函数": 2, "图像": 2, "坐标": 2, "抛物线": 2, "双曲线": 2,
            "y=": 1, "f(x)": 1, "直线": 1,
            # 几何类
            "三角形": 2, "圆形": 2, "证明": 1, "垂直": 1, "平行": 1,
            "勾股定理": 2, "全等": 1, "相似": 1,
            # 统计类
            "图表": 2, "统计": 1, "分布": 1, "柱状图": 2, "折线图": 2,
            "扇形图": 2,
            # 其他
            "数轴": 2, "角度": 1
        }

        score = 0
        content_lower = content.lower()

        for keyword, weight in diagram_keywords.items():
            if keyword.lower() in content_lower:
                score += weight

        return score >= 2

    def _scene_to_dict(self, scene: LightweightScene) -> Dict:
        """将场景对象转换为字典"""
        result = {
            "sceneID": scene.sceneID,
            "frameTitle": scene.frameTitle,
            "mainContent": scene.mainContent,
            "narration": scene.narration,
            "slideType": scene.slideType,
            "needsDiagram": scene.needsDiagram
        }

        if scene.diagramSpec:
            result["diagramSpec"] = scene.diagramSpec

        return result

    # ==================== 分页指标收集方法 ====================

    @classmethod
    def record_estimate(cls, estimated: int, actual: int = None):
        """记录估算vs实际"""
        cls._pagination_metrics['estimate_vs_actual'].append({
            'estimated': estimated,
            'actual': actual,
            'timestamp': time.time()
        })

    @classmethod
    def record_split_quality(cls, score: float, scene_type: str):
        """记录拆分质量"""
        cls._pagination_metrics['split_quality_scores'].append({
            'score': score,
            'scene_type': scene_type,
            'timestamp': time.time()
        })

    @classmethod
    def record_overflow(cls):
        """记录溢出事件"""
        cls._pagination_metrics['overflow_incidents'] += 1

    @classmethod
    def record_placeholder(cls):
        """记录占位符检测"""
        cls._pagination_metrics['placeholder_detected'] += 1

    @classmethod
    def record_pagination_trigger(cls, reason: str, scene_type: str):
        """记录拆分触发原因"""
        cls._pagination_metrics['pagination_triggers'].append({
            'reason': reason,
            'scene_type': scene_type,
            'timestamp': time.time()
        })

    @classmethod
    def record_scene_count(cls, count: int):
        """记录场景数量"""
        cls._pagination_metrics['scene_counts'].append({
            'count': count,
            'timestamp': time.time()
        })

    @classmethod
    def get_metrics(cls) -> dict:
        """获取当前指标"""
        return cls._pagination_metrics.copy()

    @classmethod
    def reset_metrics(cls):
        """重置指标（用于测试或定期清理）"""
        cls._pagination_metrics = {
            'estimate_vs_actual': [],
            'split_quality_scores': [],
            'overflow_incidents': 0,
            'placeholder_detected': 0,
            'retry_count': [],
            'pagination_triggers': [],
            'scene_counts': [],
        }

    @classmethod
    def generate_pagination_report(cls) -> dict:
        """
        生成分页性能报告

        Returns:
            报告字典
        """
        import statistics
        import time

        metrics = cls._pagination_metrics

        estimates = metrics['estimate_vs_actual']
        qualities = metrics['split_quality_scores']
        triggers = metrics['pagination_triggers']
        scene_counts = metrics['scene_counts']

        # 计算统计指标
        total_scenes = len(scene_counts)

        # 估算准确性（如果有实际数据）
        estimate_accuracy = None
        if estimates and any(e.get('actual') for e in estimates):
            est_vals = [e['estimated'] for e in estimates if e.get('actual')]
            act_vals = [e['actual'] for e in estimates if e.get('actual')]
            if len(est_vals) > 1:
                # 计算相关系数
                mean_est = statistics.mean(est_vals)
                mean_act = statistics.mean(act_vals)
                if len(est_vals) > 1:
                    numerator = sum((e - a) ** 2 for e, a in zip(est_vals, act_vals))
                    denominator = sum((a - mean_act) ** 2 for a in act_vals)
                    estimate_accuracy = 1 - (numerator / denominator) if denominator else 0

        # 平均质量分数
        avg_quality = statistics.mean([q['score'] for q in qualities]) if qualities else 0

        # 质量分数分布
        quality_distribution = {'优秀(>=0.9)': 0, '良好(0.7-0.9)': 0, '及格(0.6-0.7)': 0, '不及格(<0.6)': 0}
        for q in qualities:
            score = q['score']
            if score >= 0.9:
                quality_distribution['优秀(>=0.9)'] += 1
            elif score >= 0.7:
                quality_distribution['良好(0.7-0.9)'] += 1
            elif score >= 0.6:
                quality_distribution['及格(0.6-0.7)'] += 1
            else:
                quality_distribution['不及格(<0.6)'] += 1

        # 溢出率
        overflow_rate = metrics['overflow_incidents'] / max(1, total_scenes)

        # 占位符率
        placeholder_rate = metrics['placeholder_detected'] / max(1, total_scenes)

        # 触发原因统计
        trigger_stats = {}
        for t in triggers:
            reason = t['reason']
            trigger_stats[reason] = trigger_stats.get(reason, 0) + 1

        # 场景数量统计
        avg_scene_count = statistics.mean([s['count'] for s in scene_counts]) if scene_counts else 0
        max_scene_count = max([s['count'] for s in scene_counts]) if scene_counts else 0

        # 生成建议
        recommendation = cls._generate_recommendation(
            estimate_accuracy, avg_quality, overflow_rate, placeholder_rate
        )

        report = {
            'generated_at': time.strftime('%Y-%m-%d %H:%M:%S'),
            'period': 'all_time',
            'total_scenes': total_scenes,
            'estimate_accuracy': f'{estimate_accuracy:.2%}' if estimate_accuracy is not None else 'N/A',
            'avg_split_quality': f'{avg_quality:.2f}/1.00',
            'quality_distribution': quality_distribution,
            'overflow_rate': f'{overflow_rate:.2%}',
            'overflow_incidents': metrics['overflow_incidents'],
            'placeholder_rate': f'{placeholder_rate:.2%}',
            'placeholder_detected': metrics['placeholder_detected'],
            'avg_scene_count': f'{avg_scene_count:.1f}',
            'max_scene_count': max_scene_count,
            'trigger_reasons': trigger_stats,
            'recommendation': recommendation,
        }

        return report

    @classmethod
    def _generate_recommendation(cls, accuracy, quality, overflow, placeholder):
        """基于指标生成改进建议"""
        issues = []

        if accuracy is not None and accuracy < 0.7:
            issues.append('估算准确性低，建议调整高度公式系数')

        if quality < 0.7:
            issues.append('拆分质量不足，建议优化prompt或增加重试')

        if overflow > 0.05:
            issues.append('溢出率过高，建议降低阈值或提高安全系数')

        if placeholder > 0.03:
            issues.append('占位符频繁，建议强化prompt约束')

        if not issues:
            return '保持现状'

        return '; '.join(issues)


# ==================== 便捷函数 ====================

def map_course_to_storyboard(course_json: Dict) -> Dict:
    """
    便捷函数: 将课程内容映射为分镜

    Args:
        course_json: course.json 的内容

    Returns:
        标准分镜 JSON
    """
    mapper = CourseToVideoMapper()
    return mapper.map_to_storyboard(course_json)


# ==================== 测试代码 ====================

if __name__ == "__main__":
    # 测试数据
    test_course = {
        "title": "有理数全章核心考点巩固课",
        "grade": "七年级上册",
        "chapter": "第一章 有理数",
        "sections": {
            "导入": "同学们平时看天气预报，会看到零上5℃记做+5℃...",
            "知识点详解": "1. 有理数的概念：整数和分数统称为有理数。\n\n### 有理数的分类\n- 按定义分：整数、分数\n- 按正负分：正有理数、0、负有理数",
            "典例精讲": "【典例1】已知|x-2|+|y+3|=0，求x和y。\n【典例2】把下列数填入对应集合...",
            "易错点": "1. 去括号漏乘系数\n2. 绝对值概念理解不清",
            "知识框架": "1. 有理数的概念\n2. 有理数的分类\n3. 数轴"
        }
    }

    # 测试映射
    storyboard = map_course_to_storyboard(test_course)

    print(f"标题: {storyboard['title']}")
    print(f"总帧数: {storyboard['totalSlides']}")
    print(f"预计时长: {storyboard['estimatedDuration']}")
    print("\n分镜列表:")
    for scene in storyboard['scenes']:
        diagram_mark = " [图]" if scene['needsDiagram'] else ""
        print(f"  {scene['sceneID']}: {scene['frameTitle']} ({scene['slideType']}){diagram_mark}")
