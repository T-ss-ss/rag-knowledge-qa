from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from openai import OpenAI

from app.config import settings
from app.db.database import init_db
from app.repositories.kb_repo import KBRepo
from app.services.vector_store import VectorStoreService
from app.routers import upload, qa, documents, knowledge_bases, conversations
from app.utils.exceptions import register_exception_handlers


@asynccontextmanager
async def lifespan(app: FastAPI):
    missing = []
    if not settings.deepseek_api_key or settings.deepseek_api_key == "your-deepseek-key":
        missing.append("DEEPSEEK_API_KEY")
    if not settings.embedding_api_key or settings.embedding_api_key == "your-dashscope-key":
        missing.append("EMBEDDING_API_KEY")
    if missing:
        raise SystemExit(
            f"缺少 API Key: {', '.join(missing)}。请复制 .env.example 为 .env 并配置。"
        )
    init_db()
    app.state.vector_store = VectorStoreService()
    yield


app = FastAPI(
    title="AI 知识库问答系统",
    description="上传 PDF 文档，基于 RAG 技术进行智能问答，支持多知识库与聊天历史",
    version="0.4.0",
    lifespan=lifespan,
    docs_url=None,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

register_exception_handlers(app)

app.include_router(upload.router)
app.include_router(qa.router)
app.include_router(documents.router)
app.include_router(knowledge_bases.router)
app.include_router(conversations.router)

app.mount("/static", StaticFiles(directory="static"), name="static")


@app.get("/docs", include_in_schema=False)
async def api_docs():
    return HTMLResponse("""<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1.0" />
    <title>API 文档 · AI 知识库问答系统</title>
    <style>
        body { margin: 0; }
        /* 固定悬浮的“返回对话”入口。不占据文档流，避免与 Scalar 的布局冲突；
           即使 Scalar 依赖的 CDN 不可用（页面空白），这个按钮依然可见可用。 */
        #back-to-chat {
            position: fixed;
            right: 24px;
            bottom: 24px;
            z-index: 2147483000;
            display: inline-flex;
            align-items: center;
            gap: 8px;
            padding: 11px 18px;
            background: #1a73e8;
            color: #fff;
            border-radius: 999px;
            font-family: "Microsoft YaHei", "PingFang SC", system-ui, sans-serif;
            font-size: 14px;
            font-weight: 500;
            line-height: 1;
            text-decoration: none;
            box-shadow: 0 4px 14px rgba(26, 115, 232, 0.36);
            transition: background 0.2s, transform 0.2s, box-shadow 0.2s;
        }
        #back-to-chat:hover {
            background: #1557b0;
            transform: translateY(-2px);
            box-shadow: 0 6px 18px rgba(26, 115, 232, 0.44);
        }
        #back-to-chat:active { transform: translateY(0); }
        #back-to-chat svg { width: 16px; height: 16px; flex-shrink: 0; }
        /* 窄屏下缩成纯图标按钮，避免遮挡正文 */
        @media (max-width: 640px) {
            #back-to-chat { right: 16px; bottom: 16px; padding: 12px; }
            #back-to-chat .label { display: none; }
        }
    </style>
</head>
<body>
    <a id="back-to-chat" href="/chat" title="返回对话界面">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"
             stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
            <path d="M19 12H5" />
            <path d="M12 19l-7-7 7-7" />
        </svg>
        <span class="label">返回对话</span>
    </a>
    <script id="api-reference" data-url="/openapi.json"></script>
    <script src="https://cdn.jsdelivr.net/npm/@scalar/api-reference"></script>
</body>
</html>""")


@app.get("/", response_class=HTMLResponse)
async def home():
    return """<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>AI 知识库问答系统</title>
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body { font-family: "Microsoft YaHei", "PingFang SC", sans-serif; background: #f5f7fa; color: #333; line-height: 1.8; }
        .container { max-width: 800px; margin: 0 auto; padding: 40px 20px; }
        h1 { text-align: center; font-size: 28px; color: #1a1a2e; margin-bottom: 10px; }
        .subtitle { text-align: center; color: #666; margin-bottom: 40px; }
        .card { background: #fff; border-radius: 12px; padding: 30px; margin-bottom: 20px; box-shadow: 0 2px 12px rgba(0,0,0,0.06); }
        .card h2 { font-size: 20px; color: #1a73e8; margin-bottom: 16px; padding-bottom: 10px; border-bottom: 2px solid #e8f0fe; }
        .step { display: flex; align-items: flex-start; margin-bottom: 16px; }
        .step-num { width: 32px; height: 32px; background: #1a73e8; color: #fff; border-radius: 50%; text-align: center; line-height: 32px; font-size: 16px; font-weight: bold; flex-shrink: 0; margin-right: 14px; margin-top: 2px; }
        .step-text h3 { font-size: 16px; margin-bottom: 4px; color: #333; }
        .step-text p { color: #666; font-size: 14px; }
        .btn { display: inline-block; padding: 12px 32px; background: #1a73e8; color: #fff; border-radius: 8px; text-decoration: none; font-size: 16px; font-weight: 500; transition: background 0.2s; }
        .btn:hover { background: #1557b0; }
        .btn-secondary { background: #fff; color: #1a73e8; border: 1px solid #1a73e8; margin-left: 12px; }
        .btn-secondary:hover { background: #e8f0fe; }
        .buttons { text-align: center; margin-top: 30px; }
        .tip { background: #fffbe6; border-left: 4px solid #ffc107; padding: 12px 16px; border-radius: 0 8px 8px 0; margin-top: 16px; font-size: 14px; color: #856404; }
        code { background: #f0f0f0; padding: 2px 6px; border-radius: 4px; font-size: 13px; }
    </style>
</head>
<body>
    <div class="container">
        <h1>AI 知识库问答系统</h1>
        <p class="subtitle">上传 PDF → 智能检索 → AI 回答</p>

        <div class="card">
            <h2>使用步骤</h2>
            <div class="step">
                <div class="step-num">1</div>
                <div class="step-text">
                    <h3>上传 PDF 文档</h3>
                    <p>在接口文档页面找到 <code>POST /upload</code>，点击 <strong>Try it out</strong>，选择你的 PDF 文件，点 <strong>Execute</strong> 执行上传。</p>
                </div>
            </div>
            <div class="step">
                <div class="step-num">2</div>
                <div class="step-text">
                    <h3>开始提问</h3>
                    <p>在接口文档页面找到 <code>POST /qa</code>，点击 <strong>Try it out</strong>，把 <code>"string"</code> 替换成你的问题（比如"Python 有什么特点？"），点 <strong>Execute</strong>。</p>
                </div>
            </div>
            <div class="step">
                <div class="step-num">3</div>
                <div class="step-text">
                    <h3>查看结果</h3>
                    <p>AI 会基于你上传的文档内容给出回答，并在 <code>sources</code> 中标明答案来源的页码。</p>
                </div>
            </div>
            <div class="tip">
                <strong>注意：</strong>提问时记得把输入框里的 <code>"string"</code> 替换成你真正想问的问题，否则 AI 无法回答。
            </div>
        </div>

        <div class="buttons">
            <a href="/chat" class="btn">进入聊天界面</a>
            <a href="/docs" class="btn btn-secondary">打开接口文档</a>
        </div>
    </div>
</body>
</html>"""


@app.get("/chat", response_class=HTMLResponse)
async def chat_page():
    return FileResponse("static/chat.html")


@app.get("/health", summary="健康检查")
def health(request: Request):
    """注意：必须是同步 def。

    函数体内有阻塞式网络调用（OpenAI 同步客户端），写成 async def 会占住
    事件循环，上游 API 异常时整个服务都会失去响应。用 def 时 Starlette
    会自动把它丢进线程池执行。
    """
    vector_store: VectorStoreService = request.app.state.vector_store

    chat_ok = False
    try:
        client = OpenAI(
            api_key=settings.deepseek_api_key,
            base_url=settings.deepseek_base_url,
            timeout=5.0,
            max_retries=0,
        )
        client.models.list()
        chat_ok = True
    except Exception:
        pass

    embedding_ok = False
    try:
        client = OpenAI(
            api_key=settings.embedding_api_key,
            base_url=settings.embedding_base_url,
            timeout=5.0,
            max_retries=0,
        )
        client.models.list()
        embedding_ok = True
    except Exception:
        pass

    kb_repo = KBRepo()
    all_kbs = kb_repo.list_all()
    total_collection_chunks = 0
    total_docs = 0
    for kb in all_kbs:
        try:
            total_collection_chunks += vector_store.count(kb["collection_name"])
        except Exception:
            pass
        total_docs += kb["document_count"]

    return {
        "status": "healthy" if (chat_ok and embedding_ok) else "degraded",
        "chat_api": "connected" if chat_ok else "disconnected",
        "embedding_api": "connected" if embedding_ok else "disconnected",
        "chroma_collection_count": total_collection_chunks,
        "total_documents": total_docs,
        "knowledge_bases": len(all_kbs),
    }
