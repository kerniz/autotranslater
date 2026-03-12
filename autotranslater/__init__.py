"""
autotranslater - AI 기반 문서 자동 번역 패키지
Ollama를 활용한 EPUB, HTML 파일 번역
"""

__version__ = "0.2.0"

from autotranslater.translator import Translator, translate_file

__all__ = ["Translator", "translate_file"]
