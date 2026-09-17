# AI 知识库问答系统 — 架构文档

> 版本 0.4.0 | 2026-06-04

---

## 1. 目录树

```
RAGtest1/
├── main.py                          # FastAPI 入口，路由注册，首页/健康检查
├── requirements.txt                 # Python 依赖
├── .env                             # 环境变量（API Keys 等）
├── .env.example                     # 环境变量模板
│
├── static/
│   └── chat.html                    # 前端聊天界面 (HTML+CSS+JS)
│
├── data/
│   └── app.db                       # SQLite 数据库
│
├── chroma_data/                     # ChromaDB 持久化向量数据
│   ├── chroma.sqlite3
│   └── {uuid}/                      # 每个 collection 一个目录
│       ├── data_level0.bin
│       ├── header.bin
│       ├── length.bin
│       └── link_lists.bin
│
└── app/
    ├── config.py                    # Pydantic Settings 配置管理
    │
    ├── db/
    │   └── database.py              # SQLite 连接池、建表、迁移
    │
    ├── models/
    │   └── schemas.py               # 23 个 Pydantic 请求/响应模型
    │
    ├── repositories/                # 数据访问层 (CRUD)
    │   ├── kb_repo.py               # knowledge_bases 表
    │   ├── doc_repo.py              # documents 表
    │   ├── conv_repo.py             # conversations 表
    │   └── msg_repo.py              # messages 表
    │
    ├── services/                    # 业务逻辑层
    │   ├── rag_pipeline.py          # 共享 RAG 流水线（检索/格式化/摘要）
    │   ├── rag_service.py           # 无状态 RAG 问答
    │   ├── chat_service.py          # 多轮对话 RAG 问答
    │   ├── agent_service.py         # Agent 模式（ReAct + Tool Calling + SSE）
    │   ├── kb_tool.py               # Agent 工具：知识库检索
    │   ├── web_search_tool.py       # Agent 工具：Tavily 联网搜索
    │   ├── embedding_service.py     # 文本向量化（Qwen Embedding API）
    │   ├── vector_store.py          # ChromaDB 向量存储封装
    │   ├── pdf_service.py           # PDF 文本提取（PyMuPDF）
    │   ├── word_service.py          # DOCX 文本提取（python-docx）
    │   ├── chunking_service.py      # 文本分块（LangChain TextSplitter）
    │   └── reranker_service.py      # 重排序（FlagEmbedding BGE-Reranker）
    │
    ├── routers/                     # API 路由层
    │   ├── upload.py                # POST /api/upload
    │   ├── qa.py                    # POST /api/qa
    │   ├── documents.py             # GET/DELETE /api/documents
    │   ├── knowledge_bases.py       # CRUD /api/knowledge-bases
    │   └── conversations.py         # CRUD /api/conversations + Agent
    │
    └── utils/
        └── exceptions.py            # 自定义异常 + 全局异常处理器
```

---

## 2. 模块依赖关系

```
                        ┌─────────────┐
                        │   main.py   │
                        └──────┬──────┘
                               │
                  ┌────────────┼────────────┐
                  │            │            │
            ┌─────▼─────┐ ┌───▼───┐ ┌──────▼──────┐
            │  routers  │ │config │ │   static    │
            └─────┬─────┘ └───────┘ └─────────────┘
                  │
        ┌─────────┼─────────┐
        │         │         │
   ┌────▼────┐ ┌──▼──┐ ┌───▼───────┐
   │ schemas │ │utils│ │ services  │
   └─────────┘ └─────┘ └─────┬─────┘
                             │
                    ┌────────┼────────┐
                    │        │        │
              ┌─────▼────┐ ┌─▼──┐ ┌───▼──────────┐
              │repositories│ │ db │ │ external APIs│
              └────────────┘ └────┘ │• DeepSeek    │
                                    │• Qwen Embed  │
                                    │• Tavily      │
                                    │• ChromaDB    │
                                    └──────────────┘
```

**依赖规则：**
- Router → Service → Repository → Database（调用链）
- Router 不直接访问 Repository（由 Service 中转）
- Service 之间可互相调用（如 AgentService 调用 KBTool）
- `rag_pipeline.py` 是纯函数模块，被多个 Service 共用
- `config.py` 被所有层引用（全局单例）

---

## 3. 请求处理流程

### 3.1 上传文档

```
POST /api/upload (multipart/form-data)
  │
  ├─ upload.py: validate Content-Type (PDF/DOCX), file_size ≤ 50MB
  │
  ├─ PDFService / WordService extract_text(file_bytes)
  │     └─ pymupdf.open() / python-docx → text extraction
  │
  ├─ ChunkingService.split(full_text)
  │     └─ RecursiveCharacterTextSplitter (chunk_size=1000, overlap=200)
  │         separators: ["\n\n", "\n", "。", ".", " ", ""]
  │
  ├─ EmbeddingService.embed_texts(chunks)
  │     └─ POST {embedding_base_url}/embeddings (batch_size=20)
  │
  ├─ VectorStoreService.add_chunks(collection, chunks, embeddings, ...)
  │     └─ chromadb.Collection.add(ids, embeddings, documents, metadatas)
  │
  ├─ DocRepo.add(kb_id, doc_id, filename, page_count, chunk_count)
  ├─ KBRepo.increment_doc_count(kb_id)
  │
  └─ Response: { document_id, filename, page_count, chunk_count }
```

### 3.2 RAG 问答（无状态）

```
POST /api/qa
  │
  ├─ qa.py: validate KB exists, collection not empty
  │
  ├─ RAGService.ask(question, top_k, temperature)
  │     │
  │     ├─ rag_pipeline.retrieve_context(...)
  │     │     ├─ EmbeddingService.embed_query(question)
  │     │     ├─ VectorStoreService.query(collection, embedding, retrieval_k)
  │     │     ├─ [if rerank_enabled] RerankerService.rerank(...)
  │     │     └─ rag_pipeline.build_source_list(docs, metas)
  │     │
  │     ├─ LLM: POST {deepseek_base_url}/chat/completions
  │     │     messages: [system_prompt, user(context+question)]
  │     │
  │     └─ rag_pipeline.extract_summary(answer)
  │
  └─ Response: { question, summary, answer, sources, model_used }
```

### 3.3 多轮对话 RAG 问答

```
POST /api/conversations/{conv_id}/qa
  │
  ├─ conversations.py: validate conv & KB exist
  │
  ├─ ChatService.ask(conversation_id, question, top_k, temperature)
  │     │
  │     ├─ MsgRepo.list_recent(conversation_id, 20) → 加载历史
  │     ├─ rag_pipeline.retrieve_context(...) → 同 RAG 流程
  │     ├─ LLM: messages = [system, ...history(user+assistant), user(context+question)]
  │     ├─ MsgRepo.add(user_msg) + MsgRepo.add(assistant_msg + sources)
  │     ├─ ConvRepo.increment_message_count(...)
  │     └─ [if no title] ConvRepo.update_title(...)
  │
  └─ Response: { conversation_id, answer, summary, sources, ... }
```

### 3.4 Agent 流式问答（SSE）

```
POST /api/conversations/{conv_id}/agent/stream
  │
  ├─ conversations.py: validate, return StreamingResponse(media_type="text/event-stream")
  │
  ├─ AgentService.ask_stream(conversation_id, question, ...)
  │     │
  │     ├─ MsgRepo.add(user_msg) → 保存用户消息
  │     ├─ _build_messages() → 加载历史，过滤占位消息
  │     │
  │     ├─ ReAct Loop (最多 5 轮):
  │     │     │
  │     │     ├─ LLM (stream=True):
  │     │     │     ├─ 累积 delta.tool_calls → tool_deltas dict
  │     │     │     └─ 逐 token → SSE: event: token, data: {"token":"..."}
  │     │     │
  │     │     ├─ 如果 finish_reason == "tool_calls":
  │     │     │     ├─ SSE: event: tool_call → data: {step, tool, args}
  │     │     │     ├─ _tool_handlers[tool_name](query, top_k)
  │     │     │     │     ├─ search_knowledge_base → KBTool.search()
  │     │     │     │     └─ search_web → WebSearchTool.search()
  │     │     │     ├─ SSE: event: tool_result → data: {step, found}
  │     │     │     └─ 继续循环
  │     │     │
  │     │     └─ 如果无 tool_calls → final_answer → break
  │     │
  │     ├─ SSE: event: sources → data: {sources: [...]}
  │     ├─ MsgRepo.add(assistant_msg + sources) → 保存最终回答
  │     ├─ ConvRepo.increment_message_count(...)
  │     │
  │     └─ SSE: event: done → data: {conversation_id, message_id}
  │
  └─ 浏览器 fetch + ReadableStream 逐行解析 SSE，增量更新 UI
```

---

## 4. RAG 流程图

```
                        ┌──────────────┐
                        │  用户提问     │
                        └──────┬───────┘
                               │
                    ┌──────────▼──────────┐
                    │  EmbeddingService   │
                    │  embed_query(q)     │
                    │  → 浮点向量 [1536d] │
                    └──────────┬──────────┘
                               │
                    ┌──────────▼──────────┐
                    │  VectorStoreService │
                    │  .query(collection, │
                    │    embedding, k×3)  │
                    │  → top-k×3 候选     │
                    └──────────┬──────────┘
                               │
                    ┌──────────▼──────────┐
                    │  rerank_enabled?    │
                    │  & len(docs) > k?   │
                    └──────┬──────┬───────┘
                       Yes │      │ No
              ┌────────────▼┐     └─────────┐
              │ RerankerService│              │
              │ cross-encoder  │              │
              │ rerank(q,docs) │              │
              │ → top-k 精排   │              │
              └───────┬────────┘              │
                      └──────────┬────────────┘
                                 │
                    ┌────────────▼────────────┐
                    │  Build Context          │
                    │  [Source 1: f.pdf, P1]  │
                    │  chunk text...          │
                    │  ─────────────────      │
                    │  [Source 2: f.pdf, P3]  │
                    │  chunk text...          │
                    └────────────┬────────────┘
                                 │
                    ┌────────────▼────────────┐
                    │  Build LLM Messages     │
                    │  system: "使用上下文回答"│
                    │  user: Context + Question│
                    └────────────┬────────────┘
                                 │
                    ┌────────────▼────────────┐
                    │  DeepSeek Chat API      │
                    │  POST /chat/completions │
                    │  model: deepseek-chat   │
                    └────────────┬────────────┘
                                 │
                    ┌────────────▼────────────┐
                    │  返回: answer + sources │
                    └─────────────────────────┘
```

---

## 5. Agent 流程图

```
                        ┌──────────────┐
                        │  用户提问     │
                        └──────┬───────┘
                               │
                    ┌──────────▼──────────┐
                    │  _build_messages()   │
                    │  加载历史 + System   │
                    │  Prompt + 2 Tools    │
                    │  • search_kb         │
                    │  • search_web        │
                    └──────────┬──────────┘
                               │
              ┌────────────────▼────────────────┐
              │   ReAct Loop (max_iterations=5)  │
              │                                   │
              │  ┌───────────────────────────┐    │
              │  │  LLM call (stream=True)   │    │
              │  │  累积 tool_call deltas    │    │
              │  │  流式发送 token SSE       │    │
              │  └───────────┬───────────────┘    │
              │              │                    │
              │    ┌─────────▼─────────┐          │
              │    │ finish_reason?     │          │
              │    └────┬─────────┬────┘          │
              │         │         │               │
              │   tool_calls     stop             │
              │         │         │               │
              │  ┌──────▼──────┐  │               │
              │  │ 执行工具     │  │               │
              │  │ tool_handler │  │               │
              │  │ registry     │  │               │
              │  └──────┬──────┘  │               │
              │         │         │               │
              │  ┌──────▼──────┐  │               │
              │  │ SSE:        │  │               │
              │  │ tool_call   │  │               │
              │  │ tool_result │  │               │
              │  └──────┬──────┘  │               │
              │         │         │               │
              │         ▼         ▼               │
              │  ┌────────┐  ┌────────┐          │
              │  │ 继续循环 │  │ final  │          │
              │  │        │  │ answer │          │
              │  └────────┘  └───┬────┘          │
              └──────────────────┼───────────────┘
                                 │
                    ┌────────────▼────────────┐
                    │  SSE: sources + done    │
                    │  保存消息到 SQLite      │
                    │  更新 conversation 标题 │
                    └─────────────────────────┘
```

**SSE 事件流示例：**

```
event: tool_call
data: {"step":1,"tool":"search_knowledge_base","args":"{\"question\":\"...\"}"}

event: tool_result
data: {"step":1,"tool":"search_knowledge_base","found":4}

event: token
data: {"token":"根据"}

event: token
data: {"token":"知识库"}

event: token
data: {"token":"中的"}

... (更多 token 事件)

event: sources
data: {"sources":[{"document_id":"...","filename":"知识文档.pdf","page":0,...}]}

event: done
data: {"conversation_id":"...","message_id":42}
```

---

## 6. 数据库 ER 图

```
┌─────────────────────────────┐
│      knowledge_bases        │
├─────────────────────────────┤
│ PK id          TEXT          │◄──────────┐
│    name        TEXT UNIQUE   │           │
│    description TEXT          │           │
│    collection  TEXT UNIQUE   │           │
│    doc_count   INTEGER       │           │
│    created_at  TEXT          │           │
│    updated_at  TEXT          │           │
└──────────┬──────────────────┘           │
           │                              │
           │ FK (kb_id)                   │ FK (kb_id)
           │                              │
┌──────────▼──────────────────┐  ┌────────┴──────────────────┐
│        documents            │  │      conversations        │
├─────────────────────────────┤  ├───────────────────────────┤
│ PK id          TEXT          │  │ PK id          TEXT        │◄──────┐
│ FK kb_id       TEXT ────────┼──│ FK kb_id       TEXT ───────┼──┐    │
│    filename    TEXT          │  │    title       TEXT        │  │    │
│    page_count  INTEGER       │  │    msg_count   INTEGER     │  │    │
│    chunk_count INTEGER       │  │    created_at  TEXT        │  │    │
│    uploaded_at TEXT          │  │    updated_at  TEXT        │  │    │
└─────────────────────────────┘  └───────────────────────────┘  │    │
                                                                │    │
                                           FK (conversation_id) │    │
                                                                │    │
                               ┌────────────────────────────────┼────┘
                               │        messages               │
                               ├────────────────────────────────┤
                               │ PK id          INTEGER AUTOINC │
                               │ FK conversation_id TEXT ───────┘
                               │    role        TEXT CHECK(...)  │
                               │    content     TEXT             │
                               │    sources     TEXT (JSON)      │
                               │    model       TEXT             │
                               │    created_at  TEXT             │
                               └────────────────────────────────┘

关系:
  knowledge_bases 1──N documents      (CASCADE DELETE)
  knowledge_bases 1──N conversations  (CASCADE DELETE)
  conversations   1──N messages       (CASCADE DELETE)
```

**`sources` JSON 结构（存储在 messages 表中）：**
```json
[
  {
    "document_id": "abc123...",
    "filename": "知识文档.pdf",
    "page": 2,
    "content": "文档片段内容的前500字...",
    "relevance_score": 0.8734
  }
]
```

---

## 7. ChromaDB 数据流

```
                         ┌────────────────────┐
                         │   PDF Upload        │
                         │   (pdf_service.py)  │
                         └─────────┬──────────┘
                                   │ 原始文本
                         ┌─────────▼──────────┐
                         │   Text Chunking     │
                         │   (chunking_        │
                         │    service.py)      │
                         │   1000 char/chunk   │
                         │   200 char overlap  │
                         └─────────┬──────────┘
                                   │ list[str]
                         ┌─────────▼──────────┐
                         │   Embedding         │
                         │   (embedding_       │
                         │    service.py)      │
                         │   Qwen text-emb-v3  │
                         │   1536-dim vectors  │
                         └─────────┬──────────┘
                                   │ list[list[float]]
                         ┌─────────▼──────────┐
                         │   Vector Store      │
          ┌──────────────│   (vector_store.py) │
          │              │   ChromaDB Client   │
          │              └─────────┬──────────┘
          │                        │
          │     ┌──────────────────┼──────────────────┐
          │     │                  │                  │
          │     ▼                  ▼                  ▼
          │  ┌───────┐      ┌───────────┐      ┌───────────┐
          │  │ add() │      │  query()  │      │ delete()  │
          │  └───┬───┘      └─────┬─────┘      └─────┬─────┘
          │      │                │                  │
          │      ▼                ▼                  ▼
          │  ┌─────────────────────────────────────────────┐
          │  │         ChromaDB Persistent Storage         │
          │  │                                             │
          │  │  chroma.sqlite3                             │
          │  │  ├── collections (name, uuid, metadata)     │
          │  │  ├── embedding_metadata (id, seq_id)        │
          │  │  └── ...                                    │
          │  │                                             │
          │  │  {uuid}/                                    │
          │  │  ├── data_level0.bin   (HNSW graph)        │
          │  │  ├── header.bin        (metadata offsets)  │
          │  │  ├── length.bin        (segment lengths)   │
          │  │  └── link_lists.bin    (HNSW edges)        │
          │  └─────────────────────────────────────────────┘
          │
          │  查询时:
          │  • query_embeddings 通过 HNSW 索引找到最近邻
          │  • 返回: ids, documents, metadatas, distances
          │  • relevance_score = 1.0 - cosine_distance
          │
          └────── collection_name 命名规则 ──────
                 默认: "kb_default"
                 其他: "kb_{kb_id}"
```

### ChromaDB Metadata 结构（每 chunk 一条）

```json
{
  "document_id": "abc123def456...",
  "filename": "知识文档.pdf",
  "page": 2,
  "chunk_index": 5,
  "uploaded_at": "2026-06-04T12:00:00+00:00",
  "relevance_score": 0.8734
}
```

---

## 8. API 设计

### 8.1 端点总览

| 方法 | 路径 | 说明 | 认证 |
|------|------|------|------|
| GET | `/health` | 健康检查 | 无 |
| GET | `/chat` | 聊天界面 (SPA) | 无 |
| POST | `/api/upload` | 上传文档 (PDF/DOCX) | 无 |
| POST | `/api/qa` | 无状态 RAG 问答 | 无 |
| GET | `/api/documents` | 文档列表 | 无 |
| DELETE | `/api/documents/{id}` | 删除文档 | 无 |
| POST | `/api/knowledge-bases` | 创建知识库 | 无 |
| GET | `/api/knowledge-bases` | 知识库列表 | 无 |
| GET | `/api/knowledge-bases/{id}` | 知识库详情 | 无 |
| PUT | `/api/knowledge-bases/{id}` | 更新知识库 | 无 |
| DELETE | `/api/knowledge-bases/{id}` | 删除知识库 | 无 |
| POST | `/api/conversations` | 创建会话 | 无 |
| GET | `/api/conversations` | 会话列表 (分页) | 无 |
| GET | `/api/conversations/{id}` | 会话详情 + 消息 | 无 |
| PATCH | `/api/conversations/{id}` | 更新会话标题 | 无 |
| DELETE | `/api/conversations/{id}` | 删除会话 | 无 |
| POST | `/api/conversations/{id}/qa` | 会话内 RAG 问答 | 无 |
| POST | `/api/conversations/{id}/agent` | Agent 非流式问答 | 无 |
| POST | `/api/conversations/{id}/agent/stream` | Agent SSE 流式问答 | 无 |

### 8.2 请求/响应模型

#### 上传文档 — `POST /api/upload`

```
Request:  multipart/form-data
  file:     UploadFile  (PDF or DOCX, max 50 MB)
  kb_id:    str         (default: "default")

Response: 200
  {
    "document_id": "abc123...",
    "kb_id":        "default",
    "filename":     "report.pdf",
    "page_count":   12,
    "chunk_count":  24,
    "status":       "success"
  }
```

#### RAG 问答 — `POST /api/qa` / `POST /api/conversations/{id}/qa`

```
Request:  application/json
  {
    "question":         "Python 有什么特点?",  // 1-2000 chars
    "kb_id":            "default",             // 1-50 chars (仅 /api/qa)
    "top_k":            4,                     // 1-20
    "temperature":      0.3,                   // 0.0-1.0
    "rerank":           true,                  // bool
    "retrieval_top_k":  0                      // 0-100 (0=auto)
  }

Response: 200
  {
    "answer":           "Python 是...",
    "summary":          "Python 是一种...",
    "sources":          [{document_id, filename, page, content, relevance_score}],
    "model_used":       "deepseek-chat"
  }
```

#### Agent 问答 — `POST /api/conversations/{id}/agent`

```
Request:  application/json
  {
    "question":       "Python 有什么特点?",    // 1-2000 chars
    "top_k":          4,                       // 1-20
    "temperature":    0.3,                     // 0.0-1.0
    "max_iterations": 5                        // 1-10
  }

Response: 200
  {
    "answer":           "根据知识库...",
    "sources":          [...],
    "reasoning_steps":  [
      {step: 1, type: "tool_call",  detail: "调用 search_knowledge_base: ..."},
      {step: 1, type: "tool_result", detail: "找到 4 条结果"},
      {step: 2, type: "answer",      detail: ""}
    ],
    "model_used":       "deepseek-chat"
  }
```

#### Agent 流式 — `POST /api/conversations/{id}/agent/stream`

```
Response: text/event-stream

event: tool_call
data: {"step":1,"tool":"search_knowledge_base","args":"{...}"}

event: tool_result
data: {"step":1,"tool":"search_knowledge_base","found":4}

event: token
data: {"token":"根据"}

event: sources
data: {"sources":[{...}]}

event: done
data: {"conversation_id":"...","message_id":42}

event: error
data: {"message":"LLM 调用失败"}
```

### 8.3 错误响应格式

所有错误统一返回：

```json
{
  "detail": "Knowledge base 'xxx' not found.",
  "error_code": "KB_NOT_FOUND"
}
```

| HTTP | error_code | 触发场景 |
|------|-----------|---------|
| 400 | `INVALID_FILE_TYPE` | 上传非 PDF/DOCX 文件 |
| 400 | `EMPTY_PDF` | PDF 无可提取文本 |
| 400 | `CORRUPT_PDF` | 文件无法解析 |
| 400 | `KB_ALREADY_EXISTS` | 知识库重名 |
| 400 | `DEFAULT_KB_DELETE_FORBIDDEN` | 删除 default 知识库 |
| 404 | `KB_NOT_FOUND` | 知识库不存在 |
| 404 | `DOCUMENT_NOT_FOUND` | 文档不存在 |
| 404 | `CONVERSATION_NOT_FOUND` | 会话不存在 |
| 413 | `FILE_TOO_LARGE` | 文件超限 |
| 422 | (Pydantic) | 请求参数校验失败 |
| 500 | `RERANKER_NOT_AVAILABLE` | Reranker 不可用 |

### 8.4 查询参数约定

| 端点 | 参数 | 类型 | 默认 | 范围 |
|------|------|------|------|------|
| `GET /api/documents` | `kb_id` | str | `"default"` | — |
| `GET /api/conversations` | `kb_id` | str | `"default"` | — |
| | `page` | int | `1` | >= 1 |
| | `page_size` | int | `20` | 1-100 |
| `DELETE /api/documents/{id}` | `kb_id` | str | `"default"` | — |

---

## 9. 配置项一览

| 分类 | 配置项 | 默认值 | 说明 |
|------|--------|--------|------|
| **Chat** | `DEEPSEEK_API_KEY` | — | DeepSeek API 密钥 |
| | `DEEPSEEK_BASE_URL` | `https://api.deepseek.com` | API 地址 |
| | `CHAT_MODEL` | `deepseek-chat` | 对话模型 |
| **Embedding** | `EMBEDDING_API_KEY` | — | 阿里云 DashScope 密钥 |
| | `EMBEDDING_BASE_URL` | `https://dashscope.aliyuncs.com/compatible-mode/v1` | |
| | `EMBEDDING_MODEL` | `text-embedding-v3` | 向量模型 |
| **存储** | `SQLITE_DB_PATH` | `./data/app.db` | SQLite 路径 |
| | `CHROMA_PERSIST_DIR` | `./chroma_data` | ChromaDB 路径 |
| **分块** | `CHUNK_SIZE` | `1000` | 分块大小 |
| | `CHUNK_OVERLAP` | `200` | 分块重叠 |
| **Reranker** | `RERANKER_MODEL` | `BAAI/bge-reranker-v2-m3` | 重排序模型 |
| | `RERANK_ENABLED` | `False` | 是否启用。有效值需与请求参数取 AND；纯 CPU 单次约 10s，故默认关闭 |
| | `RETRIEVAL_MULTIPLIER` | `3` | 检索扩展倍数（候选池 = top_k × 3） |
| | `RERANK_MAX_LENGTH` | `512` | 候选截断长度。实测调到 256 会让 Recall@4 掉 15.5%，不建议改小 |
| | `RERANK_QUANTIZE` | `True` | Linear 层动态 int8 量化，2.18x 且指标无损 |
| **混合检索** | `HYBRID_ENABLED` | `True` | 向量 + BM25 双路召回，RRF 融合 |
| | `RRF_K` | `60` | RRF 平滑常数（原论文取值） |
| **Agent** | `AGENT_MAX_ITERATIONS` | `5` | ReAct 最大迭代 |
| **Web** | `TAVILY_API_KEY` | — | Tavily 搜索 API（可选） |
| **限制** | `MAX_FILE_SIZE_MB` | `50` | 最大上传 |
| | `MAX_QUESTION_LENGTH` | `2000` | 最大问题长度 |
| | `DEFAULT_TOP_K` | `4` | 默认检索数量 |
| | `EMBEDDING_BATCH_SIZE` | `10` | 嵌入批处理（DashScope text-embedding-v3 单次上限即 10） |
