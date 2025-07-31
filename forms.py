# forms.py

from flask_wtf import FlaskForm
from wtforms import StringField, PasswordField, SubmitField, BooleanField, TextAreaField
from wtforms.validators import DataRequired, Length, Email, EqualTo, ValidationError
from flask_login import current_user
from models import User

class RegistrationForm(FlaskForm):
    username = StringField('사용자 이름',
                           validators=[DataRequired(), Length(min=2, max=20)])
    email = StringField('이메일',
                        validators=[DataRequired(), Email()])
    password = PasswordField('비밀번호', validators=[DataRequired()])
    confirm_password = PasswordField('비밀번호 확인',
                                     validators=[DataRequired(), EqualTo('password', '비밀번호가 일치해야 합니다.')])
    submit = SubmitField('회원가입')

    def validate_username(self, username):
        user = User.query.filter_by(username=username.data).first()
        if user:
            raise ValidationError('해당 사용자 이름은 이미 사용 중입니다. 다른 이름을 선택해주세요.')

    def validate_email(self, email):
        user = User.query.filter_by(email=email.data).first()
        if user:
            raise ValidationError('해당 이메일은 이미 사용 중입니다. 다른 이메일을 선택해주세요.')


class LoginForm(FlaskForm):
    email = StringField('이메일',
                        validators=[DataRequired(), Email()])
    password = PasswordField('비밀번호', validators=[DataRequired()])
    remember = BooleanField('로그인 상태 유지')
    submit = SubmitField('로그인')

# ▼▼▼▼▼ [수정] 마이페이지 개편에 따라 Form들을 새로 정의 ▼▼▼▼▼

class ChangePasswordForm(FlaskForm):
    current_password = PasswordField('현재 비밀번호', validators=[DataRequired()])
    new_password = PasswordField('새 비밀번호', validators=[DataRequired(), Length(min=4, message='비밀번호는 최소 4자 이상이어야 합니다.')])
    confirm_password = PasswordField('새 비밀번호 확인',
                                     validators=[DataRequired(), EqualTo('new_password', '새 비밀번호가 일치해야 합니다.')])
    submit = SubmitField('비밀번호 변경')

class FeedbackForm(FlaskForm):
    subject = StringField('제목', validators=[DataRequired(), Length(min=2, max=100)])
    content = TextAreaField('내용', validators=[DataRequired()])
    submit = SubmitField('제출하기')

# ▲▲▲▲▲ [수정] ▲▲▲▲▲