"""
JSON 数据库管理模块

提供简单的JSON文件读写功能，支持：
- 用户管理 (users.json)
- 课程管理 (courses.json)
- 分享记录 (shares.json)
- 历史记录 (history.json)
"""

import json
import os
from pathlib import Path
from typing import Dict, List, Any, Optional
from datetime import datetime
import hashlib
import uuid


class JSONDatabase:
    """JSON数据库基类"""

    def __init__(self, data_dir: str = "./data"):
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(parents=True, exist_ok=True)

        self._lock = {}  # 简单的文件锁

    def _read_json(self, filename: str) -> Dict:
        """读取JSON文件"""
        filepath = self.data_dir / filename

        if not filepath.exists():
            return {}

        try:
            with open(filepath, 'r', encoding='utf-8') as f:
                return json.load(f)
        except json.JSONDecodeError:
            return {}

    def _write_json(self, filename: str, data: Dict):
        """写入JSON文件"""
        filepath = self.data_dir / filename

        # 确保目录存在
        self.data_dir.mkdir(parents=True, exist_ok=True)

        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

    def _get_id(self, prefix: str = "id") -> str:
        """生成唯一ID"""
        return f"{prefix}_{uuid.uuid4().hex[:8]}"


class UserDatabase(JSONDatabase):
    """用户数据库"""

    def __init__(self, data_dir: str = "./data"):
        super().__init__(data_dir)
        self.filename = "users.json"

    def init_default_data(self):
        """初始化默认数据"""
        data = self._read_json(self.filename)

        if not data.get("users"):
            # 创建默认管理员和测试用户
            data["users"] = [
                {
                    "id": "u_admin_001",
                    "username": "admin",
                    "password": self._hash_password("admin123"),
                    "role": "teacher",
                    "email": "admin@example.com",
                    "classes": [],
                    "created_at": datetime.now().isoformat()
                },
                {
                    "id": "u_teacher_001",
                    "username": "张老师",
                    "password": self._hash_password("teacher123"),
                    "role": "teacher",
                    "email": "zhang@example.com",
                    "classes": ["七年级1班", "七年级2班"],
                    "created_at": datetime.now().isoformat()
                },
                {
                    "id": "u_student_001",
                    "username": "李同学",
                    "password": self._hash_password("student123"),
                    "role": "student",
                    "email": "",
                    "student_id": "2024001",
                    "class": "七年级1班",
                    "created_at": datetime.now().isoformat()
                }
            ]
            self._write_json(self.filename, data)

    def _hash_password(self, password: str) -> str:
        """密码哈希（简单实现，生产环境应使用bcrypt）"""
        return hashlib.sha256(password.encode()).hexdigest()

    def verify_password(self, password: str, hashed: str) -> bool:
        """验证密码"""
        return self._hash_password(password) == hashed

    def get_user_by_username(self, username: str) -> Optional[Dict]:
        """根据用户名获取用户"""
        data = self._read_json(self.filename)
        for user in data.get("users", []):
            if user["username"] == username:
                return user
        return None

    def get_user_by_id(self, user_id: str) -> Optional[Dict]:
        """根据ID获取用户"""
        data = self._read_json(self.filename)
        for user in data.get("users", []):
            if user["id"] == user_id:
                return user
        return None

    def create_user(self, username: str, password: str, role: str,
                   email: str = "", student_id: str = "", class_name: str = "") -> Optional[Dict]:
        """创建用户"""
        data = self._read_json(self.filename)

        # 如果文件为空或不存在，初始化用户列表
        if "users" not in data:
            data["users"] = []

        # 检查用户名是否已存在
        if self.get_user_by_username(username):
            return None

        user = {
            "id": self._get_id("u"),
            "username": username,
            "password": self._hash_password(password),
            "role": role,
            "email": email,
            "created_at": datetime.now().isoformat()
        }

        if role == "student":
            user["student_id"] = student_id
            user["class"] = class_name
        elif role == "teacher":
            user["classes"] = []

        data["users"].append(user)

        # 写入JSON文件
        try:
            self._write_json(self.filename, data)
        except Exception as e:
            print(f"[UserDatabase] 写入用户数据失败: {e}")
            return None

        # 返回用户信息（不包含密码）
        user_info = user.copy()
        del user_info["password"]
        return user_info

    def update_user(self, user_id: str, updates: Dict) -> bool:
        """更新用户信息"""
        data = self._read_json(self.filename)

        for i, user in enumerate(data.get("users", [])):
            if user["id"] == user_id:
                data["users"][i].update(updates)
                self._write_json(self.filename, data)
                return True
        return False

    def get_students_by_class(self, class_name: str) -> List[Dict]:
        """获取班级所有学生"""
        data = self._read_json(self.filename)
        students = []
        for user in data.get("users", []):
            if user.get("role") == "student" and user.get("class") == class_name:
                user_info = user.copy()
                del user_info["password"]
                students.append(user_info)
        return students

    def get_all_teachers(self) -> List[Dict]:
        """获取所有教师"""
        data = self._read_json(self.filename)
        teachers = []
        for user in data.get("users", []):
            if user.get("role") == "teacher":
                user_info = user.copy()
                del user_info["password"]
                teachers.append(user_info)
        return teachers


class CourseDatabase(JSONDatabase):
    """课程数据库"""

    def __init__(self, data_dir: str = "./data"):
        super().__init__(data_dir)

    def create_course(self, teacher_id: str, title: str,
                     grade: str, chapter: str, version: str = "",
                     sections: Dict = None, metadata: Dict = None,
                     content: Dict = None) -> str:
        """创建课程"""
        if sections is None:
            sections = {}
        if metadata is None:
            metadata = {}
        if content is None:
            content = {}

        data = self._read_json("courses.json")

        if "courses" not in data:
            data["courses"] = []

        course = {
            "id": self._get_id("c"),
            "teacher_id": teacher_id,
            "title": title,
            "grade": grade,
            "chapter": chapter,
            "version": version,
            "sections": sections,
            "metadata": metadata,
            "content": content,
            "created_at": datetime.now().isoformat()
        }

        data["courses"].append(course)
        self._write_json("courses.json", data)

        return course["id"]

    def get_course_by_id(self, course_id: str) -> Optional[Dict]:
        """根据ID获取课程"""
        data = self._read_json("courses.json")
        for course in data.get("courses", []):
            if course["id"] == course_id:
                return course
        return None

    def get_courses_by_teacher(self, teacher_id: str) -> List[Dict]:
        """获取教师的所有课程"""
        data = self._read_json("courses.json")
        courses = []
        for course in data.get("courses", []):
            if course.get("teacher_id") == teacher_id:
                courses.append(course)
        return courses

    def find_course_by_task_id(self, teacher_id: str, task_id: str) -> Optional[Dict]:
        """根据 task_id 查找课程（用于防止重复保存）"""
        data = self._read_json("courses.json")
        for course in data.get("courses", []):
            if course.get("teacher_id") == teacher_id:
                # 检查 metadata 中是否存储了 task_id
                metadata = course.get("metadata", {})
                if metadata.get("task_id") == task_id:
                    return course
        return None

    def get_accessible_courses(self, user_id: str, user_role: str, user_class_name: str = "") -> List[Dict]:
        """获取用户可访问的课程"""
        if user_role == "teacher":
            # 教师可以访问自己创建的课程
            return self.get_courses_by_teacher(user_id)
        else:
            # 学生可以访问分享给他的课程（包括班级分享）
            share_db = ShareDatabase(self.data_dir)
            shared_course_ids = share_db.get_shared_courses_for_student(user_id, user_class_name)

            courses = []
            for course_id in shared_course_ids:
                course = self.get_course_by_id(course_id)
                if course:
                    courses.append(course)
            return courses

    def update_course(self, course_id: str, updates: Dict) -> bool:
        """更新课程"""
        data = self._read_json("courses.json")

        for i, course in enumerate(data.get("courses", [])):
            if course["id"] == course_id:
                data["courses"][i].update(updates)
                self._write_json("courses.json", data)
                return True
        return False

    def delete_course(self, course_id: str) -> bool:
        """删除课程"""
        data = self._read_json("courses.json")

        courses = data.get("courses", [])
        original_len = len(courses)
        data["courses"] = [c for c in courses if c["id"] != course_id]

        if len(data["courses"]) < original_len:
            self._write_json("courses.json", data)
            return True
        return False

    def create_course_version(self, course_id: str, content: Dict, validation: Dict = None) -> str:
        """为课程创建新版本"""
        data = self._read_json("course_versions.json")

        if "versions" not in data:
            data["versions"] = []

        # 获取当前版本号
        course_versions = [v for v in data.get("versions", []) if v.get("course_id") == course_id]
        version_number = len(course_versions) + 1

        version = {
            "id": self._get_id("v"),
            "course_id": course_id,
            "version_number": version_number,
            "content": content,
            "validation": validation,
            "created_at": datetime.now().isoformat()
        }

        data["versions"].append(version)
        self._write_json("course_versions.json", data)

        return version["id"]

    def get_course_versions(self, course_id: str) -> List[Dict]:
        """获取课程的所有版本"""
        data = self._read_json("course_versions.json")
        versions = []

        for v in data.get("versions", []):
            if v.get("course_id") == course_id:
                versions.append(v)

        # 按版本号排序
        versions.sort(key=lambda x: x.get("version_number", 0))
        return versions

    def get_version_by_id(self, version_id: str) -> Optional[Dict]:
        """根据ID获取版本"""
        data = self._read_json("course_versions.json")
        for version in data.get("versions", []):
            if version["id"] == version_id:
                return version
        return None

    def compare_versions(self, version_id1: str, version_id2: str) -> Dict:
        """对比两个版本"""
        version1 = self.get_version_by_id(version_id1)
        version2 = self.get_version_by_id(version_id2)

        if not version1 or not version2:
            return {"error": "版本不存在"}

        # 简单对比：比较内容长度和标题
        content1 = version1.get("content", {})
        content2 = version2.get("content", {})

        return {
            "version1": {
                "id": version1["id"],
                "number": version1["version_number"],
                "title": content1.get("title", ""),
                "sections_count": len(content1.get("sections", {})),
                "created_at": version1["created_at"]
            },
            "version2": {
                "id": version2["id"],
                "number": version2["version_number"],
                "title": content2.get("title", ""),
                "sections_count": len(content2.get("sections", {})),
                "created_at": version2["created_at"]
            }
        }


class ShareDatabase(JSONDatabase):
    """分享记录数据库"""

    def __init__(self, data_dir: str = "./data"):
        super().__init__(data_dir)

    def share_course_to_class(self, teacher_id: str, course_id: str,
                             class_id: str) -> str:
        """分享课程到班级"""
        data = self._read_json("shares.json")

        if "shares" not in data:
            data["shares"] = []

        # 检查是否已分享到该班级
        for share in data.get("shares", []):
            if (share.get("course_id") == course_id and
                share.get("class_id") == class_id):
                return share["id"]  # 已存在，返回现有分享ID

        share = {
            "id": self._get_id("s"),
            "teacher_id": teacher_id,
            "course_id": course_id,
            "class_id": class_id,
            "shared_at": datetime.now().isoformat()
        }

        data["shares"].append(share)
        self._write_json("shares.json", data)

        return share["id"]

    def share_course(self, teacher_id: str, course_id: str,
                    student_ids: List[str]) -> str:
        """分享课程给学生（兼容旧方法）"""
        data = self._read_json("shares.json")

        if "shares" not in data:
            data["shares"] = []

        share = {
            "id": self._get_id("s"),
            "teacher_id": teacher_id,
            "course_id": course_id,
            "student_ids": student_ids,
            "shared_at": datetime.now().isoformat()
        }

        data["shares"].append(share)
        self._write_json("shares.json", data)

        return share["id"]

    def get_shared_courses_for_student(self, student_id: str, student_class_name: str = "") -> List[str]:
        """获取分享给学生的课程ID列表"""
        data = self._read_json("shares.json")
        course_ids = []

        # 获取学生所属的班级ID
        class_id = None
        if student_class_name:
            # 创建ClassDatabase实例来查询班级信息
            class_db_instance = ClassDatabase(self.data_dir)
            for cls in class_db_instance.get_all_classes():
                if cls.get("name") == student_class_name:
                    class_id = cls["id"]
                    break

        for share in data.get("shares", []):
            # 检查是否直接分享给学生
            if student_id in share.get("student_ids", []):
                course_ids.append(share["course_id"])
            # 检查是否分享到学生所在班级
            elif class_id and share.get("class_id") == class_id:
                if share["course_id"] not in course_ids:
                    course_ids.append(share["course_id"])

        return course_ids

    def get_course_shares(self, course_id: str) -> List[Dict]:
        """获取课程的所有分享记录"""
        data = self._read_json("shares.json")
        shares = []

        # 创建ClassDatabase实例来查询班级信息
        from .database import ClassDatabase
        class_db_instance = ClassDatabase(self.data_dir)

        for share in data.get("shares", []):
            if share["course_id"] == course_id:
                # 扩展分享信息，包含班级名称
                share_info = share.copy()
                if "class_id" in share:
                    cls = class_db_instance.get_class_by_id(share["class_id"])
                    if cls:
                        share_info["class_name"] = cls["name"]
                        share_info["student_count"] = len(cls.get("student_ids", []))
                shares.append(share_info)

        return shares

    def remove_share(self, share_id: str) -> bool:
        """取消分享"""
        data = self._read_json("shares.json")

        shares = data.get("shares", [])
        original_len = len(shares)
        data["shares"] = [s for s in shares if s["id"] != share_id]

        if len(data["shares"]) < original_len:
            self._write_json("shares.json", data)
            return True
        return False


class HistoryDatabase(JSONDatabase):
    """历史记录数据库"""

    def __init__(self, data_dir: str = "./data"):
        super().__init__(data_dir)

    def add_record(self, user_id: str, action: str,
                   course_id: Optional[str] = None, details: Optional[Dict] = None):
        """添加历史记录"""
        data = self._read_json("history.json")

        if "history" not in data:
            data["history"] = []

        record = {
            "id": self._get_id("h"),
            "user_id": user_id,
            "action": action,
            "course_id": course_id,
            "details": details or {},
            "timestamp": datetime.now().isoformat()
        }

        data["history"].append(record)
        self._write_json("history.json", data)

    def get_user_history(self, user_id: str, limit: int = 50) -> List[Dict]:
        """获取用户历史记录"""
        data = self._read_json("history.json")

        history = []
        for record in data.get("history", []):
            if record.get("user_id") == user_id:
                history.append(record)

        # 按时间倒序排列
        history.sort(key=lambda x: x.get("timestamp", ""), reverse=True)

        return history[:limit]

    def get_course_history(self, course_id: str) -> List[Dict]:
        """获取课程相关历史"""
        data = self._read_json("history.json")

        history = []
        for record in data.get("history", []):
            if record.get("course_id") == course_id:
                history.append(record)

        history.sort(key=lambda x: x.get("timestamp", ""), reverse=True)

        return history


class ClassDatabase(JSONDatabase):
    """班级管理数据库"""

    def __init__(self, data_dir: str = "./data"):
        super().__init__(data_dir)

    def create_class(self, teacher_id: str, name: str,
                     grade: str = "", description: str = "") -> str:
        """教师创建班级"""
        data = self._read_json("classes.json")

        if "classes" not in data:
            data["classes"] = []

        # 检查班级名是否已存在
        for cls in data.get("classes", []):
            if cls["name"] == name:
                return None

        class_obj = {
            "id": self._get_id("cls"),
            "teacher_id": teacher_id,
            "name": name,
            "grade": grade,
            "description": description,
            "student_ids": [],
            "created_at": datetime.now().isoformat()
        }

        data["classes"].append(class_obj)
        self._write_json("classes.json", data)

        return class_obj["id"]

    def get_class_by_id(self, class_id: str) -> Optional[Dict]:
        """根据ID获取班级"""
        data = self._read_json("classes.json")
        for cls in data.get("classes", []):
            if cls["id"] == class_id:
                return cls
        return None

    def get_classes_by_teacher(self, teacher_id: str) -> List[Dict]:
        """获取教师创建的所有班级"""
        data = self._read_json("classes.json")
        classes = []
        for cls in data.get("classes", []):
            if cls.get("teacher_id") == teacher_id:
                classes.append(cls)
        return classes

    def get_all_classes(self) -> List[Dict]:
        """获取所有班级（用于学生搜索）"""
        data = self._read_json("classes.json")
        return data.get("classes", [])

    def search_classes(self, keyword: str = "") -> List[Dict]:
        """搜索班级"""
        data = self._read_json("classes.json")
        classes = []

        for cls in data.get("classes", []):
            # 搜索班级名、年级、描述
            if (keyword in cls.get("name", "") or
                keyword in cls.get("grade", "") or
                keyword in cls.get("description", "")):
                classes.append(cls)

        return classes

    def join_class(self, class_id: str, student_id: str) -> bool:
        """学生加入班级"""
        data = self._read_json("classes.json")

        for i, cls in enumerate(data.get("classes", [])):
            if cls["id"] == class_id:
                # 确保 student_ids 字段存在
                if "student_ids" not in cls:
                    data["classes"][i]["student_ids"] = []

                # 检查是否已加入
                if student_id in data["classes"][i]["student_ids"]:
                    return False

                # 添加学生ID
                data["classes"][i]["student_ids"].append(student_id)
                self._write_json("classes.json", data)

                # 同时更新用户的班级信息
                class_obj = self.get_class_by_id(class_id)
                user_db.update_user(student_id, {"class": class_obj["name"]})
                return True

        return False

    def leave_class(self, class_id: str, student_id: str) -> bool:
        """学生退出班级"""
        data = self._read_json("classes.json")

        for i, cls in enumerate(data.get("classes", [])):
            if cls["id"] == class_id:
                if student_id in cls.get("student_ids", []):
                    data["classes"][i]["student_ids"].remove(student_id)
                    self._write_json("classes.json", data)
                    return True

        return False

    def get_class_students(self, class_id: str) -> List[Dict]:
        """获取班级学生列表"""
        cls = self.get_class_by_id(class_id)
        if not cls:
            return []

        students = []
        for student_id in cls.get("student_ids", []):
            user = user_db.get_user_by_id(student_id)
            if user:
                user_info = user.copy()
                if "password" in user_info:
                    del user_info["password"]
                students.append(user_info)

        return students

    def delete_class(self, class_id: str, teacher_id: str) -> bool:
        """删除班级"""
        data = self._read_json("classes.json")

        for i, cls in enumerate(data.get("classes", [])):
            if cls["id"] == class_id:
                # 检查是否是班级创建者
                if cls.get("teacher_id") != teacher_id:
                    return False

                data["classes"].pop(i)
                self._write_json("classes.json", data)
                return True

        return False


# 数据库实例
user_db = UserDatabase()
course_db = CourseDatabase()
share_db = ShareDatabase()
history_db = HistoryDatabase()
class_db = ClassDatabase()


def init_all_databases():
    """初始化所有数据库"""
    user_db.init_default_data()
