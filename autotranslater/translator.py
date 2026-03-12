"""
핵심 번역 엔진 모듈
"""

import os
import re
import hashlib
import time
import logging
from typing import List, Dict, Optional, Callable
from concurrent.futures import ThreadPoolExecutor, as_completed

import ollama
from ebooklib import epub
from bs4 import BeautifulSoup
import ebooklib

logger = logging.getLogger(__name__)

DEFAULT_MODEL = "translategemma:27b"
DEFAULT_TIMEOUT = 180
DEFAULT_THREADS = 5
CACHE_DIR = os.path.expanduser("~/.translate_cache")


class Translator:
    """문서 번역기

    Args:
        model: Ollama 모델명
        host: Ollama 서버 호스트 (예: "kerniz3.mooo.com" 또는 "http://host:11434")
        threads: 병렬 번역 스레드 수
        use_cache: 번역 캐시 사용 여부
        timeout: 번역 요청 타임아웃 (초)
        retries: 실패 시 재시도 횟수
        progress_callback: 진행 콜백 함수 (completed, total) -> None

    사용 예시::

        from autotranslater import Translator

        t = Translator(model="translategemma:27b", host="my-server.com")
        t.translate_file("book.epub", "book_kr.epub")

        # HTML 번역
        t.translate_file("page.html", "page_kr.html")

        # 진행률 콜백
        t = Translator(progress_callback=lambda done, total: print(f"{done}/{total}"))
        t.translate_file("big.epub", "big_kr.epub")
    """

    def __init__(
        self,
        model: str = DEFAULT_MODEL,
        host: Optional[str] = None,
        threads: int = DEFAULT_THREADS,
        use_cache: bool = True,
        timeout: int = DEFAULT_TIMEOUT,
        retries: int = 3,
        progress_callback: Optional[Callable[[int, int], None]] = None,
    ):
        self.model = model
        self.threads = threads
        self.use_cache = use_cache
        self.timeout = timeout
        self.retries = retries
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
        if ":" not in host.replace("http://", "").replace("https://", ""):
            host = f"{host}:11434"
        logger.info(f"Ollama 서버 연결: {host}")
        return ollama.Client(host=host)

    # ------------------------------------------------------------------
    # 캐시
    # ------------------------------------------------------------------

    @staticmethod
    def _cache_key(text: str, model: str) -> str:
        return hashlib.md5(f"{model}:{text}".encode()).hexdigest()

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
        if not text.strip():
            return False
        if text.strip().startswith("```"):
            return True
        code_chars = sum(1 for c in text if c in "{}[]();=")
        if len(text) > 30 and code_chars / len(text) > 0.2:
            return True
        return False

    @staticmethod
    def _build_prompt(text: str, is_html: bool = False) -> str:
        if is_html:
            return (
                "Translate the following HTML content into Korean.\n"
                "CRITICAL: Keep all HTML tags (like <a>, <span>, <b>, <i>, <cite>, etc.) EXACTLY where they are.\n"
                "Only translate the visible text. Use a professional academic tone.\n"
                "Output ONLY the translated HTML content without any explanations.\n\n"
                f"HTML to translate:\n{text}"
            )
        return (
            "Translate the following text into professional Korean.\n"
            "Maintain technical accuracy and use an academic tone.\n"
            "Output ONLY the translated text.\n\n"
            f"Text:\n{text}"
        )

    def translate_text(self, text: str, is_html: bool = False) -> str:
        """단일 텍스트 번역

        Args:
            text: 번역할 텍스트
            is_html: HTML 태그 보존 모드

        Returns:
            번역된 텍스트. 실패 시 원본 반환.
        """
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
                result = response["message"]["content"].strip()

                if result.startswith('"') and result.endswith('"') and text.count('"') < 2:
                    result = result[1:-1]

                if self.use_cache:
                    self._save_cache(text, result)
                return result
            except Exception as e:
                if attempt == self.retries - 1:
                    logger.error(f"번역 실패: {str(e)[:100]}")
                    return text
                wait_time = 2 ** attempt
                logger.warning(f"재시도 {attempt+1}/{self.retries} ({wait_time}초 후)")
                time.sleep(wait_time)
        return text

    # ------------------------------------------------------------------
    # 파일 번역
    # ------------------------------------------------------------------

    def translate_file(self, input_path: str, output_path: str) -> bool:
        """파일 번역 (확장자 자동 감지)

        Args:
            input_path: 입력 파일 경로
            output_path: 출력 파일 경로

        Returns:
            성공 여부
        """
        ext = os.path.splitext(input_path)[1].lower()
        if ext == ".html":
            return self._translate_html(input_path, output_path)
        elif ext == ".epub":
            return self._translate_epub(input_path, output_path)
        else:
            raise ValueError(f"지원하지 않는 형식: {ext} (html, epub만 지원)")

    def _translate_html(self, input_path: str, output_path: str) -> bool:
        """HTML 번역 (병렬 + 태그 보존)"""
        with open(input_path, "r", encoding="utf-8") as f:
            soup = BeautifulSoup(f, "html.parser")

        elements = soup.find_all(
            ["p", "h1", "h2", "h3", "h4", "h5", "h6", "li", "figcaption", "title"]
        )

        targets = []
        for elem in elements:
            if not elem.find(["p", "div", "section", "article"]):
                content = "".join(str(c) for c in elem.contents).strip()
                if len(content) > 5 and not self._is_code_block(content):
                    targets.append((elem, content))

        total = len(targets)
        logger.info(f"{total}개 요소를 {self.threads} 스레드로 번역 시작")

        with ThreadPoolExecutor(max_workers=self.threads) as executor:
            future_map = {
                executor.submit(self.translate_text, content, True): (elem, content)
                for elem, content in targets
            }

            completed = 0
            for future in as_completed(future_map):
                elem, _ = future_map[future]
                try:
                    translated = future.result()
                    new_soup = BeautifulSoup(translated, "html.parser")
                    elem.clear()
                    elem.append(new_soup)
                except Exception as e:
                    logger.error(f"요소 업데이트 오류: {e}")

                completed += 1
                if self.progress_callback:
                    self.progress_callback(completed, total)

        with open(output_path, "w", encoding="utf-8") as f:
            f.write(str(soup))
        return True

    def _translate_epub(self, input_path: str, output_path: str) -> bool:
        """EPUB 번역 (챕터별 병렬 처리)"""
        book = epub.read_epub(input_path, options={"ignore_ncx": True})
        items = list(book.get_items_of_type(ebooklib.ITEM_DOCUMENT))

        # 전체 요소 수를 먼저 세서 진행률 계산
        all_targets = []
        for item in items:
            content = item.get_content().decode("utf-8")
            soup = BeautifulSoup(content, "html.parser")
            for elem in soup.find_all(["p", "h1", "h2", "h3", "li", "td"]):
                inner = "".join(str(c) for c in elem.contents).strip()
                if len(inner) > 3:
                    all_targets.append((item, elem, inner, soup))

        grand_total = len(all_targets)
        logger.info(f"총 {len(items)} 챕터, {grand_total}개 요소 번역 시작")

        # 챕터별로 처리
        global_completed = 0
        for idx, item in enumerate(items, 1):
            content = item.get_content().decode("utf-8")
            soup = BeautifulSoup(content, "html.parser")

            targets = []
            for elem in soup.find_all(["p", "h1", "h2", "h3", "li", "td"]):
                inner = "".join(str(c) for c in elem.contents).strip()
                if len(inner) > 3:
                    targets.append((elem, inner))

            if not targets:
                continue

            logger.info(f"챕터 {idx}/{len(items)} ({len(targets)}개 요소)")

            with ThreadPoolExecutor(max_workers=self.threads) as executor:
                future_map = {
                    executor.submit(self.translate_text, c, True): e
                    for e, c in targets
                }
                for future in as_completed(future_map):
                    elem = future_map[future]
                    try:
                        translated = future.result()
                        new_content = BeautifulSoup(translated, "html.parser")
                        elem.clear()
                        elem.append(new_content)
                    except Exception:
                        pass

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
    host: Optional[str] = None,
    threads: int = DEFAULT_THREADS,
    use_cache: bool = True,
) -> bool:
    """간편 함수: 파일 번역

    Args:
        input_path: 입력 파일
        output_path: 출력 파일
        model: Ollama 모델명
        host: Ollama 서버 호스트
        threads: 병렬 스레드 수
        use_cache: 캐시 사용 여부

    Returns:
        성공 여부

    사용 예시::

        from autotranslater import translate_file
        translate_file("book.epub", "book_kr.epub", host="my-server.com")
    """
    t = Translator(model=model, host=host, threads=threads, use_cache=use_cache)
    return t.translate_file(input_path, output_path)
