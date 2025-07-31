# services/youtube_extractor.py

import yt_dlp
import whisper
import os
import re
from datetime import datetime, timedelta
from googleapiclient.discovery import build
from dateutil.parser import isoparse
import sys
import time
import io
from pydub import AudioSegment

def _clean_youtube_id_from_url(url):
    if not url: return None
    matches = re.findall(r'([\w-]{11})', str(url))
    if matches:
        valid_ids = [match for match in matches if len(match) == 11]
        if valid_ids:
            return valid_ids[-1]
    return None

class YouTubeDataExtractor:
    def __init__(self, whisper_model_loader=None):
        self.whisper_model_loader = whisper_model_loader
        self.youtube_service = None

    def _initialize_youtube_service(self):
        if self.youtube_service is None:
            youtube_api_key = os.getenv("GOOGLE_API_KEY")
            if not youtube_api_key: print("경고: GOOGLE_API_KEY 환경 변수가 설정되지 않았습니다.")
            else:
                try:
                    self.youtube_service = build('youtube', 'v3', developerKey=youtube_api_key)
                    print("[DEBUG] YouTube Data API 서비스가 성공적으로 초기화되었습니다.")
                except Exception as e:
                    print(f"[ERROR] YouTube Data API 서비스 초기화 중 오류 발생: {e}")
                    self.youtube_service = None

    def extract_video_info_and_transcript(self, youtube_link):
        clean_youtube_link = youtube_link

        if '[' in str(youtube_link) and ']' in str(youtube_link):
            print(f"--- [DEBUG] 오염된 링크 감지. 정제를 시도합니다: {youtube_link} ---")
            video_id = _clean_youtube_id_from_url(youtube_link)
            if video_id:
                clean_youtube_link = f"https://www.youtube.com/watch?v={video_id}"

        self._initialize_youtube_service()
        
        video_info = {}
        transcript_text = ""
        audio_file_path = None

        try:
            # ▼▼▼▼▼ [핵심 수정] yt-dlp 요청 옵션에 '브라우저 위장' 헤더 추가 ▼▼▼▼▼
            ydl_opts_info = {
                'cachedir': False,
                'verbose': False,
                'quiet': True,
                'no_warnings': True,
                'skip_download': True,
                'simulate': True,
                'http_headers': {
                    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36',
                    'Accept-Language': 'en-US,en;q=0.5'
                }
            }
            # ▲▲▲▲▲ [핵심 수정] ▲▲▲▲▲
            
            print(f"\n--- [DEBUG] 영상 메타데이터 추출 시작: {clean_youtube_link} ---")
            with yt_dlp.YoutubeDL(ydl_opts_info) as ydl:
                info_dict_meta = ydl.extract_info(clean_youtube_link, download=False)
                video_info = {
                    'video_id': info_dict_meta.get('id'), 'title': info_dict_meta.get('title'),
                    'uploader': info_dict_meta.get('uploader'), 'upload_date': info_dict_meta.get('upload_date'),
                    'view_count': info_dict_meta.get('view_count'), 'like_count': info_dict_meta.get('like_count'),
                    'comment_count': info_dict_meta.get('comment_count'), 'thumbnail_url': info_dict_meta.get('thumbnail'),
                    'duration': info_dict_meta.get('duration'),
                }
                if video_info.get('upload_date') and len(video_info['upload_date']) == 8:
                    video_info['upload_date'] = f"{video_info['upload_date'][:4]}-{video_info['upload_date'][4:6]}-{video_info['upload_date'][6:]}"
            print(f"--- [DEBUG] 영상 메타데이터 추출 완료 ---")

            print("--- [DEBUG] (속도 개선) 자막 파일 우선 추출 시도 ---")
            try:
                ydl_opts_subtitle = {
                    'writesubtitles': True, 'subtitleslangs': ['ko'],
                    'skip_download': True, 'cachedir': False,
                    'verbose': False, 'quiet': True, 'no_warnings': True,
                }
                with yt_dlp.YoutubeDL(ydl_opts_subtitle) as ydl_sub:
                    info_dict_sub = ydl_sub.extract_info(clean_youtube_link, download=False)
                    
                    subtitles = info_dict_sub.get('subtitles', {}).get('ko') or \
                                info_dict_sub.get('automatic_captions', {}).get('ko')
                                
                    if subtitles:
                        vtt_subtitle = next((s for s in subtitles if s['ext'] == 'vtt'), subtitles[-1])
                        subtitle_url = vtt_subtitle['url']
                        
                        import urllib.request
                        with urllib.request.urlopen(subtitle_url) as response:
                            vtt_content = response.read().decode('utf-8')
                            
                            lines = vtt_content.splitlines()
                            transcript_parts = []
                            
                            for line in lines:
                                if '-->' in line or line.strip().isdigit() or line.strip().lower().startswith(('webvtt', 'kind:', 'language:')) or not line.strip():
                                    continue
                                
                                clean_line = re.sub(r'<[^>]+>', '', line).strip()
                                transcript_parts.append(clean_line)
                            
                            unique_lines = []
                            for i, line in enumerate(transcript_parts):
                                if i == 0 or line != transcript_parts[i-1]:
                                    unique_lines.append(line)
                            
                            final_text = " ".join(unique_lines)

                            if final_text and len(final_text) > 10:
                                transcript_text = final_text
                                print("--- [DEBUG] 자막 추출 및 정제 성공 (안정화된 최종 파서) ---")

            except Exception as e:
                print(f"[ERROR] 자막 추출 중 오류 발생: {e}. Whisper로 넘어갑니다.")

            if not transcript_text:
                print(f"--- [DEBUG] 자막 추출 실패. Whisper AI를 이용한 음성 추출 및 변환을 시작합니다. ---")
                
                ydl_opts_audio = {
                    'format': 'm4a/bestaudio/best',
                    'outtmpl': f"{video_info.get('id', 'temp_audio')}.%(ext)s",
                    'postprocessors': [{'key': 'FFmpegExtractAudio', 'preferredcodec': 'mp3', 'preferredquality': '192'}],
                    'postprocessor_args': ['-ar', '16000'],
                    'cachedir': False, 'verbose': False, 'quiet': True, 'no_warnings': True,
                    'http_headers': {
                        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36',
                    }
                }
                
                with yt_dlp.YoutubeDL(ydl_opts_audio) as ydl_audio:
                    info_dict_audio = ydl_audio.extract_info(clean_youtube_link, download=True)
                    audio_file_path = ydl_audio.prepare_filename(info_dict_audio).rsplit('.', 1)[0] + '.mp3'

                if not audio_file_path or not os.path.exists(audio_file_path) or os.path.getsize(audio_file_path) == 0:
                    raise FileNotFoundError(f"오디오 파일 저장/경로 확인 실패: {audio_file_path}")

                if self.whisper_model_loader:
                    model = self.whisper_model_loader()
                    
                    print(f"--- [DEBUG] 긴 오디오 파일 분할 처리 시작: {audio_file_path} ---")
                    sound = AudioSegment.from_mp3(audio_file_path)
                    
                    MAX_DURATION_MS = 900 * 1000
                    if len(sound) > MAX_DURATION_MS:
                        sound = sound[:MAX_DURATION_MS]
                        print(f"--- [INFO] 영상 길이가 15분을 초과하여, 앞부분 15분만 분석합니다. ---")

                    chunk_length_ms = 5 * 60 * 1000
                    chunks = [sound[i:i + chunk_length_ms] for i in range(0, len(sound), chunk_length_ms)]
                    
                    all_transcripts, temp_chunk_files = [], []
                    for i, chunk in enumerate(chunks):
                        chunk_filename = f"temp_chunk_{video_info.get('id', 'temp')}_{i}.mp3"
                        temp_chunk_files.append(chunk_filename)
                        print(f"--- [DEBUG] {i+1}/{len(chunks)}번째 오디오 조각 처리 중... ---")
                        chunk.export(chunk_filename, format="mp3")
                        
                        result = model.transcribe(
                            chunk_filename, language="ko",
                            temperature=(0.0, 0.2, 0.4, 0.6, 0.8, 1.0),
                            logprob_threshold=-0.8,
                            no_speech_threshold=0.7
                        )
                        all_transcripts.append(result["text"])
                    
                    transcript_text = " ".join(all_transcripts)
                    print(f"--- [DEBUG] 오디오 분할 처리 및 취합 완료 ---")

                    for temp_file in temp_chunk_files:
                        if os.path.exists(temp_file): os.remove(temp_file)
                    print(f"--- [DEBUG] 임시 오디오 조각 파일 정리 완료 ---")
                else:
                    transcript_text = "⚠️ Whisper 모델 로더가 없어 대본을 추출할 수 없습니다."

        except Exception as e:
            error_message = f"영상 정보 추출 또는 대본 변환 중 심각한 오류 발생: {type(e).__name__}: {e}"
            print(f"[ERROR] {error_message}", file=sys.stderr)
            if "Video unavailable" in str(e):
                transcript_text = "⚠️ 해당 영상은 삭제/비공개/지역 제한 등으로 인해 분석할 수 없습니다."
            else:
                transcript_text = f"⚠️ 오류 발생: {error_message}"
        finally:
            if audio_file_path and os.path.exists(audio_file_path):
                try:
                    os.remove(audio_file_path)
                    print(f"[DEBUG] 원본 오디오 파일 정리 완료: {audio_file_path}")
                except Exception as e:
                    print(f"[ERROR] 오디오 파일 삭제 실패: {e}")

        return video_info, transcript_text

    def _get_channel_id(self, identifier):
        self._initialize_youtube_service()
        if not self.youtube_service: return None
        if re.match(r'UC[a-zA-Z0-9_-]{22}', identifier): return identifier
        match = re.search(r'(?:youtube\.com/channel/|youtube\.com/user/|youtube\.com/c/|youtube\.com/@)([a-zA-Z0-9_-]+)', identifier)
        if match:
            potential_id = match.group(1)
            try:
                if "user/" in identifier or "/c/" in identifier or "/@" in identifier:
                    search_request = self.youtube_service.search().list(q=potential_id, type='channel', part='id', maxResults=1)
                    search_response = search_request.execute()
                    if search_response and search_response['items']: return search_response['items'][0]['id']['channelId']
                else: return potential_id
            except Exception as e:
                print(f"[ERROR] _get_channel_id API call failed for {identifier}: {e}")
        return None

    def extract_channel_info(self, channel_identifier):
        self._initialize_youtube_service()
        if not self.youtube_service: return {"error": "YouTube Data API 키가 설정되지 않았거나 서비스 초기화에 실패했습니다."}
        channel_id = self._get_channel_id(channel_identifier)
        if not channel_id: return {"error": "유효한 채널 ID 또는 URL을 추출할 수 없습니다. 형식을 확인해주세요."}
        try:
            channel_request = self.youtube_service.channels().list(part="snippet,statistics,contentDetails", id=channel_id)
            channel_response = channel_request.execute()
            if not channel_response['items']: return {"error": "채널 정보를 찾을 수 없습니다. 채널 ID를 확인해주세요."}
            channel_data = channel_response['items'][0]
            channel_title = channel_data['snippet']['title']
            subscriber_count = int(channel_data['statistics'].get('subscriberCount', 0))
            
            uploads_playlist_id = channel_data['contentDetails']['relatedPlaylists']['uploads']
            three_months_ago = datetime.now() - timedelta(days=90)
            videos, next_page_token, fetch_count, max_playlist_fetches = [], None, 0, 5
            analysis_type = "recent" 

            while True:
                if fetch_count >= max_playlist_fetches: break
                playlist_items_request = self.youtube_service.playlistItems().list(part="snippet", playlistId=uploads_playlist_id, maxResults=50, pageToken=next_page_token)
                playlist_items_response = playlist_items_request.execute()
                if not playlist_items_response['items']: break
                found_recent = False
                for item in playlist_items_response['items']:
                    video_upload_date = isoparse(item['snippet']['publishedAt']).replace(tzinfo=None)
                    if video_upload_date >= three_months_ago:
                        videos.append({'id': item['snippet']['resourceId']['videoId'], 'publishedAt': video_upload_date})
                        found_recent = True
                    else: break
                next_page_token = playlist_items_response.get('nextPageToken')
                fetch_count += 1
                if not next_page_token or not found_recent: break
            
            if not videos:
                print("[INFO] 최근 3개월 내 업로드된 영상이 없습니다. '플랜 B'를 가동하여 채널의 역대 인기 영상을 분석합니다.")
                analysis_type = "popular"
                search_request = self.youtube_service.search().list(
                    part="snippet",
                    channelId=channel_id,
                    maxResults=20, 
                    order="viewCount",
                    type="video"
                )
                search_response = search_request.execute()
                for item in search_response.get("items", []):
                    videos.append({'id': item['id']['videoId']})

            all_video_details = []
            if videos:
                for i in range(0, len(videos), 50):
                    video_ids_batch = [v['id'] for v in videos[i:i+50]]
                    if not video_ids_batch: continue
                    video_details_request = self.youtube_service.videos().list(part="snippet,statistics,contentDetails", id=",".join(video_ids_batch))
                    video_details_response = video_details_request.execute()
                    all_video_details.extend(video_details_response['items'])

            long_form_count, short_form_count, long_form_view_list, total_short_form_views, last_upload_date = 0, 0, [], 0, None
            for video_item in all_video_details:
                published_at = isoparse(video_item['snippet']['publishedAt']).replace(tzinfo=None)
                view_count = int(video_item['statistics'].get('viewCount', 0))
                if last_upload_date is None or published_at > last_upload_date: last_upload_date = published_at
                is_short = False
                if 'contentDetails' in video_item and 'duration' in video_item['contentDetails']:
                    duration_str = video_item['contentDetails']['duration']
                    h = int(re.search(r'(\d+)H', duration_str).group(1)) * 3600 if 'H' in duration_str else 0
                    m = int(re.search(r'(\d+)M', duration_str).group(1)) * 60 if 'M' in duration_str else 0
                    s = int(re.search(r'(\d+)S', duration_str).group(1)) if 'S' in duration_str else 0
                    if (h + m + s) <= 65: 
                        is_short = True
                if '#shorts' in video_item['snippet']['title'].lower(): is_short = True
                if is_short: 
                    short_form_count += 1
                    total_short_form_views += view_count
                else: 
                    long_form_count += 1
                    long_form_view_list.append(view_count)

            if analysis_type == 'popular':
                total_long_form_views_for_revenue = sum(long_form_view_list) * 10 
                total_short_form_views_for_revenue = total_short_form_views * 10
                total_recent_views = sum(long_form_view_list) + total_short_form_views
            else: 
                total_long_form_views_for_revenue = sum(long_form_view_list)
                total_short_form_views_for_revenue = total_short_form_views
                total_recent_views = total_long_form_views_for_revenue + total_short_form_views_for_revenue

            avg_long_form_views = (sum(long_form_view_list) // long_form_count) if long_form_count > 0 else 0
            avg_short_form_views = (total_short_form_views // short_form_count) if short_form_count > 0 else 0
            
            return {
                "channel_title": channel_title, "subscriber_count": f"{subscriber_count:,}",
                "recent_3_month_views": f"{total_recent_views:,}",
                "long_form_count": long_form_count, "short_form_count": short_form_count, 
                "last_upload_date": last_upload_date.strftime("%Y-%m-%d") if last_upload_date else '90일 내 활동 없음',
                "avg_long_form_views": f"{avg_long_form_views:,}", "avg_short_form_views": f"{avg_short_form_views:,}",
                "subscriber_count_raw": subscriber_count, "recent_3_month_views_raw": total_recent_views,
                "avg_long_form_views_raw": avg_long_form_views, "avg_short_form_views_raw": avg_short_form_views,
                "total_long_form_views_raw": total_long_form_views_for_revenue,
                "total_short_form_views_raw": total_short_form_views_for_revenue,
                "videos_data": all_video_details,
                "analysis_type": analysis_type,
            }
        except Exception as e:
            print(f"[ERROR] YouTubeDataExtractor.extract_channel_info: {e}")
            return {"error": f"채널 정보 추출 중 오류 발생: {str(e)}"}

    def get_popular_videos(self, channel_id, max_results=10):
        self._initialize_youtube_service()
        if not self.youtube_service:
            return [{"error": "YouTube Data API 서비스 초기화 실패"}]

        try:
            channel_request = self.youtube_service.channels().list(
                part="contentDetails",
                id=channel_id
            )
            channel_response = channel_request.execute()
            if not channel_response.get('items'):
                return [{"error": "채널 정보를 찾을 수 없습니다."}]
            
            uploads_playlist_id = channel_response['items'][0]['contentDetails']['relatedPlaylists']['uploads']
            
            three_months_ago = datetime.now() - timedelta(days=90)
            all_videos = []
            next_page_token = None
            
            for _ in range(5): 
                playlist_items_request = self.youtube_service.playlistItems().list(
                    part="snippet",
                    playlistId=uploads_playlist_id,
                    maxResults=50,
                    pageToken=next_page_token
                )
                playlist_items_response = playlist_items_request.execute()
                
                found_recent_video = False
                for item in playlist_items_response.get("items", []):
                    published_at = isoparse(item['snippet']['publishedAt']).replace(tzinfo=None)
                    if published_at >= three_months_ago:
                        all_videos.append({
                            'id': item['snippet']['resourceId']['videoId'],
                            'title': item['snippet']['title']
                        })
                        found_recent_video = True
                
                next_page_token = playlist_items_response.get('nextPageToken')
                if not next_page_token or not found_recent_video:
                    break
            
            if not all_videos:
                print("[DEBUG] 최근 90일 내 영상 없음. 전체 기간 인기 영상으로 대체 검색을 시작합니다.")
                search_request = self.youtube_service.search().list(
                    part="snippet",
                    channelId=channel_id,
                    maxResults=max_results,
                    order="viewCount",
                    type="video"
                )
                search_response = search_request.execute()
                for item in search_response.get("items", []):
                    all_videos.append({
                        'id': item['id']['videoId'],
                        'title': item['snippet']['title'],
                    })

            if not all_videos:
                return []

            video_details = []
            video_ids_to_fetch = [v['id'] for v in all_videos]
            for i in range(0, len(video_ids_to_fetch), 50):
                video_ids_batch = video_ids_to_fetch[i:i+50]
                video_details_request = self.youtube_service.videos().list(
                    part="statistics",
                    id=",".join(video_ids_batch)
                )
                video_details_response = video_details_request.execute()
                video_details.extend(video_details_response.get("items", []))

            video_stats = {item['id']: int(item['statistics'].get('viewCount', 0)) for item in video_details}
            for video in all_videos:
                video['view_count'] = video_stats.get(video['id'], 0)

            sorted_videos = sorted(all_videos, key=lambda v: v.get('view_count', 0), reverse=True)
            
            return sorted_videos[:max_results]

        except Exception as e:
            error_message = f"인기 동영상 목록을 가져오는 중 오류 발생: {e}"
            print(f"[ERROR] {error_message}", file=sys.stderr)
            return [{"error": error_message}]
            
    def get_top_comments(self, video_id, max_results=5):
        self._initialize_youtube_service()
        if not self.youtube_service:
            return [{'error': "YouTube Data API 서비스 초기화 실패"}]

        try:
            request = self.youtube_service.commentThreads().list(
                part="snippet",
                videoId=video_id,
                order="relevance", 
                maxResults=100,
                textFormat="plainText"
            )
            response = request.execute()

            all_comments = []
            for item in response.get("items", []):
                comment_snippet = item["snippet"]["topLevelComment"]["snippet"]
                all_comments.append({
                    "author": comment_snippet["authorDisplayName"],
                    "text": comment_snippet["textDisplay"],
                    "like_count": comment_snippet["likeCount"]
                })
            
            if not all_comments:
                return [{'error': '베스트 댓글을 찾을 수 없거나, 댓글이 없는 영상입니다.'}]

            sorted_comments = sorted(all_comments, key=lambda c: c.get('like_count', 0), reverse=True)
            
            return sorted_comments[:max_results]

        except Exception as e:
            error_message = f"댓글을 가져오는 중 오류가 발생했습니다: {e}"
            print(f"[ERROR] {error_message}", file=sys.stderr)
            if 'disabled comments' in str(e).lower():
                return [{'error': '이 영상은 댓글 사용이 중지되었습니다.'}]
            return [{'error': error_message}]


def clean_transcript(text):
    return re.sub(r'\s+', ' ', text).strip()

def resource_path(relative_path):
    try: base_path = sys._MEIPASS
    except Exception: base_path = os.path.abspath(".")
    return os.path.join(base_path, relative_path)