# celery_worker.py

import sys
import os
import re 
import logging
from logging.handlers import RotatingFileHandler
import functools
import torch
import whisper 
import traceback
from celery.exceptions import Ignore

# 현재 파일의 디렉토리를 sys.path에 추가하여 모듈을 찾을 수 있도록 함
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

print("✅✅✅ Celery Worker 파일이 성공적으로 로딩되었습니다. '일꾼'이 정상 출근했습니다! ✅✅✅")

from celery import Celery
from dotenv import load_dotenv

# .env 파일에서 환경 변수 로드
load_dotenv()

# Redis URL 설정
redis_url = os.getenv("CELERY_BROKER_URL", "redis://localhost:6379/0")

# Celery 앱 인스턴스 생성
celery_app = Celery(
    'tasks',
    broker=redis_url,
    backend=redis_url
)

# Celery 설정 업데이트
celery_app.conf.update(
    timezone = 'Asia/Seoul',
    enable_utc = True,
)


def parse_benchmark_report(report_text):
    data = {"strategy": "분석 실패", "formula": "분석 실패", "action_items": "분석 실패"}
    try:
        strategy_match = re.search(r'###\s*.*?채널 핵심 성공 전략.*?\s*(.*?)(?=###|$)', report_text, re.DOTALL)
        if strategy_match:
            data['strategy'] = strategy_match.group(1).strip()

        formula_match = re.search(r'###\s*.*?인기 콘텐츠 공식 분석.*?\s*(.*?)(?=###|$)', report_text, re.DOTALL)
        if formula_match:
            data['formula'] = formula_match.group(1).strip()

        action_items_match = re.search(r'###\s*.*?내 채널에 적용할 3가지 액션 아이템.*?\s*(.*?)(?=###|$)', report_text, re.DOTALL)
        if action_items_match:
            data['action_items'] = action_items_match.group(1).strip()
            
    except Exception as e:
        logging.error(f"벤치마킹 리포트 파싱 중 오류: {e}")
        data['strategy'] = "AI 응답을 해석하는 중 오류가 발생했습니다."
    return data

def setup_task_logger(logger_name, log_file_name):
    logger = logging.getLogger(logger_name)
    if not logger.handlers:
        logger.setLevel(logging.INFO)
        formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
        
        log_dir = os.path.join(os.path.dirname(__file__), 'logs')
        os.makedirs(log_dir, exist_ok=True)
        log_file_path = os.path.join(log_dir, log_file_name)

        file_handler = RotatingFileHandler(log_file_path, maxBytes=1024 * 1024 * 5, backupCount=2, encoding='utf-8')
        file_handler.setFormatter(formatter)
        logger.addHandler(file_handler)
        
        console_handler = logging.StreamHandler()
        console_handler.setFormatter(formatter)
        logger.addHandler(console_handler)
    return logger

@celery_app.task
def add(x, y):
    return x + y

@celery_app.task(bind=True)
def rewrite_script_task(self, original_script, category, title, original_task_id=None, user_id=None):
    from services import ai_service
    from prompt_templates import REWRITE_PROMPTS 

    task_logger = setup_task_logger(f'rewrite_script_task_{self.request.id}', 'rewrite_errors.log')
    
    task_logger.info(f"V12 각색 작업 시작. 전달된 카테고리: '{category}'")

    if category not in REWRITE_PROMPTS:
        error_message = f"'{category}'는 지원하지 않는 V12 각색 카테고리입니다. 사용 가능한 키: {list(REWRITE_PROMPTS.keys())}"
        task_logger.error(error_message)
        raise ValueError(error_message)

    try:
        self.update_state(state='PROGRESS', meta={'status': 'AI가 각색을 시작했습니다...'})
        rewritten_script = ai_service.rewrite_script_v12(original_script, category)
        
        result_data = {
            'final_script': rewritten_script,
            'original_script': original_script,
            'title': title,
            'original_task_id': original_task_id
        }
        return {'status': 'Complete', 'result': result_data, 'name': self.name, 'kwargs': {'user_id': user_id}}
    except Exception as e:
        task_logger.error(f"Task rewrite_script_task FAILED: {str(e)}\n{traceback.format_exc()}")
        raise Exception(f"V12 각색 작업 중 오류 발생: {type(e).__name__}")

@celery_app.task(bind=True)
def rewrite_script_v13_task(self, original_script, category, title, original_task_id=None, user_id=None):
    from services import ai_service
    
    task_logger = setup_task_logger(f'rewrite_script_v13_task_{self.request.id}', 'rewrite_v13_errors.log')
    task_logger.info(f"V13 안전 각색 작업 시작. 카테고리: '{category}'")

    try:
        self.update_state(state='PROGRESS', meta={'status': 'AI가 원본을 교정하고 있습니다... (1/2)'})
        
        v13_result = ai_service.rewrite_script_v13_safe(original_script, category)
        
        if v13_result.get("error"):
            raise Exception(v13_result["error"])

        self.update_state(state='PROGRESS', meta={'status': 'AI가 창의적인 각색을 진행 중입니다... (2/2)'})

        result_data = {
            'final_script': v13_result.get('final_script'),
            'original_script': v13_result.get('original_script'), 
            'corrected_script': v13_result.get('corrected_script'), 
            'title': title,
            'original_task_id': original_task_id
        }
        
        return {'status': 'Complete', 'result': result_data, 'name': self.name, 'kwargs': {'user_id': user_id}}

    except Exception as e:
        task_logger.error(f"Task rewrite_script_v13_task FAILED: {str(e)}\n{traceback.format_exc()}")
        raise Exception(f"V13 안전 각색 작업 중 오류 발생: {type(e).__name__}")

@celery_app.task(bind=True)
def analyze_text_task(self, script_content, filename, user_id=None):
    from services import ai_service
    task_logger = setup_task_logger(f'analyze_text_task_{self.request.id}', 'analysis_errors.log')
    try:
        def update_progress(message, step, total_steps):
            meta = {'status': message, 'current': step, 'total': total_steps}
            self.update_state(state='PROGRESS', meta=meta)

        update_progress('AI가 대본의 오타를 교정하고 있습니다...', 1, 3)
        corrected_script = ai_service.correct_transcript(script_content)
        
        update_progress('AI가 대본의 인기 요인을 분석하고 있습니다...', 2, 3)
        analysis_summary = ai_service.analyze_transcript(corrected_script)
        
        video_info = {
            'video_id': f'user_upload_{self.request.id}',
            'title': filename,
            'uploader': '사용자 업로드',
            'upload_date': None,
            'view_count': None,
            'like_count': None,
            'comment_count': None,
            'thumbnail_url': None,
            'duration': None,
        }
        
        update_progress('분석 완료! 결과를 정리하고 있습니다.', 3, 3)
        final_result = {
            **video_info, 
            'original_script': corrected_script, 
            'analysis_summary': analysis_summary, 
            'top_comments': [{'error': '텍스트 입력의 경우 댓글을 분석할 수 없습니다.'}]
        }
        
        return {'status': 'SUCCESS', 'result': final_result, 'name': self.name, 'kwargs': {'user_id': user_id}}

    except Exception as e:
        task_logger.error(f"Task analyze_text_task FAILED: {str(e)}\n{traceback.format_exc()}")
        raise Exception(f"텍스트 분석 작업 실패: {type(e).__name__}")

@celery_app.task(bind=True)
def extract_and_analyze_task(self, youtube_link, user_id=None):
    from services.youtube_extractor import YouTubeDataExtractor
    from services import ai_service
    task_logger = setup_task_logger(f'extract_and_analyze_task_{self.request.id}', 'extraction_errors.log')
    try:
        def update_progress(message, step, total_steps):
            meta = {'status': message, 'current': step, 'total': total_steps}
            self.update_state(state='PROGRESS', meta=meta)

        @functools.lru_cache(maxsize=1)
        def get_whisper_model_in_worker():
            device = "cuda" if torch.cuda.is_available() else "cpu"
            model = whisper.load_model("medium", device=device)
            return model

        update_progress('영상 정보 및 자막 추출 중...', 1, 5)
        extractor = YouTubeDataExtractor(whisper_model_loader=get_whisper_model_in_worker)
        video_info, transcript_text = extractor.extract_video_info_and_transcript(youtube_link)
        
        if transcript_text.startswith("⚠️"):
            raise Exception(transcript_text)

        update_progress('AI가 대본의 오타를 교정하고 있습니다...', 2, 5)
        corrected_script = ai_service.correct_transcript(transcript_text)
        
        update_progress('AI가 영상의 인기 요인을 분석하고 있습니다...', 3, 5)
        analysis_summary = ai_service.analyze_transcript(corrected_script)
        
        update_progress('영상에 대한 시청자 반응(베스트 댓글)을 수집합니다...', 4, 5)
        top_comments = []
        video_id = video_info.get('video_id')
        if video_id and not video_id.startswith('user_upload_'):
            top_comments = YouTubeDataExtractor().get_top_comments(video_id)

        update_progress('분석 완료! 결과를 정리하고 있습니다.', 5, 5)
        final_result = {**video_info, 'original_script': corrected_script, 'analysis_summary': analysis_summary, 'top_comments': top_comments}
        
        return {'status': 'SUCCESS', 'result': final_result, 'name': self.name, 'kwargs': {'user_id': user_id}}
    except Exception as e:
        import traceback
        tb_str = traceback.format_exc()
        print("\n\n================ CATASTROPHIC ERROR TRACEBACK ================")
        print(tb_str)
        print("============================================================\n\n")
        task_logger.error(f"Task extract_and_analyze_task FAILED: {str(e)}\n{tb_str}")
        raise Exception(f"유튜브 영상 분석 작업 실패: {type(e).__name__}: {e}\n\n--- TRACEBACK ---\n{tb_str}")

@celery_app.task(bind=True)
def analyze_channel_task(self, channel_url, user_id=None):
    from services.youtube_extractor import YouTubeDataExtractor
    from services import calculator, content_analyzer, ai_service
    
    task_logger = setup_task_logger(f'channel_analysis_{self.request.id}', 'channel_analysis.log')
    task_logger.info(f"--- [TASK START] 채널 분석 시작 (AI 리포트 포함): {channel_url} ---")
    
    def update_progress(message):
        meta = {'status': message}
        self.update_state(state='PROGRESS', meta=meta)
        task_logger.info(message)

    try:
        @functools.lru_cache(maxsize=1)
        def get_whisper_model_in_worker():
            device = "cuda" if torch.cuda.is_available() else "cpu"
            model = whisper.load_model("medium", device=device)
            return model

        update_progress('채널 기본 데이터 추출 중... (1/5)')
        extractor = YouTubeDataExtractor(whisper_model_loader=get_whisper_model_in_worker)
        channel_info = extractor.extract_channel_info(channel_url)
        if 'error' in channel_info:
            raise Exception(f"채널 정보 추출 실패: {channel_info['error']}")

        update_progress('예상 수익 계산 중... (2/5)')
        revenue_info = calculator.estimate_monthly_revenue(channel_info)

        update_progress('콘텐츠 전략 분석 중... (3/5)')
        content_info = content_analyzer.analyze_content_strategy(channel_info.get('videos_data', []))
        
        task_logger.info("인기 동영상 정보 추가 시작...")
        channel_id = extractor._get_channel_id(channel_url)
        if channel_id:
            popular_videos = extractor.get_popular_videos(channel_id, max_results=5)
            channel_info['popular_videos'] = popular_videos
        else:
            task_logger.warning("채널 ID를 찾을 수 없어 인기 동영상 정보를 추가하지 못했습니다.")
            popular_videos = []
            channel_info['popular_videos'] = []
        
        update_progress('AI 벤치마킹 리포트 생성 중... (4/5)')
        report_html = {}
        try:
            channel_stats_text = f"채널명: {channel_info.get('channel_title')} (구독자: {channel_info.get('subscriber_count')}), 최근 3개월 조회수: {channel_info.get('recent_3_month_views')}"
            top_video_titles = "\n".join([f"- {v['title']}" for v in popular_videos])
            
            task_logger.info("리포트 생성을 위해 인기 영상 대본 추출 시작...")
            top_video_summaries = []
            for video in popular_videos[:5]: 
                video_url = f"https://www.youtube.com/watch?v=N7OEaDJQG3c6"
                
                _, transcript = extractor.extract_video_info_and_transcript(video_url)
                
                if transcript.startswith("⚠️"):
                    summary = video['title'] 
                else:
                    summary = ai_service.summarize_script(transcript)
                top_video_summaries.append(summary)
            
            top_video_transcripts_text = "\n".join(top_video_summaries)
            task_logger.info("인기 영상 대본 요약 완료. AI 리포트 생성 요청.")

            report_text = ai_service.generate_benchmark_report(
                channel_stats=channel_stats_text,
                top_video_titles=top_video_titles,
                top_video_transcripts=top_video_transcripts_text
            )
            
            report_html = parse_benchmark_report(report_text)
            task_logger.info("AI 벤치마킹 리포트 생성 완료.")

        except Exception as e:
            task_logger.error(f"AI 벤치마킹 리포트 생성 중 오류 발생: {e}", exc_info=True)
            report_html = {"strategy": "AI 리포트를 생성하는 중 오류가 발생했습니다.", "formula": "", "action_items": ""}
        
        update_progress('최종 결과 취합 중... (5/5)')
        final_result = {
            'channel_info': channel_info, 
            'revenue_info': revenue_info, 
            'content_info': content_info,
            'report_html': report_html 
        }
        
        task_logger.info(f"--- [TASK SUCCESS] 채널 분석 전체 완료: {channel_url} ---")
        return {'status': 'SUCCESS', 'result': final_result, 'name': self.name, 'kwargs': {'user_id': user_id}}

    except Exception as e:
        task_logger.error(f"--- [TASK FAILURE] 채널 분석 중 심각한 오류 발생: {e} ---", exc_info=True)
        raise Exception(f"채널 분석 작업 실패: {type(e).__name__}")

@celery_app.task(bind=True)
def generate_planned_script_task(self, options, user_id=None):
    from services import ai_service
    
    task_logger = setup_task_logger(f'planned_script_{self.request.id}', 'planned_script.log')
    task_logger.info(f"--- [TASK START] 상세 기획 대본 생성 시작: {options} ---")
    
    try:
        self.update_state(state='PROGRESS', meta={'status': 'AI가 요청하신 조건에 맞춰 대본 패키지를 구상 중입니다...'})
        
        planned_result = ai_service.generate_planned_script(options)
        
        if planned_result.get("error"):
            raise Exception(planned_result["error"])
        
        result_data = {
            'options': options,
            **planned_result
        }
        
        task_logger.info(f"--- [TASK SUCCESS] 상세 기획 대본 생성 완료 ---")
        return {'status': 'SUCCESS', 'result': result_data, 'name': self.name, 'kwargs': {'user_id': user_id}}
        
    except Exception as e:
        task_logger.error(f"--- [TASK FAILURE] 상세 기획 대본 생성 중 오류 발생: {e} ---", exc_info=True)
        raise Exception(f"상세 기획 대본 생성 실패: {type(e).__name__}")