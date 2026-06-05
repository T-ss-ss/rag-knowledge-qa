<p align="center">
  <h1 align="center">📚 RAGent</h1>
  <p align="center">
    <strong>RAG + Agent 双模式知识库问答系统</strong>
    <br />
    上传 PDF / Word → 智能检索 → AI 回答 · 支持多知识库 · 联网搜索 · 流式输出
  </p>
</p>

<p align="center">
  <img src="https://img.shields.io/badge/python-3.10+-blue.svg" alt="Python">
  <img src="https://img.shields.io/badge/fastapi-0.115+-green.svg" alt="FastAPI">
  <img src="https://img.shields.io/badge/license-MIT-lightgrey.svg" alt="License">
  <img src="https://img.shields.io/badge/version-0.4.0-brightgreen.svg" alt="Version">
</p>

---

## 项目简介

RAGent 是一个基于 **RAG (Retrieval-Augmented Generation)** 的智能知识库问答系统。用户上传 PDF / Word 文档后，系统自动完成文本提取、向量化存储和语义索引，支持两种问答模式：

- **RAG 模式** — 直接从知识库检索相关片段，结合 LLM 生成带来源引用的精确回答
- **Agent 模式** — 基于 ReAct 范式的自主推理，可编排知识库检索 + Tavily 联网搜索两个工具，通过 SSE 实时流式输出

所有回答均附带 **Sources 引用**（文件名、页码、相关度分数），支持**多知识库隔离**（独立 Collection + 独立会话），具备**多轮对话记忆**能力。

---

## 功能特性

### 核心能力

| 功能 | 说明 |
|------|------|
| 📄 文档上传 | PDF / DOCX，PyMuPDF + python-docx 解析，自动文本提取、分块、向量化 |
| 🔍 语义检索 | ChromaDB HNSW 索引 + Cosine 相似度，毫秒级检索 |
| 🎯 Rerank 精排 | BGE-Reranker v2-m3 对粗筛结果重排序，提升 Top-K 精度 |
| 💬 RAG 问答 | 检索增强生成，严格依据文档上下文作答 |
| 🤖 Agent 模式 | ReAct + OpenAI Function Calling，自主决策工具调用 |
| 🌐 联网搜索 | Tavily Search API，Agent 可检索互联网最新信息 |
| 📡 SSE 流式输出 | Agent 模式下 token 逐字推送，工具调用/返回实时可见 |
| 📁 多知识库 | 独立 Collection 隔离，支持 CRUD，默认知识库不可删除 |
| 🧠 会话记忆 | 多轮对话上下文注入，Agent 模式自动过滤工具消息 |
| 📎 Sources 引用 | 每个回答标注来源文件名、页码、相关度分数 |

### 附加特性

- **双模式前端**：`/chat` 聊天界面支持 RAG / Agent 一键切换
- **Swagger 文档**：`/docs` 自动生成完整 API 文档
- **健康检查**：`/health` 实时监控 Chat API / Embedding API / 向量库状态
- **错误码体系**：12 类自定义异常 + 统一 JSON 错误响应
- **Schema 自动迁移**：检测旧版数据库约束并安全升级，不丢数据

---

## 技术栈

| 层级 | 技术 | 用途 |
|------|------|------|
| **Web 框架** | FastAPI 0.115+ | REST API + SSE Streaming |
| **LLM** | DeepSeek Chat (`deepseek-chat`) | 文本生成 / Function Calling |
| **Embedding** | Qwen `text-embedding-v3` (阿里云) | 文本向量化（1024 维） |
| **向量数据库** | ChromaDB (PersistentClient) | HNSW 索引 + Cosine 相似度 |
| **关系数据库** | SQLite (WAL 模式) | 知识库/文档/会话/消息持久化 |
| **PDF 解析** | PyMuPDF (fitz) | 逐页文本提取 |
| **Word 解析** | python-docx | 段落文本提取 |
| **文本分块** | LangChain TextSplitter | RecursiveCharacter 分块 |
| **Reranker** | BGE-Reranker v2-m3 (FlagEmbedding) | Cross-encoder 精排 |
| **联网搜索** | Tavily Search API | Agent 联网工具 |
| **配置管理** | Pydantic Settings | `.env` + 类型校验 |
| **数据校验** | Pydantic v2 | 14 个请求/响应模型 |
| **前端** | 原生 HTML/CSS/JS | `ReadableStream` SSE 消费 |

---

## 系统架构

```
┌──────────────────────────────────────────────────────────────┐
│                     Browser  (chat.html)                      │
│              SSE ReadableStream   /   REST JSON               │
└──────────────────────────┬───────────────────────────────────┘
                           │
┌──────────────────────────▼───────────────────────────────────┐
│                    FastAPI  (main.py)                          │
│  ┌──────────┐  ┌──────────────┐  ┌─────────────────────┐    │
│  │   CORS   │  │ StaticFiles  │  │ Exception Handlers  │    │
│  └──────────┘  └──────────────┘  └─────────────────────┘    │
│                                                               │
│  Routers:  /api/upload  /api/qa  /api/documents              │
│            /api/knowledge-bases  /api/conversations           │
└──────────────────────────────────────────────────────────────┘
                           │
        ┌──────────────────┼──────────────────┐
        ▼                  ▼                  ▼
┌───────────────┐  ┌──────────────┐  ┌──────────────────┐
│  Service Layer│  │  Pydantic    │  │  Repository      │
│               │  │  Models      │  │  Layer            │
│  rag_pipeline │  └──────────────┘  │  kb / doc         │
│  rag_service  │                    │  conv / msg       │
│  chat_service │                    └────────┬─────────┘
│  agent_service│                             │
│  pdf_service  │                    ┌────────▼─────────┐
│  word_service │                             │
│  chunking     │                    │  SQLite (WAL)    │
│  embedding    │                    └──────────────────┘
│  reranker     │
│  kb_tool      │
│  web_search   │
└───────┬───────┘
        │
┌───────▼──────────────────────────────────────────────────────┐
│                     External APIs                              │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────────┐   │
│  │  DeepSeek    │  │  Qwen        │  │  Tavily          │   │
│  │  (Chat LLM)  │  │  (Embedding) │  │  (Web Search)    │   │
│  └──────────────┘  └──────────────┘  └──────────────────┘   │
└──────────────────────────────────────────────────────────────┘

┌──────────────────────┐
│  ChromaDB (本地持久化) │
│  Collection per KB   │
│  HNSW + Cosine       │
└──────────────────────┘
```

---

## RAG 流程

```
用户问题
    │
    ▼
┌──────────────────────────────────────────────┐
│  1. Embedding                                │
│     Qwen text-embedding-v3 → 1024 维向量     │
└──────────────────┬───────────────────────────┘
                   ▼
┌──────────────────────────────────────────────┐
│  2. 粗筛 (Vector Search)                      │
│     ChromaDB HNSW + Cosine → top_k × 3       │
└──────────────────┬───────────────────────────┘
                   ▼
              rerank_enabled?
              ┌────┴────┐
              ▼         ▼
┌─────────────────────┐  ┌────────────┐
│ 3. 精排 (BGE-Rerank)│  │  跳过       │
│    Cross-encoder    │  │            │
│    重打分 → top_k   │  │            │
└─────────┬───────────┘  └─────┬──────┘
          └────────┬────────────┘
                   ▼
┌──────────────────────────────────────────────┐
│  4. 格式化 Context                            │
│     [Source N: filename, Page P]             │
│     content...                                │
└──────────────────┬───────────────────────────┘
                   ▼
┌──────────────────────────────────────────────┐
│  5. LLM 生成                                  │
│     DeepSeek Chat + System Prompt            │
│     → 带来源引用的精确回答                     │
└──────────────────────────────────────────────┘
```

### RAG 多轮对话

多轮对话模式下，额外注入**最近 20 条历史消息**到 LLM 上下文，使 AI 能理解指代和上下文延续。同时过滤 Agent 模式下产生的 `tool`/`system` 角色消息以及工具调用占位文本，避免 OpenAI API 协议冲突。

---

## Agent 流程

Agent 基于 **ReAct (Reasoning + Acting)** 范式，通过 OpenAI Function Calling 协议实现自主工具编排。

### 工具清单

| 工具 | 函数名 | 能力 |
|------|--------|------|
| 📚 知识库检索 | `search_knowledge_base` | 在已上传文档中语义搜索 |
| 🌐 联网搜索 | `search_web` | 通过 Tavily API 搜索互联网最新信息 |

### ReAct 循环

```
用户问题
    │
    ▼
┌────────────────────────────────────────┐
│  构建上下文                             │
│  System Prompt + History (40条)        │
│  + Tools 定义 + User Question          │
└──────────────────┬─────────────────────┘
                   │
        ┌──────────▼──────────┐
        │   LLM 推理           │
        │   (DeepSeek + Tools) │◄──────────────┐
        └──────────┬──────────┘                │
                   │                           │
            finish_reason?                     │
           ┌───────┴───────┐                   │
           ▼               ▼                   │
      tool_calls        content                │
           │               │                   │
           ▼               ▼                   │
┌──────────────────┐  ┌────────────┐          │
│  执行工具         │  │ 流式输出    │          │
│  KB Search 或    │  │ SSE token   │          │
│  Web Search      │  │ 逐字推送    │          │
└────────┬─────────┘  └────────────┘          │
         │                                     │
         ▼                                     │
┌──────────────────┐                           │
│  追加工具结果      │                          │
│  到消息上下文      │──────────────────────────┘
└──────────────────┘    (继续循环，最多 5 轮)
```

### SSE 事件流

```
event: tool_call
data: {"step":1,"tool":"search_knowledge_base","args":"..."}

event: tool_result
data: {"step":1,"tool":"search_knowledge_base","found":4}

event: token
data: {"token":"根据"}

event: token
data: {"token":"文档"}

event: token
data: {"token":"内容"}

...

event: sources
data: {"sources":[{...}]}

event: done
data: {"conversation_id":"...","message_id":123}
```

### Agent 决策规则

1. **纯问候/闲聊** → 直接回复，不调用工具
2. **事实/知识类问题** → 优先 `search_knowledge_base`
3. **知识库无结果** → 自动 fallback `search_web`
4. **实时信息**（天气、新闻、股价）→ 直接 `search_web`
5. **两个工具都无结果** → 诚实告知，允许从自身知识回答

---

## 快速启动

### 前置条件

- Python 3.10+
- DeepSeek API Key（[申请](https://platform.deepseek.com)）
- 阿里云 DashScope API Key（[申请](https://dashscope.console.aliyun.com)）
- Tavily API Key（可选，仅联网搜索需要，[申请](https://tavily.com)）

### 1. 克隆项目

```bash
git clone <repo-url>
cd RAGtest1
```

### 2. 配置环境变量

```bash
cp .env.example .env
# 编辑 .env，填入你的 API Key
```

`.env` 内容：

```env
DEEPSEEK_API_KEY=sk-xxx
DEEPSEEK_BASE_URL=https://api.deepseek.com
CHAT_MODEL=deepseek-chat

EMBEDDING_API_KEY=sk-xxx
EMBEDDING_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
EMBEDDING_MODEL=text-embedding-v3

TAVILY_API_KEY=tvly-xxx   # 可选
```

### 3. 安装依赖

```bash
pip install -r requirements.txt
```

### 4. 启动服务

```bash
uvicorn main:app --reload --port 8080
```

### 5. 访问

| 页面 | 说明 |
|------|------|
| `http://127.0.0.1:8080` | 项目首页 |
| `http://127.0.0.1:8080/chat` | 聊天界面 |
| `http://127.0.0.1:8080/docs` | Swagger API 文档 |
| `http://127.0.0.1:8080/health` | 健康检查 |

---

## API 说明

### 文档上传

```http
POST /api/upload
Content-Type: multipart/form-data

file: example.pdf        # PDF / DOCX 文件（必填）
kb_id: default           # 知识库 ID（可选，默认 default）
```

### 知识库管理

```http
POST   /api/knowledge-bases          # 创建知识库
GET    /api/knowledge-bases          # 知识库列表
GET    /api/knowledge-bases/{id}     # 知识库详情
PUT    /api/knowledge-bases/{id}     # 更新知识库
DELETE /api/knowledge-bases/{id}     # 删除知识库
```

### 文档管理

```http
GET    /api/documents?kb_id=default  # 文档列表
DELETE /api/documents/{id}           # 删除文档
```

### 无状态问答

```http
POST /api/qa
Content-Type: application/json

{
  "question": "Python 有什么特点？",
  "kb_id": "default",
  "top_k": 4,
  "temperature": 0.3,
  "rerank": true
}
```

### 会话管理

```http
POST   /api/conversations                       # 创建会话
GET    /api/conversations?kb_id=default         # 会话列表
GET    /api/conversations/{id}                  # 会话详情（含消息）
PATCH  /api/conversations/{id}                  # 修改标题
DELETE /api/conversations/{id}                  # 删除会话
```

### 会话问答

```http
POST /api/conversations/{id}/qa                 # RAG 多轮问答
POST /api/conversations/{id}/agent              # Agent 问答（非流式）
POST /api/conversations/{id}/agent/stream       # Agent 流式问答（SSE）
```

### 通用请求体

```json
// RAG 问答
{
  "question": "string  (1-2000 chars)",
  "top_k": 4,
  "temperature": 0.3,
  "rerank": true,
  "retrieval_top_k": 0
}

// Agent 问答
{
  "question": "string  (1-2000 chars)",
  "top_k": 4,
  "temperature": 0.3,
  "max_iterations": 5
}
```

### 响应示例

```json
{
  "conversation_id": "abc123",
  "answer": "Python 是一种解释型、面向对象的高级编程语言，具有简洁的语法和丰富的标准库……",
  "summary": "Python 是一种解释型、面向对象的高级编程语言",
  "sources": [
    {
      "document_id": "def456",
      "filename": "python-guide.pdf",
      "page": 12,
      "content": "Python is an interpreted, object-oriented...",
      "relevance_score": 0.9421
    }
  ],
  "model_used": "deepseek-chat"
}
```

---

## 项目亮点

### 功能亮点

- **RAG + Agent 双模式** — 简单查询用 RAG（快），复杂推理用 Agent（强），前端一键切换
- **Agent 双工具协同** — 知识库检索 + 联网搜索，Agent 自主编排调用顺序，覆盖静态知识 + 实时信息
- **SSE 流式输出** — token 逐字渲染 + 推理步骤实时展示，体验接近 ChatGPT
- **Sources 精确溯源** — 每个回答标注文件名、页码、相关度分数，KB/WEB 来源可区分
- **多知识库隔离** — 独立 ChromaDB Collection + SQLite FK 关联，支持创建/删除/切换
- **Rerank 可选降级** — BGE-Reranker 惰性加载，`rerank_enabled=False` 跳过，无 GPU 不阻塞
- **自动 Schema 迁移** — 检测旧版数据库 CHECK 约束并自动升级，不丢数据

### 工程亮点

- **分层架构** — Router → Service → Repository 三层解耦，FastAPI Depends 依赖注入
- **共享 RAG 管线** — `rag_pipeline.py` 消除 3 处重复的检索代码
- **Tool Registry 模式** — dict 映射工具名 → 处理函数，新增工具只需注册无需改 ReAct 循环
- **线程安全 SQLite** — `threading.local()` 连接隔离 + WAL 模式读写并发
- **最小化依赖** — 仅 8 个 PyPI 包，不依赖 LangChain 重型框架
- **优雅降级** — Reranker 加载失败 → 回退原始排序；Web Search 失败 → 降级为纯 KB 问答

---

## 后续规划

### 短期 (v0.5)

- [ ] 支持更多文档格式：Word (.docx)、Markdown、TXT
- [ ] Agent 工具可视化：在前端以卡片形式展示每个工具调用的输入/输出
- [ ] 用户反馈机制：点赞/点踩，用于评估回答质量
- [ ] 会话搜索：按关键词检索历史对话

### 中期 (v0.6)

- [ ] 混合检索：BM25 关键词 + 向量语义融合（Hybrid Search）
- [ ] 查询重写：对用户问题进行改写/扩展以提升召回率
- [ ] 多轮对话压缩：长对话自动摘要，避免超出上下文窗口
- [ ] 引用高亮：前端点击来源直接在原文中高亮对应段落

### 长期 (v1.0)

- [ ] 多模态支持：图片上传 + OCR + 图片问答
- [ ] 用户认证与多租户：JWT + 用户级知识库隔离
- [ ] Docker 一键部署：`docker-compose up`
- [ ] RAGAS 评估集成：自动化忠实度/相关性/准确性评测
- [ ] 知识图谱集成：实体关系抽取 + GraphRAG
- [ ] 本地模型支持：Ollama / vLLM 替代云端 API

---

## License

MIT License

---

<p align="center">
  <sub>Built with Python · FastAPI · ChromaDB · DeepSeek · Qwen · Tavily</sub>
</p>
