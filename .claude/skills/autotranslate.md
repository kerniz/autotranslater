---
name: autotranslate
description: Ollama 기반 문서/텍스트 자동 번역 도구 (autotranslater 패키지) 사용법. EPUB, HTML 파일 번역 및 Python API 사용 시 참조.
triggers:
  - translate
  - 번역
  - autotranslate
  - autotranslater
  - translategemma
  - epub
  - html 번역
---

# autotranslater - Ollama 기반 자동 번역 패키지

## 패키지 정보
- **레포**: https://github.com/kerniz/autotranslater
- **버전**: 0.2.0
- **라이선스**: MIT
- **Python**: >= 3.9
- **의존성**: ollama, ebooklib, beautifulsoup4

## 설치

```bash
# GitHub에서 직접 설치
pip install git+https://github.com/kerniz/autotranslater.git

# 로컬 개발 (editable)
git clone https://github.com/kerniz/autotranslater.git
pip install -e ./autotranslater

# SSH
pip install git+ssh://git@github.com/kerniz/autotranslater.git
```

## CLI 사용법

```bash
# 기본 사용 (kerniz3.mooo.com 서버, Korean, translategemma:27b)
autotranslate book.epub book_kr.epub

# 서버/모델 지정
autotranslate page.html page_kr.html --host other-server.com --model gemma3:12b

# 일본어 번역, 8스레드
autotranslate doc.epub doc_ja.epub --lang Japanese --threads 8

# 캐시 없이
autotranslate book.epub book_kr.epub --no-cache
```

### CLI 옵션

| 옵션 | 기본값 | 설명 |
|------|--------|------|
| `input` | (필수) | 입력 파일 (epub, html) |
| `output` | (필수) | 출력 파일 경로 |
| `--model` | `translategemma:27b` | Ollama 모델명 |
| `--host` | `kerniz3.mooo.com` | Ollama 서버 호스트 |
| `--threads` | `5` | 병렬 스레드 수 |
| `--lang` | `Korean` | 번역 대상 언어 |
| `--no-cache` | false | 캐시 사용 안 함 |

## Python API

### 간편 함수

```python
from autotranslater import translate_file

# 기본 번역 (Korean)
translate_file("book.epub", "book_kr.epub")

# 일본어 번역
translate_file("doc.html", "doc_ja.html", target_lang="Japanese")

# 서버/모델 지정
translate_file("book.epub", "book_en.epub",
               host="my-server.com",
               model="gemma3:27b",
               target_lang="English")
```

### Translator 클래스

```python
from autotranslater import Translator

# 기본 생성
t = Translator()

# 전체 옵션 지정
t = Translator(
    model="translategemma:27b",     # Ollama 모델
    host="kerniz3.mooo.com",        # Ollama 서버
    threads=5,                       # 병렬 스레드 수
    use_cache=True,                  # 번역 캐시 사용
    timeout=180,                     # 요청 타임아웃 (초)
    retries=3,                       # 실패 시 재시도 횟수
    target_lang="Korean",            # 번역 대상 언어
    progress_callback=None,          # 진행 콜백 (completed, total) -> None
)

# 단일 텍스트 번역
result = t.translate_text("Hello world")

# HTML 태그 보존 번역
result = t.translate_text("<p>Hello <b>world</b></p>", is_html=True)

# 파일 번역 (epub, html)
t.translate_file("input.epub", "output.epub")
t.translate_file("input.html", "output.html")
```

### 진행률 콜백

```python
def on_progress(completed, total):
    pct = completed / total * 100
    print(f"[{completed}/{total}] {pct:.1f}%")

t = Translator(progress_callback=on_progress)
t.translate_file("big_book.epub", "big_book_kr.epub")
```

### 다국어 번역 예시

```python
from autotranslater import Translator

text = "FDA approved a new drug for clinical trials"

# 각 언어별 Translator 인스턴스 생성 (target_lang은 생성자에서 설정)
t_ko = Translator(target_lang="Korean")
t_ja = Translator(target_lang="Japanese")
t_zh = Translator(target_lang="Chinese")

print(t_ko.translate_text(text))  # 한국어
print(t_ja.translate_text(text))  # 日本語
print(t_zh.translate_text(text))  # 中文
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
| `translategemma:27b` | 번역 전용 (추천) | 빠름 | 높음 |
| `qwen3:30b` | 범용 다국어 | 느림 | 높음 |
| `gemma3:27b` | 범용 | 보통 | 보통 |
| `llama3.1:8b` | 경량 | 빠름 | 낮음 (일본어 약함) |

## 아키텍처

```
autotranslater/
├── __init__.py          # 패키지 진입점 (Translator, translate_file 공개)
├── translator.py        # 핵심 번역 엔진
│   ├── Translator       # 메인 클래스
│   │   ├── translate_text()   # 단일 텍스트 번역
│   │   ├── translate_file()   # 파일 번역 (epub/html 자동 감지)
│   │   ├── _translate_html()  # HTML 파일 번역 (BeautifulSoup)
│   │   ├── _translate_epub()  # EPUB 파일 번역 (ebooklib)
│   │   ├── _build_prompt()    # 번역 프롬프트 생성
│   │   ├── _get_cached()      # 캐시 조회
│   │   └── _save_cache()      # 캐시 저장
│   └── translate_file()       # 간편 함수
└── cli.py               # CLI 엔트리포인트 (autotranslate 명령어)
```

## 캐시 시스템
- 캐시 키: `sha256(model:target_lang:text)` (모델+언어+텍스트 조합)
- 캐시 위치: `~/.autotranslate_cache/` (환경변수로 변경 가능)
- 같은 텍스트를 같은 모델+언어로 번역하면 캐시 히트
- `--no-cache` 또는 `use_cache=False`로 비활성화

## 주의사항
- `target_lang`은 Translator 생성자에서 설정 (translate_text의 인자 아님)
- 코드 블록(```로 시작)은 자동으로 번역 건너뜀
- HTML 번역 시 태그 구조 보존
- 실패 시 원본 텍스트 반환 (에러로 중단되지 않음)
- Ollama 서버가 GPU를 사용하므로 동시에 여러 모델 로드 시 느려질 수 있음
