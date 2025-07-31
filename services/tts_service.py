# services/tts_service.py

from google.cloud import texttospeech
from pydub import AudioSegment
import io
import os
from .youtube_extractor import resource_path
import re

def synthesize_speech(text, voice_name="ko-KR-Standard-A"):
    """
    주어진 텍스트를 Google TTS를 사용하여 음성으로 변환하고 mp3 바이너리를 반환합니다.
    """
    key_path = resource_path('gcp-tts-key.json')
    if not os.path.exists(key_path):
        raise FileNotFoundError("GCP 키 파일('gcp-tts-key.json')을 찾을 수 없습니다. 2단계 가이드를 확인해주세요.")
    
    client = texttospeech.TextToSpeechClient.from_service_account_json(key_path)
    synthesis_input = texttospeech.SynthesisInput(text=text)
    voice = texttospeech.VoiceSelectionParams(
        language_code="ko-KR", name=voice_name
    )
    audio_config = texttospeech.AudioConfig(
        audio_encoding=texttospeech.AudioEncoding.MP3
    )

    try:
        response = client.synthesize_speech(
            input=synthesis_input, voice=voice, audio_config=audio_config
        )
        return response.audio_content
    except Exception as e:
        print(f"Google TTS API 호출 중 오류 발생: {e}")
        return None

def text_to_speech_file(script_text):
    """
    긴 대본을 문장으로 나눠 처리하고, 하나의 MP3 파일로 합친 뒤 BytesIO 버퍼를 반환합니다.
    """
    # ▼▼▼▼▼ [V4 대본용 최종 전처리기] ▼▼▼▼▼
    print(f"[DEBUG] TTS 전처리 전 원본 V4 대본: {script_text[:200]}...")
    
    # 1단계: (괄호로 묶인 모든 지문)을 제거합니다. 예: (눈을 크게 뜨며...)
    processed_text = re.sub(r'\s*\([^)]*\)\s*', ' ', script_text)
    
    # 2단계: **0초~3초:** 와 같은 타임스탬프를 제거합니다.
    processed_text = re.sub(r'\*\*\d+초~\d+초:\*\*', '', processed_text)
    
    # 3단계: 기타 불필요한 기호들을 제거합니다.
    processed_text = processed_text.replace('###', ' ').replace('#', ' ')

    # 4단계: 여러 줄의 공백이나 양 끝의 공백을 최종적으로 정리합니다.
    processed_text = '\n'.join([line.strip() for line in processed_text.splitlines() if line.strip()])
    
    print(f"[DEBUG] TTS 최종 변환 대상 텍스트: {processed_text[:200]}...")
    # ▲▲▲▲▲ [V4 대본용 최종 전처리기] ▲▲▲▲▲

    # 마침표, 물음표, 느낌표, 줄바꿈을 기준으로 문장을 분할
    sentences = re.split(r'(?<=[.?!])\s*|\n+', processed_text)
    sentences = [s.strip() for s in sentences if s and s.strip()]
    
    if not sentences:
        return None

    audio_segments = []
    print(f"총 {len(sentences)}개의 문장으로 분리하여 음성 변환을 시작합니다.")
    
    for i, sentence in enumerate(sentences):
        print(f"  - 문장 {i+1}/{len(sentences)} 변환 중...")
        audio_content = synthesize_speech(sentence) 
        
        if audio_content:
            segment = AudioSegment.from_file(io.BytesIO(audio_content), format="mp3")
            audio_segments.append(segment)
    
    if not audio_segments:
        print("음성 변환 결과물이 없습니다.")
        return None

    print("모든 오디오 조각을 하나로 합치는 중...")
    combined_audio = sum(audio_segments, AudioSegment.empty())
    
    buffer = io.BytesIO()
    combined_audio.export(buffer, format="mp3")
    buffer.seek(0)
    
    print("음성 파일 생성 완료.")
    return buffer