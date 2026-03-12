"""
핵심 번역 엔진 모듈
"""

import os
import hashlib
import time
import logging
from typing import Optional, Callable
from urllib.parse import urlparse
from concurrent.futures import ThreadPoolExecutor, as_completed

import ollama
from ebooklib import epub
from bs4 import BeautifulSoup
import ebooklib

logger = logging.getLogger(__name__)

DEFAULT_MODEL = os.environ.get("AUTOTRANSLATE_MODEL", "gemma3:27b")
DEFAULT_HOST = os.environ.get("AUTOTRANSLATE_HOST", "kerniz3.mooo.com")
DEFAULT_TIMEOUT = int(os.environ.get("AUTOTRANSLATE_TIMEOUT", "180"))
DEFAULT_THREADS = int(os.environ.get("AUTOTRANSLATE_THREADS", "5"))
DEFAULT_LANG = os.environ.get("AUTOTRANSLATE_LANG", "Korean")
CACHE_DIR = os.environ.get(
    "AUTOTRANSLATE_CACHE_DIR", os.path.expanduser("~/.autotranslate_cache")
)

# 번역 대상 HTML 태그
_BLOCK_TAGS = ["p", "h1", "h2", "h3", "h4", "h5", "h6", "li", "figcaption", "title"]
_EPUB_TAGS = ["p", "h1", "h2", "h3", "li", "td"]
# 블록 자식이 있으면 건너뛸 태그
_SKIP_CHILDREN = ["p", "div", "section", "article"]


def _ensure_dir(path: str):
    d = os.path.dirname(path)
    if d:
        os.makedirs(d, exist_ok=True)


def _extract_content(response) -> str:
    """ollama 응답에서 content 추출 (dict / object 호환)"""
    try:
        return response["message"]["content"]
    except (TypeError, KeyError):
        return response.message.content


def _replace_elem_content(elem, translated_html: str):
    """BeautifulSoup 요소의 내용을 번역 결과로 교체"""
    parsed = BeautifulSoup(translated_html, "html.parser")
    elem.clear()
    for child in list(parsed.contents):
        elem.append(child)


class Translator:
    """문서 번역기

    Args:
        model: Ollama 모델명 (env: AUTOTRANSLATE_MODEL)
        host: Ollama 서버 호스트 (env: AUTOTRANSLATE_HOST, 기본: kerniz3.mooo.com)
        threads: 병렬 번역 스레드 수 (env: AUTOTRANSLATE_THREADS)
        use_cache: 번역 캐시 사용 여부
        timeout: 번역 요청 타임아웃 초 (env: AUTOTRANSLATE_TIMEOUT)
        retries: 실패 시 재시도 횟수
        target_lang: 번역 대상 언어 (env: AUTOTRANSLATE_LANG, 기본: Korean)
        progress_callback: 진행 콜백 (completed, total) -> None
    """

    def __init__(
        self,
        model: str = DEFAULT_MODEL,
        host: Optional[str] = DEFAULT_HOST,
        threads: int = DEFAULT_THREADS,
        use_cache: bool = True,
        timeout: int = DEFAULT_TIMEOUT,
        retries: int = 3,
        target_lang: str = DEFAULT_LANG,
        progress_callback: Optional[Callable[[int, int], None]] = None,
    ):
        self.model = model
        self.threads = threads
        self.use_cache = use_cache
        self.timeout = timeout
        self.retries = retries
        self.target_lang = target_lang
        self.progress_callback = progress_callback
        self._client = self._init_client(host)

        if use_cache:
            os.makedirs(CACHE_DIR, exist_ok=True)

    @staticmethod
    def _init_client(host: Optional[str]):
        if not host:
            return ollama
        if not host.startswith("http"):
            host = f"http://{host}"
        parsed = urlparse(host)
        if not parsed.port:
            host = f"{parsed.scheme}://{parsed.hostname}:11434"
        logger.info("Ollama 서버 연결: %s", host)
        return ollama.Client(host=host)

    # ------------------------------------------------------------------
    # 캐시
    # ------------------------------------------------------------------

    @staticmethod
    def _cache_key(text: str, model: str) -> str:
        return hashlib.sha256(f"{model}:{text}".encode()).hexdigest()[:32]

    def _get_cached(self, text: str) -> Optional[str]:
        path = os.path.join(CACHE_DIR, f"{self._cache_key(text, self.model)}.txt")
        if os.path.exists(path):
            with open(path, "r", encoding="utf-8") as f:
                return f.read()
        return None

    def _save_cache(self, text: str, translated: str):
        path = os.path.join(CACHE_DIR, f"{self._cache_key(text, self.model)}.txt")
        with open(path, "w", encoding="utf-8") as f:
            f.write(translated)

    # ------------------------------------------------------------------
    # 번역 코어
    # ------------------------------------------------------------------

    @staticmethod
    def _is_code_block(text: str) -> bool:
        text = text.strip()
        if not text:
            return False
        if text.startswith("```"):
            return True
        if len(text) > 30:
            code_chars = sum(1 for c in text if c in "{}[]();=")
            if code_chars / len(text) > 0.2:
                return True
        return False

    def _build_prompt(self, text: str, is_html: bool = False) -> str:
        lang = self.target_lang
        if is_html:
            return (
                f"Translate the following HTML content into {lang}.\n"
                "CRITICAL: Keep all HTML tags (like <a>, <span>, <b>, <i>, <cite>, etc.) EXACTLY where they are.\n"
                "Only translate the visible text. Use a professional academic tone.\n"
                "Output ONLY the translated HTML content without any explanations.\n\n"
                f"HTML to translate:\n{text}"
            )
        return (
            f"Translate the following text into professional {lang}.\n"
            "Maintain technical accuracy and use an academic tone.\n"
            "Output ONLY the translated text.\n\n"
            f"Text:\n{text}"
        )

    def translate_text(self, text: str, is_html: bool = False) -> str:
        """단일 텍스트 번역. 실패 시 원본 반환."""
        if not text.strip() or self._is_code_block(text):
            return text

        if self.use_cache:
            cached = self._get_cached(text)
            if cached:
                return cached

        prompt = self._build_prompt(text, is_html)

        for attempt in range(self.retries):
            try:
                response = self._client.chat(
                    model=self.model,
                    messages=[{"role": "user", "content": prompt}],
                    options={"timeout": self.timeout, "temperature": 0.3},
                )
                result = _extract_content(response).strip()

                if result.startswith('"') and result.endswith('"') and text.count('"') < 2:
                    result = result[1:-1]

                if self.use_cache:
                    self._save_cache(text, result)
                return result
            except Exception as e:
                if attempt == self.retries - 1:
                    logger.error("번역 실패: %s", str(e)[:100])
                    return text
                wait_time = 2 ** attempt
                logger.warning("재시도 %d/%d (%d초 후)", attempt + 1, self.retries, wait_time)
                time.sleep(wait_time)
        return text

    # ------------------------------------------------------------------
    # 파일 번역
    # ------------------------------------------------------------------

    def translate_file(self, input_path: str, output_path: str) -> bool:
        """파일 번역 (확장자 자동 감지: .html, .epub)"""
        if not os.path.exists(input_path):
            raise FileNotFoundError(f"파일 없음: {input_path}")
        _ensure_dir(output_path)

        ext = os.path.splitext(input_path)[1].lower()
        if ext == ".html":
            return self._translate_html(input_path, output_path)
        elif ext == ".epub":
            return self._translate_epub(input_path, output_path)
        else:
            raise ValueError(f"지원하지 않는 형식: {ext} (html, epub만 지원)")

    def _translate_html(self, input_path: str, output_path: str) -> bool:
        with open(input_path, "r", encoding="utf-8", errors="replace") as f:
            soup = BeautifulSoup(f, "html.parser")

        targets = []
        for elem in soup.find_all(_BLOCK_TAGS):
            if not elem.find(_SKIP_CHILDREN):
                content = "".join(str(c) for c in elem.contents).strip()
                if len(content) > 5 and not self._is_code_block(content):
                    targets.append((elem, content))

        total = len(targets)
        logger.info("%d개 요소를 %d 스레드로 번역 시작", total, self.threads)

        with ThreadPoolExecutor(max_workers=self.threads) as executor:
            future_map = {
                executor.submit(self.translate_text, content, True): elem
                for elem, content in targets
            }

            completed = 0
            for future in as_completed(future_map):
                elem = future_map[future]
                try:
                    _replace_elem_content(elem, future.result())
                except Exception as e:
                    logger.error("요소 업데이트 오류: %s", e)

                completed += 1
                if self.progress_callback:
                    self.progress_callback(completed, total)

        with open(output_path, "w", encoding="utf-8") as f:
            f.write(str(soup))
        return True

    def _translate_epub(self, input_path: str, output_path: str) -> bool:
        book = epub.read_epub(input_path, options={"ignore_ncx": True})
        items = list(book.get_items_of_type(ebooklib.ITEM_DOCUMENT))

        # 메타데이터(제목) 번역
        title_meta = book.get_metadata("DC", "title")
        if title_meta:
            original_title = title_meta[0][0]
            translated_title = self.translate_text(original_title)
            book.set_title(translated_title)
            logger.info("제목 번역: %s -> %s", original_title, translated_title)

        # 전체 요소 수 카운트 (진행률용) - 가벼운 단일 패스
        grand_total = 0
        for item in items:
            soup = BeautifulSoup(item.get_content().decode("utf-8", errors="replace"), "html.parser")
            for elem in soup.find_all(_EPUB_TAGS):
                inner = "".join(str(c) for c in elem.contents).strip()
                if len(inner) > 3:
                    grand_total += 1

        logger.info("총 %d 챕터, %d개 요소 번역 시작", len(items), grand_total)

        # 단일 ThreadPool로 전체 챕터 처리
        global_completed = 0
        with ThreadPoolExecutor(max_workers=self.threads) as executor:
            for idx, item in enumerate(items, 1):
                content = item.get_content().decode("utf-8", errors="replace")
                soup = BeautifulSoup(content, "html.parser")

                targets = []
                for elem in soup.find_all(_EPUB_TAGS):
                    inner = "".join(str(c) for c in elem.contents).strip()
                    if len(inner) > 3:
                        targets.append((elem, inner))

                if not targets:
                    continue

                logger.info("챕터 %d/%d (%d개 요소)", idx, len(items), len(targets))

                future_map = {
                    executor.submit(self.translate_text, c, True): e
                    for e, c in targets
                }
                for future in as_completed(future_map):
                    elem = future_map[future]
                    try:
                        _replace_elem_content(elem, future.result())
                    except Exception as e:
                        logger.error("EPUB 요소 업데이트 오류: %s", e)

                    global_completed += 1
                    if self.progress_callback:
                        self.progress_callback(global_completed, grand_total)

                item.set_content(str(soup).encode("utf-8"))

        epub.write_epub(output_path, book)
        return True


def translate_file(
    input_path: str,
    output_path: str,
    model: str = DEFAULT_MODEL,
    host: Optional[str] = DEFAULT_HOST,
    threads: int = DEFAULT_THREADS,
    use_cache: bool = True,
    target_lang: str = DEFAULT_LANG,
    progress_callback: Optional[Callable[[int, int], None]] = None,
) -> bool:
    """간편 함수: 파일 번역

    사용 예시::

        from autotranslater import translate_file
        translate_file("book.epub", "book_kr.epub", host="my-server.com")
        translate_file("doc.html", "doc_ja.html", target_lang="Japanese")
    """
    t = Translator(
        model=model,
        host=host,
        threads=threads,
        use_cache=use_cache,
        target_lang=target_lang,
        progress_callback=progress_callback,
    )
    return t.translate_file(input_path, output_path)
