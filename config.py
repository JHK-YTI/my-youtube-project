# config.py

# =================================================================
# ▼▼▼▼▼ V12.10 최종 엔진: 안정성 강화 ▼▼▼▼▼
# =================================================================

# OpenAI 모델 설정
PREMIUM_MODEL = 'gpt-4-turbo'
STANDARD_MODEL = 'gpt-3.5-turbo'
FAST_MODEL = 'gpt-3.5-turbo' # 사전 분석 등 빠른 작업에 사용

# 각색 카테고리별 온도 설정
TEMPERATURE_CONFIG = {
    'ssultoon': 0.8,
    'community': 0.7,
    'top_n': 0.6,
    'knowledge': 0.5,
    'review': 0.7
}

# Gemini 모델 설정 (안정적인 모델명으로 변경)
GEMINI_MODEL_NAME = 'gemini-1.0-pro'