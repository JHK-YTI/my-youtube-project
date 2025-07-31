# set_admin.py

from app import create_app, db
from models import User

# Flask 애플리케이션의 환경을 불러옵니다.
app = create_app()
app.app_context().push()

def set_admin_user():
    """
    사용자 이메일을 입력받아 해당 사용자를 관리자로 설정하는 스크립트.
    """
    try:
        # 터미널에서 이메일을 입력받습니다.
        email = input("▶ 관리자로 지정할 계정의 이메일 주소를 입력하고 엔터를 누르세요: ")
        
        # 입력된 이메일로 사용자를 찾습니다.
        user = User.query.filter_by(email=email).first()

        # 사용자를 찾았다면
        if user:
            user.is_admin = True  # is_admin 값을 True로 변경
            db.session.commit()   # 데이터베이스에 변경사항 저장
            print(f"\n✅ 성공: '{user.username}' ({user.email}) 님이 관리자로 지정되었습니다.")
        else:
            print(f"\n❌ 오류: 이메일 '{email}'에 해당하는 사용자를 찾을 수 없습니다. 이메일을 다시 확인해주세요.")

    except Exception as e:
        db.session.rollback()
        print(f"\n❌ 오류: 작업 중 에러가 발생했습니다: {e}")

# 이 스크립트를 실행하면 set_admin_user 함수가 호출됩니다.
if __name__ == "__main__":
    set_admin_user()