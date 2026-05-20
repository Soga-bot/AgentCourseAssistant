# 初中数学双模式生成系统

基于豆包2.0 Pro模型的初中数学内容生成系统，支持两种模式：
- **🎬 视频模式**：数学题讲解视频生成
- **📚 课程模式**：课程内容生成

## 功能特点

### 课程模式
- 支持4个主流教材版本（人教版、北师大版、苏科版、沪科版）
- 学情适配（基础薄弱、中等巩固、培优拓展）
- 多种用途（学生自学、教师教案、复习串讲、习题课）
- 可选输出模块（例题、习题、板书设计、授课逐字稿）
- 支持导出Word/PDF

## 快速开始

### 1. 安装依赖

```bash
cd teacher
pip install -r requirements.txt
```

### 2. 配置API密钥

编辑 `.env` 文件，将占位符替换为你的真实 API Key：

```
LLM_API_KEY=your_api_key_here
```

### 3. 启动服务

```bash
python main.py
```

服务启动后访问：http://localhost:8000/

## 目录结构

```
teacher/
├── main.py                    # 主程序入口
├── index.html                 # 前端界面
├── .env                       # 环境配置
├── requirements.txt            # 依赖列表
│
├── shared/                    # 共享模块
│   ├── llm_client.py          # LLM客户端
│   ├── prompt_builder.py      # 提示词构建器
│   ├── validators.py          # 内容校验器
│   └── utils.py               # 公共工具
│
├── course_pipeline/           # 课程流水线
│   ├── course_generator.py    # 课程生成器
│   ├── knowledge_base.py      # 知识库管理
│   ├── templates.py           # 提示词模板
│   └── exporters.py           # 文档导出
│
└── knowledge/                 # 知识库数据
    ├── textbooks/             # 教材目录
    │   ├── renjiao_v1.json   # 人教版
    │   ├── beishi_v1.json    # 北师大版
    │   ├── suke_v1.json      # 苏科版
    │   └── huke_v1.json      # 沪科版
    ├── formulas.json          # 公式库
    ├── terms.json             # 术语库
    ├── forbidden_keywords.json # 超纲关键词
    └── curriculum_standard.json # 课标库
```

## API接口

### 知识库查询
- `GET /textbooks/versions` - 获取教材版本列表
- `GET /textbooks/{version}/grades` - 获取年级列表
- `GET /textbooks/{version}/{grade}/chapters` - 获取章节列表

### 课程生成
- `POST /generate/course` - 生成课程内容
- `GET /course/{task_id}` - 获取课程内容
- `GET /export/word/{task_id}` - 导出Word
- `GET /export/pdf/{task_id}` - 导出PDF

### 进度查询
- `GET /progress/{task_id}` - 查询任务进度

### 系统状态
- `GET /health` - 健康检查
- `GET /docs` - API文档

## 配置说明

### 环境变量

| 变量名 | 说明 | 默认值 |
|--------|------|--------|
| `LLM_API_KEY` | 豆包API密钥 | - |
| `LLM_MODEL` | 模型名称 | doubao-seed-2-0-pro-260215 |
| `LLM_BASE_URL` | API地址 | https://ark.cn-beijing.volces.com/api/v3 |
| `LLM_TEMPERATURE` | 温度参数 | 0.1 |
| `LLM_MAX_TOKENS` | 最大Token数 | 12000 |
| `KNOWLEDGE_DIR` | 知识库目录 | ./knowledge |

## 知识库结构

### 教材章节 (textbooks/*.json)
```json
{
  "version": "renjiao_v1",
  "version_name": "人教版",
  "grades": {
    "七年级上册": {
      "chapters": [
        {
          "id": "c1_youshu",
          "name": "第一章 有理数",
          "order": 1,
          "knowledge_points": [...],
          "key_difficulties": [...],
          "common_mistakes": [...],
          "common_question_types": [...],
          "curriculum_requirement": "掌握"
        }
      ]
    }
  }
}
```

## 开发说明

### 添加新教材版本
1. 在 `knowledge/textbooks/` 创建新文件
2. 按照JSON格式添加章节数据
3. 重启服务

### 自定义提示词模板
编辑 `course_pipeline/templates.py` 中的模板定义

### 添加新的导出格式
在 `course_pipeline/exporters.py` 中添加新的Exporter类

## 常见问题

### Q: 如何获取豆包API密钥？
A: 访问 https://console.volcengine.com/ark 创建应用并获取API密钥

### Q: PDF导出失败怎么办？
A: 需要先安装 pandoc：https://pandoc.org/installing.html

### Q: 如何修改模型参数？
A: 编辑 `.env` 文件中的 `LLM_TEMPERATURE` 等参数

## 版本历史
- v2.0.0 - 初始版本，支持课程内容生成

## 许可证
MIT License
