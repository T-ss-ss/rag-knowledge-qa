# AI 知识库问答系统 — 面试项目说明

> 适用场景：校招 / 实习面试 · 后端开发 / AI 应用开发岗位  
> 技术栈：Python · FastAPI · ChromaDB · SQLite · DeepSeek · Qwen Embedding · Tavily

---

## 一、项目目录结构

```
RAGtest1/
├── main.py                          # FastAPI 入口：lifespan、路由注册、静态文件挂载
├── requirements.txt                 # 最小化依赖声明
├── .env                             # API Key 等敏感配置（不入库）
├── static/
│   └── chat.html                    # 前端聊天界面（SSE 流式消费）
├── data/
│   └── app.db                       # SQLite 数据库文件（WAL 模式）
├── chroma_data/                     # ChromaDB 持久化向量存储
└── app/
    ├── config.py                    # Pydantic Settings 集中配置
    ├── db/
    │   └── database.py              # SQLite 连接池、表初始化、Schema 自动迁移
    ├── models/
    │   └── schemas.py               # Pydantic 请求/响应模型（194 行）
    ├── repositories/
    │   ├── kb_repo.py               # 知识库 CRUD
    │   ├── doc_repo.py              # 文档记录 CRUD
    │   ├── conv_repo.py             # 会话 CRUD + 消息计数
    │   └── msg_repo.py              # 消息持久化（含 role/tool 支持）
    ├── services/
    │   ├── pdf_service.py           # PyMuPDF 解析 PDF
    │   ├── word_service.py          # python-docx 解析 DOCX
    │   ├── chunking_service.py      # RecursiveCharacterTextSplitter 文本切块
    │   ├── embedding_service.py     # Qwen text-embedding-v3 批量/单条向量化
    │   ├── vector_store.py          # ChromaDB PersistentClient 封装（HNSW+Cosine）
    │   ├── reranker_service.py      # BGE-Reranker v2-m3 重排序（惰性加载）
    │   ├── rag_pipeline.py          # 共享 RAG 管线：检索→重排→格式化→去重
    │   ├── rag_service.py           # 无状态 RAG 问答
    │   ├── chat_service.py          # 会话 RAG 问答（带多轮记忆）
    │   ├── kb_tool.py               # Agent 工具：知识库检索 + Function Schema
    │   ├── web_search_tool.py       # Agent 工具：Tavily 联网搜索 + Function Schema
    │   └── agent_service.py         # ReAct Agent：Tool Calling + 流式 SSE + 多轮记忆
    ├── routers/
    │   ├── upload.py                # POST /api/upload — PDF / DOCX 上传
    │   ├── qa.py                    # POST /api/qa — 无状态问答
    │   ├── documents.py             # GET/DELETE /api/documents — 文档管理
    │   ├── knowledge_bases.py       # CRUD /api/knowledge-bases — 知识库管理
    │   └── conversations.py         # CRUD + RAG + Agent + Agent/stream — 会话中心
    └── utils/
        └── exceptions.py            # 自定义异常 + FastAPI exception_handlers
```

---

## 二、核心模块职责

| 模块 | 职责 | 关键设计 |
|------|------|---------|
| `config.py` | 全局配置中心 | Pydantic Settings，`.env` 注入，含 LLM/Embedding/Reranker/Agent/Tavily 全部配置 |
| `database.py` | SQLite 连接管理 | `threading.local()` 线程安全，WAL 模式，`init_db()` 建表 + 自动 Schema 迁移 |
| `schemas.py` | 请求/响应校验 | 14 个 Pydantic Model，含 Field 约束和 description |
| `pdf_service.py` | PDF 解析 | PyMuPDF 逐页提取文本 |
| `word_service.py` | DOCX 解析 | python-docx 段落提取文本 |
| `chunking_service.py` | 文本切块 | RecursiveCharacterTextSplitter，1000 字/块，200 字重叠，中文分隔符优先 |
| `embedding_service.py` | 向量化 | Qwen `text-embedding-v3`，支持批量（20 条/批）和单条查询 |
| `vector_store.py` | 向量存储/检索 | ChromaDB PersistentClient，HNSW + Cosine 相似度，按 document_id 条件删除 |
| `reranker_service.py` | 精排 | BGE-Reranker v2-m3，惰性加载 + 降级回退，FP16 加速，输出归一化分数 |
| `rag_pipeline.py` | 共享 RAG 管线 | `retrieve_context()` 统一检索流程，"粗筛→精排→格式化"三段式 |
| `rag_service.py` | 无状态问答 | 单轮 Q&A，不保存历史 |
| `chat_service.py` | 会话问答 | 多轮记忆（最近 20 条），自动过滤 Agent tool 消息 |
| `kb_tool.py` | Agent 知识库工具 | 封装 `retrieve_context()` 为 OpenAI Function Calling 格式 |
| `web_search_tool.py` | Agent 联网工具 | Tavily Search API 封装，返回格式与 KB 工具对齐 |
| `agent_service.py` | ReAct Agent | Tool Calling 循环、SSE 流式、tool registry 模式、多轮上下文 |
| `conversations.py` | 会话路由 | 6 个端点：CRUD + RAG QA + Agent QA + Agent Stream |
| `chat.html` | 前端界面 | 原生 JS，`ReadableStream` 消费 SSE，流式渲染 + 推理步骤可视化 |

---

## 三、技术架构图

### 3.1 系统架构总览

```
┌──────────────────────────────────────────────────────────────────┐
│                         Browser (chat.html)                       │
│   SSE ReadableStream / fetch API / REST JSON                     │
└──────────────────────────┬───────────────────────────────────────┘
                           │
┌──────────────────────────▼───────────────────────────────────────┐
│                     FastAPI (main.py)                             │
│  ┌────────────┐  ┌─────────────┐  ┌──────────────────────────┐  │
│  │ CORS       │  │ StaticFiles │  │ Exception Handlers       │  │
│  │ Middleware │  │ /static     │  │ (404/422/500→JSON)       │  │
│  └────────────┘  └─────────────┘  └──────────────────────────┘  │
│                                                                   │
│  Router Layer (app/routers/)                                      │
│  ┌──────────┬──────────┬──────────┬─────────────┬──────────────┐ │
│  │ /upload  │ /qa      │ /docs    │ /kb         │ /conversations│ │
│  └──────────┴──────────┴──────────┴─────────────┴──────────────┘ │
└──────────────────────────────────────────────────────────────────┘
                           │
           ┌───────────────┼───────────────┐
           ▼               ▼               ▼
┌──────────────────┐ ┌──────────┐ ┌──────────────────┐
│  Service Layer   │ │ Models   │ │  Repository      │
│  ┌────────────┐  │ │(Pydantic)│ │  Layer           │
│  │RAG Pipeline│  │ └──────────┘ │  ┌────────────┐  │
│  │Agent Service│  │              │  │ KB / Doc   │  │
│  │Chat Service │  │              │  │ Conv / Msg │  │
│  │RAG Service  │  │              │  └────────────┘  │
│  │PDF Service  │  │              └──────────────────┘
│  │Word Service │  │
│  │Chunking     │  │                       │
│  │Embedding    │  │              ┌────────▼────────┐
│  │Reranker     │  │              │  SQLite (WAL)   │
│  │Web Search   │  │              │  data/app.db    │
│  └────────────┘  │              └─────────────────┘
└──────────────────┘
                           │
┌──────────────────┐       │
│ External APIs    │       │
│ ┌──────────────┐ │       │
│ │ DeepSeek     │◄├───────┤
│ │ (Chat LLM)  │ │       │
│ └──────────────┘ │       │
│ ┌──────────────┐ │       │
│ │ Qwen         │◄├───────┘
│ │ (Embedding)  │ │
│ └──────────────┘ │
│ ┌──────────────┐ │
│ │ Tavily       │◄┤
│ │ (Web Search) │ │
│ └──────────────┘ │
└──────────────────┘

┌──────────────────┐
│ ChromaDB         │
│ (chroma_data/)   │
│ ┌──────────────┐ │
│ │ kb_default   │ │
│ │ kb_<kb_id>   │ │
│ │  · chunk_0   │ │
│ │  · chunk_1   │ │
│ │  · ...       │ │
│ └──────────────┘ │
└──────────────────┘
```

### 3.2 RAG 检索流程

```
User Question
      │
      ▼
┌─────────────┐
│ Embedding   │  Qwen text-embedding-v3 → query vector
│ Service     │
└──────┬──────┘
       ▼
┌─────────────┐
│ Vector      │  ChromaDB HNSW + Cosine → top_k × 3 candidates
│ Store       │
└──────┬──────┘
       ▼
   rerank_enabled?
    ┌─────┴─────┐
    ▼           ▼
┌───────┐   ┌───────┐
│BGE    │   │ Skip  │
│Rerank │   │       │
└───┬───┘   └───┬───┘
    ▼           ▼
┌─────────────┐
│ Format       │  "[Source N: filename, Page P]\ncontent"
│ Context      │
└──────┬──────┘
       ▼
┌─────────────┐
│ LLM          │  DeepSeek Chat → answer + sources
│ Generation   │
└─────────────┘
```

### 3.3 Agent ReAct 循环（流式 SSE）

```
User Question
      │
      ▼
┌─────────────────────────┐
│ Build Messages          │  System Prompt + History (filtered) + Question
└──────────┬──────────────┘
           │
    ┌──────▼──────┐       max_iterations = 5
    │  Iteration  │◄──────────────────────┐
    └──────┬──────┘                       │
           ▼                              │
┌──────────────────────┐                  │
│ LLM Call (stream=True)│  DeepSeek with TOOLS=[KB, WebSearch]
└──────────┬───────────┘                  │
           ▼                              │
     finish_reason?                       │
    ┌─────┴─────┐                         │
    ▼           ▼                         │
 tool_calls   content                     │
    │           │                         │
    ▼           ▼                         │
┌────────┐  ┌────────┐                    │
│Execute │  │ Stream │    SSE: token      │
│Tool    │  │ Answer │    event stream    │
└───┬────┘  └───┬────┘                    │
    │           │                         │
    ▼           ▼                         │
 SSE events:  ┌────────┐                  │
 tool_call    │Finalize│                  │
 tool_result  └────────┘                  │
    │                                     │
    └─────────────────────────────────────┘
```

### 3.4 数据库 ER 图

```
┌─────────────────────┐
│   knowledge_bases   │
├─────────────────────┤        ┌─────────────────────┐
│ id        TEXT PK    │───────│    documents         │
│ name      TEXT UNIQUE│       ├─────────────────────┤
│ description TEXT     │       │ id        TEXT PK    │
│ collection_name TEXT │       │ kb_id     TEXT FK    │──┐
│ document_count INT   │       │ filename  TEXT       │  │
│ created_at TEXT       │       │ page_count INT       │  │
│ updated_at TEXT       │       │ chunk_count INT      │  │
└──────────┬──────────┘       │ uploaded_at TEXT      │  │
           │                  └───────────────────────┘  │
           │ 1:N                                         │
           ▼                                              │
┌─────────────────────┐                                   │
│   conversations     │                                   │
├─────────────────────┤                                   │
│ id        TEXT PK    │                                   │
│ kb_id     TEXT FK    │──┐                                │
│ title     TEXT       │  │                                │
│ message_count INT    │  │                                │
│ created_at TEXT      │  │                                │
│ updated_at TEXT      │  │                                │
└──────────┬──────────┘  │                                │
           │              │ CASCADE DELETE                 │
           │ 1:N          │                                │
           ▼              ▼                                │
┌─────────────────────────────────────────────────────────┐│
│                      messages                            ││
├─────────────────────────────────────────────────────────┤│
│ id          INTEGER PK AUTOINCREMENT                    ││
│ conversation_id TEXT FK ──► conversations(id) CASCADE    │◄┘
│ role   TEXT CHECK(user/assistant/system/tool/function)  │
│ content     TEXT NOT NULL                               │
│ sources     TEXT DEFAULT NULL   ← JSON serialized       │
│ model       TEXT DEFAULT NULL                           │
│ created_at  TEXT NOT NULL                               │
└─────────────────────────────────────────────────────────┘
```

### 3.5 ChromaDB 数据流

```
PDF / DOCX Upload
    │
    ▼
PyMuPDF / python-docx → text
    │
    ▼
RecursiveCharacterTextSplitter → chunks[N]
    │
    ▼
Qwen Embedding (batch=20) → embeddings[N][1024]
    │
    ▼
ChromaDB PersistentClient
  Collection: kb_<kb_id>  (HNSW:space=cosine)
  ├── {id}: <doc_id>_0
  │   document: "chunk text..."
  │   embedding: [0.123, -0.456, ...]
  │   metadata: {document_id, filename, page, chunk_index, uploaded_at}
  ├── {id}: <doc_id>_1
  │   ...
  └── {id}: <doc_id>_N

Query Time:
  question → embed → ChromaDB.query(top_k, cosine) → [chunks + distances + metadatas]
    → relevance_score = 1.0 - distance
    → (optional) BGE Reranker re-score & re-rank
    → format context → LLM
```

---

## 四、项目亮点

### 4.1 功能亮点

| 亮点 | 说明 |
|------|------|
| **多知识库隔离** | 每个知识库独立 ChromaDB Collection + 独立 SQLite 外键关联，支持 CRUD，默认知识库不可删除 |
| **完整的 RAG 管线** | Embedding → HNSW 粗筛 → BGE-Reranker 精排 → 格式化 → LLM 生成，每一步可配置 |
| **ReAct Agent + Tool Calling** | 基于 OpenAI Function Calling 协议，Agent 自主决策调用哪个工具、何时停止 |
| **双工具协同** | `search_knowledge_base`（文档检索）+ `search_web`（Tavily 联网搜索），Agent 自主编排调用顺序 |
| **SSE 流式输出** | Agent 模式下 token 逐字推送，工具调用/返回实时可见，前端原生 `ReadableStream` 消费 |
| **会话多轮记忆** | 最近 N 条历史注入 LLM，Agent 模式自动过滤工具调用占位消息，RAG 模式过滤 tool/system 角色 |
| **Sources 精确引用** | 每个回答标注来源文件名、页码、相关度分数，联网搜索区分 KB Source / Web Source |
| **Rerank 可选降级** | BGE-Reranker 惰性加载，`rerank_enabled=False` 直接跳过，不阻塞无 GPU 环境 |
| **向后兼容 Schema 迁移** | 检测旧版 CHECK 约束并自动重建表，不丢数据 |
| **统一错误处理** | 自定义异常类 + FastAPI `exception_handler` 装饰器，所有错误返回统一 JSON |

### 4.2 工程亮点

| 亮点 | 说明 |
|------|------|
| **分层架构** | Router → Service → Repository，职责清晰，依赖注入（FastAPI Depends） |
| **共享 RAG 管线** | `rag_pipeline.py` 消除 `rag_service / chat_service / kb_tool` 三处重复代码 |
| **Tool Registry 模式** | `_tool_handlers` dict 映射工具名 → 处理函数，新增工具只需注册无需改 ReAct 循环 |
| **线程安全 SQLite** | `threading.local()` 隔离连接，WAL 模式支持读写并发 |
| **矢量存储降级友好** | Reranker 加载失败自动 fallback 原始排序，Web Search 失败返回错误文本而不崩溃 |
| **最小化依赖** | 仅 8 个 PyPI 包，无 LangChain 重型框架，直接用 OpenAI SDK |
| **前后端分离** | `main.py` 179 行纯 FastAPI 配置，`static/chat.html` 独立前端，`StaticFiles` 挂载 |
| **Pydantic 全量校验** | 14 个 Schema 覆盖所有请求/响应，含 Field 约束（length, ge, le）和 description |

### 4.3 技术决策

| 决策 | 理由 |
|------|------|
| DeepSeek Chat 而非 GPT-4 | 性价比高，中文能力强，兼容 OpenAI SDK |
| Qwen Embedding 而非 OpenAI Embedding | 中文检索精度更高，阿里云国内访问延迟低 |
| ChromaDB 而非 Milvus/Qdrant | 轻量级，零运维，PersistentClient 直接落盘 |
| SQLite 而非 PostgreSQL | 单机部署，WAL 模式足够，免安装 |
| 原生 SSE 而非 WebSocket | 单向推送，实现简单，浏览器原生 `EventSource`/`ReadableStream` |
| Tavily 而非 SerpAPI | 专为 AI Agent 设计，返回结构化内容，含相关性分数 |
| 非 LangChain 实现 Agent | 更轻量，逻辑完全可控，面试能讲清楚每一行 |

---

## 五、简历描述（Bullet Points）

**AI 知识库问答系统** | Python · FastAPI · ChromaDB · DeepSeek | 独立开发

- 设计并实现了**多知识库 RAG 问答系统**，支持 PDF / DOCX 文档上传、文本切块、向量化存储与语义检索，用户可创建/管理多个隔离的知识库
- 基于 **ReAct 模式构建 Agent**，通过 OpenAI Function Calling 协议实现双工具调用：`search_knowledge_base`（文档检索）与 `search_web`（Tavily 联网搜索），Agent 自主编排工具调用顺序并决策终止
- 使用 **SSE (Server-Sent Events)** 实现 Agent 流式输出，前端通过 `ReadableStream` 逐字渲染 token、实时展示工具调用/返回的推理链
- 实现**会话多轮记忆**：注入最近 N 条历史到 LLM 上下文，自动过滤 Agent tool 角色的占位消息避免协议冲突
- 设计**共享 RAG 管线**（粗筛→精排→格式化），消除 3 处重复代码；采用 **Tool Registry 模式**使 Agent 工具可插拔扩展
- 集成 **BGE-Reranker v2-m3** 对粗筛结果重排序提升召回精度，惰性加载 + 优雅降级确保无 GPU 环境可用
- 采用**分层架构**（Router → Service → Repository），FastAPI Depends 依赖注入，Pydantic 全量校验，SQLite WAL 模式，统一异常处理
- 每个回答标注 **Sources 引用**（文件名、页码、相关度分数），区分知识库来源与联网搜索来源

---

## 六、面试官可能提问的问题

### RAG 基础

| # | 问题 | 考察点 |
|---|------|--------|
| 1 | RAG 的核心流程是什么？你的项目里每步是怎么实现的？ | Embedding 选型、向量库、检索策略 |
| 2 | 为什么用 ChromaDB 而不是 FAISS/Milvus？HNSW 的原理是什么？ | 向量数据库对比、索引算法理解 |
| 3 | Reranker 的作用是什么？为什么不能只用 embedding 相似度？ | 语义匹配 vs 关键词匹配，Cross-encoder vs Bi-encoder |
| 4 | 文本切块的 chunk_size=1000、overlap=200 是怎么定的？有什么 trade-off？ | 工程经验，完整性 vs 精确性的平衡 |
| 5 | 如果检索出来的上下文不相关，怎么处理？ | 降级策略、阈值过滤、用户反馈 |

### Agent & Tool Calling

| # | 问题 | 考察点 |
|---|------|--------|
| 6 | ReAct 模式是什么？你的 Agent 的循环终止条件是什么？ | Agent 设计模式，max_iterations，finish_reason 判断 |
| 7 | Function Calling 的协议是什么样的？你怎么把工具定义传给 LLM？ | OpenAI tool schema 格式，tools 参数 |
| 8 | Agent 什么时候选知识库检索，什么时候选联网搜索？ | System Prompt 设计，决策逻辑 |
| 9 | 如果 Tool Calling 的 JSON 参数解析失败怎么处理？ | 容错设计 |
| 10 | Agent 的最大迭代次数设多少？为什么？ | 成本控制 vs 任务完成度的平衡 |

### 系统设计

| # | 问题 | 考察点 |
|---|------|--------|
| 11 | 你的多知识库是怎么做到数据隔离的？ | 表设计（FK）、ChromaDB Collection 隔离 |
| 12 | 为什么要用 SQLite WAL 模式？ | 并发读写原理 |
| 13 | 会话记忆是怎么实现的？历史消息怎么注入 LLM？ | 上下文窗口管理，消息过滤逻辑 |
| 14 | SSE 和 WebSocket 的区别？你为什么选 SSE？ | 协议选型，单向 vs 双向，实现复杂度 |
| 15 | 你的项目怎么处理高并发？当前方案的瓶颈在哪？ | `threading.local()`、SQLite 限制、LLM API 延迟 |

### 工程实践

| # | 问题 | 考察点 |
|---|------|--------|
| 16 | 你的 Service / Repository 分层是怎么设计的？为什么这么做？ | 分层架构理解，关注点分离 |
| 17 | Pydantic Settings 相比直接 `os.getenv` 有什么优势？ | 类型安全、校验、集中管理 |
| 18 | 你怎么处理 LLM API 调用失败的情况？ | 异常处理、重试策略、降级 |
| 19 | Schema 迁移是怎么自动触发的？会不会丢数据？ | 数据库迁移策略 |
| 20 | 如果要把这个项目部署到服务器，你会怎么做？ | Docker、环境变量、反向代理、GPU 需求 |

### 深入思考

| # | 问题 | 考察点 |
|---|------|--------|
| 21 | BGE-Reranker 是 Cross-encoder，为什么不能直接用它做全量检索？ | 计算复杂度 O(N) vs O(logN) |
| 22 | 你的 Embedding 是调 API 的，如果网络超时或限流怎么处理？ | 重试、降级、本地模型备选 |
| 23 | 如果知识库有 10 万篇文档，ChromaDB 还够用吗？你会怎么优化？ | 分布式向量库、分段索引、混合检索 |
| 24 | 你这个系统有没有做用户认证和多租户？如果需要怎么加？ | 安全设计，JWT、API Key |
| 25 | 如果让你重新设计这个项目，你会有什么不同的选择？ | 技术反思能力 |

### 场景题

| # | 问题 | 考察点 |
|---|------|--------|
| 26 | 用户问"总结一下这份 PDF"，但 PDF 有 200 页，你的系统会怎么处理？ | 长文档策略，Map-Reduce/Refine |
| 27 | 如果你发现 RAG 回答质量不好，你会从哪些方面排查？ | 排障思路：切块、检索、rerank、prompt |
| 28 | 如何评估 RAG 系统的回答质量？你有没有做过评估？ | 评估指标：忠实度、相关性、RAGAS 等 |

---

*文档生成日期：2026-06-04 · 适用项目版本：v0.4.0*
