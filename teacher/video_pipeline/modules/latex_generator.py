"""
LaTeX生成器模块（完整版）

从 pipeline.py 完整提取所有LaTeX生成逻辑
版本：A1完整版
创建时间：2026-03-20
"""

import asyncio
import json
import logging
import re
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Any, Optional

# 使用统一的日志配置
from ..logging_config import get_module_logger
logger = get_module_logger(__name__, "latex_generator")

# 导入外置的 LaTeX 修复规则表
from .latex_fix_rules import LATEX_FIX_RULES, EXTRA_PACKAGES_NEEDED, REQUIRED_PACKAGES

# 导入frame映射类型定义
from .pagination_types import FrameMapping


@dataclass
class LaTeXGenerationResult:
    """LaTeX生成结果"""
    success: bool
    tex_content: str = ""
    expected_frames: int = 0
    actual_frames: int = 0
    violations: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    frame_details: List[str] = field(default_factory=list)
    frame_mappings: List[FrameMapping] = field(default_factory=list)  # 新增：frame映射信息
    error: str = ""


class LaTeXGenerator:
    """
    LaTeX生成器（完整版）

    完整包含pipeline.py中的所有LaTeX生成逻辑
    """

    # ========== 常量配置 ==========
    FRAME_BREAK_THRESHOLDS = {
        'max_effective_lines': 15,
        'max_chinese_chars': 400,
        'max_items': 6,
        'max_math_formulas': 5,
        'min_score_to_split': 2,
    }

    # LaTeX 修复规则已外置到 latex_fix_rules.py
    # 使用方式: from .latex_fix_rules import LATEX_FIX_RULES, EXTRA_PACKAGES_NEEDED, REQUIRED_PACKAGES

    def __init__(self, llm_client):
        self.llm = llm_client
        self.last_frame_mappings = []  # 存储最后一次分页的frame映射
        logger.info("[LaTeXGenerator] 初始化完成")
        logger.info("[LaTeXGenerator] ========== 2025升级版配置 ==========")
        logger.info("[LaTeXGenerator]   - Beamer区块优先: block/exampleblock/alertblock")
        logger.info("[LaTeXGenerator]   - 多栏布局: columns（对比场景）")
        logger.info("[LaTeXGenerator]   - 扁平化列表: itemize（block内用换行）")
        logger.info("[LaTeXGenerator]   - 扁平化原则: block内用换行不嵌套itemize")
        logger.info("[LaTeXGenerator]   - max_tokens: 首批12000, 后续8000")
        logger.info("[LaTeXGenerator] =====================================")

    def get_frame_mappings(self) -> List[FrameMapping]:
        """获取最后一次分页的frame映射"""
        return self.last_frame_mappings

    async def generate(
        self,
        storyboard: Dict[str, Any],
        diagrams_dir: Optional[Path] = None
    ) -> LaTeXGenerationResult:
        """生成LaTeX Beamer代码（2025升级版 - 教学设计优先）"""
        title = storyboard.get("title", "课程")
        scenes = storyboard.get("scenes", [])

        # 检查是否有预处理数据
        preprocessed_data = storyboard.get('_preprocessed', {})
        has_preprocessing = bool(preprocessed_data)

        logger.info(f"[LaTeXGenerator] ========== 开始生成 LaTeX ==========")
        logger.info(f"[LaTeXGenerator] 课程: {title}")
        logger.info(f"[LaTeXGenerator] 场景数: {len(scenes)}")
        if has_preprocessing:
            logger.info(f"[LaTeXGenerator] ✅ 检测到预处理数据，将启用简化模式")
            logger.info(f"[LaTeXGenerator]    建议批次大小: {preprocessed_data.get('batchSuggestion', 2)}")
        logger.info(f"[LaTeXGenerator] ========== 2025升级版特性 ==========")
        logger.info(f"[LaTeXGenerator]   - Beamer区块: block/exampleblock/alertblock")
        logger.info(f"[LaTeXGenerator]   - 多栏布局: columns（对比场景）")
        logger.info(f"[LaTeXGenerator]   - 紧凑列表: compactitem（减少30%空间）")
        logger.info(f"[LaTeXGenerator]   - 扁平化: block内用换行不嵌套")
        logger.info(f"[LaTeXGenerator]   - 嵌套展平: 自动展平>3层嵌套")
        logger.info(f"[LaTeXGenerator] =====================================")

        try:
            safe_scenes = await self._preprocess_scenes(scenes, preprocessed_data.get('scenes', []))
            tex_content = await self._generate_latex_batches(
                title,
                safe_scenes,
                len(scenes),
                preprocessed_data=preprocessed_data
            )

            # 安全检查：确保tex_content不为None
            if tex_content is None:
                logger.error("[LaTeXGenerator] _generate_latex_batches返回None，无法继续")
                raise Exception("_generate_latex_batches返回None")

            contract_result = self._validate_frame_contract(safe_scenes, tex_content)
            tex_content = self._fix_latex_common_errors(tex_content)

            # 再次安全检查：确保tex_content仍然不为None
            if tex_content is None:
                logger.error("[LaTeXGenerator] _fix_latex_common_errors返回None，无法继续")
                raise Exception("_fix_latex_common_errors返回None")

            # ========== 直接生成frame_mappings（不再分页） ==========
            frame_mappings = self._create_frame_mappings_from_scenes(safe_scenes)
            self.last_frame_mappings = frame_mappings
            logger.info(f"[LaTeX生成] 完成: {len(safe_scenes)}帧, frame_mappings: {len(frame_mappings)}个")

            return LaTeXGenerationResult(
                success=True,
                tex_content=tex_content,
                expected_frames=len(safe_scenes),
                actual_frames=tex_content.count(r'\begin{frame}'),
                violations=contract_result['violations'],
                warnings=contract_result.get('warnings', []),
                frame_details=contract_result.get('details', {}).get('actual_frame_titles', []),
                frame_mappings=frame_mappings
            )

        except Exception as e:
            logger.error(f"[LaTeXGenerator] 生成失败: {str(e)}")
            return LaTeXGenerationResult(success=False, error=str(e))

    async def _preprocess_scenes(self, scenes: List[Dict], preprocessed_scenes: List[Dict] = None) -> List[Dict]:
        """
        预处理场景数据

        Args:
            scenes: 原始场景数据
            preprocessed_scenes: 预处理后的场景数据（如果有）
        """
        safe_scenes = []

        # 创建预处理数据索引（方便快速查找）
        preprocessed_map = {}
        if preprocessed_scenes:
            for pp in preprocessed_scenes:
                scene_id = pp.get('sceneID', '')
                preprocessed_map[scene_id] = pp

        for scene in scenes:
            scene_id = scene.get("sceneID", "")

            # 优先使用预处理后的标题（已清理分页标记和冗余词）
            if scene_id in preprocessed_map:
                pp_data = preprocessed_map[scene_id]
                title = self._escape_text(pp_data.get("frameTitle", scene.get("frameTitle", "")))
            else:
                title = self._escape_text(scene.get("frameTitle", ""))

            content = self._escape_text(scene.get("mainContent", ""))

            # 如果有预处理数据，使用预处理后的内容
            if scene_id in preprocessed_map:
                pp_data = preprocessed_map[scene_id]
                # 使用预处理过的内容块
                if pp_data.get('contentBlocks'):
                    # 重建内容（从预处理后的内容块）
                    content = self._rebuild_content_from_blocks(pp_data['contentBlocks'])

            title = self._smart_latex_sanitize(title)
            content = self._smart_latex_sanitize(content)

            safe_scene = {
                "sceneID": scene_id,
                "frameTitle": title,
                "mainContent": content,
            }

            # 添加预处理元数据
            if scene_id in preprocessed_map:
                pp_data = preprocessed_map[scene_id]
                safe_scene['_preprocessed'] = {
                    'suggestedEnvironments': pp_data.get('suggestedEnvironments', []),
                    'estimatedHeight': pp_data.get('estimatedHeight', 0),
                    'needsMathMode': pp_data.get('needsMathMode', False),
                }

            safe_scenes.append(safe_scene)

        return safe_scenes

    def _rebuild_content_from_blocks(self, content_blocks: List[Dict]) -> str:
        """从预处理的内容块重建内容字符串"""
        parts = []
        for block in content_blocks:
            title = block.get('title', '')
            content = block.get('content', '')
            if title:
                parts.append(f"【{title}】{content}")
            else:
                parts.append(content)
        return '\n'.join(parts)

    def _escape_text(self, text: str) -> str:
        """转义LaTeX特殊字符和Unicode数学符号"""
        if not text:
            return ""

        # 0. 分数转换（最先处理，避免与其他处理冲突）
        # 将 a/b 转换为 \frac{a}{b} 格式
        text = self._convert_fractions(text)

        unicode_math_replacements = {
            '∠': r'$\angle$', '△': r'$\triangle$', '⊙': r'$\odot$',
            '∥': r'$\parallel$', '⊥': r'$\perp$', '°': '度',
            '′': '分', '″': '秒', '≌': r'$\cong$', '∽': r'$\sim$',
            '∈': r'$\in$', '∪': r'$\cup$', '∩': r'$\cap$',
            '±': r'$\pm$', '∑': r'$\sum$', '∏': r'$\prod$',
            'α': r'$\alpha$', 'β': r'$\beta$', 'γ': r'$\gamma$',
            'δ': r'$\delta$', 'θ': r'$\theta$', 'π': r'$\pi$',
            '≤': r'$\leq$', '≥': r'$\geq$', '≠': r'$\neq$',
            '≈': r'$\approx$', '∞': r'$\infty$',
            '＜': '<', '＞': '>', '（': '(', '）': ')',
            '【': '[', '】': ']',
            '，': ',', '。': '.', '：': ':', '；': ';',
            '？': '?', '！': '!',
        }

        for char, latex_cmd in unicode_math_replacements.items():
            text = text.replace(char, latex_cmd)

        latex_escapes = {
            '&': r'\&', '#': r'\#', '_': r'\_',
            '~': r'\textasciitilde{}', '%': r'\%',
            '|': r'\textbar{}', '{': r'\{', '}': r'\}',
        }

        for char, escape in latex_escapes.items():
            text = text.replace(char, escape)

        # 恢复分数占位符（在字符转义之后）
        text = self._restore_fraction_placeholders(text)

        return text

    def _auto_fix_brackets(self, text: str) -> str:
        """
        自动修复括号配对问题

        原则：
        1. 检测未闭合的左括号，自动补全右括号
        2. 检测多余的右括号，尝试转义或删除
        3. 优先修复数学模式中的括号问题
        """
        # 定义括号配对
        bracket_pairs = {'{': '}', '(': ')', '[': ']'}

        # 逐个字符检查括号配对
        result = []
        stack = []  # 存储未闭合的左括号

        i = 0
        n = len(text)

        while i < n:
            char = text[i]

            # 检查是否在数学模式中
            in_math = False
            if char == '$' and i + 1 < n and text[i + 1] != '$':
                # 进入数学模式，找到配对的$
                j = i + 1
                while j < n and text[j] != '$':
                    j += 1
                if j < n:
                    # 数学模式中的内容，暂时跳过括号检查
                    result.append(text[i:j + 1])
                    i = j + 1
                    continue

            if char in bracket_pairs:
                # 左括号，入栈
                stack.append((char, len(result)))
                result.append(char)
            elif char in bracket_pairs.values():
                # 右括号，检查是否有配对的左括号
                if stack:
                    left_bracket, _ = stack[-1]
                    if bracket_pairs[left_bracket] == char:
                        # 配对成功
                        stack.pop()
                        result.append(char)
                    else:
                        # 括号不匹配，转义这个右括号
                        if char == '}':
                            result.append(r'\}')
                        else:
                            result.append(char)
                else:
                    # 多余的右括号，转义它
                    if char == '}':
                        result.append(r'\}')
                    else:
                        result.append(char)
            else:
                result.append(char)

            i += 1

        # 处理未闭合的括号
        while stack:
            left_bracket, pos = stack.pop()
            # 在末尾添加对应的右括号
            result.append(bracket_pairs[left_bracket])

        return ''.join(result)

    def _smart_latex_sanitize(self, text: str) -> str:
        """
        智能净化LaTeX内容

        原则：
        1. 修复语法错误，不改变语义
        2. 优先使用兼容性更好的写法
        3. 保持中文内容的可读性

        处理顺序：
        1. 智能数学模式包裹（x^2 → $x^2$）
        2. 括号智能处理和修复
        3. 绝对值智能处理（||x|| → $|x|^2$）
        4. 特殊符号智能映射
        """
        import re

        if not text:
            return text

        # 1. 智能数学模式包裹（检测形如 字母^数字 的模式）
        # 在非数学模式中检测：x^2, a^3 等
        def wrap_bare_exponent(match):
            base = match.group(1)
            exp = match.group(2)
            return f'${{base}}^{{{exp}}}$'

        # 使用负向后顾确保不在数学模式中
        text = re.sub(r'(?<![^$]\$)([a-zA-Z])\^(\d+)(?![^$]\$)', wrap_bare_exponent, text)

        # 2. 括号智能处理和修复
        text = self._auto_fix_brackets(text)

        # 3. 绝对值智能处理（检测 ||x|| 双绝对值模式）
        # 将 ||x|| 转换为 $|x|^2$ 或 $\lvert x \rvert^2$
        text = re.sub(r'\|\|([^|]+)\|\|', r'$|\1|^2$', text)

        # 4. 集合写法转换 {a|b>0} → $\{a \mid b>0\}$
        text = re.sub(r'\{([^{}]*)\|([^{}]*)\}', r'$\\{\\1 \\mid \\2\\}$', text)

        return text

    def _convert_fractions(self, text: str) -> str:
        """
        将横式分数转换为LaTeX竖式分数格式
        例如: MB=1/2 CM=R → MB=$\\frac{1}{2}$CM=R

        特点：
        - 自动识别数字/数字、字母/字母格式
        - 排除URL中的斜杠（http://, https://, ftp://）
        - 避免重复转换已包含\\frac的内容
        - 使用占位符避免被后续转义影响
        """
        import re

        # 存储转换后的分数，使用不会被LaTeX转义的占位符
        fractions = []

        def replace_fraction(match):
            """替换单个分数，返回占位符"""
            numerator = match.group(1)
            denominator = match.group(2)

            # 检查是否为有效的分数格式
            if self._is_valid_fraction_part(numerator) and self._is_valid_fraction_part(denominator):
                # 生成LaTeX分数
                frac_latex = f'$\\frac{{{numerator}}}{{{denominator}}}$'
                # 使用不会被转义的占位符（包含括号，括号会被转义但我们先保存）
                placeholder = f'<<<FRAC{len(fractions)}>>>'
                fractions.append(frac_latex)
                return placeholder
            return match.group(0)

        # 先检查是否已包含 \frac（避免重复转换）
        if r'\frac' in text:
            return text

        # 先排除URL，避免误转换
        url_pattern = r'\b[a-z]+://[^\s]+'
        urls = []
        def save_url(match):
            urls.append(match.group(0))
            return f'<<<URL{len(urls)-1}>>>'

        text_without_urls = re.sub(url_pattern, save_url, text, flags=re.IGNORECASE)

        # 正则模式：匹配 a/b 格式
        pattern = r'(?<![a-zA-Z0-9:])(\d+|[a-zA-Z]+)\s*/\s*(\d+|[a-zA-Z]+)(?![a-zA-Z0-9/])'

        # 应用转换（使用占位符）
        result = re.sub(pattern, replace_fraction, text_without_urls)

        # 恢复URL
        for i, url in enumerate(urls):
            result = result.replace(f'<<<URL{i}>>>', url)

        # 将fractions列表作为属性存储，供后续恢复使用
        self._pending_fractions = fractions

        if fractions:
            logger.debug(f"[分数转换] 转换了{len(fractions)}个分数")

        return result

    def _restore_fraction_placeholders(self, text: str) -> str:
        """恢复分数占位符为实际的LaTeX代码"""
        if not hasattr(self, '_pending_fractions') or not self._pending_fractions:
            return text

        for i, frac_latex in enumerate(self._pending_fractions):
            # 恢复占位符（括号已被转义为 \{ 和 \}）
            text = text.replace(f'<<<FRAC{i}>>>', frac_latex)

        # 清空占位符列表
        self._pending_fractions = []
        return text

    def _is_valid_fraction_part(self, part: str) -> bool:
        """
        检查是否为有效的分数部分（分子或分母）

        允许：
        - 纯数字：123
        - 纯字母：AB, CM, x, y
        - 简单变量名：AB1, x2（无空格）

        不允许：
        - 包含空格
        - 空字符串
        """
        part = part.strip()

        # 空字符串无效
        if not part:
            return False

        # 包含空格无效
        if ' ' in part:
            return False

        # 允许：纯数字
        if part.isdigit():
            return True

        # 允许：纯字母
        if part.isalpha():
            return True

        # 允许：字母数字组合（无空格）
        if part.isalnum():
            return True

        return False

    # ========== 提示词构建方法 ==========
    def _build_first_batch_prompt(
        self,
        title: str,
        batch_scenes: List[Dict],
        total_scenes: int,
        preprocessing_hints: str = None
    ) -> str:
        """
        构建第一批次的提示词（2025升级版 - 教学设计优先）

        Args:
            title: 课程标题
            batch_scenes: 批次场景数据
            total_scenes: 总场景数
            preprocessing_hints: 预处理提示信息（如果有）
        """
        scene_ids = ', '.join([s.get('sceneID', '') for s in batch_scenes])

        # 检测是否有预处理
        has_preprocessing = preprocessing_hints is not None

        if has_preprocessing:
            logger.info("[Prompt构建] 使用简化模式（预处理已生效）")
            logger.info("[Prompt构建]   - 符号转换: 已完成")
            logger.info("[Prompt构建]   - 结构分析: 已完成")
            logger.info("[Prompt构建]   - LLM只需生成LaTeX代码")
        else:
            logger.info("[Prompt构建] 使用2025升级版prompt规则（首批）")
            logger.info("[Prompt构建]   - Beamer区块: block/exampleblock/alertblock")
            logger.info("[Prompt构建]   - 多栏布局: columns（对比场景）")
            logger.info("[Prompt构建]   - 紧凑列表: compactitem")
            logger.info("[Prompt构建]   - 扁平化: block内用换行不嵌套")

        batch_count = (total_scenes + batch_size - 1) // batch_size if 'batch_size' in dir() else (total_scenes + 1) // 2
        expected_count = len(batch_scenes)

        # 构建场景列表摘要
        scene_summary = "\n".join([
            f"  {i+1}. SceneID: {s.get('sceneID', '')}, 标题: {s.get('frameTitle', '')}"
            for i, s in enumerate(batch_scenes)
        ])

        # 【修改】生成严格的模板，强制LLM按SceneID顺序生成
        scene_templates_list = []
        for s in batch_scenes:
            title = s.get('frameTitle', '')
            scene_id = s.get('sceneID', '')
            # 使用字符串拼接避免花括号转义问题
            template = "\\begin{frame}{" + title + "}\n"
            template += "% SceneID: " + scene_id + "\n"
            template += "[在此处填写内容]\n"
            template += "\\end{frame}"
            scene_templates_list.append(template)
        scene_templates = "\n\n".join(scene_templates_list)

        # 使用普通字符串而非f-string，避免花括号转义问题
        scenes_json = json.dumps(batch_scenes, ensure_ascii=False, separators=(',', ':'), indent=2)

        # 基础prompt
        base_prompt = f"""# 任务
将以下教学场景转换为LaTeX Beamer代码（第一批次，包含文档头部）

# ⚠️ 最高优先级规则（违反即错误）
1. 【输出数量】必须且只能生成{expected_count}个frame，数量不对即为错误
2. 【SceneID列表】输出中只能包含以下SceneID：{scene_ids}
3. 【禁止事项】绝对禁止生成任何不在上述列表中的SceneID
4. 【SceneID顺序】必须按SceneID顺序输出，不能颠倒或跳过"""

        # 如果有预处理提示，添加简化版本
        if has_preprocessing:
            simplified_rules = """
# 内容格式规则（简化版 - 预处理已完成）

## 基础规则
1. 数学符号包裹：变量、公式使用$...$包裹
2. 使用建议的LaTeX环境（block/exampleblock/alertblock/itemize）

## block内容格式
使用\\textbf{{}}+\\\\组织内容：
```latex
\\begin{{block}}{{标题}}
  \\textbf{{要点1}}：内容\\\\
  \\textbf{{要点2}}：内容
\\end{{block}}
```

## 输出要求
1. 必须包含模板中的所有SceneID
2. SceneID顺序必须与模板一致
3. 只输出LaTeX代码
"""
            prompt = base_prompt + "\n" + preprocessing_hints + "\n" + simplified_rules
        else:
            # 使用完整的格式规则（原有逻辑）
            prompt = base_prompt + """
# 强制模板（请按此格式输出，不要改变SceneID）
```latex
\\documentclass{{beamer}}
\\usepackage{{ctex}}
\\usepackage{{amsthm}}
\\usepackage{{graphicx}}
\\usepackage{{xcolor}}
\\usepackage{{booktabs}}
\\usepackage{{multicol}}
\\usepackage{{amsmath,amssymb}}
\\begin{{document}}

{scene_templates}

\\end{{document}}
```

# 场景数据（用于填写模板内容）
```json
{scenes_json}
```

# 内容格式规则（2025升级版 - 教学设计优先）

## 通用规则
1. **禁止使用方括号作为文本标记**：不要使用[题目]、[思路引导]等格式，LaTeX中方括号用于可选参数
2. **必须使用\\\\textbf{{}}代替方括号**：\\\\textbf{{题目}}、\\\\textbf{{易错提醒}}、\\\\textbf{{方法总结}}
3. **数学符号包裹**：变量、公式使用$...$包裹，如$a$, $x^2$"""

            # 这里继续添加原有的完整格式规则...
            # 为了节省空间，暂时简化，实际部署时需要保留完整规则

        prompt += f"""

# 强制模板
```latex
\\documentclass{{beamer}}
\\usepackage{{ctex}}
\\usepackage{{amsthm}}
\\usepackage{{graphicx}}
\\usepackage{{xcolor}}
\\usepackage{{booktabs}}
\\usepackage{{multicol}}
\\usepackage{{amsmath,amssymb}}
\\begin{{document}}

{scene_templates}

\\end{{document}}
```

# 场景数据
```json
{scenes_json}
```

只输出完整的LaTeX代码。"""

        # 添加预处理提示（如果有）
        if preprocessing_hints:
            # 在格式规则之前插入预处理提示
            prompt = prompt.replace(
                "# 内容格式规则（2025升级版 - 教学设计优先）",
                preprocessing_hints + "\n\n# 内容格式规则（简化版 - 预处理已完成）"
            )
            # 同时简化格式规则（因为预处理已完成大部分工作）
            # 这里暂时保留完整规则，后续可以进一步简化

        return prompt

    def _build_subsequent_batch_prompt(
        self,
        batch_scenes: List[Dict],
        is_last_batch: bool,
        preprocessing_hints: str = None
    ) -> str:
        """
        构建后续批次的提示词（2025升级版 - 教学设计优先）

        Args:
            batch_scenes: 批次场景数据
            is_last_batch: 是否最后一批
            preprocessing_hints: 预处理提示信息（如果有）
        """
        scene_ids = ', '.join([s.get('sceneID', '') for s in batch_scenes])
        suffix = "（最后一批）" if is_last_batch else ""

        if preprocessing_hints:
            logger.info("[Prompt构建] 使用简化模式（预处理已生效，后续批次%s）", suffix)
        else:
            logger.info("[Prompt构建] 使用2025升级版prompt规则（后续批次%s）", suffix)

        expected_count = len(batch_scenes)

        # 构建场景列表摘要
        scene_summary = "\n".join([
            f"  {s.get('sceneID', '')}: {s.get('frameTitle', '')}"
            for s in batch_scenes
        ])

        # 【修改】生成严格的模板，强制LLM按SceneID顺序生成
        scene_templates_list = []
        for s in batch_scenes:
            title = s.get('frameTitle', '')
            scene_id = s.get('sceneID', '')
            # 使用字符串拼接避免花括号转义问题
            template = "\\begin{frame}{" + title + "}\n"
            template += "% SceneID: " + scene_id + "\n"
            template += "[在此处填写内容]\n"
            template += "\\end{frame}"
            scene_templates_list.append(template)
        scene_templates = "\n\n".join(scene_templates_list)

        # 使用普通字符串而非f-string，避免花括号转义问题
        scenes_json = json.dumps(batch_scenes, ensure_ascii=False, separators=(',', ':'))

        # 基础prompt
        base_task = f"""# 任务
生成LaTeX Beamer的**frame片段**{suffix}

# ⚠️ 最高优先级规则（违反即错误）
1. 【输出数量】必须且只能生成{expected_count}个frame，数量不对即为错误
2. 【SceneID列表】输出中只能包含以下SceneID：{scene_ids}
3. 【禁止事项】绝对禁止生成任何不在上述列表中的SceneID
4. 【SceneID顺序】必须按SceneID顺序输出，不能颠倒或跳过"""

        # 添加预处理提示（如果有）
        if preprocessing_hints:
            base_task += "\n" + preprocessing_hints + "\n"

        prompt = base_task + f"""

# 强制模板（请按此格式输出，不要改变SceneID）
```latex
{scene_templates}
```

# 场景数据（用于填写模板内容）
```json
{scenes_json}
```

# 内容格式规则（2025升级版 - 教学设计优先）

## 通用规则
1. **禁止使用方括号作为文本标记**：不要使用[题目]、[思路引导]等格式，LaTeX中方括号用于可选参数
2. **必须使用\\\\textbf{{}}代替方括号**：\\\\textbf{{题目}}、\\\\textbf{{易错提醒}}、\\\\textbf{{方法总结}}
3. **数学符号包裹**：变量、公式使用$...$包裹，如$a$, $x^2$

## 【重要】block内容格式（适用于所有block类型）

### ❌ 错误示例（禁止嵌套itemize）
```latex
\\\\begin{{block}}{{性质}}
  \\\\begin{{itemize}}
    \\\\item 性质1
    \\\\item 性质2
  \\\\end{{itemize}}
\\\\end{{block}}
```

### ✅ 正确示例（使用\\textbf{{}}+\\\\）
```latex
\\\\begin{{block}}{{性质}}
  \\\\textbf{{性质1}}：xxx\\\\\\
  \\\\textbf{{性质2}}：xxx\\\\\\
  \\\\textbf{{性质3}}：xxx
\\\\end{{block}}
```

## 输出要求
1. 必须包含模板中的所有SceneID
2. SceneID顺序必须与模板一致
3. 只输出frame片段，不输出文档头部和\\\\end{{document}}

只输出LaTeX代码。"""
        return prompt

    # ========== 分批生成方法 ==========
    async def _generate_latex_batches(
        self,
        title: str,
        safe_scenes: List[Dict],
        total_scenes: int,
        preprocessed_data: Dict = None
    ) -> str:
        """
        分批生成LaTeX

        Args:
            title: 课程标题
            safe_scenes: 预处理后的场景数据
            total_scenes: 总场景数
            preprocessed_data: 预处理元数据（包含批次建议等）
        """
        # 【调试】确认函数被调用
        import traceback
        logger.info(f"[调试] _generate_latex_batches被调用，调用栈:\n{''.join(traceback.format_stack()[-3:])}")

        # 使用预处理的批次建议，或默认值
        if preprocessed_data:
            batch_size = preprocessed_data.get('batchSuggestion', 2)
            has_preprocessing_hints = 'hints' in preprocessed_data
        else:
            batch_size = 2  # 默认批次大小降低到2
            has_preprocessing_hints = False

        logger.info(f"[分批LaTeX] 批次大小: {batch_size} (来源: {'预处理建议' if preprocessed_data else '默认值'})")
        scene_batches = [safe_scenes[i:i + batch_size] for i in range(0, len(safe_scenes), batch_size)]

        logger.info(f"[分批LaTeX] 总场景数: {len(safe_scenes)}, 分成 {len(scene_batches)} 批")

        batch_results = []
        MAX_BATCH_RETRY = 2

        for batch_idx, batch_scenes in enumerate(scene_batches):
            logger.info(f"[分批LaTeX] ========== 开始处理批次{batch_idx+1}/{len(scene_batches)}")
            is_first_batch = (batch_idx == 0)
            is_last_batch = (batch_idx == len(scene_batches) - 1)
            expected_frames = len(batch_scenes)

            if is_first_batch:
                batch_prompt = self._build_first_batch_prompt(
                    title,
                    batch_scenes,
                    len(safe_scenes),
                    preprocessed_data.get('hints') if preprocessed_data else None
                )
                max_tokens_batch = 10000  # 预处理后降低token需求
            else:
                batch_prompt = self._build_subsequent_batch_prompt(
                    batch_scenes,
                    is_last_batch,
                    preprocessed_data.get('hints') if preprocessed_data else None
                )
                max_tokens_batch = 6000   # 预处理后降低token需求
                max_tokens_batch = 8000   # 稳妥值：后续批次也需要充足空间

            logger.info(f"[分批LaTeX] 批次{batch_idx+1}: 期望{expected_frames}帧")
            logger.info(f"[分批LaTeX] 场景IDs: {[s.get('sceneID', '') for s in batch_scenes]}")

            # 契约验证：带重试的生成
            batch_tex = ""

            # 重试循环：最多尝试MAX_BATCH_RETRY+1次
            for retry in range(MAX_BATCH_RETRY + 1):
                try:
                    from shared.llm_client import LLMRequest

                    request = LLMRequest(
                        messages=[{"role": "user", "content": batch_prompt}],
                        temperature=0.0,
                        max_tokens=max_tokens_batch
                    )

                    response = await self.llm.call(request)

                    if not response.success:
                        logger.error(f"[分批LaTeX] 批次{batch_idx+1}失败: {response.error}")
                        raise Exception(f"批次{batch_idx+1}生成失败")

                    batch_tex = response.content.strip()

                    # 移除markdown标记
                    if "```" in batch_tex:
                        match = re.search(r'```(?:latex)?\s*([\s\S]*?)\s*```', batch_tex)
                        if match:
                            batch_tex = match.group(1).strip()

                    # 【2025-04-04】后处理：规范化LaTeX命令
                    # 使用ContentConverter处理非标准LaTeX命令
                    from .content_converter import ContentConverter
                    converter = ContentConverter()

                    original_tex = batch_tex
                    batch_tex = converter.normalize_latex_commands(batch_tex)

                    # 【调试】记录后处理执行情况（强制输出）
                    neqq_before = original_tex.count('\\neqq')
                    neqq_after = batch_tex.count('\\neqq')
                    print(f"[DEBUG PRINT] LaTeX后处理批次{batch_idx+1}: neqq处理前={neqq_before}, 处理后={neqq_after}")
                    logger.warning(f"[LaTeX后处理调试] 批次{batch_idx+1}: neqq处理前={neqq_before}, 处理后={neqq_after}")

                    if batch_tex != original_tex:
                        normalized_count = original_tex.count('\\neqq') + original_tex.count('\\leqq') + original_tex.count('\\geqq')
                        logger.info(f"[LaTeX后处理] 批次{batch_idx+1}规范化了{normalized_count}个非标准命令")

                    # 契约验证：严格检查SceneID
                    actual_frames = batch_tex.count('\\begin{frame}')

                    # 【增强】提取所有SceneID并详细验证
                    batch_scene_ids_set = set(s.get('sceneID', '') for s in batch_scenes)
                    batch_scene_ids_list = [s.get('sceneID', '') for s in batch_scenes]
                    actual_scene_ids_list = []
                    actual_scene_ids_set = set()

                    for sid_match in re.finditer(r'% SceneID:\s*(\S+)', batch_tex):
                        sid = sid_match.group(1)
                        actual_scene_ids_list.append(sid)
                        actual_scene_ids_set.add(sid)

                    # 【调试】始终输出详细SceneID对比信息
                    logger.info(f"[契约验证-调试] 批次{batch_idx+1} SceneID对比:")
                    logger.info(f"  期望SceneID: {batch_scene_ids_list}")
                    logger.info(f"  实际SceneID: {actual_scene_ids_list}")
                    logger.info(f"  期望SceneID集合: {batch_scene_ids_set}")
                    logger.info(f"  实际SceneID集合: {actual_scene_ids_set}")

                    # 【新增】检查没有SceneID的frame
                    all_frames = re.findall(r'\\begin\{frame\}.*?\\end\{frame\}', batch_tex, re.DOTALL)
                    frames_without_sceneid = []
                    for i, frame in enumerate(all_frames):
                        if not re.search(r'% SceneID:\s*\S+', frame):
                            title_match = re.search(r'\\begin\{frame\}\{([^}]*)\}|\\frametitle\{([^}]*)\}', frame)
                            title = title_match.group(1) or title_match.group(2) if title_match else "未知标题"
                            frames_without_sceneid.append(f"Frame {i+1}: {title}")

                    if frames_without_sceneid:
                        logger.warning(f"[契约验证-调试] 批次{batch_idx+1}发现{len(frames_without_sceneid)}个没有SceneID的frame:")
                        for frame_info in frames_without_sceneid:
                            logger.warning(f"    - {frame_info}")

                    # 【新增】输出批次LaTeX前500字符用于调试
                    logger.debug(f"[契约验证-调试] 批次{batch_idx+1} LaTeX内容预览:\n{batch_tex[:500]}")

                    # 【新增】验证SceneID顺序（检查是否按预期顺序出现）
                    if actual_scene_ids_list and actual_scene_ids_list != batch_scene_ids_list:
                        # 检查SceneID是否乱序
                        order_correct = True
                        for expected_sid, actual_sid in zip(batch_scene_ids_list, actual_scene_ids_list):
                            if expected_sid != actual_sid:
                                order_correct = False
                                break

                        if not order_correct:
                            logger.error(f"[契约验证-严重] 批次{batch_idx+1} SceneID顺序错误!")
                            logger.error(f"  预期顺序: {batch_scene_ids_list}")
                            logger.error(f"  实际顺序: {actual_scene_ids_list}")
                            logger.error(f"  这会导致内容错位，需要重新生成该批次!")

                    # 【新增】明显标记 - 验证新代码是否生效
                    logger.info(f"[新代码标记] 契约验证已执行 - 批次{batch_idx+1}")

                    # 详细验证
                    extra_scene_ids = actual_scene_ids_set - batch_scene_ids_set
                    missing_scene_ids = batch_scene_ids_set - actual_scene_ids_set

                    # 【新增】严格验证SceneID顺序
                    order_correct = True
                    if actual_scene_ids_list and len(actual_scene_ids_list) == len(batch_scene_ids_list):
                        for i, (expected, actual) in enumerate(zip(batch_scene_ids_list, actual_scene_ids_list)):
                            if expected != actual:
                                order_correct = False
                                logger.error(f"[契约验证-严重] 批次{batch_idx+1} SceneID顺序错误:")
                                logger.error(f"  位置{i+1}: 期望={expected}, 实际={actual}")
                                break
                    elif actual_scene_ids_list:
                        order_correct = False
                        logger.error(f"[契约验证-严重] 批次{batch_idx+1} SceneID数量不匹配:")
                        logger.error(f"  期望{len(batch_scene_ids_list)}个, 实际{len(actual_scene_ids_list)}个")

                    # 如果顺序错误，拒绝该批次并重试
                    if not order_correct:
                        logger.error(f"[契约验证-严重] 批次{batch_idx+1} SceneID顺序验证失败!")
                        logger.error(f"  期望顺序: {batch_scene_ids_list}")
                        logger.error(f"  实际顺序: {actual_scene_ids_list}")
                        logger.error(f"  该批次将被拒绝并重新生成")
                        if retry < MAX_BATCH_RETRY:
                            logger.warning(f"[契约验证] 重新生成批次{batch_idx+1} ({retry+1}/{MAX_BATCH_RETRY})")
                            break  # 跳出验证循环，重新生成
                        else:
                            logger.error(f"[契约验证] 批次{batch_idx+1}顺序错误且重试次数已用尽")
                            # 继续处理，让后续逻辑处理

                    # 场景1：有超出范围的SceneID（严重错误）
                    if extra_scene_ids:
                        logger.error(f"[契约验证] 批次{batch_idx+1}发现非法SceneID: {extra_scene_ids}")
                        logger.error(f"[契约验证] 期望SceneID: {batch_scene_ids_list}")
                        logger.error(f"[契约验证] 实际SceneID: {actual_scene_ids_list}")

                        # 尝试修复：删除超出范围的frame
                        logger.warning(f"[契约验证] 尝试删除非法frame...")
                        for extra_sid in extra_scene_ids:
                            # 删除包含该SceneID的完整frame
                            pattern = r'\\begin\{frame\}.*?% SceneID:\s*' + re.escape(extra_sid) + r'.*?\\end\{frame\}'
                            batch_tex = re.sub(pattern, '', batch_tex, flags=re.DOTALL)
                            logger.info(f"[契约验证] 已删除SceneID={extra_sid}的frame")

                        # 更新计数
                        actual_frames = batch_tex.count('\\begin{frame}')
                        actual_scene_ids_list = [m.group(1) for m in re.finditer(r'% SceneID:\s*(\S+)', batch_tex)]

                    # 场景2：有缺失的SceneID（警告）
                    if missing_scene_ids:
                        logger.warning(f"[契约验证] 批次{batch_idx+1}缺失SceneID: {missing_scene_ids}")
                        logger.warning(f"[契约验证] 期望SceneID: {batch_scene_ids_list}")
                        logger.warning(f"[契约验证] 实际SceneID: {actual_scene_ids_list}")

                    # 只检查是否有严重违约（帧数过少）
                    if actual_frames == 0:
                        if retry < MAX_BATCH_RETRY:
                            logger.warning(f"[契约验证] 批次{batch_idx+1}未生成任何frame，重试{retry+1}/{MAX_BATCH_RETRY}")
                            break
                        else:
                            logger.error(f"[契约验证] 批次{batch_idx+1}未生成任何frame且重试失败")
                            # 继续处理，让后续逻辑处理
                    elif actual_frames < expected_frames // 2:
                        # 帧数少于期望的一半，记录警告但继续
                        logger.warning(f"[契约验证] 批次{batch_idx+1}帧数偏少: {actual_frames}/{expected_frames}，将由智能分页模块处理")
                    elif extra_scene_ids:
                        # 已在上文处理，这里只记录
                        logger.info(f"[契约验证] 批次{batch_idx+1}: {actual_frames}帧（已删除{len(extra_scene_ids)}个非法frame）")
                    elif missing_scene_ids:
                        logger.warning(f"[契约验证] 批次{batch_idx+1}: {actual_frames}帧（缺失{len(missing_scene_ids)}个frame）")
                    else:
                        # 帧数合理或超过期望（LLM自主分页），正常记录
                        logger.info(f"[契约验证] 批次{batch_idx+1}: {actual_frames}帧（期望{expected_frames}场景，LLM已自主分页）")

                    logger.info(f"[分批LaTeX] 批次{batch_idx+1}生成完成, 长度={len(batch_tex)}")
                    break  # 成功，跳出重试循环

                except Exception as e:
                    logger.error(f"[分批LaTeX] 批次{batch_idx+1}异常(重试{retry}/{MAX_BATCH_RETRY}): {e}")
                    if retry < MAX_BATCH_RETRY:
                        logger.info(f"[分批LaTeX] 重试{retry+1}/{MAX_BATCH_RETRY}")
                        continue  # 继续下一次重试
                    else:
                        logger.error(f"[分批LaTeX] 批次{batch_idx+1}重试失败，跳过")
                        # 不重新抛出异常，继续处理下一批次
                        break  # 跳出重试循环

            if batch_tex:
                batch_results.append(batch_tex)
                logger.info(f"[分批LaTeX] 批次{batch_idx+1}已添加到结果列表")
            else:
                logger.warning(f"[分批LaTeX] 批次{batch_idx+1}内容为空，未添加")

        # 拼接所有批次
        tex_content = self._merge_batch_latex(batch_results)

        # 验证和修复frame顺序
        tex_content = self._validate_and_fix_frame_order(tex_content, safe_scenes)

        final_frame_count = tex_content.count(r'\begin{frame}')
        logger.info(f"[分批LaTeX] 拼接完成: 共 {final_frame_count} 个frame")

        return tex_content

    def _merge_batch_latex(self, batch_results: List[str]) -> str:
        """拼接所有批次的LaTeX代码"""
        if not batch_results:
            return ""

        logger.info(f"[分批LaTeX] 开始合并，共 {len(batch_results)} 个批次")
        merged_tex = batch_results[0]

        for i, batch_tex in enumerate(batch_results[1:], start=2):
            # 在f-string外计算frame数量，避免f-string中的转义问题
            batch_frame_count = batch_tex.count(r'\begin{frame}')
            logger.info(f"[分批LaTeX] 处理批次{i}: 原始长度={len(batch_tex)}, frame数量={batch_frame_count}")
            frame_fragments = self._extract_frames_fragment(batch_tex)

            # 调试：检查函数返回后的状态
            fragment_frame_count = frame_fragments.count(r'\begin{frame}')
            logger.info(f"[分批LaTeX] 批次{i}提取片段: 长度={len(frame_fragments)}, frame数量={fragment_frame_count}")

            # 验证：使用不同的计数方法
            count1 = frame_fragments.count(r'\begin{frame}')
            count2 = frame_fragments.count('\\begin{frame}')
            count3 = frame_fragments.count(r'\\begin{frame}')
            logger.info(f"[分批LaTeX] 批次{i}计数验证: r'\\begin{{frame}}'={count1}, '\\\\begin{{frame}}'={count2}, r'\\\\begin{{frame}}'={count3}")

            # 显示片段内容前200字符
            if frame_fragments:
                preview = frame_fragments[:200] if len(frame_fragments) > 200 else frame_fragments
                logger.info(f"[分批LaTeX] 批次{i}片段内容预览: {repr(preview)}...")
            if frame_fragments:
                end_doc_pos = merged_tex.rfind("\\end{document}")
                if end_doc_pos != -1:
                    merged_tex = merged_tex[:end_doc_pos] + frame_fragments + "\n" + merged_tex[end_doc_pos:]
                    logger.info(f"[分批LaTeX] 已合并批次{i} (插入\\end{{document}}前)")
                else:
                    # 找不到\end{document}时，直接追加到末尾
                    merged_tex = merged_tex + "\n" + frame_fragments
                    logger.info(f"[分批LaTeX] 已合并批次{i} (追加到末尾)")
            else:
                logger.warning(f"[分批LaTeX] 批次{i}提取片段为空")

        merged_frame_count = merged_tex.count(r'\begin{frame}')
        logger.info(f"[分批LaTeX] 拼接完成: 共 {merged_frame_count} 个frame")
        return merged_tex

    def _extract_frames_fragment(self, batch_tex: str) -> str:
        """从批次LaTeX中提取frame片段"""
        original_length = len(batch_tex)
        original_frames = batch_tex.count(r'\begin{frame}')

        # 使用re.escape构建正确的正则模式（匹配LaTeX中的\documentclass等）
        batch_tex = re.sub(re.escape(r'\documentclass') + r'\[[^\]]*\]\{[^\}]+\}', '', batch_tex)
        batch_tex = re.sub(re.escape(r'\usetheme') + r'\{[^\}]+\}', '', batch_tex)
        batch_tex = re.sub(re.escape(r'\begin{document}'), '', batch_tex)
        batch_tex = re.sub(re.escape(r'\end{document}'), '', batch_tex)
        result = batch_tex.strip()

        # 调试：检查返回前的状态
        result_frames = result.count(r'\begin{frame}')
        logger.info(f"[提取片段] 原始: {original_frames}帧, {original_length}字符 → 提取后: {result_frames}帧, {len(result)}字符")

        # 验证：在返回前再次计数
        verify_count = result.count(r'\begin{frame}')
        logger.info(f"[提取片段-验证] 返回前验证计数={verify_count}")

        # 显示提取后的内容前300字符
        preview = result[:300] if len(result) > 300 else result
        logger.info(f"[提取片段-内容预览] {repr(preview)}...")

        return result

    def _validate_and_fix_frame_order(self, tex_content: str, expected_scenes: List[Dict]) -> str:
        """
        验证和修复frame顺序

        检查生成的frames是否按照expected_scenes的顺序排列，
        如果发现顺序错误，尝试通过标题匹配重新排序

        Args:
            tex_content: LaTeX内容
            expected_scenes: 预期的场景列表（按正确顺序）

        Returns:
            修复后的LaTeX内容
        """
        import re

        logger.info("[顺序验证] 开始验证frame顺序")

        # 提取所有frames及其SceneID
        pattern = r'\\begin\{frame\}(?:\{([^\\}]*)\})?\s*(?:% SceneID:\s*(\S+))?\s*\n(.*?)\\end\{frame\}'
        frames_with_scene = []

        for match in re.finditer(pattern, tex_content, re.DOTALL):
            frame_title = match.group(1) or ""
            scene_id = match.group(2) or ""
            frame_content = match.group(3)
            full_frame = match.group(0)

            frames_with_scene.append({
                'title': frame_title.strip(),
                'scene_id': scene_id,
                'content': frame_content,
                'full_frame': full_frame
            })

        if not frames_with_scene:
            logger.warning("[顺序验证] 未找到任何frame，跳过验证")
            return tex_content

        # 统计有SceneID标记的frames
        frames_with_id = [f for f in frames_with_scene if f['scene_id']]
        logger.info(f"[顺序验证] 总共{len(frames_with_scene)}个frame，其中{len(frames_with_id)}个有SceneID标记")

        # 如果大部分frames都有SceneID，验证顺序
        if len(frames_with_id) >= len(frames_with_scene) * 0.5:
            # 检查顺序是否正确
            expected_scene_ids = [s.get('sceneID', '') for s in expected_scenes]
            actual_scene_ids = [f['scene_id'] for f in frames_with_scene if f['scene_id']]

            # 检查是否有顺序错误
            order_issues = []
            total_frames = len(actual_scene_ids)
            if total_frames == 0:
                return tex_content

            # 普适性检查1：最后几个frame的位置检查
            # 检查最后20%或至少3个frame的顺序
            check_count = max(3, int(total_frames * 0.2))
            for i in range(total_frames - check_count, total_frames):
                actual_id = actual_scene_ids[i]
                if actual_id in expected_scene_ids:
                    expected_pos = expected_scene_ids.index(actual_id)
                    # 最后部分的frame应该严格在正确位置
                    if expected_pos != i:
                        order_issues.append(f"❌ 关键位置错误：Frame{i}({actual_id})应在位置{expected_pos}")

            # 普适性检查2：使用相对比例而非绝对偏差
            threshold = max(2, int(total_frames * 0.15))  # 15%或至少2个位置
            for i, actual_id in enumerate(actual_scene_ids):
                if actual_id in expected_scene_ids:
                    expected_pos = expected_scene_ids.index(actual_id)
                    if abs(expected_pos - i) > threshold:
                        order_issues.append(f"Frame{i}({actual_id})应在位置{expected_pos}，实际在{i}（偏差{abs(expected_pos - i)}，阈值{threshold}）")

            if order_issues:
                logger.warning(f"[顺序验证] 发现{len(order_issues)}个顺序问题:")
                for issue in order_issues[:5]:  # 只显示前5个
                    logger.warning(f"  - {issue}")

                # 尝试重新排序
                logger.info("[顺序验证] 尝试通过SceneID重新排序frames")
                result = self._reorder_frames_by_scene_id(tex_content, expected_scene_ids)
                if result is not None:
                    return result
                else:
                    logger.warning("[顺序验证] 重新排序返回None，使用原始内容")
                    return tex_content
        else:
            logger.info("[顺序验证] SceneID标记不足，使用标题匹配验证和修复顺序")
            # 通过标题匹配验证并修复顺序
            result = self._validate_and_fix_order_by_title(tex_content, expected_scenes)
            if result is not None:
                return result
            else:
                logger.warning("[顺序验证] 标题匹配返回None，使用原始内容")
                return tex_content

        logger.info("[顺序验证] 顺序验证通过")
        return tex_content

    def _reorder_frames_by_scene_id(self, tex_content: str, expected_scene_ids: List[str]) -> str:
        """通过SceneID重新排序frames"""
        import re

        # 提取文档头部
        doc_start = tex_content.find(r'\begin{document}')
        if doc_start == -1:
            logger.error("[顺序修复] 无法找到\\begin{document}")
            return tex_content

        doc_header = tex_content[:doc_start + len(r'\begin{document}')]

        # 提取所有frames
        pattern = r'(\\begin\{frame\}.*?\\end\{frame\})'
        frames = re.findall(pattern, tex_content, re.DOTALL)

        # 提取每个frame的SceneID
        frame_map = {}  # scene_id -> frame
        for frame in frames:
            scene_match = re.search(r'% SceneID:\s*(\S+)', frame)
            if scene_match:
                scene_id = scene_match.group(1)
                frame_map[scene_id] = frame

        logger.info(f"[顺序修复] 找到{len(frame_map)}个有SceneID的frame，期望{len(expected_scene_ids)}个")

        # 检查是否有超出expected_scene_ids的多余frame
        extra_frames = [sid for sid in frame_map if sid not in expected_scene_ids]
        if extra_frames:
            logger.warning(f"[顺序修复] 发现{len(extra_frames)}个多余frame将被移除: {extra_frames}")

        # 按expected_scene_ids顺序重建（只保留在expected_scene_ids中的frame）
        ordered_frames = []
        used_ids = set()

        for scene_id in expected_scene_ids:
            if scene_id in frame_map and scene_id not in used_ids:
                ordered_frames.append(frame_map[scene_id])
                used_ids.add(scene_id)
            else:
                logger.warning(f"[顺序修复] 期望的frame {scene_id} 未找到")

        # 添加没有SceneID的frames（这些通常是分页产生的子frame）
        frames_without_id = [f for f in frames if not re.search(r'% SceneID:\s*\S+', f)]
        if frames_without_id:
            logger.info(f"[顺序修复] 添加{len(frames_without_id)}个无SceneID的frame")
            ordered_frames.extend(frames_without_id)

        logger.info(f"[顺序修复] 重新排序完成: {len(ordered_frames)}个frame")

        # 重建LaTeX
        new_tex = doc_header + "\n" + "\n\n".join(ordered_frames) + "\n" + r'\end{document}'

        return new_tex

    def _validate_and_fix_order_by_title(self, tex_content: str, expected_scenes: List[Dict]) -> str:
        """
        通过标题匹配验证并修复顺序

        当SceneID标记不足时，通过frame标题与expected_scenes的frameTitle匹配
        来检测和修复顺序问题
        """
        import re

        logger.info("[标题顺序修复] 开始通过标题匹配分析frame顺序")

        # 提取所有frames及其标题（改进的提取逻辑）
        frame_pattern = r'\\begin\{frame\}(?:\{([^\\}]*)\})?\s*\n(.*?)\\end\{frame\}'
        frames_info = []

        for match in re.finditer(frame_pattern, tex_content, re.DOTALL):
            full_frame = match.group(0)
            title_brace = match.group(1) or ""  # \begin{frame}{标题}
            content = match.group(2)

            # 尝试多种方式提取标题
            frame_title = title_brace

            # 尝试从content中提取\frametitle
            frametitle_match = re.search(r'\\frametitle\{([^\\}]*)\}', content)
            if frametitle_match:
                frame_title = frametitle_match.group(1)

            # 如果还是没有标题，尝试从内容开头提取
            if not frame_title:
                first_line = content.strip().split('\n')[0]
                if first_line and not first_line.startswith('\\'):
                    frame_title = first_line[:50]

            frames_info.append({
                'full_frame': full_frame,
                'title': frame_title.strip(),
                'original_pos': len(frames_info)
            })

            # 调试：输出前几个frame的标题
            if len(frames_info) <= 10:
                logger.debug(f"[标题顺序修复] Frame{len(frames_info)-1}: {frame_title[:50]}")

        logger.info(f"[标题顺序修复] 提取到{len(frames_info)}个frame")

        # 构建expected的标题列表（按顺序）
        expected_titles = []
        for i, scene in enumerate(expected_scenes):
            title = scene.get('frameTitle', '').strip()
            expected_titles.append(title)
            if i < 10:  # 只输出前10个
                logger.debug(f"[标题顺序修复] Expected{i}: {title[:50]}")

        # 创建标题到expected位置的映射（改进的匹配逻辑）
        title_to_expected_pos = {}
        for i, title in enumerate(expected_titles):
            if title:
                title_to_expected_pos[title] = i
                # 添加关键词匹配
                keywords = [k for k in title.split() if len(k) > 2]
                for kw in keywords:
                    if kw not in title_to_expected_pos:  # 避免覆盖精确匹配
                        title_to_expected_pos[kw] = i

        logger.info(f"[标题顺序修复] 构建了{len(title_to_expected_pos)}个标题映射")

        # 检查每个frame的预期位置
        frame_positions = []
        mismatches = []

        for i, frame_info in enumerate(frames_info):
            frame_title = frame_info['title']
            expected_pos = None

            # 尝试精确匹配
            if frame_title in title_to_expected_pos:
                expected_pos = title_to_expected_pos[frame_title]
            else:
                # 尝试关键词匹配
                for kw, pos in title_to_expected_pos.items():
                    if kw in frame_title and len(kw) > 2:
                        expected_pos = pos
                        break

            frame_positions.append({
                'index': i,
                'expected_pos': expected_pos,
                'title': frame_title[:30]
            })

            # 检测严重偏差
            if expected_pos is not None and abs(expected_pos - i) > 3:
                mismatches.append({
                    'frame_idx': i,
                    'expected_pos': expected_pos,
                    'title': frame_title[:30]
                })

        logger.info(f"[标题顺序修复] 发现{len(mismatches)}个严重位置偏差")

        # 输出具体的偏差信息
        for mismatch in mismatches[:10]:
            logger.warning(f"[标题顺序修复] Frame{mismatch['frame_idx']}({mismatch['title']})应在位置{mismatch['expected_pos']}")

        # 如果偏差超过阈值，进行重新排序
        if len(mismatches) > 2:
            logger.warning(f"[标题顺序修复] 检测到严重顺序问题，开始重新排序")

            # 按expected_pos重新排序frames（改进的排序算法）
            sorted_frames = []
            used_indices = set()

            # 首先按expected顺序放置frames
            for expected_pos in range(len(expected_titles)):
                expected_title = expected_titles[expected_pos]
                best_match_idx = None
                best_score = 0

                # 寻找最佳匹配
                for i, frame_info in enumerate(frames_info):
                    if i in used_indices:
                        continue

                    frame_title = frame_info['title']

                    # 计算匹配分数
                    score = 0
                    if frame_title == expected_title:
                        score = 100  # 完全匹配
                    elif expected_title in frame_title or frame_title in expected_title:
                        score = 50  # 包含关系
                    else:
                        # 关键词匹配
                        common_keywords = set(expected_title.split()) & set(frame_title.split())
                        score = len(common_keywords) * 10

                    if score > best_score:
                        best_match_idx = i
                        best_score = score

                # 如果找到匹配的frame，添加到排序结果
                if best_match_idx is not None and best_score >= 10:
                    sorted_frames.append(frames_info[best_match_idx]['full_frame'])
                    used_indices.add(best_match_idx)
                    logger.debug(f"[标题顺序修复] 位置{expected_pos}匹配到Frame{best_match_idx}（分数{best_score}）")

            # 添加未匹配的frames
            for i, frame_info in enumerate(frames_info):
                if i not in used_indices:
                    sorted_frames.append(frame_info['full_frame'])
                    logger.debug(f"[标题顺序修复] Frame{i}未匹配，追加到末尾")

            logger.info(f"[标题顺序修复] 重新排序完成: {len(sorted_frames)}个frame")

            # 重建LaTeX
            doc_start = tex_content.find(r'\begin{document}')
            if doc_start == -1:
                logger.error("[标题顺序修复] 无法找到\\begin{document}")
                return tex_content

            doc_header = tex_content[:doc_start + len(r'\begin{document}')]

            # 移除文档尾
            end_pos = tex_content.rfind(r'\end{document}')
            if end_pos != -1:
                new_tex = doc_header + "\n" + "\n\n".join(sorted_frames) + "\n" + tex_content[end_pos:]
            else:
                new_tex = doc_header + "\n" + "\n\n".join(sorted_frames) + "\n" + r'\end{document}'

            logger.info(f"[标题顺序修复] ✓ 重建LaTeX完成，已修复顺序问题")
            return new_tex
        else:
            logger.info(f"[标题顺序修复] ✓ 顺序基本正确（{len(mismatches)}个小偏差可忽略）")

        return tex_content

    def _create_frame_mappings_from_scenes(self, scenes: List[Dict]) -> List[FrameMapping]:
        """
        从场景列表创建frame映射（简化版）

        Args:
            scenes: 场景列表

        Returns:
            FrameMapping列表
        """
        mappings = []
        for i, scene in enumerate(scenes):
            # 提取内容摘要
            content = scene.get('mainContent', '')
            content_summary = self._extract_content_summary(content)

            mapping = FrameMapping(
                original_scene_id=scene.get('sceneID', ''),
                frame_num=i + 1,
                total_frames=len(scenes),
                frame_title=scene.get('frameTitle', ''),
                original_title=scene.get('frameTitle', ''),
                content_summary=content_summary,
                full_content=content
            )
            mappings.append(mapping)

        return mappings

    def _extract_content_summary(self, content: str, max_length: int = 150) -> str:
        """
        提取内容摘要（用于语音生成）

        Args:
            content: 完整内容
            max_length: 最大长度

        Returns:
            内容摘要
        """
        if not content:
            return ""

        # 清理LaTeX命令
        import re
        clean = re.sub(r'\\[a-zA-Z]+({[^}]*})?', '', content)
        clean = re.sub(r'[{}$\\]', '', clean)
        clean = re.sub(r'\n+', ' ', clean)
        clean = clean.strip()

        if len(clean) <= max_length:
            return clean

        # 在句号处截断
        truncated = clean[:max_length]
        last_period = truncated.rfind('。')
        if last_period > max_length // 2:
            return truncated[:last_period + 1]

        return truncated + "..."

    def _validate_frame_contract(self, expected_scenes: List[Dict], generated_latex: str) -> Dict[str, Any]:
        """验证LLM是否遵守帧数契约"""
        expected_count = len(expected_scenes)
        actual_count = generated_latex.count('\\begin{frame}')

        violations = []
        details = {
            'expected_scenes': [s.get('sceneID', '') for s in expected_scenes],
            'actual_frame_titles': [],
        }

        pattern = r'\\begin{frame}(?:\[[^\]]*\])?\{([^\}]+)\}'
        for match in re.finditer(pattern, generated_latex):
            frame_title = match.group(1).strip()
            details['actual_frame_titles'].append(frame_title)

        if actual_count != expected_count:
            diff = abs(actual_count - expected_count)
            if actual_count > expected_count:
                violations.append(f"LLM生成了{diff}个额外frame（契约规定{expected_count}个）")
            else:
                violations.append(f"LLM只生成了{actual_count}个frame（契约规定{expected_count}个）")

        return {
            'contract_obeyed': len(violations) == 0,
            'expected_frames': expected_count,
            'actual_frames': actual_count,
            'violations': violations,
            'details': details
        }

    def _fix_latex_common_errors(self, tex: str) -> str:
        """修复LaTeX常见错误（完整版）"""
        import re

        # ========== 【2025-04-04 新增】规范化LaTeX命令（最优先） ==========
        from .content_converter import ContentConverter
        converter = ContentConverter()

        original_tex = tex
        tex = converter.normalize_latex_commands(tex)

        neqq_before = original_tex.count('\\neqq')
        neqq_after = tex.count('\\neqq')
        if neqq_before > 0:
            logger.info(f"[LaTeX修复] ContentConverter规范化处理: neqq处理前={neqq_before}, 处理后={neqq_after}")

        # ========== 新增：itemize环境验证和修复（最优先） ==========
        logger.info("[LaTeX修复] ========== itemize环境验证 ==========")

        # 检查1：环境配对
        itemize_begin = tex.count(r'\begin{itemize}')
        itemize_end = tex.count(r'\end{itemize}')
        enumerate_begin = tex.count(r'\begin{enumerate}')
        enumerate_end = tex.count(r'\end{enumerate}')

        logger.info(f"[LaTeX修复] itemize环境: begin={itemize_begin}, end={itemize_end}")
        logger.info(f"[LaTeX修复] enumerate环境: begin={enumerate_begin}, end={enumerate_end}")

        # 检查2：检测并移除空的itemize环境
        empty_itemize_pattern = r'\\begin\{itemize\}\s*\\end\{itemize\}'
        empty_count = len(re.findall(empty_itemize_pattern, tex))
        if empty_count > 0:
            logger.warning(f"[LaTeX修复] 发现{empty_count}个空itemize环境，移除中...")
            tex = re.sub(empty_itemize_pattern, '', tex)

        empty_enum_pattern = r'\\begin\{enumerate\}\s*\\end\{enumerate\}'
        empty_enum_count = len(re.findall(empty_enum_pattern, tex))
        if empty_enum_count > 0:
            logger.warning(f"[LaTeX修复] 发现{empty_enum_count}个空enumerate环境，移除中...")
            tex = re.sub(empty_enum_pattern, '', tex)

        # 检查3：检测itemize环境内是否有\item
        def check_itemize_content(match):
            """检查itemize环境内容是否有效"""
            content = match.group(1)
            # 如果环境内没有任何\item
            if r'\item' not in content:
                logger.warning(f"[LaTeX修复] itemize环境缺少\\item，移除环境")
                return ''  # 移除这个无效的环境
            return match.group(0)

        # 检查并移除没有\item的itemize环境
        tex = re.sub(
            r'\\begin\{itemize\}([\s\S]*?)\\end\{itemize\}',
            check_itemize_content,
            tex
        )

        # 检查4：修复转义的\item
        if r'\item' in tex:
            logger.warning(f"[LaTeX修复] 发现转义的\\item，修复中...")
            tex = tex.replace(r'\item', r'\item')

        # 检查5：移除itemize环境开头多余的文本
        def fix_text_before_item(match):
            r"""移除\begin{itemize}和第一个\item之间的文本"""
            begin = match.group(1)
            content = match.group(2)
            # 如果内容开头不是\item，而是其他文本
            if content.strip() and not content.strip().startswith(r'\item'):
                # 尝试找到第一个\item
                item_match = re.search(r'\\item', content)
                if item_match:
                    # 保留从第一个\item开始的内容
                    new_content = content[item_match.start():]
                    logger.warning(f"[LaTeX修复] 移除itemize环境开头的多余文本")
                    return begin + new_content
                else:
                    # 没有任何\item，移除整个环境
                    logger.warning(f"[LaTeX修复] itemize环境完全没有\\item，移除环境")
                    return ''
            return match.group(0)

        # 只检查第一个itemize（避免重复处理）
        first_itemize = re.search(
            r'(\\begin\{itemize\})([\s\S]*?)(\\end\{itemize\})',
            tex
        )
        if first_itemize:
            fixed = fix_text_before_item(first_itemize)
            if fixed != first_itemize.group(0):
                tex = tex[:first_itemize.start()] + fixed + tex[first_itemize.end():]

        logger.info("[LaTeX修复] ========== itemize环境验证完成 ==========")

        # ========== 使用规则表进行修复 ==========
        logger.info("[LaTeX修复] ========== 应用错误修复规则表 ==========")

        fix_stats = {
            '符号替换': 0,
            '全角字符': 0,
            '宏包移除': 0,
            '重复命令': 0,
            '环境修复': 0,
            '宏包补全': 0,
        }

        # 1. 应用规则表中的简单替换（字符级、符号级）
        # ========== 正则表达式调试 ==========
        logger.info("[LaTeX修复] ========== 验证正则表达式 ==========")
        invalid_patterns = []
        for pattern, (replacement, description, needs_package) in LATEX_FIX_RULES.items():
            try:
                re.compile(pattern)
            except re.error as e:
                invalid_patterns.append((pattern, str(e)))
                logger.error(f"[LaTeX修复] ❌ 无效正则: {repr(pattern)[:50]}")
                logger.error(f"[LaTeX修复]    错误原因: {e}")

        if invalid_patterns:
            logger.error(f"[LaTeX修复] 发现 {len(invalid_patterns)} 个无效正则表达式")
            for pattern, error in invalid_patterns[:3]:  # 只显示前3个
                logger.error(f"  - 模式: {repr(pattern)[:50]}")
                logger.error(f"    错误: {error}")

        logger.info("[LaTeX修复] ========== 应用修复规则 ==========")

        for pattern, (replacement, description, needs_package) in LATEX_FIX_RULES.items():
            try:
                if re.search(pattern, tex):
                    tex = re.sub(pattern, replacement, tex)
                    if '符号' in description or 'Unicode' in description:
                        fix_stats['符号替换'] += 1
                    elif '全角' in description:
                        fix_stats['全角字符'] += 1
                    elif '宏包' in description:
                        fix_stats['宏包移除'] += 1
                    elif '重复' in description:
                        fix_stats['重复命令'] += 1
                    logger.debug(f"[LaTeX修复] {description}")
            except re.error as e:
                logger.warning(f"[LaTeX修复] 跳过无效规则: {description[:50]}, 错误: {e}")
                continue

        # 2. 确保itemize环境配对
        open_count = tex.count('\\begin{itemize}')
        close_count = tex.count('\\end{itemize}')

        if open_count > close_count:
            def add_missing_end(match):
                return '\\end{itemize}\n' + match.group(0)
            tex = re.sub(r'\\end\{frame\}', add_missing_end, tex)
            fix_stats['环境修复'] += 1
            logger.info(f"[LaTeX修复] 补全 {open_count - close_count} 个 \\end{{itemize}}")
        elif close_count > open_count:
            excess = close_count - open_count
            for _ in range(excess):
                tex = tex.replace('\\end{itemize}', '', 1)
            fix_stats['环境修复'] += 1
            logger.info(f"[LaTeX修复] 移除 {excess} 个多余的 \\end{{itemize}}")

        # 3. 确保enumerate环境配对
        enum_open = tex.count('\\begin{enumerate}')
        enum_close = tex.count('\\end{enumerate}')

        if enum_open > enum_close:
            def add_missing_enum_end(match):
                return '\\end{enumerate}\n' + match.group(0)
            tex = re.sub(r'\\end\{frame\}', add_missing_enum_end, tex)
            fix_stats['环境修复'] += 1
            logger.info(f"[LaTeX修复] 补全 {enum_open - enum_close} 个 \\end{{enumerate}}")
        elif enum_close > enum_open:
            excess = enum_close - enum_open
            for _ in range(excess):
                tex = tex.replace('\\end{enumerate}', '', 1)
            fix_stats['环境修复'] += 1
            logger.info(f"[LaTeX修复] 移除 {excess} 个多余的 \\end{{enumerate}}")

        # 3.5. 【2025升级版】展平深层嵌套的itemize环境，减少输入栈使用
        def flatten_itemize_nesting(content: str) -> str:
            """展平深层嵌套的itemize环境（强力版）"""
            import re

            # 检测当前最大嵌套深度
            def get_nesting_depth(text: str) -> int:
                max_depth = 0
                current_depth = 0
                for line in text.split('\n'):
                    stripped = line.strip()
                    if re.search(r'\\begin\{(itemize|enumerate)\}', stripped):
                        current_depth += 1
                        max_depth = max(max_depth, current_depth)
                    elif re.search(r'\\end\{(itemize|enumerate)\}', stripped):
                        current_depth -= 1
                return max_depth

            max_depth = get_nesting_depth(content)
            if max_depth > 3:
                logger.info(f"[LaTeX修复] 检测到嵌套深度{max_depth}，尝试展平...")

                # 强力展平策略：递归处理所有深层嵌套
                iteration = 0
                while True:
                    iteration += 1
                    old_content = content

                    # 匹配 \item xxx \begin{itemize} \item yyy \end{itemize}
                    # 将双层嵌套展平为单层
                    pattern = r'(\\item\s+[^\n]*?)\s*\\begin{itemize}\s*(\\item\s+[^\n]*?)\s*\\end{itemize}'

                    def flatten_match(match):
                        parent_item = match.group(1).strip()
                        child_item = match.group(2).strip()
                        # 使用缩进区分层级
                        return f"{parent_item}\n  {child_item}"

                    content = re.sub(pattern, flatten_match, content)
                    new_depth = get_nesting_depth(content)

                    # 如果深度足够或没有变化，停止
                    if new_depth <= 3 or content == old_content:
                        break

                    if iteration > 10:  # 防止无限循环
                        logger.warning(f"[LaTeX修复] 展平达到最大迭代次数")
                        break

                logger.info(f"[LaTeX修复] 展平完成: 原深度{max_depth} → 新深度{new_depth}，迭代{iteration}次")

            return content

        tex = flatten_itemize_nesting(tex)

        # 4. 补全文档结构和宏包
        if not tex.startswith("\\documentclass"):
            # 【2025升级版移除】输入栈配置已移除（Tectonic固定为5000）
            header = r"""\documentclass[aspectratio=169,12pt]{ctexbeamer}
\usetheme{Madrid}
\usepackage{amsmath,amssymb,amsthm,graphicx,xcolor,booktabs,multicol}
\setbeamersize{text margin left=10mm, text margin right=10mm}
\addtobeamertemplate{frametitle}{\vspace*{0.3cm}}{}
\addtobeamertemplate{frame start}{\vspace*{0.2cm}}{}
\addtobeamertemplate{frame end}{}{\vspace*{0.8cm}}
\begin{document}
"""
            tex = header + tex
            logger.info("[LaTeX修复] 补全文档结构")
        else:
            # LLM已生成documentclass，检查并补全缺失的宏包
            existing_packages = set()
            for match in re.finditer(r'\\usepackage\{([^}]+)\}', tex):
                packages = match.group(1).replace(' ', '').split(',')
                existing_packages.update(packages)

            # 检查规则表中需要的额外宏包
            extra_packages_needed = set()
            for cmd, pkg in EXTRA_PACKAGES_NEEDED.items():
                # 使用正则检测命令（避免匹配到字符串的一部分）
                pattern = r'\\' + re.escape(cmd) + r'\b'
                if re.search(pattern, tex) and pkg not in existing_packages:
                    extra_packages_needed.add(pkg)
                    logger.info(f"[LaTeX修复] 检测到命令 \\{cmd}，需要宏包: {pkg}")

            # 检查必需宏包
            missing_packages = [pkg for pkg in REQUIRED_PACKAGES if pkg not in existing_packages]
            missing_packages.extend(extra_packages_needed)

            if missing_packages:
                # 找到第一个 \usepackage 行，在其后插入
                first_usepackage = re.search(r'\\usepackage\{', tex)
                if first_usepackage:
                    insert_pos = tex.find('\n', first_usepackage.end()) + 1
                    packages_to_add = []
                    for pkg in missing_packages:
                        if pkg in REQUIRED_PACKAGES:
                            packages_to_add.append(REQUIRED_PACKAGES[pkg])
                        else:
                            packages_to_add.append(f'\\usepackage{{{pkg}}}')
                    tex = tex[:insert_pos] + '\n'.join(packages_to_add) + '\n' + tex[insert_pos:]
                    fix_stats['宏包补全'] = len(missing_packages)
                    logger.info(f"[LaTeX修复] 补全缺失宏包: {', '.join(missing_packages)}")
                    # 2025升级版：特别记录paralist宏包（已禁用，与beamer不兼容）
                    # if 'paralist' in missing_packages:
                    #     logger.info("[2025升级版] paralist紧凑列表宏包已启用")

            # 【2025升级版移除】输入栈扩容代码已移除
            # 原因：Tectonic的输入栈大小固定为5000，无法通过LaTeX命令修改
            # 解决方案：使用嵌套展平规则减少输入栈使用

        if "\\end{document}" not in tex:
            tex += "\n\\end{document}"

        # 打印修复统计
        total_fixes = sum(fix_stats.values())
        if total_fixes > 0:
            logger.info(f"[LaTeX修复] 修复统计: {fix_stats}")

        # ========== 返回修复后的LaTeX ==========
        return tex

# =============================================================================
# 便捷函数
# =============================================================================

async def generate_latex(
    llm_client,
    storyboard: Dict[str, Any],
    diagrams_dir: Optional[Path] = None
) -> LaTeXGenerationResult:
    """生成LaTeX的便捷函数"""
    generator = LaTeXGenerator(llm_client)
    return await generator.generate(storyboard, diagrams_dir)
