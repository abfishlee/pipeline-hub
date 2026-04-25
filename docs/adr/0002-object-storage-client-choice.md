# ADR-0002 — Object Storage 클라이언트 선택 (boto3 + asyncio.to_thread)

- **Status:** Accepted
- **Date:** 2026-04-25
- **Deciders:** abfishlee + Claude
- **Phase:** 1.2.6 (Object Storage 통합)

## 1. 컨텍스트

Phase 1.2.7(수집 API) 에서 PDF/이미지/HTML/대형 JSON 을 MinIO(로컬) 와 NCP
Object Storage(운영)에 저장한다. 두 환경 모두 S3 호환이므로 S3 SDK 를 쓰면 된다.
FastAPI 는 async 이므로 호출 경로가 async 여야 한다.

Python 의 S3 클라이언트는 3가지 후보가 있다.

| 옵션 | 특징 | 주요 단점 |
|---|---|---|
| **boto3** (동기) + `asyncio.to_thread` | AWS 공식, 가장 성숙, 단일 의존성 | thread pool 사용 — 초당 1000+ 요청 시 오버헤드 가능 |
| **aioboto3** | boto3 async wrapper | 별도 패키지, boto3 ver skew 주의, 타입 힌트 부족 |
| **aiobotocore** | 저수준 async | 저수준 API, 직접 쓰기 번거로움 |

## 2. 결정

**boto3 + `asyncio.to_thread`** 를 채택한다. async 래핑 패턴은 본 프로젝트에서
단일 어댑터(`app/integrations/object_storage.py`)에만 제한된다.

```python
async def put(self, key: str, data: bytes, content_type: str) -> str:
    await asyncio.to_thread(
        self._client.put_object,
        Bucket=self._bucket, Key=key, Body=data, ContentType=content_type,
    )
    return self.object_uri(key)
```

### 2.1 근거

1. **규모 대비 충분**. 우리 목표는 10만~30만 rows/일 + OCR 1,000 page/일. 초당
   평균 3~10 OPS, 피크에도 100 OPS 미만. `asyncio.to_thread` 의 오버헤드가 문제 될
   규모가 아니다 (thread pool default 가 수십 개).
2. **의존성 1개**. aioboto3 는 별도 패키지 + botocore 버전 싱크 이슈가 간헐적으로 발생.
3. **타입 안정성**. boto3 의 부분 타입 힌트가 그나마 가장 풍부. aioboto3 는 타입 stub
   이 늦게 따라온다.
4. **디버깅 단순**. 문제 발생 시 blocking call 만 따로 떼어내 `python -c` 로 재현
   가능. async stack 미궁 없음.
5. **운영팀 이관 편의**. 운영팀 6~7명 (9월 합류) 대부분 AWS/boto3 경험 있음.

### 2.2 성능 재평가 조건

다음 중 하나 발생 시 aioboto3 또는 네이티브 async 로 재검토:
- Object Storage 호출이 초당 500 OPS 이상 지속
- Thread pool exhaustion 관찰 (uvicorn 경고)
- 단일 request 안에서 수십 개 이상 병렬 Object Storage 호출 필요

## 3. 클라이언트 설정

```python
from botocore.config import Config

Config(
    connect_timeout=5,                # 5s 연결 타임아웃
    read_timeout=30,                  # 30s 읽기 타임아웃 (대용량 파일 고려)
    retries={"max_attempts": 3, "mode": "adaptive"},
    signature_version="s3v4",         # MinIO + NCP OS 공통 요구
    s3={"addressing_style": "path"},  # MinIO 는 path-style 필수, NCP 호환
)
```

endpoint_url:
- `APP_OS_SCHEME=minio` → `APP_OS_ENDPOINT` 사용 (예: `http://localhost:9000`)
- `APP_OS_SCHEME=ncp`   → `https://kr.object.ncloudstorage.com` 사용

## 4. URI 스킴

DB 에 저장하는 `raw_object.object_uri` 는 환경별로 식별자를 다르게 둔다.
이유: 운영/개발 데이터가 섞인 덤프를 복원할 때 출처를 즉시 알 수 있게.

- MinIO(local/dev): `s3://bucket/key`
- NCP Object Storage: `nos://bucket/key`

애플리케이션은 URI 의 scheme 부분을 파싱해 현 환경의 클라이언트로 복원해 읽는다.

## 5. 멀티파트 업로드

대용량(>5MB) 은 multipart upload 패턴을 `put_stream()` 에 구현한다. S3 규격상
part 최소 크기 5MB, 마지막 part 는 그 이하 허용. 실패 시 `abort_multipart_upload`
로 부분 업로드 정리.

## 6. 대안별 비교표

| 기준 | boto3 + to_thread | aioboto3 | aiobotocore |
|---|---|---|---|
| 초당 100 OPS | ✅ 충분 | ✅ 충분 | ✅ 충분 |
| 초당 1000 OPS | ⚠️ thread pool 주의 | ✅ | ✅ |
| 코드 단순성 | ✅ 단일 어댑터 안에 봉쇄 | ⚠️ async def 전파 | ❌ 저수준 |
| 타입 힌트 | 🟡 부분 지원 | ❌ 스텁 없음 | ❌ 스텁 없음 |
| 학습 비용 | ✅ boto3 표준 | ⚠️ wrapper quirk | ❌ 고급 |
| 운영팀 친숙도 | ✅ 대부분 알고 있음 | ⚠️ | ❌ |
| 의존성 트리 | ✅ 최소 | ⚠️ 추가 | ⚠️ 추가 |

**결론**: 규모에 비해 복잡도가 낮은 boto3 채택이 우월.

## 7. 영향

- `app/integrations/object_storage.py` 에 단일 어댑터. `ObjectStorage` Protocol 으로
  인터페이스만 노출. 향후 aioboto3 교체 시 이 어댑터만 바뀐다.
- FastAPI lifespan 에서 object storage ping 추가 (`/readyz` 반영).
- presigned URL 생성은 boto3 의 sync 메서드가 순수 연산(네트워크 없음) 이라 to_thread 없이도 안전.

## 8. 참고

- [boto3 S3 Client](https://boto3.amazonaws.com/v1/documentation/api/latest/reference/services/s3.html)
- [asyncio.to_thread docs](https://docs.python.org/3/library/asyncio-task.html#asyncio.to_thread)
- [NCP Object Storage S3 API 호환](https://api.ncloud-docs.com/docs/storage-objectstorage)
- [MinIO S3 compatibility](https://min.io/docs/minio/linux/administration/object-management.html)
