"""외부 서비스 어댑터 계층.

원칙: `requests`/`httpx`/`boto3` 등 외부 SDK 직접 호출은 이 패키지 안에서만.
도메인/API 는 Protocol 기반 추상 인터페이스만 본다.
"""
