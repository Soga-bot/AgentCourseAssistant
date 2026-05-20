"""
课程生成流水线

提供课程内容生成的核心功能
"""

from .course_generator import CourseGenerator
from .models import CourseGenerateRequest, CourseContent, CourseGeneratorConfig
from .knowledge_base import KnowledgeBase, ChapterInfo
from .templates import PromptTemplates
from .exporters import WordExporter, PDFExporter, MarkdownExporter, HTMLExporter, LaTeXExporter, export_to_latex
from .generators import BaseGenerator, TextbookGenerator, CustomGenerator

__all__ = [
    "CourseGenerator",
    "CourseGeneratorConfig",
    "CourseGenerateRequest",
    "CourseContent",
    "KnowledgeBase",
    "ChapterInfo",
    "PromptTemplates",
    "WordExporter",
    "PDFExporter",
    "MarkdownExporter",
    "HTMLExporter",
    "LaTeXExporter",
    "export_to_latex",
    "BaseGenerator",
    "TextbookGenerator",
    "CustomGenerator",
]
