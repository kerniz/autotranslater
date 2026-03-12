"""
CLI 엔트리포인트
"""

import sys
import os
import time
import logging
import argparse

from autotranslater.translator import (
    Translator,
    DEFAULT_MODEL,
    DEFAULT_HOST,
    DEFAULT_THREADS,
    DEFAULT_LANG,
)


def main():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        handlers=[logging.StreamHandler(sys.stdout)],
    )

    parser = argparse.ArgumentParser(
        description="AI 기반 문서 자동 번역 도구 (Ollama)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""사용 예시:
  autotranslate book.epub book_kr.epub
  autotranslate page.html page_kr.html --host other-server.com
  autotranslate doc.epub doc_ja.epub --lang Japanese --threads 8

환경변수로 기본값 변경 가능:
  AUTOTRANSLATE_MODEL, AUTOTRANSLATE_HOST, AUTOTRANSLATE_THREADS,
  AUTOTRANSLATE_LANG, AUTOTRANSLATE_TIMEOUT, AUTOTRANSLATE_CACHE_DIR
""",
    )
    parser.add_argument("input", help="입력 파일 경로 (epub, html)")
    parser.add_argument("output", help="출력 파일 경로")
    parser.add_argument("--model", default=DEFAULT_MODEL, help=f"Ollama 모델명 (기본: {DEFAULT_MODEL})")
    parser.add_argument("--host", default=DEFAULT_HOST, help=f"Ollama 서버 호스트 (기본: {DEFAULT_HOST})")
    parser.add_argument("--threads", type=int, default=DEFAULT_THREADS, help=f"병렬 스레드 수 (기본: {DEFAULT_THREADS})")
    parser.add_argument("--lang", default=DEFAULT_LANG, help=f"번역 대상 언어 (기본: {DEFAULT_LANG})")
    parser.add_argument("--no-cache", action="store_true", help="캐시 사용 안 함")

    args = parser.parse_args()

    def show_progress(completed, total):
        pct = completed / total * 100 if total else 0
        print(f"\r  [{completed}/{total}] {pct:.1f}%", end="", flush=True)
        if completed == total:
            print()

    t = Translator(
        model=args.model,
        host=args.host,
        threads=args.threads,
        use_cache=not args.no_cache,
        target_lang=args.lang,
        progress_callback=show_progress,
    )

    start = time.time()
    try:
        success = t.translate_file(args.input, args.output)
    except (ValueError, FileNotFoundError, OSError) as e:
        print(f"오류: {e}")
        sys.exit(1)

    if success:
        elapsed = time.time() - start
        print(f"번역 완료! ({elapsed:.1f}초) -> {args.output}")
    else:
        print("번역 실패")
        sys.exit(1)


if __name__ == "__main__":
    main()
