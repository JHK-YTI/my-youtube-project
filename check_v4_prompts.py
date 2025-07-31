# check_v4_prompts.py (진단용 스크립트)
import os

file_path = 'prompt_templates.py'
check_variable = 'V4_ANALYZE_TOPIC_PROMPT' # 우리가 확인할 변수 이름

print("="*60)
print(f"'{file_path}' 파일 진단을 시작합니다.")
print(f"핵심 변수인 '{check_variable}'가 포함되어 있는지 확인합니다.")
print("="*60)

try:
    # 현재 위치를 기준으로 파일의 전체 경로를 만듭니다.
    full_path = os.path.join(os.getcwd(), file_path)
    print(f"[정보] 파이썬은 이 경로에서 파일을 찾습니다:\n{full_path}\n")

    with open(full_path, 'r', encoding='utf-8') as f:
        content = f.read()
    
    print(f"--- [성공] '{file_path}' 파일을 읽었습니다. ---")
    
    if check_variable in content:
        print(f"[최종 진단]: ✅ 정상입니다. 파일에 '{check_variable}' 변수가 존재합니다.")
        print("이 메시지가 나왔다면, 문제는 파일 내용이 아니라 '서버 재시작' 과정에 있는 것입니다.")
        print("해결책: VS Code의 모든 터미널을 닫고, '터미널 분할' 방식으로 서버를 다시 켜보세요.")
    else:
        print(f"[최종 진단]: 🚨 원인 발견! 파일 내용이 최신 버전이 아닙니다.")
        print(f"파일을 성공적으로 읽었지만, 내용 안에 '{check_variable}' 변수가 없습니다.")
        print("이것은 사장님께서 코드를 붙여넣으신 후 파일이 제대로 저장되지 않았다는 증거입니다.")
        print("해결책: 제가 이전에 드렸던 `prompt_templates.py` 전체 코드를 다시 파일에 붙여넣고, **반드시 '파일 저장'(Ctrl+S)을 눌러주세요.**")

except FileNotFoundError:
    print(f"[최종 진단]: 🚨 심각! '{file_path}' 파일을 찾을 수 없습니다.")
    print("현재 터미널의 위치가 프로젝트 폴더가 맞는지 확인해주세요.")
except Exception as e:
    print(f"[최종 진단]: 파일을 읽는 중 예상치 못한 오류 발생: {e}")

print("="*60)