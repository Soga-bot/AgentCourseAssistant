"""
教材知识库查询模块

提供教材版本、年级、章节信息的查询接口
"""

from fastapi import HTTPException
from shared.knowledge_base import knowledge_base


async def get_textbook_versions():
    """获取所有教材版本"""
    versions = knowledge_base.get_versions()
    return {
        "versions": [
            {"id": v.version_id, "name": v.version_name}
            for v in versions
        ]
    }


async def get_grades(version: str):
    """获取指定版本的年级列表"""
    grades = knowledge_base.get_grades(version)
    version_name = knowledge_base.get_version_names().get(version, version)
    return {
        "version": version_name,
        "grades": grades
    }


async def get_chapters(version: str, grade: str):
    """获取指定版本的章节列表"""
    chapters = knowledge_base.get_chapters(version, grade)
    return {
        "version": version,
        "grade": grade,
        "chapters": [
            {
                "id": ch.get("id"),
                "name": ch.get("name"),
                "order": ch.get("order", 0)
            }
            for ch in chapters
        ]
    }


async def get_chapter_detail(version: str, grade: str, chapter_id: str):
    """获取章节详细信息"""
    info = knowledge_base.get_chapter_info(version, grade, chapter_id)
    if not info:
        raise HTTPException(status_code=404, detail="章节不存在")

    return {
        "id": info.chapter_id,
        "name": info.chapter_name,
        "order": info.order,
        "knowledge_points": info.knowledge_points,
        "key_difficulties": info.key_difficulties,
        "common_mistakes": info.common_mistakes,
        "common_question_types": info.common_question_types,
        "curriculum_requirement": info.curriculum_requirement
    }


def register_textbook_routes(app):
    """注册教材知识库查询路由"""

    @app.get("/textbooks/versions")
    async def api_get_textbook_versions():
        """获取所有教材版本"""
        return await get_textbook_versions()

    @app.get("/textbooks/{version}/grades")
    async def api_get_grades(version: str):
        """获取指定版本的年级列表"""
        return await get_grades(version)

    @app.get("/textbooks/{version}/{grade}/chapters")
    async def api_get_chapters(version: str, grade: str):
        """获取指定版本的章节列表"""
        return await get_chapters(version, grade)

    @app.get("/textbooks/{version}/{grade}/chapters/{chapter_id}")
    async def api_get_chapter_detail(version: str, grade: str, chapter_id: str):
        """获取章节详细信息"""
        return await get_chapter_detail(version, grade, chapter_id)
