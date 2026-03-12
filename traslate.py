#!/usr/bin/env python3
"""
EPUB 번역 스크립트
사용법: python translate_epub.py input.epub output.epub [모델이름]
"""

import sys
import ollama
from ebooklib import epub
from bs4 import BeautifulSoup
import ebooklib
import argparse
import os
import signal

# 타임아웃 핸들러
def timeout_handler(signum, frame):
    raise TimeoutError("번역 요청 타임아웃")

def translate_text(text, model='translategemma:27b', timeout=120):
    """텍스트 번역"""
    if not text.strip():
        return text
    
    prompt = f'''다음 영어 텍스트를 자연스러운 한국어로 번역해주세요. 
 문학적 표현과 맥락을 유지하면서 번역하세요. 번역문만 출력하세요.
 책의 내용만 번역하세요. 제목은 영문과 한글 병기해주세요.

 {text}'''
    
    try:
        response = ollama.chat(
            model=model, 
            messages=[{
                'role': 'user',
                'content': prompt
            }],
            options={'timeout': timeout}
        )
        return response['message']['content']
    except Exception as e:
        print(f"번역 오류: {e}")
        return text

def translate_batch(texts, model='translategemma:27b', timeout=180):
    if not texts:
        return []
    
    combined = '\n---\n'.join(texts)
    prompt = f'''다음 영어 텍스트들을 한국어로 번역하세요. 
각 단락은 ---로 구분되어 있습니다. 같은 형식으로 번역문을 출력하세요.

{combined}'''
    
    try:
        response = ollama.chat(
            model=model, 
            messages=[{
                'role': 'user',
                'content': prompt
            }],
            options={'timeout': timeout}
        )
        return response['message']['content'].split('---')
    except Exception as e:
        print(f"배치 번역 오류: {e}")
        return texts

def translate_epub(input_path, output_path, model='translategemma:27b', batch_size=10):
    """EPUB 파일 번역"""
    
    # 입력 파일 확인
    if not os.path.exists(input_path):
        print(f"❌ 오류: 입력 파일을 찾을 수 없습니다: {input_path}")
        return False
    
    # 출력 디렉토리 생성
    output_dir = os.path.dirname(output_path)
    if output_dir and not os.path.exists(output_dir):
        os.makedirs(output_dir)
        print(f"✓ 출력 디렉토리 생성: {output_dir}")
    
    print(f"\n{'='*60}")
    print(f"📖 EPUB 번역 시작")
    print(f"{'='*60}")
    print(f"입력: {input_path}")
    print(f"출력: {output_path}")
    print(f"모델: {model}")
    print(f"배치 크기: {batch_size}")
    print(f"{'='*60}\n")
    
    try:
        # EPUB 로드
        print("📂 EPUB 파일 로딩 중...")
        book = epub.read_epub(input_path)
        
        # 메타데이터 번역
        title = book.get_metadata('DC', 'title')
        if title:
            print(f"📝 제목 번역 중: {title[0][0]}")
            translated_title = translate_text(title[0][0], model)
            book.set_title(translated_title)
            print(f"   → {translated_title}")
        
        # 챕터 가져오기
        items = list(book.get_items_of_type(ebooklib.ITEM_DOCUMENT))
        total_chapters = len(items)
        print(f"\n📚 총 {total_chapters}개 챕터 발견\n")
        
        for idx, item in enumerate(items, 1):
            try:
                item.uid = f"chapter_{idx}"
            except:
                pass
            print(f"[{idx}/{total_chapters}] 챕터 번역 중...")
            
            content = item.get_content().decode('utf-8')
            soup = BeautifulSoup(content, 'html.parser')
            paragraphs = soup.find_all(['p', 'h1', 'h2', 'h3'])
            
            # 배치로 모으기
            batch = []
            batch_elements = []
            para_count = 0
            
            for p in paragraphs:
                text = p.get_text().strip()
                if text and len(text) > 1:
                    batch.append(text)
                    batch_elements.append(p)
                    para_count += 1
                    
                    if len(batch) >= batch_size:
                        translated = translate_batch(batch, model)
                        for elem, trans in zip(batch_elements, translated):
                            elem.clear()
                            elem.insert(0, trans.strip())
                        print(f"  ✓ {para_count}개 단락 번역 완료")
                        batch = []
                        batch_elements = []
            
            if batch:
                translated = translate_batch(batch, model)
                for elem, trans in zip(batch_elements, translated):
                    elem.clear()
                    elem.insert(0, trans.strip())
                print(f"  ✓ {para_count}개 단락 번역 완료")
            
            item.set_content(str(soup).encode('utf-8'))
        
        print(f"\n💾 중간 저장 중...")
        book.toc = []
        epub.write_epub(output_path, book)
        
        print(f"\n💾 번역된 EPUB 저장 중: {output_path}")
        epub.write_epub(output_path, book)
        
        # 완료
        print(f"\n{'='*60}")
        print(f"✅ 번역 완료!")
        print(f"{'='*60}")
        print(f"저장 위치: {os.path.abspath(output_path)}")
        print(f"파일 크기: {os.path.getsize(output_path) / (1024*1024):.2f} MB")
        print(f"{'='*60}\n")
        
        return True
        
    except Exception as e:
        print(f"\n❌ 오류 발생: {e}")
        import traceback
        traceback.print_exc()
        return False

def main():
    # 커맨드라인 인자 파서
    parser = argparse.ArgumentParser(
        description='EPUB 파일을 한국어로 번역합니다.',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog='''
사용 예시:
  python translate_epub.py book.epub book_kr.epub
  python translate_epub.py input.epub output.epub qwen2.5:3b
  python translate_epub.py /path/to/book.epub /path/to/translated.epub
        '''
    )
    
    parser.add_argument('input', help='입력 EPUB 파일 경로')
    parser.add_argument('output', help='출력 EPUB 파일 경로')
    parser.add_argument('model', nargs='?', default='translategemma:27b',
                       help='사용할 Ollama 모델 (기본값: qwen2.5:3b)')
    parser.add_argument('--batch-size', type=int, default=10,
                       help='배치 크기 (기본값: 10)')
    
    args = parser.parse_args()
    
    # 번역 실행
    success = translate_epub(
        args.input,
        args.output,
        model=args.model,
        batch_size=args.batch_size
    )
    
    sys.exit(0 if success else 1)

if __name__ == "__main__":
    main()
