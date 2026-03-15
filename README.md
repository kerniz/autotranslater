# autotranslater

Ollama 기반 문서 자동 번역 도구. EPUB, HTML 파일을 병렬로 번역합니다.

## 설치

```bash
pip install git+https://github.com/kerniz/autotranslater.git
```

## CLI 사용법

```bash
# 기본 (kerniz3.mooo.com 서버, Korean, translategemma:27b)
autotranslate book.epub book_kr.epub

# 다른 서버/모델
autotranslate page.html page_kr.html --host other-server.com --model gemma3:12b

# 일본어로 번역, 8스레드
autotranslate doc.epub doc_ja.epub --lang Japanese --threads 8

# 캐시 없이
autotranslate book.epub book_kr.epub --no-cache
```

## Python API

```python
from autotranslater import Translator, translate_file

# 간편 함수
translate_file("book.epub", "book_kr.epub")

# 클래스 사용
t = Translator(model="translategemma:27b", threads=8)
t.translate_file("page.html", "page_kr.html")

# 단일 텍스트
result = t.translate_text("Hello world")

# 일본어 번역 + 진행률
t = Translator(
    target_lang="Japanese",
    progress_callback=lambda done, total: print(f"{done}/{total}")
)
t.translate_file("book.epub", "book_ja.epub")
```

## 환경변수

| 변수 | 기본값 | 설명 |
|------|--------|------|
| `AUTOTRANSLATE_MODEL` | `translategemma:27b` | Ollama 모델명 |
| `AUTOTRANSLATE_HOST` | `kerniz3.mooo.com` | Ollama 서버 호스트 |
| `AUTOTRANSLATE_THREADS` | `5` | 병렬 스레드 수 |
| `AUTOTRANSLATE_LANG` | `Korean` | 번역 대상 언어 |
| `AUTOTRANSLATE_TIMEOUT` | `180` | 요청 타임아웃 (초) |
| `AUTOTRANSLATE_CACHE_DIR` | `~/.autotranslate_cache` | 캐시 디렉토리 |

## 추천 모델

| 모델 | 용도 | 속도 | 품질 |
|------|------|------|------|
| `translategemma:27b` | 번역 전용 (기본값) | 빠름 | 높음 |
| `qwen3:30b` | 범용 다국어 | 느림 | 높음 |
| `llama3.1:8b` | 경량 | 빠름 | 낮음 |
