from app.config import settings

from pydantic import BaseModel, Field


# --- Knowledge Base ---
class KnowledgeBaseCreate(BaseModel):
    name: str = Field(min_length=1, max_length=50, description="知识库名称")
    description: str = Field(default="", max_length=200, description="描述")


class KnowledgeBaseUpdate(BaseModel):
    name: str | None = Field(default=None, max_length=50, description="知识库名称")
    description: str | None = Field(default=None, max_length=200, description="描述")


class KnowledgeBaseInfo(BaseModel):
    id: str = Field(description="知识库 ID")
    name: str = Field(description="知识库名称")
    description: str = Field(description="描述")
    document_count: int = Field(description="文档数量")
    collection_name: str = Field(description="ChromaDB 集合名")
    created_at: str = Field(description="创建时间")
    updated_at: str = Field(description="更新时间")


class KnowledgeBaseListResponse(BaseModel):
    knowledge_bases: list[KnowledgeBaseInfo] = Field(description="知识库列表")
    total_count: int = Field(description="知识库总数")


# --- Upload ---
class UploadResponse(BaseModel):
    document_id: str = Field(description="文档唯一标识")
    kb_id: str = Field(description="所属知识库 ID")
    filename: str = Field(description="文件名")
    page_count: int = Field(
        description="文档页数；0 表示该格式未记录页数（如未保存过渲染页数的 DOCX）"
    )
    chunk_count: int = Field(description="切块数量")
    status: str = Field(default="success", description="状态")


# --- Q&A ---
class QuestionRequest(BaseModel):
    question: str = Field(
        min_length=1, max_length=2000, description="你想问的问题"
    )
    kb_id: str = Field(
        default="default", min_length=1, max_length=50, description="知识库 ID"
    )
    top_k: int = Field(
        default=4, ge=1, le=20, description="返回的相关文档块数量"
    )
    temperature: float = Field(
        default=0.3, ge=0.0, le=1.0, description="LLM 温度参数"
    )
    rerank: bool = Field(
        default=True, description="是否启用 Rerank 重排序"
    )
    retrieval_top_k: int = Field(
        default=0, ge=0, le=100, description="粗筛候选数，0 表示自动 = top_k × 3"
    )


class SourceChunk(BaseModel):
    document_id: str = Field(description="来源文档 ID")
    filename: str = Field(description="来源文件名")
    page: int = Field(
        default=0,
        description="来源页码，按 chunk 位置估算；0 表示页码不可知（Web 结果或未记录页数的文档）",
    )
    chunk_index: int = Field(
        default=-1,
        description="该片段在文档内的切块序号；-1 表示未知（如 Web 结果）",
    )
    content: str = Field(description="相关文档片段")
    relevance_score: float = Field(description="相关度分数")
    score_type: str = Field(
        default="cosine",
        description="相关度分数的量纲：cosine（1-余弦距离，-1~1）/ rrf（多路融合分，无固定上界）/ "
        "rerank（BGE sigmoid，0~1）/ web（Tavily score）",
    )


class AnswerResponse(BaseModel):
    question: str = Field(description="原始问题")
    summary: str = Field(description="一句话摘要")
    answer: str = Field(description="AI 完整回答")
    sources: list[SourceChunk] = Field(description="参考来源")
    model_used: str = Field(description="使用的模型")


# --- Documents ---
class DocumentInfo(BaseModel):
    document_id: str = Field(description="文档 ID")
    filename: str = Field(description="文件名")
    page_count: int = Field(
        description="文档页数；0 表示该格式未记录页数（如未保存过渲染页数的 DOCX）"
    )
    chunk_count: int = Field(description="切块数")
    uploaded_at: str = Field(description="上传时间")


class DocumentListResponse(BaseModel):
    documents: list[DocumentInfo] = Field(description="文档列表")
    total_count: int = Field(description="文档总数")


class DeleteResponse(BaseModel):
    document_id: str = Field(description="已删除的文档 ID")
    status: str = Field(default="deleted", description="操作状态")


# --- Conversations ---
class ConversationCreate(BaseModel):
    kb_id: str = Field(default="default", min_length=1, max_length=50, description="所属知识库 ID")
    title: str = Field(default="", max_length=100, description="可选标题")


class ConversationUpdate(BaseModel):
    title: str = Field(min_length=1, max_length=100, description="新标题")


class ConversationQARequest(BaseModel):
    question: str = Field(min_length=1, max_length=2000, description="你想问的问题")
    top_k: int = Field(default=4, ge=1, le=20, description="返回的相关文档块数量")
    temperature: float = Field(default=0.3, ge=0.0, le=1.0, description="LLM 温度参数")
    rerank: bool = Field(
        default=True, description="是否启用 Rerank 重排序"
    )
    retrieval_top_k: int = Field(
        default=0, ge=0, le=100, description="粗筛候选数，0 表示自动 = top_k × 3"
    )


class MessageInfo(BaseModel):
    id: int = Field(description="消息 ID")
    role: str = Field(description="角色: user / assistant")
    content: str = Field(description="消息内容")
    sources: list[SourceChunk] | None = Field(default=None, description="引用来源（仅 assistant）")
    model: str | None = Field(default=None, description="模型名（仅 assistant）")
    created_at: str = Field(description="创建时间")


class ConversationInfo(BaseModel):
    id: str = Field(description="会话 ID")
    kb_id: str = Field(description="所属知识库 ID")
    title: str = Field(description="会话标题")
    message_count: int = Field(description="消息数")
    created_at: str = Field(description="创建时间")
    updated_at: str = Field(description="更新时间")


class ConversationDetail(BaseModel):
    id: str = Field(description="会话 ID")
    kb_id: str = Field(description="所属知识库 ID")
    title: str = Field(description="会话标题")
    message_count: int = Field(description="消息数")
    messages: list[MessageInfo] = Field(description="消息列表")
    created_at: str = Field(description="创建时间")
    updated_at: str = Field(description="更新时间")


class ConversationListResponse(BaseModel):
    conversations: list[ConversationInfo] = Field(description="会话列表")
    total_count: int = Field(description="会话总数")


class ConversationQAResponse(BaseModel):
    conversation_id: str = Field(description="会话 ID")
    user_message: MessageInfo | None = Field(default=None, description="用户消息，空 KB 时为 None")
    assistant_message: MessageInfo = Field(description="AI 回复")
    answer: str = Field(description="AI 回答文本（与 assistant_message.content 相同）")
    summary: str = Field(default="", description="回答摘要")
    sources: list[SourceChunk] = Field(default_factory=list, description="参考来源")
    model_used: str = Field(default="", description="使用的模型")


# --- Agent ---
class AgentQARequest(BaseModel):
    question: str = Field(min_length=1, max_length=2000, description="你想问的问题")
    top_k: int = Field(default=4, ge=1, le=20, description="检索文档块数量")
    temperature: float = Field(default=0.3, ge=0.0, le=1.0, description="LLM 温度参数")
    rerank: bool = Field(
        default=True,
        description="是否启用 BGE-Reranker 精排（需全局 RERANK_ENABLED=true 才生效）",
    )
    max_iterations: int = Field(default=settings.agent_max_iterations, ge=1, le=10, description="Agent 最大推理步数")


class AgentStep(BaseModel):
    step: int = Field(description="步骤序号")
    type: str = Field(description="步骤类型: tool_call / tool_result / answer")
    detail: str = Field(default="", description="步骤详情")


class AgentQAResponse(BaseModel):
    conversation_id: str = Field(description="会话 ID")
    user_message: MessageInfo | None = Field(default=None, description="用户消息")
    assistant_message: MessageInfo = Field(description="AI 回复")
    answer: str = Field(description="AI 回答文本")
    summary: str = Field(default="", description="回答摘要")
    sources: list[SourceChunk] = Field(default_factory=list, description="参考来源")
    model_used: str = Field(default="", description="使用的模型")
    reasoning_steps: list[AgentStep] = Field(default_factory=list, description="Agent 推理步骤")


# --- Health ---
class HealthResponse(BaseModel):
    status: str = Field(description="系统状态")
    chat_api: str = Field(description="聊天 API 连接状态")
    embedding_api: str = Field(description="嵌入 API 连接状态")
    chroma_collection_count: int = Field(description="向量库记录数")
    total_documents: int = Field(description="已上传文档数")
