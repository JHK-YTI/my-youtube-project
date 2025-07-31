# check_db.py
import sqlite3
import os

DB_FILE = "youtube_app.db"
print("="*60)
print(f"'{DB_FILE}' 파일의 내부 구조 진단을 시작합니다.")
print("="*60)

if not os.path.exists(DB_FILE):
    print(f"[진단 결과] 🚨 심각: '{DB_FILE}' 파일을 찾을 수 없습니다.")
    print("이전 단계에서 파일을 삭제하셨다면, 정상입니다.")
    print("이제 'python app.py'를 실행하여 새 데이터베이스를 만드세요.")
else:
    try:
        conn = sqlite3.connect(DB_FILE)
        cursor = conn.cursor()
        
        # 'user' 테이블의 모든 열 정보를 조회하는 쿼리
        cursor.execute("PRAGMA table_info(user)")
        columns = cursor.fetchall()
        
        conn.close()
        
        print("[정보] 현재 'user' 테이블에 들어있는 열 목록:")
        column_names = []
        for col in columns:
            column_name = col[1]
            column_names.append(column_name)
            print(f"  - {column_name}")

        print("\n" + "="*60)
        if 'created_at' in column_names:
            print("[진단 결과] ✅ 정상: 'created_at' 열이 데이터베이스에 존재합니다.")
            print("이 경우, 다른 원인이 있을 수 있으니 이 화면을 캡처해서 저에게 보여주세요.")
        else:
            print("[진단 결과] 🚨 원인 확정: 'created_at' 열이 데이터베이스에 없습니다.")
            print("이것은 'models.py'는 수정되었지만, 실제 DB 파일은 옛날 버전이라는 확실한 증거입니다.")
            print("\n[해결책] 왼쪽 탐색기에서 'youtube_app.db' 파일을 '완전히 삭제'하신 후,")
            print("다시 'python app.py'를 실행하고 '새로 회원가입'을 진행하시면 문제가 해결됩니다.")

    except Exception as e:
        print(f"\n[진단 결과] 🚨 오류: 데이터베이스 분석 중 에러가 발생했습니다: {e}")

print("="*60)