import os
import openai
from dotenv import load_dotenv

def test_api_connection():
    """
    .env 파일에서 API 키를 불러와 OpenAI API와 통신이 잘 되는지 테스트하는 함수
    """
    print("1. .env 파일에서 환경 변수를 불러옵니다...")
    try:
        load_dotenv()
        api_key = os.getenv("OPENAI_API_KEY")

        if not api_key:
            print("🚨 오류: .env 파일에서 OPENAI_API_KEY를 찾을 수 없습니다.")
            print("   .env 파일이 프로젝트 최상위 폴더에 있는지, 내용이 올바른지 확인해주세요.")
            return

        openai.api_key = api_key
        print("2. API 키를 성공적으로 불러왔습니다.")

    except Exception as e:
        print(f"🚨 .env 파일을 불러오는 중 오류 발생: {e}")
        return

    print("3. OpenAI API에 테스트 메시지를 전송합니다...")
    try:
        response = openai.chat.completions.create(
            model="gpt-3.5-turbo",  # 테스트용으로 가장 빠르고 저렴한 모델 사용
            messages=[
                {"role": "system", "content": "You are a helpful assistant."},
                {"role": "user", "content": "안녕하세요! 간단히 인사해주세요."}
            ],
            temperature=0.7,
            max_tokens=50
        )

        ai_message = response.choices[0].message.content
        print("\n4. AI로부터 응답을 받았습니다! ✅")
        print("------------------------------------")
        print(f"🤖 AI 응답: {ai_message}")
        print("------------------------------------")
        print("\n🎉 축하합니다! GPT API와의 통신에 성공했습니다.")

    except openai.AuthenticationError as e:
        print("🚨 인증 오류가 발생했습니다. API 키가 유효하지 않거나 잘못되었습니다.")
        print("   .env 파일에 있는 OPENAI_API_KEY를 다시 한번 확인해주세요.")

    except Exception as e:
        print(f"🚨 API 호출 중 예측하지 못한 오류가 발생했습니다: {e}")

if __name__ == "__main__":
    test_api_connection()