"""Phase 4.0.4 — backend internal endpoint 호출 wrapper.

scheduled_pipelines DAG 가 같은 분 안에서 trigger 시각이 도래한 워크플로 ID 들을
이 함수로 일괄 호출. 본 모듈은 Airflow PythonOperator 의 callable 로 사용된다.

Variable:
  - `BACKEND_INTERNAL_URL`     — http://backend-api:8000 (NKS) 또는
                                  http://host.docker.internal:8000 (로컬 docker)
  - `BACKEND_INTERNAL_TOKEN`   — backend Settings.airflow_internal_token 와 일치

Pool:
  - `backend_internal` (slots=4) — 동시 호출 4개로 제한 (rate limit 차원)
"""

from __future__ import annotations

import logging
from typing import Any

import httpx

log = logging.getLogger(__name__)

DEFAULT_TIMEOUT = 10.0


def trigger_pipeline_run(
    *,
    workflow_id: int,
    base_url: str,
    token: str,
    timeout: float = DEFAULT_TIMEOUT,
) -> dict[str, Any]:
    """backend 의 POST /v1/pipelines/internal/runs 호출. 응답 dict 반환.

    응답 예 (created=True 면 신규, False 면 같은 (workflow, today) 의 기존 run):
        {"pipeline_run_id": 42, "run_date": "2026-04-26", "status": "RUNNING", "created": true}

    오류 시 RuntimeError — 호출자(Airflow task) 가 retry 설정에 따라 재시도.
    """
    url = f"{base_url.rstrip('/')}/v1/pipelines/internal/runs"
    headers = {
        "Content-Type": "application/json",
        "X-Internal-Token": token,
    }
    body = {"workflow_id": int(workflow_id)}
    log.info("triggering pipeline run: workflow_id=%s url=%s", workflow_id, url)
    try:
        with httpx.Client(timeout=timeout) as client:
            resp = client.post(url, json=body, headers=headers)
    except httpx.TransportError as exc:
        raise RuntimeError(f"backend unreachable ({exc})") from exc

    if resp.status_code in (401, 503):
        raise RuntimeError(
            f"backend rejected internal call: status={resp.status_code} body={resp.text}"
        )
    if resp.status_code in (200, 202):
        data: dict[str, Any] = resp.json()
        log.info(
            "trigger ok: workflow_id=%s pipeline_run_id=%s created=%s",
            workflow_id,
            data.get("pipeline_run_id"),
            data.get("created"),
        )
        return data

    # 422 (PUBLISHED 아님 / cycle / no nodes) — 재시도해도 무의미.
    if resp.status_code == 422:
        log.warning(
            "workflow %s rejected by backend (likely not PUBLISHED): %s",
            workflow_id,
            resp.text,
        )
        return {
            "pipeline_run_id": None,
            "run_date": None,
            "status": "REJECTED_BY_BACKEND",
            "created": False,
            "_skipped_reason": resp.text[:200],
        }

    raise RuntimeError(f"unexpected status {resp.status_code}: {resp.text[:300]}")


__all__ = ["trigger_pipeline_run"]
