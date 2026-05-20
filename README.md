# AgentCourseAssistant - 初中数学智能课程生成系统

基于大语言模型的初中数学课程内容自动生成系统，支持课程生成与讲解视频制作双模式，覆盖人教版、北师大版、苏科版、沪科版四大主流教材。

## 功能概览

### 课程生成模式
- **多教材适配** — 支持人教版、北师大版、苏科版、沪科版四大版本
- **学情分层** — 基础薄弱 / 中等巩固 / 培优拓展，按学生水平动态调整内容深度
- **多用途输出** — 学生自学、教师教案、复习串讲、习题课
- **完整课程结构** — 自动生成导入、学习目标、知识点详解、典例精讲、易错点、随堂小测、知识框架、课后拓展八大板块
- **内容校验** — 自动检测超纲内容、占位符、LaTeX 语法错误

### 视频生成模式
- **数学讲解视频** — 将课程内容转化为带旁白的视频讲解
- **LaTeX 公式渲染** — 数学公式自动排版为高质量幻灯片帧
- **TTS 语音合成** — 阿里云 NLS 语音合成，生成讲解音频
- **视频合成** — FFmpeg 自动合成幻灯片 + 语音为 MP4 视频

### 平台功能
- **教师端** — 课程生成、视频制作、班级管理、课程分享、练习题管理
- **学生端** — 课程学习、AI 辅导、练习作答、错题本
- **用户系统** — 注册登录、角色权限（教师/学生/管理员）
- **AI 学习助手** — 基于课程内容的多轮对话辅导

## 系统架构

```
┌─────────────────────────────────────────────────┐
│              用户层 (Frontend)                    │
│   教师端 Web UI  │  学生端 Web UI  │  登录页      │
└────────┬────────────────┬───────────────┬────────┘
         │                │               │
┌────────▼────────────────▼───────────────▼────────┐
│              API 层 (FastAPI)                      │
│  课程生成 │ 视频生成 │ 用户认证 │ 班级管理 │ AI 聊天  │
└───┬────────────┬──────────────┬──────────────┬────┘
    │            │              │              │
┌───▼────┐ ┌────▼─────┐ ┌─────▼─────┐ ┌─────▼─────┐
│ Agent  │ │ Course   │ │  Video    │ │  Shared   │
│ 智能体 │ │ Pipeline │ │  Pipeline │ │  Modules  │
│        │ │ 课程生成  │ │  视频生成  │ │  公共模块  │
└───┬────┘ └────┬─────┘ └─────┬─────┘ └─────┬─────┘
    │            │              │              │
    ▼            ▼              ▼              ▼
┌─────────────────────────────────────────────────┐
│              外部服务                              │
│  豆包 / DeepSeek LLM  │  阿里云 TTS  │  FFmpeg   │
└─────────────────────────────────────────────────┘
```

## 目录结构

```
AgentCourseAssistant/
├── main.py                          # FastAPI 主程序入口
├── .gitignore                       # Git 忽略规则
│
├── api/                             # API 路由模块
│   ├── routes.py                    # 路由注册器
│   ├── auth.py                      # 用户认证
│   ├── agent.py                     # Agent 接口
│   ├── teacher.py                   # 教师端 API
│   ├── student.py                   # 学生端 API
│   ├── admin.py                     # 管理后台 API
│   ├── class_management.py          # 班级管理
│   ├── course_generation.py         # 课程生成
│   ├── video_generation.py          # 视频生成
│   ├── task_management.py           # 任务管理
│   └── textbook.py                  # 知识库查询
│
├── agents/                          # Agent 智能体
│   ├── course_generation.py         # 课程生成 Agent
│   ├── learning_tutor.py            # 学习辅导 Agent
│   └── video_generation.py          # 视频生成 Agent
│
├── shared/                          # 共享模块
│   ├── agent/                       # Agent 基础框架
│   │   ├── base.py                  # Agent 基类
│   │   ├── react.py                 # ReAct 推理循环
│   │   ├── memory.py                # Agent 记忆
│   │   ├── tools.py                 # 工具定义
│   │   └── tool_registry.py         # 工具注册器
│   ├── llm_client.py                # 统一 LLM 客户端
│   ├── database.py                  # JSON 数据库
│   ├── knowledge_base.py            # 知识库管理
│   ├── prompt_builder.py            # 提示词构建器
│   ├── validators.py                # 内容校验器
│   ├── session.py                   # 会话管理
│   ├── utils.py                     # 工具函数
│   └── pages/login.html             # 共享登录页
│
├── teacher/                         # 教师端
│   ├── .env                          # 环境配置（占位符，需填入真实密钥）
│   ├── requirements.txt             # Python 依赖
│   ├── course_pipeline/             # 课程生成流水线
│   │   ├── course_generator.py      # 课程生成器
│   │   ├── knowledge_base.py        # 知识库
│   │   ├── templates.py             # 提示词模板
│   │   ├── exporters.py             # 文档导出 (Word/PDF/LaTeX)
│   │   ├── generators/              # 多种生成策略
│   │   ├── models/                  # 数据模型
│   │   └── validators/              # 内容校验
│   ├── video_pipeline/              # 视频生成流水线
│   │   ├── pipeline.py              # 完整视频流水线
│   │   ├── simple_pipeline.py       # 简化视频流水线
│   │   ├── config.py                # 视频生成配置
│   │   ├── audio_utils.py           # 音频处理
│   │   └── modules/                 # 视频处理模块
│   │       ├── content_generator.py
│   │       ├── content_converter.py
│   │       ├── latex_generator.py
│   │       ├── pdf_compiler.py
│   │       ├── speech_generator.py
│   │       ├── tts_video_synthesizer.py
│   │       └── ...                  # 其他处理模块
│   ├── knowledge/                   # 教材知识库
│   │   ├── textbooks/               # 教材数据
│   │   │   ├── renjiao_v1.json      # 人教版
│   │   │   ├── beishi_v1.json       # 北师大版
│   │   │   ├── suke_v1.json         # 苏科版
│   │   │   └── huke_v1.json         # 沪科版
│   │   ├── formulas.json            # 公式库
│   │   ├── terms.json               # 术语库
│   │   ├── forbidden_keywords.json  # 超纲关键词
│   │   └── curriculum_standard.json # 课标数据
│   ├── frontend/                    # 教师端前端
│   └── shared/math_symbol_reader.py # 数学符号读取
│
├── student/                         # 学生端
│   └── frontend/                    # 学生端前端
│
├── data/                            # 运行时数据（Git 忽略）
├── output/                          # 生成输出（Git 忽略）
├── temp/                            # 临时文件（Git 忽略）
└── docs/                            # 文档
    ├── architecture_diagram.mmd     # 架构图 (Mermaid)
    └── architecture_diagram.puml    # 架构图 (PlantUML)
```

## 快速开始

### 环境要求

- Python 3.10+
- [FFmpeg](https://ffmpeg.org/)（视频生成功能需要）
- [Tectonic](https://tectonic-typesetting.github.io/) 或 TeX Live（LaTeX 编译需要）
- [Pandoc](https://pandoc.org/)（PDF 导出需要，可选）

### 1. 克隆项目

```bash
git clone https://github.com/your-username/AgentCourseAssistant.git
cd AgentCourseAssistant
```

### 2. 安装依赖

```bash
pip install -r teacher/requirements.txt
```

### 3. 配置环境变量

编辑 `teacher/.env` 文件，将占位符替换为你的真实 API 密钥：

```ini
# 豆包 API（主推）— 获取地址：https://console.volcengine.com/ark
LLM_API_KEY=your_doubao_api_key_here

# DeepSeek API（备用）— 获取地址：https://platform.deepseek.com
# LLM_API_KEY=your_deepseek_api_key_here
# LLM_MODEL=deepseek-chat
# LLM_BASE_URL=https://api.deepseek.com

# 阿里云 TTS（视频生成需要）— 获取地址：https://nls-portal.console.aliyun.com/
TTS_APPKEY=your_tts_appkey_here
TTS_TOKEN=your_tts_access_token_here
```

### 4. 启动服务

```bash
python main.py
```

服务启动后访问：
- 首页：http://localhost:8000/
- API 文档：http://localhost:8000/docs
- 健康检查：http://localhost:8000/health

### 5. 测试账号

首次启动会自动创建测试账号（可在 `shared/database.py` 中修改）：

| 角色   | 用户名   | 密码         |
|--------|----------|--------------|
| 管理员 | admin    | admin123     |
| 教师   | 张老师   | teacher123   |
| 学生   | 李同学   | student123   |

## 核心模块说明

### Agent 智能体框架 (`shared/agent/`)

系统基于 ReAct（Reasoning + Acting）范式构建了 Agent 框架：

- **BaseAgent** — 智能体基类，定义推理-行动循环
- **ReActLoop** — 实现 Thought → Action → Observation 推理循环
- **ToolRegistry** — 工具注册与调度管理
- **Memory** — Agent 上下文记忆管理

### LLM 客户端 (`shared/llm_client.py`)

统一的 LLM 调用客户端，支持：
- 豆包 2.0 Pro（主推）/ DeepSeek-V3（备用）
- 自动重试 + 指数退避
- 请求限流 + 并发控制
- 可选响应缓存

### 课程生成流水线 (`teacher/course_pipeline/`)

1. **知识库查询** — 根据教材版本、年级、章节检索知识要点
2. **提示词构建** — 组装系统提示 + 教材上下文 + 学情参数
3. **LLM 生成** — 调用大模型生成八大板块内容
4. **内容校验** — 检测超纲、占位符、LaTeX 错误
5. **文档导出** — 支持导出 Word / Markdown / LaTeX

### 视频生成流水线 (`teacher/video_pipeline/`)

1. **内容解析** — 将课程内容拆解为独立知识点帧
2. **LaTeX 生成** — 数学公式自动生成 LaTeX Beamer 代码
3. **PDF 编译** — Tectonic/XeLaTeX 编译为 PDF
4. **帧提取** — PDF 转为高质量 PNG 图片
5. **语音脚本** — 生成与帧同步的讲解文本
6. **TTS 合成** — 阿里云语音合成生成 MP3 音频
7. **视频合成** — FFmpeg 合成图片 + 音频为 MP4

## API 接口概览

### 认证
| 方法   | 路径                    | 说明     |
|--------|------------------------|----------|
| POST   | `/api/auth/register`   | 用户注册 |
| POST   | `/api/auth/login`      | 用户登录 |
| POST   | `/api/auth/logout`     | 用户登出 |
| GET    | `/api/auth/me`         | 当前用户 |

### 课程生成
| 方法   | 路径                        | 说明           |
|--------|----------------------------|----------------|
| POST   | `/generate/course`          | 生成课程       |
| POST   | `/generate/course/outline`  | 生成大纲       |
| GET    | `/progress/{task_id}`       | 查询生成进度   |
| GET    | `/course/{task_id}/preview` | 课程预览       |
| POST   | `/course/{task_id}/save`    | 保存课程       |

### 文档导出
| 方法 | 路径                        | 说明       |
|------|----------------------------|------------|
| GET  | `/export/word/{task_id}`    | 导出 Word  |
| GET  | `/export/pdf/{task_id}`     | 导出 PDF   |
| GET  | `/export/latex/{task_id}`   | 导出 LaTeX |

### 教师端
| 方法   | 路径                               | 说明         |
|--------|-----------------------------------|--------------|
| GET    | `/api/teacher/courses`             | 课程列表     |
| DELETE | `/api/teacher/course/{course_id}`  | 删除课程     |
| POST   | `/api/teacher/share`               | 分享课程     |
| GET    | `/api/teacher/history`             | 历史记录     |

### 学生端
| 方法   | 路径                               | 说明         |
|--------|-----------------------------------|--------------|
| GET    | `/api/student/courses`             | 可访问课程   |
| POST   | `/api/student/submit`              | 提交练习     |
| GET    | `/api/student/mistakes`            | 错题本       |

### 班级管理
| 方法   | 路径                               | 说明         |
|--------|-----------------------------------|--------------|
| POST   | `/api/teacher/class`               | 创建班级     |
| GET    | `/api/teacher/classes`             | 班级列表     |
| POST   | `/api/student/class/join`          | 加入班级     |

### AI 辅导
| 方法 | 路径                | 说明             |
|------|--------------------|------------------|
| POST | `/api/ai/chat`     | AI 学习助手对话  |
| GET  | `/api/ai/status`   | AI 服务状态      |

## 环境变量说明

| 变量名                   | 说明                | 默认值                                              |
|-------------------------|---------------------|-----------------------------------------------------|
| `LLM_API_KEY`           | LLM API 密钥        | （必填）                                            |
| `LLM_MODEL`             | 模型名称            | `doubao-seed-2-0-pro-260215`                        |
| `LLM_BASE_URL`          | API 地址            | `https://ark.cn-beijing.volces.com/api/v3`          |
| `LLM_TEMPERATURE`       | 温度参数            | `0.1`                                               |
| `LLM_MAX_TOKENS`        | 最大 Token 数       | `16384`                                             |
| `LLM_MAX_RETRIES`       | 最大重试次数        | `5`                                                 |
| `LLM_REQUEST_INTERVAL`  | 请求间隔（秒）      | `2.0`                                               |
| `COURSE_API_KEY`        | 课程生成 API 密钥   | 默认同 `LLM_API_KEY`                                |
| `TTS_APPKEY`            | 阿里云 TTS AppKey   | （视频生成需要）                                    |
| `TTS_TOKEN`             | 阿里云 TTS Token    | （视频生成需要）                                    |
| `TTS_VOICE`             | 语音发音人          | `zhida`                                             |
| `API_HOST`              | 服务监听地址        | `0.0.0.0`                                           |
| `API_PORT`              | 服务端口            | `8000`                                              |
| `TASK_RETENTION_HOURS`  | 任务保留时间        | `24`                                                |

## 技术栈

| 层级       | 技术                                          |
|------------|-----------------------------------------------|
| 后端框架   | FastAPI + Uvicorn                             |
| 前端       | 原生 HTML/CSS/JS + MathJax                    |
| LLM        | 豆包 2.0 Pro / DeepSeek-V3                    |
| TTS        | 阿里云 NLS 语音合成                            |
| LaTeX      | Tectonic / XeLaTeX + Beamer                   |
| 视频合成   | FFmpeg                                        |
| 数据存储   | JSON 文件（轻量级，无需数据库）                |
| 公式渲染   | MathJax (前端) + LaTeX (视频)                  |

## 扩展指南

### 添加新教材版本

1. 在 `teacher/knowledge/textbooks/` 下创建 JSON 文件（如 `xinban_v1.json`）
2. 按照现有格式填入年级、章节、知识点数据
3. 重启服务即可生效

### 切换 LLM 提供商

编辑 `.env` 文件，修改以下配置即可切换：

```ini
# 切换到 DeepSeek
LLM_API_KEY=your_deepseek_key
LLM_MODEL=deepseek-chat
LLM_BASE_URL=https://api.deepseek.com
```

### 自定义提示词模板

编辑 `teacher/course_pipeline/templates.py` 中的模板定义，调整课程生成的风格和结构。

## 许可证

MIT License
