# RAG 知识库问答系统 — 面试题详细答案

> 配合 `PROJECT_PORTFOLIO.md` 第六节使用，覆盖全部 28 道面试题。
> 每个答案均基于项目实际代码，标注了关键文件和行号。

---

## RAG 基础

### 1. RAG 的核心流程是什么？你的项目里每步是怎么实现的？

**标准 RAG 流程：索引（Indexing）+ 检索（Retrieval）+ 生成（Generation）。**

本项目对应实现 (`app/services/rag_pipeline.py:5-38`)：

| 步骤 | 实现 | 关键代码 |
|------|------|---------|
| **1. Embedding** | Qwen `text-embedding-v3` 将问题转为 1024 维向量 | `embedding_service.embed_query(question)` |
| **2. 粗筛** | ChromaDB HNSW 索引 + Cosine 相似度，检索 `top_k × 3` 条候选 | `vector_store.query(collection_name, query_embedding, actual_k)` |
| **3. 精排** | BGE-Reranker v2-m3 (Cross-encoder) 对候选重排序，截取 top_k | `reranker.rerank(question, documents, metadatas, top_k)` |
| **4. 格式化** | 拼接为 `[Source N: filename, Page P]\ncontent` 格式 | `rag_pipeline.py:28-32` |
| **5. 生成** | DeepSeek Chat 根据 System Prompt + Context 生成回答 | `chat_service.py:68-73` |

**核心技术选型理由**：
- **Embedding 选 Qwen 而非 OpenAI**：中文检索精度更高，阿里云国内延迟低
- **ChromaDB 而非 FAISS**：PersistentClient 直接落盘，零运维，支持 metadata 过滤
- **DeepSeek 而非 GPT-4**：性价比高（约 1/10 价格），中文能力强，兼容 OpenAI SDK

---

### 2. 为什么用 ChromaDB 而不是 FAISS / Milvus？HNSW 的原理是什么？

**选型对比**：

| 维度 | FAISS | Milvus | ChromaDB |
|------|-------|--------|----------|
| 部署复杂度 | 纯库，需自建服务 | 需 Docker/ K8s | `pip install` 即可 |
| 持久化 | 需手动序列化 | 自带 | PersistentClient 自动落盘 |
| Metadata 过滤 | 不支持 | 支持 | 原生支持 `where=` 过滤 |
| 适用规模 | 百万~亿级 | 亿级+ | 万~十万级 |
| 运维成本 | 高 | 高 | 零 |

本项目选 ChromaDB 的原因：
- 单机知识库场景，文档量在千级，不需要分布式
- `PersistentClient(path="./chroma_data")` 一行代码搞定持久化
- 支持 `where={"document_id": doc_id}` 按条件删除，配合文档管理

**HNSW (Hierarchical Navigable Small World) 原理**：

HNSW 是多层图结构：
1. **底层**：包含所有节点，连接密集，保证召回率
2. **上层**：稀疏采样，长距离边，"高速公路"跳转
3. **检索时**：从顶层开始贪心搜索，逐层下降到底层，复杂度 O(log N)
4. **与 NSW 的区别**：分层结构使检索从 O(N) 降到 O(log N)，类似跳表的思想

本项目配置 `hnsw:space=cosine`（`vector_store.py:23-25`），使用余弦相似度而非欧氏距离，更适合文本语义匹配。

---

### 3. Reranker 的作用是什么？为什么不能只用 embedding 相似度？

**核心区别：Bi-encoder vs Cross-encoder**

| | Bi-encoder (Embedding) | Cross-encoder (Reranker) |
|------|------|------|
| 工作方式 | Query 和 Doc 分别编码，然后算相似度 | Query 和 Doc 拼接后一起送进模型 |
| 交互 | 无交互，各自独立 | 全交互，token-level 交叉注意力 |
| 速度 | 极快（向量已预计算） | 慢（每次配对都要推理） |
| 精度 | 一般 | 高 |
| 适用 | 全量召回 (粗筛) | Top-K 精排 |

**为什么不能只用 Embedding**：
- Embedding 将文档压缩为一个固定向量，不可避免有信息损失
- 相似度是全局语义匹配，可能把"讲 Python 性能"和"讲 Python 语法"都打高分
- Cross-encoder 逐 token 交叉注意力，能捕捉精确的语义匹配关系

**本项目实现** (`reranker_service.py:32-62`)：
```python
# BGE-Reranker v2-m3，对粗筛结果逐对打分
pairs = [[question, doc] for doc in documents]
scores = self._model.compute_score(pairs, normalize=True)
# 按分数降序排列，截取 top_k
```

配置 `RERANK_ENABLED=false` 可直接跳过，避免无 GPU 环境阻塞。Reranker 惰性加载（首次调用才下载约 2.1 GB 权重，落在项目内 `models/bge-reranker-v2-m3/`），加载失败自动 fallback 原始排序。

**实测记录**（`RERANK_ENABLED=true`，纯 CPU 推理，5 条示例候选）：原本排在向量检索第 4 位的「RAG 系统通常先用向量检索召回候选，再用 reranker 做精排」被提到第 1（score 0.9603），而余弦相似度最高、但语义无关的「今天天气不错，适合出门散步」被挤出 top 3（score 0.0125）。单次 5 对候选推理约 0.8~1.2 秒。

---

### 4. 文本切块的 chunk_size=1000、overlap=200 是怎么定的？有什么 trade-off？

**取值来源** (`config.py:23-24`)：
```python
chunk_size: int = 1000      # 每块约 1000 字符
chunk_overlap: int = 200    # 相邻块重叠 200 字符
```

**Trade-off 分析**：

| 维度 | chunk_size 小 (如 256) | chunk_size 大 (如 2000) |
|------|------|------|
| 语义完整性 | 差，一个概念可能被切碎 | 好，上下文完整 |
| 检索精度 | 高，返回精准片段 | 低，包含无关内容 |
| LLM 上下文消耗 | 少，同窗口可放更多 chunk | 多，占用 Token |
| Embedding 质量 | 片段太短，向量语义弱 | 片段合适，语义表达好 |

**1000 + 200 的选择逻辑**：
- 1000 字符 ≈ 300-500 中文词，是一个"段落级"的语义单元，足够承载一个完整概念
- 200 重叠 (20%) 防止关键句刚好落在切分边界被截断
- 分隔符优先级设置为 `["\n\n", "\n", "。", ".", " ", ""]`（`chunking_service.py:10`），优先在自然段落/句子边界切分，减少生硬截断

**实际调试经验**：如果发现回答"漏掉"文档中的关键信息，优先怀疑 overlap 太小导致关键句被切在边界；如果回答"答非所问"，优先怀疑 chunk_size 太大导致检索到不相关段落。

---

### 5. 如果检索出来的上下文不相关，怎么处理？

本项目采用**多层降级策略**：

1. **Reranker 重排序**（第一道防线）：Cross-encoder 把不相关的候选推到后面，`relevance_score` 可通过阈值过滤（当前项目未硬过滤，而是保留所有 top_k 给 LLM）

2. **RAG System Prompt 指令约束** (`chat_service.py:13-18`)：
   ```
   If the context does not contain enough information to answer the question,
   say "根据已有文档无法回答此问题。" Do not make up information.
   ```
   这条约束强制 LLM 在上下文不相关时诚实告知，而非编造。

3. **Agent 模式的 fallback**（`agent_service.py:34-51` System Prompt）：
   - 知识库无结果 → 自动触发 `search_web` 联网搜索
   - 联网搜索也无结果 → 诚实告知 + 允许从自身知识回答

4. **可进一步优化的方向**（当前未实现）：
   - 设置 relevance_score 阈值（如 < 0.3 直接丢弃）
   - Query Rewriting：在检索前先改写/扩展用户问题
   - 用户反馈 "不满意" 按钮，收集低质量 case 用于调优

---

## Agent & Tool Calling

### 6. ReAct 模式是什么？你的 Agent 的循环终止条件是什么？

**ReAct (Reasoning + Acting)** 是让 LLM 交替进行"思考→行动→观察"的 Agent 范式：
- **Reasoning**：分析当前状态，决定下一步做什么
- **Acting**：调用工具执行具体操作
- **Observation**：接收工具返回结果，进入下一轮推理

**本项目实现** (`agent_service.py:330-381`)：
```python
for _ in range(max_iterations):        # 最多 5 轮
    response = llm.chat(messages, tools=TOOLS)
    msg = response.choices[0].message
    
    if msg.tool_calls:                 # LLM 选择调工具
        for tc in msg.tool_calls:
            result = execute_tool(tc)
            messages.append(tool_result)   # 追加到上下文
    else:                              # LLM 选择直接回复
        final_answer = msg.content
        break
```

**循环终止条件**：
1. **finish_reason ≠ "tool_calls"**：LLM 输出 content 而非 tool_call，认为任务完成
2. **达到 max_iterations**：默认 5 轮（`config.py:36`），超限后返回 "抱歉，Agent 在最大迭代次数内未能完成推理"
3. **异常退出**：LLM API 调用失败 → 返回 "AI 服务暂时不可用"

**为什么是 5 轮**：大多数问题 1-2 轮工具调用即可回答（知识库搜一次，或联网搜一次），5 轮留足 buffer 应对 "KB 无结果 → 联网搜索" 的 fallback 场景。更多轮次增加延迟和 API 费用，ROI 低。

---

### 7. Function Calling 的协议是什么样的？你怎么把工具定义传给 LLM？

**OpenAI Function Calling 协议**本质是让 LLM 输出结构化的 JSON 来"调用函数"，而非直接输出文本。

**工具定义格式**（以 `search_web` 为例，`web_search_tool.py:62-83`）：
```json
{
  "type": "function",
  "function": {
    "name": "search_web",
    "description": "搜索互联网获取最新信息...",
    "parameters": {
      "type": "object",
      "properties": {
        "query": {
          "type": "string",
          "description": "要在互联网上搜索的关键词"
        }
      },
      "required": ["query"]
    }
  }
}
```

**传给 LLM 的方式** (`agent_service.py:233-237`)：
```python
response = self.llm_client.chat.completions.create(
    model=self.model,
    messages=messages,
    tools=self.tools,      # ← 工具列表作为 tools 参数传入
    temperature=temperature,
    stream=True,
)
```

**LLM 返回 tool_call → 执行工具 → 追加结果到 messages**：
```python
# LLM 返回后，追加 assistant 消息（含 tool_calls）
messages.append({"role": "assistant", "content": None,
                 "tool_calls": [{"id": tc_id, "type": "function",
                                 "function": {"name": ..., "arguments": ...}}]})
# 追加 tool 消息（含执行结果）
messages.append({"role": "tool", "content": result_text, "tool_call_id": tc_id})
```

注意：DeepSeek Chat 兼容 OpenAI SDK，直接用 `openai.OpenAI` 客户端，`base_url` 指向 `https://api.deepseek.com`。

---

### 8. Agent 什么时候选知识库检索，什么时候选联网搜索？

决策权在 **LLM**，通过 System Prompt 给出规则指导 (`agent_service.py:34-51`)：

```
1. 纯问候/闲聊（"你好"、"hi"）→ 跳过工具，直接回复
2. 事实、知识、概念、数据等 → 必须先调工具
   优先 search_knowledge_base
3. 知识库无结果，或问题明显需要最新信息 → 调 search_web
   （天气、新闻、股价、当前事件等）
4. 两个工具都没结果 → 诚实告知 + 可从自身知识回答
```

**关键设计：Tool Registry 模式** (`agent_service.py:94-98`)
```python
self._tool_handlers = {
    "search_knowledge_base": self._run_kb_search,
    "search_web": self._run_web_search,
}
```
新增工具只需注册 handler + 添加 tool schema，ReAct 循环无需修改。

**如果 Tavily API Key 未配置** (`agent_service.py:58-61`)：
```python
def _build_tools(tavily_configured):
    if tavily_configured:
        return [KB_TOOL, WEB_TOOL]
    return [KB_TOOL]        # 只有知识库工具
```
自动降级为纯 KB Agent。

---

### 9. 如果 Tool Calling 的 JSON 参数解析失败怎么处理？

**容错设计** (`agent_service.py:68-72`)：
```python
def _parse_tool_args(tool_args: str) -> dict:
    try:
        return json.loads(tool_args)
    except (json.JSONDecodeError, TypeError):
        return {}    # 解析失败返回空 dict，不崩溃
```

返回空 `{}` 后，`_execute_tool` 会 fallback 使用用户原始问题作为 query：
```python
query = args.get("query", args.get("question", question))
#                                                   ↑ fallback 到原始问题
```

**为什么这样做**：DeepSeek 偶尔会输出非标准 JSON（如参数值含未转义引号）。返回 `{}` 比直接崩溃好——至少用户原始问题还能作为搜索关键词执行一次检索。

---

### 10. Agent 的最大迭代次数设多少？为什么？

**当前配置：5** (`config.py:36`：`agent_max_iterations: int = 5`)

**决策逻辑**：
- 绝大多数有效问题 1-2 轮即可完成（知识库搜一次，或联网一次）
- 3-4 轮覆盖 "KB 无结果 → 联网搜索" 或 "用户追问→二次检索"
- 5 轮是安全阈值——超过这个数通常是 LLM 陷入幻觉式工具调用循环
- 每多一轮 = 一次额外 LLM API 调用 + 延迟 2-5 秒，成本递增

**超限处理** (`agent_service.py:377-378`)：
```
最终回答："抱歉，Agent 在最大迭代次数内未能完成推理。"
```
同时在 stderr 输出日志，方便后端监控异常循环。

---

## 系统设计

### 11. 你的多知识库是怎么做到数据隔离的？

**双层隔离机制**：

**1. ChromaDB 层 — Collection 隔离**：
```python
# 每个知识库对应一个独立 ChromaDB Collection
# collection_name = f"kb_{kb_id}"
collection = client.get_or_create_collection(f"kb_{kb_id}")
```
每个 Collection 有自己的 HNSW 索引，检索时只查对应 Collection，不同知识库的向量物理隔离。

**2. SQLite 层 — 外键关联** (`database.py:52-109`)：
```sql
documents.kb_id → knowledge_bases.id (CASCADE DELETE)
conversations.kb_id → knowledge_bases.id (CASCADE DELETE)
messages.conversation_id → conversations.id (CASCADE DELETE)
```

所有查询带上 `kb_id` 过滤，删除知识库时级联删除关联的文档、会话、消息。

**3. 默认知识库不可删除**（Router 层保护）：确保系统始终至少有一个可用知识库。

---

### 12. 为什么要用 SQLite WAL 模式？

**WAL (Write-Ahead Logging) 的核心思想**：写操作先追加到 WAL 文件（顺序写），后台在 checkpoint 时合并回主数据库文件。读操作需要同时考虑主文件和 WAL 中尚未合并的最新提交，从而**不需要等待写事务结束**，实现读写并发。

**本项目配置** (`database.py:18-19`)：
```python
conn.execute("PRAGMA journal_mode=WAL")
conn.execute("PRAGMA busy_timeout=5000")
```

**为什么需要 WAL**：
- **读写并发**：默认（rollback journal）模式下 SQLite 写时阻塞所有读。WAL 模式下写操作追加到 WAL 文件，读操作读取「主文件 + WAL 未合并部分」的一致快照，读写互不阻塞，**多读单写**
- **SSE 流式场景**：Agent 回答时，流式线程在写消息，HTTP 请求可能在读会话列表，WAL 保证互不等待
- **busy_timeout=5000**：遇到锁时等待最多 5 秒而非立即报错，减少并发冲突

**局限**：SQLite 毕竟是嵌入式数据库，WAL 只支持单机并发。如果需要多实例部署，需要迁移到 PostgreSQL。

---

### 13. 会话记忆是怎么实现的？历史消息怎么注入 LLM？

**实现** (`chat_service.py:50-66`)：
```python
# 1. 从 messages 表加载最近 N 条历史
history_msgs = self.msg_repo.list_recent(conversation_id, MAX_HISTORY_MESSAGES=20)

# 2. 构建 LLM messages 列表
llm_messages = [{"role": "system", "content": SYSTEM_PROMPT}]

# 3. 注入历史（带过滤）
for msg in history_msgs:
    if role not in ("user", "assistant"):
        continue   # 跳过 tool/system/function 角色
    if msg.content starts with "[调用工具" or "[工具返回":
        continue   # 跳过 Agent 模式产生的工具调用占位文本
    llm_messages.append({"role": role, "content": content})

# 4. 追加当前问题 + Context
llm_messages.append({"role": "user", "content": f"Context:\n\n{context}\n\nQuestion: {question}"})
```

**关键过滤逻辑**：
- **RAG 模式**：过滤 `tool`/`system`/`function` 角色的消息，过滤 `[调用工具]`/`[工具返回]` 占位文本
- **Agent 模式**：过滤同上，注入最多 40 条（因为 Agent 本身需要工具调用轮次，给更多上下文空间）
- **过滤动机**：OpenAI 协议要求 `tool` 角色的消息必须携带 `tool_call_id`。我们从 DB 读出来的是自定义的占位文本记录，没有该字段，直接注入会导致 API 返回 **400 Bad Request** —— 所以必须先按角色白名单（只保留 `user`/`assistant`）过滤掉。

> 这一点在 Agent 路径上曾是真实 bug：`_build_messages` 最初只过滤了 assistant 的占位文本，漏掉了 `role="tool"` 的消息，导致同一会话第二轮提问时 API 400。现在两条路径统一为「只保留 `user`/`assistant`」。

**为什么是 20 条而不是更多**：DeepSeek 上下文窗口 64K token，20 条消息 + Context + 回答绰绰有余。更多历史对延迟和费用不划算。

---

### 14. SSE 和 WebSocket 的区别？你为什么选 SSE？

| 维度 | SSE | WebSocket |
|------|-----|-----------|
| 通信方向 | 单向（服务端 → 客户端） | 双向（全双工） |
| 协议 | HTTP（标准、简单） | 独立协议 `ws://`（需升级握手） |
| 重连 | 浏览器自动重连 | 需手动实现 |
| 穿透代理/防火墙 | 天然兼容 HTTP 代理 | 可能被企业防火墙拦截 |
| 实现复杂度 | 极低，`text/event-stream` | 较高，需 WebSocket 库 |
| 适用场景 | 实时推送（通知、日志、AI 流式输出） | 双向实时（聊天、游戏、协作编辑） |

**选 SSE 的理由**：
1. Agent 回答是**单向流式推送**（服务端推 token，客户端接收），不需要客户端主动发消息
2. 前端实现极简 — `ReadableStream` 消费 `response.body`，逐行解析 `event:` / `data:`
3. `StreamingResponse` 直接返回同步生成器，FastAPI 原生支持，无需额外库
4. 代理/防火墙兼容性好，企业环境也能用

**本项目实现** (`conversations.py:248-262`)：
```python
return StreamingResponse(
    agent_service.ask_stream(...),
    media_type="text/event-stream",
    headers={
        "Cache-Control": "no-cache",
        "Connection": "keep-alive",
        "X-Accel-Buffering": "no",   # 禁用 Nginx 缓冲
    },
)
```

---

### 15. 你的项目怎么处理高并发？当前方案的瓶颈在哪？

**当前的并发策略**：

| 层面 | 方案 |
|------|------|
| Web 框架 | FastAPI + Uvicorn |
| 阻塞调用的处理 | **非流式端点一律用同步 `def`**，由 Starlette 自动丢进线程池执行（见下方说明） |
| 数据库 | SQLite WAL 模式 + `busy_timeout=5000` |
| 线程安全 | `threading.local()` 连接隔离，每线程独立连接 |
| 写事务 | 单连接 + 单 `commit()`，保证原子性 |

**为什么端点用 `def` 而不是 `async def`**：

项目的底层调用**全部是同步阻塞**的 —— OpenAI 同步客户端、`sqlite3`、`chromadb`、`requests`。如果把这类代码放进 `async def`，会直接占住事件循环，**比写成 `def` 更糟**：写成 `def` 时 Starlette 会自动把它调度到线程池，反而能并发。

所以除了两个例外，所有端点都是 `def`：
- `upload.py` 的 `upload_file`：函数体里有 `await file.read()`，必须保持 `async def`
- `conversations.py` 的 `conversation_agent_stream`：返回 `StreamingResponse`，传入的是同步生成器，Starlette 会用 `iterate_in_threadpool` 包装，本身安全

**这也是我踩过的坑**：一开始所有端点都写成 `async def`，觉得"异步框架就该全异步"，后来发现同步 SDK 会阻塞事件循环，才统一改成 `def`。要真正全链路异步，得换成 `httpx.AsyncClient` + `aiosqlite` 这类异步驱动。

**瓶颈分析**：

| 瓶颈 | 说明 | 优先级 |
|------|------|--------|
| **LLM API 延迟** | DeepSeek 单次调用 2-5 秒（流式），这是最大延迟来源 | 无法优化，换更快模型或加缓存 |
| **SQLite 写锁** | WAL 虽允许多读单写，但极端并发下写操作仍会排队 | 中 |
| **Embedding API** | Qwen 批量 embedding 有速率限制 | 中 |
| **Reranker 推理** | CPU 推理 BGE-Reranker，单次约 0.5-1 秒 | 可 GPU 加速 |
| **ChromaDB 单机** | PersistentClient 不支持分布式 | 万级文档量还好 |

**如果要支撑高并发**：
1. SQLite → PostgreSQL（去掉写锁瓶颈）
2. 引入 LLM 响应缓存（相同问题直接返回缓存）
3. Embedding 预计算 + 缓存，减少 API 调用
4. ChromaDB → Milvus/Qdrant 分布式部署
5. FastAPI 前加 Nginx 反向代理 + 负载均衡
6. Uvicorn workers 设置 `--workers 4`

---

## 工程实践

### 16. 你的 Service / Repository 分层是怎么设计的？为什么这么做？

**分层架构** (Router → Service → Repository)：

```
Router (conversations.py)
  │  处理 HTTP 请求/响应、参数校验、依赖注入
  │
  ▼
Service (agent_service.py / chat_service.py / rag_pipeline.py)
  │  业务逻辑、LLM 调用、RAG 管线、Agent 循环
  │
  ▼
Repository (conv_repo.py / msg_repo.py / kb_repo.py / doc_repo.py)
  │  数据持久化、SQL 查询、CRUD 操作
  │
  ▼
Database (database.py)
    连接管理、表结构、Schema 迁移
```

**为什么要分层**：
1. **关注点分离** — Router 不关心 SQL 怎么写，Repository 不关心 HTTP 头怎么设
2. **可测试性** — 可以 mock Repository 来单独测试 Service 逻辑
3. **可替换性** — 如果要从 SQLite 换 PostgreSQL，只改 Repository 层，Service 层不动
4. **依赖注入** — FastAPI `Depends()` 在 Router 层注入依赖，Service 层不关心对象从哪来

---

### 17. Pydantic Settings 相比直接 `os.getenv` 有什么优势？

**直接对比**：

```python
# os.getenv 方式
api_key = os.getenv("DEEPSEEK_API_KEY")           # 返回 str | None，无校验
timeout = int(os.getenv("TIMEOUT", "30"))          # 手动类型转换，可能抛异常

# Pydantic Settings 方式 (config.py)
class Settings(BaseSettings):
    deepseek_api_key: str = ""                     # 类型安全
    agent_max_iterations: int = 5                  # 有默认值
    chunk_size: int = 1000                         # IDE 有自动补全

settings = Settings()                              # 自动从 .env 加载
```

**优势**：

| 特性 | os.getenv | Pydantic Settings |
|------|------|------|
| 类型校验 | 无，需手动转换 | 自动，声明即类型 |
| 默认值 | 手动写第二个参数 | 声明时 `= default` |
| IDE 支持 | 无 | 自动补全、跳转定义 |
| .env 加载 | 需手动 `load_dotenv()` | 自动（`env_file=".env"`） |
| 集中管理 | 散落各处 | 一个 `Settings` 类 |
| 校验失败 | 运行时才发现 | 启动时立即报错 |

---

### 18. 你怎么处理 LLM API 调用失败的情况？

**分层异常处理**：

**1. LLM 调用层** (`agent_service.py:238-241`)：
```python
try:
    stream = self.llm_client.chat.completions.create(...)
except Exception:
    print(f"[Agent Stream] LLM call failed:", file=sys.stderr)
    traceback.print_exc()
    yield _format_sse("error", {"message": "LLM 调用失败"})
    return    # 终止流式输出
```

**2. Embedding 调用层** (`embedding_service.py:25-28`)：
```python
try:
    response = self.client.embeddings.create(...)
except Exception as e:
    raise EmbeddingAPIError(f"Embedding API call failed: {e}") from e
```
`EmbeddingAPIError` → FastAPI `exception_handler` → HTTP 502 JSON 响应。

**3. Agent 非流式模式** (`agent_service.py:344-348`)：
```python
except Exception:
    final_answer = "抱歉，AI 服务暂时不可用，请稍后重试。"
    break    # 优雅降级，不崩溃
```

**4. Agent 流式中断保护** (`agent_service.py:318-326`)：
```python
finally:
    if not finalized:
        # 保存已生成的 partial answer，不让用户白等
        self.msg_repo.add(conversation_id, "assistant", partial, ...)
```

**未实现但可考虑的**：
- 指数退避重试（Exponential Backoff）
- 断路器（Circuit Breaker）：连续 N 次失败后暂停一段时间
- 多模型 fallback：DeepSeek 不可用时切到备用模型

---

### 19. Schema 迁移是怎么自动触发的？会不会丢数据？

**自动检测 + 安全迁移** (`database.py:26-46`)：

```python
def _migrate_messages_schema(conn):
    row = conn.execute(
        "SELECT sql FROM sqlite_master WHERE type='table' AND name='messages'"
    ).fetchone()
    # 检测旧版 CHECK 约束（只允许 user/assistant）
    if row and "role IN ('user', 'assistant')" in row[0]:
        # 迁移前先做文件级备份
        backup = db_path.with_name(f"{db_path.name}.bak-{timestamp}")
        shutil.copy2(db_path, backup)
        # 四步迁移，整体包在显式事务里
        conn.executescript("""
            BEGIN IMMEDIATE;
            CREATE TABLE messages_new (...);  -- 1. 建新表（扩展 role 约束）
            INSERT INTO messages_new SELECT * FROM messages;  -- 2. 数据迁移
            DROP TABLE messages;                              -- 3. 删旧表
            ALTER TABLE messages_new RENAME TO messages;      -- 4. 重命名
            COMMIT;
        """)
```

**会不会丢数据**：

- **流程上不会**：`INSERT INTO messages_new SELECT * FROM messages` 全量复制后再删旧表
- SQLite 不支持 `ALTER TABLE ... ALTER CONSTRAINT`，所以用 "建新表→搬数据→删旧→重命名" 的经典模式
- `init_db()` 在应用启动时（`lifespan`）自动执行，用户无感知
- 新部署的数据库 `CREATE TABLE IF NOT EXISTS` 直接建新表，不走迁移

**这里有个必须讲清楚的风险点**：

`DROP TABLE` 和 `ALTER TABLE ... RENAME` 之间存在一个**窗口期** —— 如果进程恰好在此时挂掉，旧表已删、新表还没改名，数据就真丢了。

原因有两层：
1. `executescript()` 会先隐式提交一次；
2. Python `sqlite3` 默认隔离级别下，**DDL 语句不参与隐式事务**（只有 INSERT/UPDATE/DELETE 会），所以这三条 DDL 原本是各自独立执行的。

**修复方式**（已落地）：
- SQLite 本身**支持事务性 DDL**，只要显式写 `BEGIN IMMEDIATE; ... COMMIT;` 包住整个脚本，迁移就是原子的；
- 额外在迁移前做一次数据库文件备份（`*.bak-<时间戳>`），异常时 `ROLLBACK` 并抛出。

面试时这样答更稳：「流程上是全量复制不丢数据，但原来的实现缺少原子性保护，我已经用 `BEGIN IMMEDIATE` 包住并加了迁移前备份」—— 比直接说"不会丢数据"经得起追问。

---

### 20. 如果要把这个项目部署到服务器，你会怎么做？

**已完成的 Docker 部署方案**：

```bash
# 一键启动
docker compose up -d
```

**3 个持久化卷** → 删容器不丢数据：
- `./data:/app/data` → SQLite 数据库
- `./chroma_data:/app/chroma_data` → 向量索引
- `./models:/app/models` → Reranker 模型缓存

**生产环境增强建议**：

```
                        ┌─────────────┐
                        │  Nginx      │  ← 反向代理 + HTTPS + 限流
                        └──────┬──────┘
                               │
                  ┌────────────┼────────────┐
                  ▼            ▼            ▼
           ┌──────────┐ ┌──────────┐ ┌──────────┐
           │ uvicorn  │ │ uvicorn  │ │ uvicorn  │  ← 多 worker
           │ worker 1 │ │ worker 2 │ │ worker N │
           └──────────┘ └──────────┘ └──────────┘
                  │            │            │
                  └────────────┼────────────┘
                               │
                        ┌──────▼──────┐
                        │  SQLite     │  ← 或迁移到 PostgreSQL
                        │  ChromaDB   │
                        └─────────────┘
```

**步骤清单**：
1. 配置 `.env` 填入生产 API Key
2. Nginx 配置 SSL 证书（Let's Encrypt）+ `proxy_pass http://app:8080`
3. 配置 `X-Accel-Buffering: no` 确保 SSE 流式不被缓冲
4. 设置 `restart: unless-stopped`（已配置）
5. 配置日志收集（`docker compose logs -f` 或接入 ELK）
6. 监控：`/health` 端点 + Uptime Kuma / Prometheus

---

## 深入思考

### 21. BGE-Reranker 是 Cross-encoder，为什么不能直接用它做全量检索？

**复杂度分析**：

| 方法 | 计算量 | 时间复杂度 |
|------|------|------|
| Bi-encoder (Embedding) | 对每个 doc 做一次推理，**向量可离线预计算并缓存** | 建库 O(N)；查询时仅需为 query 编码一次 + 向量检索 O(log N) |
| Cross-encoder (Reranker) | 必须对每个 (query, doc) 对做一次完整推理，无法预计算 | 每次查询 O(N) |

**举例**：假设知识库有 1000 个 chunk，单次 Cross-encoder 推理 0.1 秒。

- **Bi-encoder 粗筛 + Cross-encoder 精排**：Embedding 检索不到 0.01 秒，Reranker 对 top_k×3=12 个候选打分 = 1.2 秒
- **纯 Cross-encoder 全量检索**：1000 × 0.1 = 100 秒

这就是经典的 **"召回→精排" 两阶段架构**：用快速的 Bi-encoder 把候选从 1000 缩小到 12，再用慢但准的 Cross-encoder 精选出 top 4。

---

### 22. 你的 Embedding 是调 API 的，如果网络超时或限流怎么处理？

**当前防护**：

1. **包装异常为 `EmbeddingAPIError`** (`embedding_service.py:25-28`) → HTTP 502 返回给前端
2. **超时控制**：`openai-python` v1 的默认超时是 **600 秒**（`openai._constants.DEFAULT_TIMEOUT`），对交互式问答来说太长。项目在阻塞风险高的地方（`/health`）显式设成 5 秒 + `max_retries=0`，避免上游异常时长时间挂住；业务链路后续也应显式传入合理的 timeout
3. **批量处理** (`embedding_service.py:18-19`)：每批 20 条，减少 API 调用次数

**可考虑的增强**：

| 策略 | 实现 |
|------|------|
| **指数退避重试** | 失败后 1s → 2s → 4s 重试，最多 3 次 |
| **本地模型备选** | 配置 `sentence-transformers` 本地模型作为 fallback |
| **限流感知** | 捕获 429 错误，读取 `Retry-After` 头，按指示等待 |
| **缓存热门查询** | Redis 缓存常见问题的 embedding，减少重复 API 调用 |

当前项目面向单机/小团队场景，API 限流风险低，所以保持简单处理。

---

### 23. 如果知识库有 10 万篇文档，ChromaDB 还够用吗？你会怎么优化？

**ChromaDB 在 10 万篇场景的问题**：

假设每篇 50 个 chunk，10 万 × 50 = **500 万向量**。ChromaDB PersistentClient 的 HNSW 索引全在内存，500 万 × 1024 维 × 4 字节 ≈ 20GB，单机内存可能吃紧。

**优化方案（按优先级）**：

1. **混合检索 (Hybrid Search)**：BM25 关键词 + 向量语义融合。先用 BM25 做关键词初筛，再向量精排
2. **分库/分区**：按知识库或文档类别拆分为多个 Collection，检索时先确定范围
3. **迁移到 Milvus/Qdrant**：支持分布式索引 + 磁盘索引（DiskANN），10 亿级向量无压力
4. **分层索引**：热门文档走内存 HNSW，冷门文档走磁盘索引
5. **摘要检索**：对大文档先生成摘要，检索摘要而非全量 chunk
6. **查询缓存**：相同/相似问题直接返回缓存结果

**ChromaDB 的适用边界**：单 Collection 百万级向量以下表现良好，超过则建议迁移。

---

### 24. 你这个系统有没有做用户认证和多租户？如果需要怎么加？

**当前状态**：无用户认证，单租户模式。

**加多租户的方案**：

**方案 A：JWT + 中间件（推荐）**

```
用户登录 → 返回 JWT Token → 前端每次请求带 Authorization Header
→ FastAPI 中间件验证 JWT → 从 Token 提取 user_id
→ 所有 DB 查询加 user_id 过滤
```

**关键改动**：

| 层 | 改动 |
|------|------|
| 数据库 | 所有表加 `user_id` 列 + 索引 + FK |
| 知识库 | `kb.user_id` 隔离，用户 A 看不到用户 B 的知识库 |
| 中间件 | `Depends(get_current_user)` 注入当前用户 |
| 路由 | 所有端点加 `current_user: User = Depends(get_current_user)` |
| .env | 加 `JWT_SECRET_KEY`、`JWT_EXPIRE_MINUTES` |

**为什么不用 Session**：RESTful API + SPA 前端，JWT 是无状态的，不需要服务端存 Session。

**ChromaDB 层隔离**：Collection 名称变为 `kb_{user_id}_{kb_id}`，物理隔离。

---

### 25. 如果让你重新设计这个项目，你会有什么不同的选择？

**坦诚反思**：

1. **SQLite → PostgreSQL**：一开始觉得单机 SQLite 够用，但随着事务复杂度增加（多表写入原子性），PostgreSQL 的真正的 `BEGIN...COMMIT` 事务+ 行级锁会更优雅

2. **ChromaDB → Qdrant**：ChromaDB 的 `PersistentClient` 在并发 + delete 场景下偶发不稳定（Collection 突然找不到），Qdrant 的 gRPC API + 磁盘索引更成熟

3. **提前引入结构化日志**：`print(f"...", file=sys.stderr)` 在调试时够用，但生产环境需要 `structlog` + JSON 格式日志 + 链路追踪 ID

4. **API 设计更 RESTful**：当前 `/api/conversations/{id}/qa` 和 `/api/conversations/{id}/agent` 是 RPC 风格，更好的做法可能是 `/api/conversations/{id}/messages` 统一消息端点

5. **增加测试**：项目开发时优先赶功能，单元测试只覆盖了一部分。目前有的是 `test_runner.py` 接口级测试脚本和 `TEST_CHECKLIST.md` 手工用例清单，但缺少 pytest 单元测试和 CI。重新来会从 Day 1 就写 pytest + pytest-asyncio 集成测试

6. **前端框架**：原生 HTML/JS 对 MVP 足够，但交互复杂后（多知识库切换、工具调用可视化）可以考虑 Vue/React

**但保留的设计**：
- 分层架构 (Router→Service→Repository) ✓
- Tool Registry 模式 ✓
- Pydantic Settings 集中配置 ✓
- 非 LangChain 实现 Agent ✓（面试能讲清楚每一行）

---

## 场景题

### 26. 用户问"总结一下这份 PDF"，但 PDF 有 200 页，你的系统会怎么处理？

**当前行为**：

200 页 PDF → `PyMuPDF` 逐页提取 → `RecursiveCharacterTextSplitter` 分块 → N 个 chunk 存入 ChromaDB

用户问"总结"时：
1. 问题 "总结一下这份 PDF" 转 embedding
2. ChromaDB 返回 top_k × 3 个最相关的 chunk（大约 12 个片段）
3. 格式化后注入 LLM → LLM 基于这些片段生成"总结"

**问题**：12 个 chunk 只能覆盖 PDF 的小部分，总结不完整。

**改进方案**：

| 方案 | 做法 | 适用 |
|------|------|------|
| **Map-Reduce** | 每个 chunk 单独总结 → 合并所有总结 → LLM 二次总结 | 适合概括全文 |
| **Refine** | 逐段总结，每次用前一段总结 + 新 chunk 生成更新后的总结 | 质量更高，但串行慢 |
| **分层总结** | 先总结每页 → 总结每章 → 总结全文 | 适合有结构的文档 |

**最实用的实现**（对本项目改动最小）：
1. 检测到"总结全文"类问题时，不从向量库检索，而是直接拿到文档的所有 chunk
2. Map 阶段：每 10 个 chunk 一批，并行生成段落总结
3. Reduce 阶段：拼接所有段落总结，生成最终总结
4. 按 `chunk_size=1000` 字符估算，中文 200 页 PDF 约产生 **200 个左右** chunk（一页约 500-600 字），每批 10 个需 20 次 Map + 1 次 Reduce，约 1 分钟

**另外要注意的坑**：每个 chunk 的页码是按它在全文中的位置线性折算的估算值（`upload.py:28-46` `_estimate_chunk_pages`），不是真实页号 —— 页边界在切块前就丢失了。文档级的总页数是真实的：PDF 取 `len(pages)`（`pdf_service.py:18`），DOCX 取 `docProps/app.xml` 的 `<Pages>` 节点（`word_service.py`），因为 DOCX 正文里根本不含分页信息（分页是排版渲染的结果）。要精确定位到页，需要改造解析层让它逐页返回 `(页码, 文本)` 并逐页切块。

约定：`page == 0` 表示该来源没有页码概念（联网搜索结果）或页数不可知，前端此时不展示页码。

---

### 27. 如果你发现 RAG 回答质量不好，你会从哪些方面排查？

**排查清单（从数据到模型，逐步排查）**：

```
问题表现              可能原因               排查方法
──────────────────────────────────────────────────────────
回答"胡编乱造"   →   检索结果不相关       →   检查 top_k 个 chunk 的内容是否与问题相关
                  →   System Prompt 太弱   →   加强 "不要编造信息" 约束
                  →   temperature 太高     →   降到 0.1~0.3

回答"答非所问"   →   chunk 被截断          →   检查 chunk_size / overlap
                  →   分隔符不合理         →   检查切分边界是否在句子中间

回答"漏掉信息"   →   top_k 太小            →   增大 top_k → 更多候选
                  →   Reranker 过度过滤    →   检查被 reranker 丢弃的文档是否相关
                  →   overlap 太小          →   增大 overlap，防止关键信息在边界

回答"过于泛泛"   →   没有精排             →   开启 Reranker
                  →   embedding 质量差     →   换更好的 embedding 模型

检索慢          →   向量库索引效率        →   ChromaDB query 耗时统计
                  →   Embedding API 延迟   →   embed_query 耗时统计
```

**实操步骤**：
1. 先用 `POST /api/qa` 测试同一问题，观察返回的 `sources` 列表的相关性
2. 在 `rag_pipeline.py` 中加 `print` 打日志，看粗筛返回了什么、精排后保留了什么
3. 手动构造几条明显的问答对（你知道文档里写了什么），验证检索能否找回
4. 对比 Reranker 开关对质量的影响
5. 调整 `CHUNK_SIZE` / `CHUNK_OVERLAP` 并重新上传测试

---

### 28. 如何评估 RAG 系统的回答质量？你有没有做过评估？

**主流评估框架**：

| 指标 | 含义 | 评估方法 |
|------|------|------|
| **Faithfulness（忠实度）** | 回答是否严格基于检索到的上下文，有无编造 | LLM 逐句比对 answer ↔ context |
| **Answer Relevance（答案相关性）** | 回答是否切题 | LLM 根据 answer 反向生成问题，看与原始问题的相似度 |
| **Context Recall（上下文召回率）** | 检索到的上下文是否覆盖了参考答案所需信息 | 比对 ground truth ↔ retrieved context |
| **Context Precision（上下文精确率）** | 检索到的上下文是否都是相关的，有无噪声 | 相关 chunk 在 top_k 中的排名 |

**RAGAS 框架** (`pip install ragas`) 自动化计算以上指标：
```python
from ragas import evaluate
from ragas.metrics import faithfulness, answer_relevancy, context_recall

result = evaluate(dataset, metrics=[faithfulness, answer_relevancy, context_recall])
```

**本项目当前状态**：未集成自动化评估，但有较完整的**手工测试资产**：

- `test_runner.py`（693 行）：可执行的接口级测试脚本
- `TEST_CHECKLIST.md`：8 大类约百条带编号用例，覆盖知识库管理（TC-KB）、文档上传（TC-UP）、RAG 问答（TC-RAG）、会话管理（TC-CONV）、Agent（TC-AG）、联网搜索（TC-WS）、来源展示（TC-SRC）、Rerank（TC-RR）
- `sources` 中的 `relevance_score`（含 `score_type` 区分量纲）作为检索质量的间接指标
- 后续计划（见 README roadmap）：集成 RAGAS 自动化评估

**评估最佳实践**：
1. 准备 50-100 条标注的 ground truth 问答对
2. 每次改动后跑 RAGAS 评估，对比指标变化
3. 建立评估基线（baseline），新 PR 不能低于基线
4. 定期人工抽检低分 case，分析根因

> 诚实说明：目前的验证是「用例覆盖 + 人工判断」，缺少量化指标。这也是我下一步最想补的一块 —— 有 ground truth 才能证明「加 Reranker 确实变好了」这类结论。

---

*文档生成日期：2026-06-09 · 适用项目版本：v0.4.0*
