"""系统设置接口：rerank 相关字段的保存与校验。"""


async def test_settings_roundtrip_rerank_fields(client, admin_token):
    resp = await client.put(
        "/api/settings",
        headers={"Authorization": f"Bearer {admin_token}"},
        json={"chunk_size": 800, "chunk_overlap": 100, "top_k": 10,
              "rerank_enabled": True, "rrf_top_n": 20, "top_n": 6,
              "retrieval_min_score": 0.6},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["rerank_enabled"] is True
    assert body["rrf_top_n"] == 20
    assert body["top_n"] == 6
    assert body["retrieval_min_score"] == 0.6


async def test_settings_rejects_top_n_over_rrf_top_n(client, admin_token):
    resp = await client.put(
        "/api/settings",
        headers={"Authorization": f"Bearer {admin_token}"},
        json={"chunk_size": 800, "chunk_overlap": 100, "top_k": 5,
              "rerank_enabled": True, "rrf_top_n": 5, "top_n": 6,
              "retrieval_min_score": 0.5},
    )
    assert resp.status_code == 400


async def test_settings_rejects_min_score_out_of_range(client, admin_token):
    resp = await client.put(
        "/api/settings",
        headers={"Authorization": f"Bearer {admin_token}"},
        json={"chunk_size": 800, "chunk_overlap": 100, "top_k": 5,
              "rerank_enabled": False, "rrf_top_n": 5, "top_n": 5,
              "retrieval_min_score": 1.5},
    )
    assert resp.status_code == 400
