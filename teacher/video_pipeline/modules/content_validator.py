"""
内容一致性验证器（Content Consistency Validator）

职责：
1. 验证语音脚本是否覆盖了页面的关键概念
2. 检查narration与mainContent的一致性
3. 检测遗漏的重要知识点
4. 提供改进建议

使用场景：
- 语音脚本生成后的质量检查
- LLM生成结果的验证
- 回退策略的质量监控
"""

import re
import logging
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set, Tuple
from collections import Counter

# 使用统一的日志配置
from ..logging_config import get_module_logger
logger = get_module_logger(__name__, "content_validator")


@dataclass
class ConceptExtraction:
    """概念提取结果"""
    keywords: Set[str]  # 关键词集合
    formulas: Set[str]  # 数学公式
    terms: Set[str]  # 专业术语
    total_count: int  # 总概念数


@dataclass
class ConsistencyIssue:
    """一致性问题"""
    severity: str  # low/medium/high
    issue_type: str  # missing_keyword/missing_formula/length_mismatch/etc
    description: str
    suggestion: str


@dataclass
class ValidationResult:
    """验证结果"""
    scene_id: str
    is_valid: bool
    coverage_score: float  # 0-1，概念覆盖率
    issues: List[ConsistencyIssue] = field(default_factory=list)
    extracted_concepts: ConceptExtraction = None
    narration_stats: Dict = field(default_factory=dict)


class ContentConsistencyValidator:
    """
    内容一致性验证器

    功能：
    1. 从mainContent中提取关键概念
    2. 检查narration是否覆盖这些概念
    3. 验证narration长度是否合理
    4. 检测数学公式是否被正确朗读
    """

    # 关键词提取配置
    KEYWORD_PATTERNS = {
        'math_terms': r'(有理数|无理数|整数|分数|绝对值|相反数|倒数|幂|根号|方程|不等式|函数|定义域|值域)',
        'geometry_terms': r'(三角形|正方形|长方形|圆|角|边|顶点|高|底|周长|面积|体积)',
        'operations': r'(加法|减法|乘法|除法|乘方|开方|混合运算)',
        'concepts': r'(定义|性质|定理|公理|推论|公式|法则|方法|步骤)',
    }

    # LaTeX公式提取模式
    LATEX_PATTERNS = [
        r'\$[^$]+\$',  # $...$ 行内公式
        r'\\\[.*?\\\]',  # \[...\] 行间公式
        r'\\\(.*?\\\)',  # \(...\) 行内公式（另一种写法）
    ]

    def __init__(self, min_coverage: float = 0.6):
        """
        初始化验证器

        Args:
            min_coverage: 最低概念覆盖率（0-1），低于此值视为不合格
        """
        self.min_coverage = min_coverage
        logger.info("[ContentValidator] 初始化完成，min_coverage=%.2f", min_coverage)

    def extract_concepts_from_content(self, content: str) -> ConceptExtraction:
        """
        从内容中提取关键概念

        Args:
            content: mainContent内容

        Returns:
            ConceptExtraction: 提取的概念集合
        """
        keywords = set()
        formulas = set()
        terms = set()

        # 1. 提取数学术语和几何术语
        for category, pattern in self.KEYWORD_PATTERNS.items():
            matches = re.findall(pattern, content)
            keywords.update(matches)
            if category in ['math_terms', 'geometry_terms']:
                terms.update(matches)

        # 2. 提取LaTeX公式
        for pattern in self.LATEX_PATTERNS:
            matches = re.findall(pattern, content)
            formulas.update(matches)

        # 3. 提取其他重要术语（中文+数字组合，如"二次函数"）
        # 匹配2-4个字的中文术语
        chinese_term_pattern = r'[\u4e00-\u9fa5]{2,4}(?:定义|性质|定理|公式|法则|方法)'
        chinese_terms = re.findall(chinese_term_pattern, content)
        terms.update(chinese_terms)

        # 4. 提取数字相关概念（如"一次函数"、"二次方程"）
        number_concept_pattern = r'[\u4e00-\u9fa5]+[一二三四两三四五六七八九十次幂方根]+'
        number_concepts = re.findall(number_concept_pattern, content)
        terms.update(number_concepts)

        total_count = len(keywords) + len(formulas) + len(terms)

        logger.debug(f"[ContentValidator] 提取概念: 关键词{len(keywords)}个, 公式{len(formulas)}个, 术语{len(terms)}个")

        return ConceptExtraction(
            keywords=keywords,
            formulas=formulas,
            terms=terms,
            total_count=total_count
        )

    def validate_scene(
        self,
        scene_id: str,
        main_content: str,
        narration_list: List[str],
        slide_type: str
    ) -> ValidationResult:
        """
        验证单个场景的内容一致性

        Args:
            scene_id: 场景ID
            main_content: 主要内容（mainContent）
            narration_list: 旁白列表
            slide_type: 幻灯片类型

        Returns:
            ValidationResult: 验证结果
        """
        logger.info(f"[ContentValidator] 验证场景 {scene_id} ({slide_type})")

        issues = []

        # 1. 提取内容中的关键概念
        concepts = self.extract_concepts_from_content(main_content)

        # 2. 合并所有narration文本
        full_narration = " ".join(narration_list)

        # 3. 计算概念覆盖率
        coverage = self._calculate_concept_coverage(concepts, full_narration)

        # 4. 检查遗漏的关键概念
        missing_keywords = self._find_missing_concepts(concepts.keywords, full_narration)
        missing_formulas = self._find_missing_concepts(concepts.formulas, full_narration)

        if missing_keywords:
            issues.append(ConsistencyIssue(
                severity="high",
                issue_type="missing_keyword",
                description=f"遗漏关键词: {', '.join(list(missing_keywords)[:5])}",
                suggestion=f"在narration中提及这些关键词以保持一致性"
            ))

        if missing_formulas:
            issues.append(ConsistencyIssue(
                severity="medium",
                issue_type="missing_formula",
                description=f"可能未讲解的公式: {len(missing_formulas)}个",
                suggestion=f"确保每个重要公式都有相应的语音讲解"
            ))

        # 5. 验证narration长度
        total_length = sum(len(n) for n in narration_list)
        length_valid, length_issue = self._validate_narration_length(
            total_length, slide_type, main_content
        )
        if not length_valid:
            issues.append(length_issue)

        # 6. 检查数学符号格式
        symbol_issues = self._check_math_symbols_format(narration_list)
        issues.extend(symbol_issues)

        # 7. 生成统计信息
        narration_stats = {
            'total_length': total_length,
            'segment_count': len(narration_list),
            'avg_segment_length': total_length // len(narration_list) if narration_list else 0
        }

        # 8. 计算是否有效
        is_valid = coverage >= self.min_coverage and not any(
            i.severity == "high" for i in issues
        )

        result = ValidationResult(
            scene_id=scene_id,
            is_valid=is_valid,
            coverage_score=coverage,
            issues=issues,
            extracted_concepts=concepts,
            narration_stats=narration_stats
        )

        logger.info(f"[ContentValidator] {scene_id}: 覆盖率={coverage:.2%}, 问题数={len(issues)}, 有效={is_valid}")

        return result

    def _calculate_concept_coverage(
        self,
        concepts: ConceptExtraction,
        narration: str
    ) -> float:
        """计算概念覆盖率"""
        if concepts.total_count == 0:
            return 1.0  # 没有概念需要覆盖，视为完全覆盖

        covered = 0
        total = 0

        # 检查关键词覆盖率
        for keyword in concepts.keywords:
            total += 1
            if keyword in narration:
                covered += 1

        # 检查术语覆盖率
        for term in concepts.terms:
            total += 1
            if term in narration:
                covered += 1

        # 检查公式覆盖率（简化：检查是否有相关讲解）
        for formula in concepts.formulas:
            total += 1
            # 公式可能不会直接出现在narration中（会被转换），所以检查是否有相关词汇
            # 这里简化处理：如果narration包含"公式"、"计算"、"等于"等词，认为已覆盖
            if any(word in narration for word in ['公式', '计算', '等于', '是']):
                covered += 1

        return covered / total if total > 0 else 1.0

    def _find_missing_concepts(
        self,
        concepts: Set[str],
        narration: str
    ) -> Set[str]:
        """找出narration中未提及的概念"""
        missing = set()
        for concept in concepts:
            if concept not in narration:
                missing.add(concept)
        return missing

    def _validate_narration_length(
        self,
        length: int,
        slide_type: str,
        content: str
    ) -> Tuple[bool, Optional[ConsistencyIssue]]:
        """验证narration长度是否合理"""
        # 根据slide类型设定期望长度范围
        length_ranges = {
            'title': (30, 100),
            'objectives': (50, 150),
            'intro': (80, 200),
            'concept': (100, 300),
            'example': (120, 350),
            'practice': (100, 300),
            'summary': (150, 400),
        }

        min_len, max_len = length_ranges.get(slide_type, (80, 250))

        # 根据内容长度动态调整
        content_len = len(content)
        if content_len > 400:
            max_len += 150
            min_len += 50

        if length < min_len:
            return False, ConsistencyIssue(
                severity="medium",
                issue_type="length_too_short",
                description=f"narration过短: {length}字 < 最小{min_len}字",
                suggestion=f"增加讲解细节，至少达到{min_len}字"
            )
        elif length > max_len:
            return False, ConsistencyIssue(
                severity="low",
                issue_type="length_too_long",
                description=f"narration过长: {length}字 > 最大{max_len}字",
                suggestion=f"精简内容，控制在{max_len}字以内"
            )

        return True, None

    def _check_math_symbols_format(
        self,
        narration_list: List[str]
    ) -> List[ConsistencyIssue]:
        """检查数学符号格式是否正确"""
        issues = []

        # 检查连续的英文大写字母（应该有空格分隔）
        for narration in narration_list:
            # 查找可能的问题模式（连续2个以上大写字母且没有空格）
            # 但要排除已经被正确格式化的（带空格的）
            # 这里只检查明显的问题，如"连接AB"这种

            # 检查是否有未格式化的连续大写字母
            # 排除"的"、"是"等中文后的情况
            problematic_patterns = [
                r'[\u4e00-\u9fa5]([A-Z]{2,})[^\s]',  # 中文+连续大写字母+非空格
            ]

            for pattern in problematic_patterns:
                matches = re.finditer(pattern, narration)
                for match in matches:
                    consecutive = match.group(1)
                    if len(consecutive) >= 2:
                        issues.append(ConsistencyIssue(
                            severity="low",
                            issue_type="symbol_format",
                            description=f"可能未格式化的连续字母: {consecutive}",
                            suggestion=f"将{consecutive}格式化为{' '.join(consecutive)}以确保TTS正确朗读"
                        ))

        return issues

    def validate_storyboard(
        self,
        storyboard_data: Dict,
        script_result: Dict
    ) -> Dict[str, ValidationResult]:
        """
        验证整个分镜的脚本一致性

        Args:
            storyboard_data: 分镜数据（包含mainContent）
            script_result: 脚本生成结果（包含narration）

        Returns:
            Dict[scene_id, ValidationResult]: 每个场景的验证结果
        """
        logger.info("[ContentValidator] ========== 开始验证分镜一致性 ==========")

        results = {}

        scenes = storyboard_data.get('scenes', [])
        script_by_scene = script_result.get('scriptByScene', {})

        for scene in scenes:
            scene_id = scene.get('sceneID', '')
            main_content = scene.get('mainContent', '')
            slide_type = scene.get('slideType', '')

            # 从脚本结果中获取narration
            script = script_by_scene.get(scene_id, {})
            narration = script.get('narration', [])

            if not narration:
                logger.warning(f"[ContentValidator] 场景{scene_id}没有narration")
                continue

            # 验证单个场景
            result = self.validate_scene(
                scene_id=scene_id,
                main_content=main_content,
                narration_list=narration,
                slide_type=slide_type
            )

            results[scene_id] = result

        # 生成总结报告
        self._print_validation_summary(results)

        return results

    def _print_validation_summary(self, results: Dict[str, ValidationResult]):
        """打印验证总结报告"""
        total = len(results)
        valid = sum(1 for r in results.values() if r.is_valid)
        avg_coverage = sum(r.coverage_score for r in results.values()) / total if total > 0 else 0
        total_issues = sum(len(r.issues) for r in results.values())

        print("\n" + "=" * 60)
        print("[ContentValidator] 内容一致性验证报告")
        print("=" * 60)
        print(f"总场景数: {total}")
        print(f"验证通过: {valid} ({valid/total*100:.1f}%)")
        print(f"平均覆盖率: {avg_coverage:.1%}")
        print(f"发现问题: {total_issues} 个")
        print("=" * 60)

        # 列出有问题的高优先级场景
        high_priority_issues = [
            (sid, r) for sid, r in results.items()
            if not r.is_valid or any(i.severity == "high" for i in r.issues)
        ]

        if high_priority_issues:
            print("\n需要关注的场景:")
            for scene_id, result in high_priority_issues[:5]:  # 最多显示5个
                print(f"  - {scene_id}: 覆盖率={result.coverage_score:.1%}, 问题={len(result.issues)}个")
                for issue in result.issues[:2]:  # 每个场景最多显示2个问题
                    print(f"      [{issue.severity}] {issue.description}")

        print("=" * 60 + "\n")


# 便捷函数

def validate_content_consistency(
    storyboard_data: Dict,
    script_result: Dict,
    min_coverage: float = 0.6
) -> Dict[str, ValidationResult]:
    """
    验证内容一致性的便捷函数

    Args:
        storyboard_data: 分镜数据
        script_result: 脚本结果
        min_coverage: 最低覆盖率要求

    Returns:
        Dict[scene_id, ValidationResult]: 验证结果
    """
    validator = ContentConsistencyValidator(min_coverage=min_coverage)
    return validator.validate_storyboard(storyboard_data, script_result)
