# check_file.py (진단용 스크립트)
import os

# 우리가 확인하고 싶은 파일의 이름
file_path = 'prompt_templates.py'

print("="*60)
print(f"'{file_path}' 파일의 실제 위치와 내용을 확인하는 진단을 시작합니다.")
print("="*60)

# 1. 현재 이 스크립트가 실행되고 있는 폴더의 경로를 확인합니다.
current_directory = os.getcwd()
print(f"[정보] 현재 터미널의 실행 위치는 아래와 같습니다:\n{current_directory}\n")

# 2. 현재 위치를 기준으로 파일의 전체 경로를 만듭니다.
full_path = os.path.join(current_directory, file_path)
print(f"[정보] 따라서, 파이썬은 아래 경로에서 파일을 찾으려고 시도합니다:\n{full_path}\n")

# 3. 해당 경로에 파일이 실제로 존재하는지, 그리고 내용을 읽을 수 있는지 확인합니다.
try:
    with open(full_path, 'r', encoding='utf-8') as f:
        content = f.read()
    
    print(f"--- [성공] 성공적으로 '{file_path}' 파일을 읽었습니다. ---")
    
    # 4. 파일 내용 안에 우리가 찾는 변수가 있는지 최종 확인합니다.
    print("파일에서 찾은 내용 미리보기 (최대 500자):")
    print("--------------------------------------------------")
    print(content[:500])
    print("--------------------------------------------------\n")

    if 'ANALYSIS_PROMPT' in content and 'CORRECTION_PROMPT' in content:
        print("[최종 진단]: 정상입니다. 파일의 내용과 위치가 모두 올바릅니다.")
        print("이 메시지가 나왔는데도 서버 실행 시 오류가 발생한다면, '서버 재시작' 과정에 문제가 있는 것입니다.")
    else:
        print("[최종 진단]: [!!! 핵심 원인 발견 !!!]")
        print("파일을 읽는 데는 성공했지만, 파일 내용에 'ANALYSIS_PROMPT'나 'CORRECTION_PROMPT' 같은 핵심 변수가 없습니다.")
        print("이것은 사장님께서 편집하고 저장한 파일과, 현재 파이썬이 읽고 있는 파일이 서로 다른 '유령 파일'이라는 결정적인 증거입니다.")

except FileNotFoundError:
    print(f"[최종 진단]: [!!! 심각한 오류 !!!]")
    print(f"현재 위치에서 '{file_path}' 파일을 찾을 수 없습니다.")
    print("터미널의 현재 위치가 'my-youtube-project' 폴더가 맞는지 다시 한번 확인해주십시오.")
except Exception as e:
    print(f"[최종 진단]: 파일을 읽는 중 예상치 못한 오류 발생: {e}")

print("="*60)