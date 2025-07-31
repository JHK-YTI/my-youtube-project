# services/content_analyzer.py

from collections import Counter
from konlpy.tag import Okt
import re

def analyze_content_strategy(videos_data):
    """
    상세 비디오 목록을 받아 콘텐츠 전략을 분석합니다. (현재: 키워드 분석)
    """
    if not videos_data:
        return {"error": "분석할 영상 데이터가 없습니다."}

    analysis_result = {}

    # --- 1. 인기 영상 핵심 키워드 분석 ---
    try:
        sorted_videos = sorted(
            videos_data, 
            key=lambda v: int(v.get('statistics', {}).get('viewCount', 0)), 
            reverse=True
        )

        total_videos = len(sorted_videos)
        sample_size = min(max(5, int(total_videos * 0.2)), 20)
        target_videos = sorted_videos[:sample_size]

        if not target_videos:
             analysis_result['top_keywords'] = {'error': '키워드를 분석할 영상이 부족합니다.'}
        else:
            print(f"[DEBUG] 콘텐츠 키워드 분석 시작. (대상 영상: {len(target_videos)}개)")
            okt = Okt()
            all_nouns = []
            
            title_clean_pattern = re.compile('[^가-힣 ]')
            korean_stopwords = ['shorts', '유튜브', '영상', '이유', '방법', '사람', '공개', '추천', '리뷰', '구독', '좋아요', '알림', '설정', '뉴스']

            for video in target_videos:
                title = video.get('snippet', {}).get('title', '')
                cleaned_title = title_clean_pattern.sub(' ', title)
                nouns = okt.nouns(cleaned_title)
                valuable_nouns = [noun for noun in nouns if len(noun) > 1 and noun.lower() not in korean_stopwords]
                all_nouns.extend(valuable_nouns)
            
            if all_nouns:
                keyword_counts = Counter(all_nouns)
                analysis_result['top_keywords'] = keyword_counts.most_common(15)
            else:
                analysis_result['top_keywords'] = []
            print(f"[DEBUG] 키워드 분석 완료. 상위 키워드: {analysis_result.get('top_keywords')}")

    except Exception as e:
        error_message = f"키워드 분석 중 오류 발생: {e}"
        print(f"[ERROR] services.content_analyzer.analyze_content_strategy: {error_message}")
        analysis_result['top_keywords'] = {'error': error_message}

    return analysis_result