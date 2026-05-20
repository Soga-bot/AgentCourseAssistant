# API 模块化重构说明

本项目将 main.py (2838行) 中的代码拆分为独立的模块文件，以提高代码的可维护性和可读性。

## 模块结构

```
api/
├── __init__.py              # 模块初始化
├── routes.py                # 路由注册器
├── auth.py                  # 认证模块 (~150行)
├── ai_chat.py               # AI 聊天模块 (~100行)
├── teacher.py               # 教师端模块 (~350行)
├── student.py               # 学生端模块 (~120行)
├── class_management.py      # 班级管理模块 (~180行)
├── course_generation.py     # 课程生成模块 (~150行)
└── README.md                # 本文档
```

## 已完成的模块

### 1. api/auth.py - 认证模块
**路由:**
- `POST /api/auth/register` - 用户注册
- `POST /api/auth/login` - 用户登录
- `POST /api/auth/logout` - 用户登出
- `GET /api/auth/me` - 获取当前用户信息

### 2. api/ai_chat.py - AI 聊天模块
**路由:**
- `POST /api/ai/chat` - AI 学习助手聊天
- `GET /api/ai/status` - AI 服务状态查询

**特性:**
- 使用豆包2.0 Pro模型
- 支持多轮对话
- 支持课程内容上下文

### 3. api/teacher.py - 教师端模块
**路由:**
- `GET /api/teacher/courses` - 获取教师课程列表
- `GET /api/teacher/course/{course_id}` - 获取课程详情
- `DELETE /api/teacher/course/{course_id}` - 删除课程
- `POST /api/teacher/share` - 分享课程
- `GET /api/teacher/history` - 获取历史记录
- `GET /api/teacher/students` - 获取班级学生
- `POST /api/teacher/exercise` - 创建练习题
- `GET /api/teacher/exercises` - 获取练习题列表
- `GET /api/teacher/exercise/{exercise_id}/records` - 获取练习提交记录
- `POST /api/teacher/grade/{record_id}` - 批改解答题
- `GET /api/teacher/lesson-plans` - 获取教案列表
- `GET /api/teacher/lesson-plans/{plan_id}` - 获取教案详情
- `GET /api/teacher/lesson-plans/{plan_id}/download` - 下载教案
- `DELETE /api/teacher/lesson-plans/{plan_id}` - 删除教案

### 4. api/student.py - 学生端模块
**路由:**
- `GET /api/student/courses` - 获取可访问课程
- `GET /api/student/course/{course_id}` - 获取课程详情
- `GET /api/student/exercises/{course_id}` - 获取练习题
- `POST /api/student/submit` - 提交练习答案
- `GET /api/student/records` - 获取练习记录
- `GET /api/student/mistakes` - 获取错题本
- `DELETE /api/student/mistake/{mistake_id}` - 移除错题

### 5. api/class_management.py - 班级管理模块
**路由:**
- `POST /api/teacher/class` - 创建班级
- `GET /api/teacher/classes` - 获取教师班级列表
- `GET /api/class/{class_id}/students` - 获取班级学生
- `DELETE /api/teacher/class/{class_id}` - 删除班级
- `GET /api/classes` - 搜索班级
- `POST /api/student/class/join` - 加入班级
- `POST /api/student/class/leave` - 退出班级

### 6. api/course_generation.py - 课程生成模块
**路由:**
- `POST /generate/course` - 生成课程
- `GET /progress/{task_id}` - 获取生成进度
- `GET /course/{task_id}/preview` - 获取课程预览
- `POST /course/{task_id}/save` - 保存课程

**特性:**
- 支持教材章节模式
- 支持自定义内容模式
- 异步生成，支持进度查询

## 使用方式

在 main.py 中添加：

```python
from api.routes import register_all_routes

# 在创建 app 之后
app = FastAPI(...)

# 注册所有模块路由
register_all_routes(app)
```

## 模块化优势

1. **代码分离** - 每个功能独立文件，职责清晰
2. **易于维护** - 修改某个功能只需编辑对应模块
3. **团队协作** - 不同开发者可并行开发不同模块
4. **测试友好** - 每个模块可独立测试
5. **代码复用** - 模块可在其他项目中复用

## 模块依赖关系

```
┌─────────────────────────────────────────┐
│           main.py (FastAPI)              │
├─────────────────────────────────────────┤
│              api/routes.py               │
├─────────────────────────────────────────┤
│  auth  │ ai_chat │ teacher │ student    │
├─────────────────────────────────────────┤
│        class_management │ course_gen    │
├─────────────────────────────────────────┤
│     shared/database.py (数据层)          │
│     course_pipeline (业务逻辑)           │
│     video_pipeline (业务逻辑)            │
└─────────────────────────────────────────┘
```

## 重构进度

### 已完成 (~1050行)
- [x] 认证模块 (auth.py) - ~150行
- [x] AI 聊天模块 (ai_chat.py) - ~100行
- [x] 教师端模块 (teacher.py) - ~350行
- [x] 学生端模块 (student.py) - ~120行
- [x] 班级管理模块 (class_management.py) - ~180行
- [x] 课程生成模块 (course_generation.py) - ~150行

### 待拆分 (~1200行)
- [ ] 视频生成模块 - ~700行
- [ ] 知识库查询模块 - ~100行
- [ ] 系统管理模块 - ~150行
- [ ] 通用工具模块 - ~50行
- [ ] 进度管理模块 - ~100行
- [ ] 页面路由模块 - ~100行

## 统计数据

- **重构前**: main.py 2838 行
- **已拆分**: ~1050 行 (37%)
- **待拆分**: ~1200 行 (43%)
- **主文件保留**: ~600 行 (20%, FastAPI 配置、会话、工具函数)

## 注意事项

1. **循环依赖** - 各模块通过 `main.py` 导入共享函数（如 `get_session`），避免模块间直接依赖
2. **数据库连接** - 所有模块共享 `shared/database.py` 中的数据库实例
3. **业务逻辑** - 复杂业务逻辑保留在 `course_pipeline` 和 `video_pipeline` 中
4. **向后兼容** - 所有 API 路由路径保持不变，前端无需修改
