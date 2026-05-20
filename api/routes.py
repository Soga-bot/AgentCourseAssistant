"""
API 路由注册模块

集中管理所有 API 路由的注册
"""


def register_all_routes(app, progress_manager, output_dir, temp_dir, static_dir, base_dir):
    """
    注册所有 API 路由

    Args:
        app: FastAPI 应用实例
        progress_manager: 进度管理器实例
        output_dir: 输出目录
        temp_dir: 临时目录
        static_dir: 静态文件目录
        base_dir: 项目根目录
    """
    from api.auth import register_auth_routes
    from api.teacher import register_teacher_routes
    from api.student import register_student_routes
    from api.class_management import register_class_routes
    from api.course_generation import register_course_generation_routes
    from api.textbook import register_textbook_routes
    from api.video_generation import register_video_routes
    from api.task_management import register_task_routes
    from api.admin import register_admin_routes
    from api.agent import register_agent_routes

    # 初始化需要依赖的模块
    import api.video_generation as video_gen
    import api.task_management as task_mgmt
    import api.admin as admin_mod
    import api.course_generation as course_gen

    video_gen.init_video_generation(progress_manager, output_dir, base_dir)
    task_mgmt.init_task_management(progress_manager)
    admin_mod.init_admin(progress_manager, output_dir, temp_dir, static_dir, base_dir)
    course_gen.init_course_generation(progress_manager, output_dir)

    # 注册认证路由
    register_auth_routes(app)
    print("[API] [OK] 认证路由已注册")

    # 注册教师端路由
    register_teacher_routes(app)
    print("[API] [OK] 教师端路由已注册")

    # 注册学生端路由
    register_student_routes(app)
    print("[API] [OK] 学生端路由已注册")

    # 注册班级管理路由
    register_class_routes(app)
    print("[API] [OK] 班级管理路由已注册")

    # 注册课程生成路由
    register_course_generation_routes(app)
    print("[API] [OK] 课程生成路由已注册")

    # 注册教材知识库路由
    register_textbook_routes(app)
    print("[API] [OK] 教材知识库路由已注册")

    # 注册视频生成路由
    register_video_routes(app)
    print("[API] [OK] 视频生成路由已注册")

    # 注册任务管理路由
    register_task_routes(app)
    print("[API] [OK] 任务管理路由已注册")

    # 注册系统管理路由
    register_admin_routes(app)
    print("[API] [OK] 系统管理路由已注册")

    # 注册Agent路由
    register_agent_routes(app)
    print("[API] [OK] Agent路由已注册")

    print("[API] 所有路由模块已注册完成")
