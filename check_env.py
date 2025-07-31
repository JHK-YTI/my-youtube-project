import os
from dotenv import load_dotenv

print("--- .env 파일 진단 프로그램을 시작합니다 ---")

# .env 파일의 경로를 명시적으로 지정하여 확실하게 불러옵니다.
# verbose=True 옵션은 어떤 파일을 읽으려고 시도했는지 알려줍니다.
env_path = os.path.join(os.path.dirname(__file__), '.env')
found = load_dotenv(dotenv_path=env_path, verbose=True)

if not found:
    print("\n[진단 결과 🚨] .env 파일을 찾지 못했습니다.")
    print(f"현재 경로: {os.path.dirname(__file__)}")
    print("파일이 정확한 위치에 있는지 다시 한번 확인해주세요.")
else:
    print("\n[진단 결과 ✅] .env 파일을 성공적으로 찾고 읽었습니다.")

    # .env 파일에 저장된 모든 키를 확인합니다.
    keys_to_check = [
        "GEMINI_API_KEY",
        "YOUTUBE_API_KEY",
        "GOOGLE_API_KEY",
        "OPENAI_API_KEY"
    ]

    all_keys_found = True
    print("\n--- 저장된 키 확인 ---")
    for key in keys_to_check:
        value = os.getenv(key)
        if value:
            # 키 값의 일부만 보여주어 보안을 유지합니다.
            print(f"  - {key}: ...{value[-4:]} (✅ 불러오기 성공)")
        else:
            print(f"  - {key}: (🚨 불러오기 실패!)")
            all_keys_found = False

    if all_keys_found:
        print("\n[최종 진단] 모든 키를 성공적으로 불러왔습니다. 이제 test_gpt.py가 정상적으로 작동할 것입니다.")
    else:
        print("\n[최종 진단] 일부 키를 불러오지 못했습니다. .env 파일의 내용에 오타가 있거나, 눈에 보이지 않는 특수문자가 포함되었을 수 있습니다.")
        print("해결책: .env 파일을 삭제하고, 메모장이 아닌 다른 편집기(예: VS Code)에서 새로 만들어 내용을 다시 붙여넣어 보세요.")

print("\n--- 진단 프로그램을 종료합니다 ---")