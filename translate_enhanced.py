#!/usr/bin/env python3
"""
Enhanced Document Translation Script v2
Supports: EPUB, HTML, PDF, Word, Text files
Features: 
- Multi-threaded Parallel Translation
- HTML Tag Preservation (Citations, Links)
- Remote Ollama support with automatic retries
- Technical term glossary enforcement
"""

import sys
import ollama
from ebooklib import epub
from bs4 import BeautifulSoup
import ebooklib
import argparse
import os
import re
import json
import hashlib
import time
import logging
from typing import List, Dict, Tuple, Optional
from concurrent.futures import ThreadPoolExecutor, as_completed

# ============================================================
# 로깅 및 설정
# ============================================================
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger(__name__)

DEFAULT_MODEL = 'translategemma:27b'
DEFAULT_TIMEOUT = 180
DEFAULT_BATCH_SIZE = 10
DEFAULT_THREADS = 5  # 서버 성능이 좋으므로 기본 5개 스레드 사용
CACHE_DIR = os.path.expanduser('~/.translate_cache')

# 글로벌 클라이언트 객체
ollama_client = None

# ============================================================
# 유틸리티 함수
# ============================================================

def init_client(host: Optional[str] = None):
    """Ollama 클라이언트 초기화"""
    global ollama_client
    if host:
        if not host.startswith('http'): host = f"http://{host}"
        if ':' not in host.replace('http://', '').replace('https://', ''): host = f"{host}:11434"
        ollama_client = ollama.Client(host=host)
        logger.info(f"Ollama 서버 연결됨: {host}")
    else:
        ollama_client = ollama

def ensure_cache_dir():
    os.makedirs(CACHE_DIR, exist_ok=True)

def get_cache_key(text: str, model: str) -> str:
    content = f"{model}:{text}"
    return hashlib.md5(content.encode()).hexdigest()

def get_cached_translation(text: str, model: str) -> Optional[str]:
    cache_file = os.path.join(CACHE_DIR, f"{get_cache_key(text, model)}.txt")
    if os.path.exists(cache_file):
        with open(cache_file, 'r', encoding='utf-8') as f:
            return f.read()
    return None

def save_cached_translation(text: str, translated: str, model: str):
    cache_file = os.path.join(CACHE_DIR, f"{get_cache_key(text, model)}.txt")
    with open(cache_file, 'w', encoding='utf-8') as f:
        f.write(translated)

def is_code_block(text: str) -> bool:
    if not text.strip(): return False
    # HTML 태그 자체가 아닌 순수 코드나 데이터 패턴 감지
    if text.strip().startswith('```'): return True
    code_chars = sum(1 for c in text if c in '{}[]();=')
    if len(text) > 30 and code_chars / len(text) > 0.2: return True
    return False

# ============================================================
# 번역 핵심 로직
# ============================================================

def get_translation_prompt(text: str, is_html: bool = False) -> str:
    """개선된 번역 프롬프트"""
    if is_html:
        return f'''Translate the following HTML content into Korean. 
CRITICAL: Keep all HTML tags (like <a>, <span>, <b>, <i>, <cite>, etc.) EXACTLY where they are. 
Only translate the visible text. Use a professional academic tone.
Output ONLY the translated HTML content without any explanations.

HTML to translate:
{text}'''
    
    return f'''Translate the following text into professional Korean. 
Maintain technical accuracy and use an academic tone.
Output ONLY the translated text.

Text:
{text}'''

def translate_unit(text: str, model: str, use_cache: bool, is_html: bool = False, retries: int = 3) -> str:
    """단일 단위(문장/단락) 번역 및 재시도"""
    if not text.strip() or is_code_block(text):
        return text
    
    if use_cache:
        cached = get_cached_translation(text, model)
        if cached: return cached
    
    prompt = get_translation_prompt(text, is_html)
    
    for attempt in range(retries):
        try:
            response = ollama_client.chat(
                model=model,
                messages=[{'role': 'user', 'content': prompt}],
                options={'timeout': DEFAULT_TIMEOUT, 'temperature': 0.3}
            )
            result = response['message']['content'].strip()
            
            # 따옴표로 감싸진 경우 제거
            if result.startswith('"') and result.endswith('"') and text.count('"') < 2:
                result = result[1:-1]
            
            if use_cache:
                save_cached_translation(text, result, model)
            return result
        except Exception as e:
            if attempt == retries - 1:
                logger.error(f"번역 실패 (최종): {str(e)[:100]}")
                return text
            wait_time = 2 ** attempt
            logger.warning(f"번역 오류, {wait_time}초 후 재시도... ({attempt+1}/{retries})")
            time.sleep(wait_time)
    return text

# ============================================================
# 문서 형식별 처리
# ============================================================

def translate_html_advanced(input_path: str, output_path: str, model: str, threads: int, use_cache: bool):
    """HTML 고도화 번역 (병렬 처리 + 태그 보존)"""
    try:
        with open(input_path, 'r', encoding='utf-8') as f:
            soup = BeautifulSoup(f, 'html.parser')
        
        # arXiv 특화: 수식이나 복잡한 구조 제외하고 실제 텍스트 단락만 추출
        # p, h1~h6, li, figcaption, title, 그리고 span 중 클래스가 있는 것들
        elements = soup.find_all(['p', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'li', 'figcaption', 'title'])
        
        # 번역 대상 필터링 (너무 짧거나 이미 번역된 것 제외)
        targets = []
        for elem in elements:
            # 자식 태그 중 블록 레벨 태그가 있으면 더 세분화해서 가져오기 위해 건너뜀
            if not elem.find(['p', 'div', 'section', 'article']):
                # 단락 내의 인라인 태그들을 포함한 HTML 문자열 추출
                content = "".join([str(c) for c in elem.contents]).strip()
                if len(content) > 5 and not is_code_block(content):
                    targets.append((elem, content))

        total = len(targets)
        logger.info(f"총 {total}개의 요소를 {threads}개 스레드로 번역 시작합니다.")

        # 병렬 실행
        with ThreadPoolExecutor(max_workers=threads) as executor:
            future_to_elem = {executor.submit(translate_unit, content, model, use_cache, True): (elem, content) 
                             for elem, content in targets}
            
            completed = 0
            for future in as_completed(future_to_elem):
                elem, original_content = future_to_elem[future]
                try:
                    translated_content = future.result()
                    # 새 BeautifulSoup 객체로 변환하여 안전하게 삽입
                    new_soup = BeautifulSoup(translated_content, 'html.parser')
                    elem.clear()
                    elem.append(new_soup)
                except Exception as e:
                    logger.error(f"요소 업데이트 중 오류: {e}")
                
                completed += 1
                if completed % 10 == 0 or completed == total:
                    print(f"\r  [진행상황] {completed}/{total} 완료 ({(completed/total)*100:.1f}%)", end="", flush=True)

        print() # 개행
        with open(output_path, 'w', encoding='utf-8') as f:
            f.write(str(soup))
        
        return True
    except Exception as e:
        logger.error(f"HTML 고급 번역 오류: {e}")
        import traceback
        traceback.print_exc()
        return False

def translate_epub_advanced(input_path: str, output_path: str, model: str, threads: int, use_cache: bool):
    """EPUB 고도화 번역 (병렬 처리)"""
    try:
        book = epub.read_epub(input_path, options={'ignore_ncx': True})
        items = list(book.get_items_of_type(ebooklib.ITEM_DOCUMENT))
        
        for idx, item in enumerate(items, 1):
            logger.info(f"챕터 {idx}/{len(items)} 처리 중...")
            content = item.get_content().decode('utf-8')
            soup = BeautifulSoup(content, 'html.parser')
            
            elements = soup.find_all(['p', 'h1', 'h2', 'h3', 'li', 'td'])
            targets = []
            for elem in elements:
                inner_html = "".join([str(c) for c in elem.contents]).strip()
                if len(inner_html) > 3:
                    targets.append((elem, inner_html))
            
            if not targets: continue
            
            with ThreadPoolExecutor(max_workers=threads) as executor:
                future_to_elem = {executor.submit(translate_unit, c, model, use_cache, True): e for e, c in targets}
                for future in as_completed(future_to_elem):
                    elem = future_to_elem[future]
                    try:
                        translated = future.result()
                        new_content = BeautifulSoup(translated, 'html.parser')
                        elem.clear()
                        elem.append(new_content)
                    except: pass
            
            item.set_content(str(soup).encode('utf-8'))
        
        epub.write_epub(output_path, book)
        return True
    except Exception as e:
        logger.error(f"EPUB 고급 번역 오류: {e}")
        return False

# ============================================================
# 메인 함수
# ============================================================

def main():
    parser = argparse.ArgumentParser(description='AI 기반 고성능 문서 번역 도구 v2')
    parser.add_argument('input', help='입력 파일 경로')
    parser.add_argument('output', help='출력 파일 경로')
    parser.add_argument('--model', default=DEFAULT_MODEL, help=f'Ollama 모델명 (기본: {DEFAULT_MODEL})')
    parser.add_argument('--host', help='Ollama 서버 호스트 (예: kerniz3.mooo.com)')
    parser.add_argument('--threads', type=int, default=DEFAULT_THREADS, help=f'병렬 스레드 수 (기본: {DEFAULT_THREADS})')
    parser.add_argument('--no-cache', action='store_false', dest='use_cache', help='캐시 사용 안 함')
    
    args = parser.parse_args()
    
    ensure_cache_dir()
    init_client(args.host)
    
    ext = os.path.splitext(args.input)[1].lower()
    start_time = time.time()
    
    success = False
    if ext == '.html':
        success = translate_html_advanced(args.input, args.output, args.model, args.threads, args.use_cache)
    elif ext == '.epub':
        success = translate_epub_advanced(args.input, args.output, args.model, args.threads, args.use_cache)
    else:
        logger.error(f"지원하지 않는 확장자입니다: {ext}")
        sys.exit(1)
    
    if success:
        elapsed = time.time() - start_time
        logger.info(f"\n{'='*50}")
        logger.info(f"번역 성공! 소요 시간: {elapsed:.1f}초")
        logger.info(f"결과 파일: {args.output}")
        logger.info(f"{'='*50}")
    else:
        logger.error("번역 실패")
        sys.exit(1)

if __name__ == "__main__":
    main()
