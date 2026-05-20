"""
知识库管理器

负责查询和管理教材、课标等数据
"""

import json
from pathlib import Path
from typing import Dict, List, Optional, Set
from dataclasses import dataclass, field


@dataclass
class ChapterInfo:
    """章节信息"""
    chapter_id: str
    chapter_name: str
    order: int
    knowledge_points: List[str]
    key_difficulties: List[str]
    common_mistakes: List[str]
    common_question_types: List[str]
    curriculum_requirement: str

    def __str__(self) -> str:
        return f"{self.chapter_name} (ID: {self.chapter_id})"


@dataclass
class GradeInfo:
    """年级信息"""
    grade_id: str
    grade_name: str
    chapters_count: int


@dataclass
class VersionInfo:
    """教材版本信息"""
    version_id: str
    version_name: str
    grades: List[str]


class KnowledgeBase:
    """
    知识库管理器

    功能：
    - 教材目录查询
    - 章节信息获取
    - 课标要求查询
    - 公式库查询
    - 超纲关键词检查

    使用示例：
    ```python
    kb = KnowledgeBase("./knowledge")

    # 获取版本列表
    versions = kb.get_versions()

    # 获取章节列表
    chapters = kb.get_chapters("renjiao_v1", "七年级上册")

    # 获取章节详情
    info = kb.get_chapter_info("renjiao_v1", "七年级上册", "c1_youshu")
    ```
    """

    # 支持的教材版本
    SUPPORTED_VERSIONS = {
        "renjiao_v1": "人教版",
        "beishi_v1": "北师大版",
        "suke_v1": "苏科版",
        "huke_v1": "沪科版",
    }

    # 课标要求层级
    CURRICULUM_LEVELS = ["了解", "理解", "掌握", "应用"]

    def __init__(self, knowledge_dir: str = "./teacher/knowledge"):
        """
        初始化知识库

        Args:
            knowledge_dir: 知识库目录路径
        """
        self.knowledge_dir = Path(knowledge_dir)
        self._textbooks: Dict[str, Dict] = {}
        self._curriculum: Dict = {}
        self._formulas: List[Dict] = []
        self._terms: Set[str] = set()
        self._forbidden_keywords: Set[str] = set()

        # 加载所有知识库数据
        self._load_all()

        print(f"[KnowledgeBase] 初始化完成")
        print(f"  目录: {self.knowledge_dir}")
        print(f"  教材版本: {len(self._textbooks)}")
        print(f"  公式数量: {len(self._formulas)}")
        print(f"  超纲关键词: {len(self._forbidden_keywords)}")

    def _load_all(self):
        """加载所有知识库数据"""
        self._load_textbooks()
        self._load_curriculum()
        self._load_formulas()
        self._load_terms()
        self._load_forbidden_keywords()

    def _load_textbooks(self):
        """加载教材目录"""
        textbook_dir = self.knowledge_dir / "textbooks"
        if not textbook_dir.exists():
            print(f"  [!] 教材目录不存在: {textbook_dir}")
            # 创建默认的空结构
            textbook_dir.mkdir(parents=True, exist_ok=True)
            self._create_default_textbook_files()
            return

        for file in textbook_dir.glob("*.json"):
            try:
                with open(file, encoding="utf-8") as f:
                    data = json.load(f)
                    version_id = data.get("version", file.stem)
                    self._textbooks[version_id] = data
                    print(f"  加载教材: {version_id}")
            except Exception as e:
                print(f"  [!] 加载教材失败 {file}: {e}")

    def _create_default_textbook_files(self):
        """创建默认的教材文件（占位符）"""
        for version_id, version_name in self.SUPPORTED_VERSIONS.items():
            default_data = {
                "version": version_id,
                "version_name": version_name,
                "subject": "数学",
                "stage": "初中",
                "grades": {
                    "七年级上册": {"chapters": []},
                    "七年级下册": {"chapters": []},
                    "八年级上册": {"chapters": []},
                    "八年级下册": {"chapters": []},
                    "九年级上册": {"chapters": []},
                    "九年级下册": {"chapters": []},
                }
            }
            file_path = self.knowledge_dir / "textbooks" / f"{version_id}.json"
            with open(file_path, "w", encoding="utf-8") as f:
                json.dump(default_data, f, ensure_ascii=False, indent=2)
            self._textbooks[version_id] = default_data
            print(f"  创建默认教材文件: {version_id}")

    def _load_curriculum(self):
        """加载课标库"""
        file = self.knowledge_dir / "curriculum_standard.json"
        if file.exists():
            try:
                with open(file, encoding="utf-8") as f:
                    self._curriculum = json.load(f)
            except Exception as e:
                print(f"  [!] 加载课标失败: {e}")

    def _load_formulas(self):
        """加载公式库"""
        file = self.knowledge_dir / "formulas.json"
        if file.exists():
            try:
                with open(file, encoding="utf-8") as f:
                    data = json.load(f)
                    self._formulas = data.get("formulas", [])
            except Exception as e:
                print(f"  [!] 加载公式库失败: {e}")

    def _load_terms(self):
        """加载术语库"""
        file = self.knowledge_dir / "terms.json"
        if file.exists():
            try:
                with open(file, encoding="utf-8") as f:
                    data = json.load(f)
                    self._terms = set(data.get("terms", []))
            except Exception as e:
                print(f"  [!] 加载术语库失败: {e}")

    def _load_forbidden_keywords(self):
        """加载超纲关键词库"""
        file = self.knowledge_dir / "forbidden_keywords.json"
        if file.exists():
            try:
                with open(file, encoding="utf-8") as f:
                    data = json.load(f)
                    keywords = data.get("keywords", [])
                    self._forbidden_keywords = set(keywords)
            except Exception as e:
                print(f"  [!] 加载超纲关键词库失败: {e}")
        else:
            # 使用默认的关键词
            self._forbidden_keywords = {
                "导数", "微分", "积分", "极限",
                "正弦定理", "余弦定理",
                "向量", "矩阵", "行列式",
            }

    # ========== 查询接口 ==========

    def get_versions(self) -> List[VersionInfo]:
        """获取所有教材版本"""
        return [
            VersionInfo(
                version_id=v,
                version_name=data.get("version_name", v),
                grades=list(data.get("grades", {}).keys())
            )
            for v, data in self._textbooks.items()
        ]

    def get_version_names(self) -> Dict[str, str]:
        """获取版本ID到名称的映射"""
        return {
            v: data.get("version_name", v)
            for v, data in self._textbooks.items()
        }

    def get_grades(self, version: str) -> List[str]:
        """获取指定版本的年级列表"""
        textbook = self._textbooks.get(version)
        if not textbook:
            return []
        return list(textbook.get("grades", {}).keys())

    def get_chapters(self, version: str, grade: str) -> List[Dict]:
        """获取指定版本的章节列表"""
        textbook = self._textbooks.get(version)
        if not textbook:
            return []

        grade_data = textbook.get("grades", {}).get(grade, {})
        return grade_data.get("chapters", [])

    def get_chapter_info(
        self,
        version: str,
        grade: str,
        chapter_id: str
    ) -> Optional[ChapterInfo]:
        """
        获取章节详细信息

        Args:
            version: 教材版本ID
            grade: 年级
            chapter_id: 章节ID

        Returns:
            章节信息，不存在返回None
        """
        chapters = self.get_chapters(version, grade)
        for chapter in chapters:
            if chapter.get("id") == chapter_id:
                return ChapterInfo(
                    chapter_id=chapter.get("id", ""),
                    chapter_name=chapter.get("name", ""),
                    order=chapter.get("order", 0),
                    knowledge_points=chapter.get("knowledge_points", []),
                    key_difficulties=chapter.get("key_difficulties", []),
                    common_mistakes=chapter.get("common_mistakes", []),
                    common_question_types=chapter.get("common_question_types", []),
                    curriculum_requirement=chapter.get("curriculum_requirement", "")
                )
        return None

    def search_chapters(
        self,
        version: str,
        keyword: str
    ) -> List[Dict]:
        """
        搜索章节（按名称或知识点）

        Args:
            version: 教材版本
            keyword: 搜索关键词

        Returns:
            匹配的章节列表
        """
        results = []
        textbook = self._textbooks.get(version)
        if not textbook:
            return results

        for grade_name, grade_data in textbook.get("grades", {}).items():
            for chapter in grade_data.get("chapters", []):
                # 搜索章节名称
                if keyword.lower() in chapter.get("name", "").lower():
                    results.append({
                        **chapter,
                        "grade": grade_name
                    })
                    continue

                # 搜索知识点
                for kp in chapter.get("knowledge_points", []):
                    if keyword.lower() in kp.lower():
                        results.append({
                            **chapter,
                            "grade": grade_name
                        })
                        break

        return results

    # ========== 校验接口 ==========

    def check_forbidden_keywords(self, content: str) -> List[str]:
        """
        检查内容是否包含超纲关键词

        Args:
            content: 待检查的内容

        Returns:
            找到的关键词列表
        """
        found = []
        content_lower = content.lower()

        for keyword in self._forbidden_keywords:
            if keyword.lower() in content_lower:
                found.append(keyword)

        return found

    def is_valid_curriculum_level(self, level: str) -> bool:
        """检查课标要求层级是否有效"""
        return level in self.CURRICULUM_LEVELS

    def get_formula(self, formula_id: str) -> Optional[Dict]:
        """根据ID获取公式"""
        for formula in self._formulas:
            if formula.get("id") == formula_id:
                return formula
        return None

    def search_formulas(self, keyword: str) -> List[Dict]:
        """搜索公式"""
        results = []
        keyword_lower = keyword.lower()

        for formula in self._formulas:
            if (keyword_lower in formula.get("name", "").lower() or
                keyword_lower in formula.get("category", "").lower()):
                results.append(formula)

        return results

    # ========== 数据管理接口 ==========

    def add_chapter(
        self,
        version: str,
        grade: str,
        chapter: Dict
    ):
        """添加或更新章节"""
        if version not in self._textbooks:
            self._textbooks[version] = {
                "version": version,
                "grades": {}
            }

        if grade not in self._textbooks[version]["grades"]:
            self._textbooks[version]["grades"][grade] = {"chapters": []}

        chapters = self._textbooks[version]["grades"][grade]["chapters"]
        chapter_id = chapter.get("id")

        # 检查是否已存在
        for i, ch in enumerate(chapters):
            if ch.get("id") == chapter_id:
                chapters[i] = chapter
                return

        # 不存在则添加
        chapters.append(chapter)

    def save_textbooks(self):
        """保存教材数据到文件"""
        textbook_dir = self.knowledge_dir / "textbooks"
        textbook_dir.mkdir(parents=True, exist_ok=True)

        for version_id, data in self._textbooks.items():
            file_path = textbook_dir / f"{version_id}.json"
            with open(file_path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)

    def add_forbidden_keyword(self, keyword: str):
        """添加超纲关键词"""
        self._forbidden_keywords.add(keyword)

    def get_forbidden_keywords(self) -> Set[str]:
        """获取所有超纲关键词"""
        return self._forbidden_keywords.copy()

