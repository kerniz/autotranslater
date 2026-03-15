# autotranslater

Ollama 기반 문서 자동 번역 패키지. EPUB, HTML 파일을 병렬로 번역합니다.

## Skills
- `.claude/skills/autotranslate.md` — 설치법, CLI 사용법, Python API, 환경변수, 모델 추천 등 전체 레퍼런스

## 개발 규칙
- 번역 모델 기본값: `translategemma:27b` (번역 전용 모델, 속도+품질 균형)
- Ollama 서버: `kerniz3.mooo.com:11434`
- 캐시 키에 반드시 `model + target_lang + text` 조합 사용 (언어별 캐시 분리)
- 테스트 시 `--no-cache`로 캐시 우회 가능
