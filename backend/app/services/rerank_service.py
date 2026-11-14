"""重排（rerank）服务客户端：把候选文本按与查询的相关性重新打分排序。

仅对接 DashScope 原生 text-rerank 协议；provider/密钥等连接配置只读 .env。
失败时抛出异常，由调用方降级为融合顺序，不影响问答可用性。
"""
import httpx

from app.config import settings

_DASHSCOPE_RERANK_PATH = "/api/v1/services/rerank/text-rerank/text-rerank"
_TIMEOUT_SECONDS = 10.0


async def rerank_documents(query: str, documents: list[str], top_n: int | None = None) -> list[tuple[int, float]]:
    """返回按相关性降序的 (候选下标, 相关性分数)；下标对应传入 documents 的位置。"""
    if settings.rerank_provider != "dashscope":
        raise RuntimeError("未启用重排服务，请检查 RERANK_PROVIDER 配置")
    if not settings.rerank_api_key:
        raise RuntimeError("未配置重排服务密钥 RERANK_API_KEY")

    parameters: dict = {"return_documents": False}
    if top_n:
        parameters["top_n"] = top_n
    url = settings.rerank_base_url.rstrip("/") + _DASHSCOPE_RERANK_PATH
    async with httpx.AsyncClient(timeout=_TIMEOUT_SECONDS) as client:
        response = await client.post(
            url,
            json={
                "model": settings.rerank_model,
                "input": {"query": query, "documents": documents},
                "parameters": parameters,
            },
            headers={"Authorization": f"Bearer {settings.rerank_api_key}"},
        )
        response.raise_for_status()
        results = response.json()["output"]["results"]
    ranked = [(int(item["index"]), float(item["relevance_score"])) for item in results]
    return ranked[:top_n] if top_n else ranked
