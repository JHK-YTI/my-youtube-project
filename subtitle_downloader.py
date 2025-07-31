import yt_dlp
import sys
import os

def download_subtitle(video_url):
    """
    지정된 유튜브 URL에서 한국어 자막을 .vtt 파일로 다운로드하는 독립 테스트 스크립트.
    """
    print("="*60)
    print(f"독립 자막 다운로드 테스트를 시작합니다: {video_url}")
    print("="*60)

    # 저장될 파일 이름 설정
    output_filename = 'downloaded_subtitle.ko.vtt'

    # 파일이 이미 존재하면 삭제하여 항상 새로 다운로드 받도록 함
    if os.path.exists(output_filename):
        os.remove(output_filename)
        print(f"기존 '{output_filename}' 파일을 삭제했습니다.")

    # yt-dlp 옵션 설정
    ydl_opts = {
        'writesubtitles': True,      # 자막 다운로드 활성화
        'subtitleslangs': ['ko'],    # 한국어 자막 지정
        'skip_download': True,       # 영상 자체는 다운로드 안 함
        'outtmpl': 'downloaded_subtitle', # 저장될 파일의 기본 이름
        'quiet': True,               # 불필요한 로그 최소화
        'no_warnings': True,         # 경고 메시지 숨김
    }

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            print("자막 다운로드를 시도합니다...")
            ydl.download([video_url])
        
        if os.path.exists(output_filename):
            print("\n" + "="*60)
            print(f"🎉 [성공] '{output_filename}' 파일로 저장이 완료되었습니다.")
            print("이제 프로젝트 폴더에 생성된 해당 파일을 열어,")
            print("내용이 끝까지 완전하게 저장되었는지 확인해주십시오.")
            print("="*60)
        else:
            print("\n" + "="*60)
            print("⚠️ [실패] 자막 파일이 생성되지 않았습니다. 해당 영상에 한국어 자막이 없는 것 같습니다.")
            print("="*60)

    except Exception as e:
        print(f"\n" + "="*60)
        print(f"❌ [오류] 자막 다운로드 중 예상치 못한 오류가 발생했습니다: {e}")
        print("="*60)

if __name__ == '__main__':
    if len(sys.argv) < 2:
        print("\n[사용법]")
        print("터미널에 다음과 같이 입력해주세요:")
        print('python subtitle_downloader.py "유튜브_영상_URL"')
        print('예시: python subtitle_downloader.py "https://youtu.be/sCXdpjBF65o?si=6YLzE7T97p8wjlAY"')
    else:
        url_to_test = sys.argv[1]
        download_subtitle(url_to_test)