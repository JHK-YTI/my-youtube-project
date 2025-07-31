# models.py

from flask_sqlalchemy import SQLAlchemy
from flask_login import UserMixin
from flask_bcrypt import Bcrypt
from datetime import datetime

# db, bcrypt 객체를 여기서 생성합니다.
db = SQLAlchemy()
bcrypt = Bcrypt()

class Feedback(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    subject = db.Column(db.String(100), nullable=False)
    content = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)

    def __repr__(self):
        return f"Feedback('{self.subject}', '{self.created_at}')"

class AnalysisHistory(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    video_title = db.Column(db.String(200), nullable=False)
    video_url = db.Column(db.String(200), nullable=False)
    analysis_summary = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)

    def __repr__(self):
        return f"AnalysisHistory('{self.video_title}', '{self.created_at}')"


class User(db.Model, UserMixin):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(20), unique=True, nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    image_file = db.Column(db.String(20), nullable=False, default='default.jpg')
    password_hash = db.Column(db.String(60), nullable=False)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    is_admin = db.Column(db.Boolean, nullable=False, default=False)
    
    # ▼▼▼▼▼ [핵심 수정] server_default 옵션 추가 ▼▼▼▼▼
    plan = db.Column(db.String(20), nullable=False, default='free', server_default='free')
    credits = db.Column(db.Integer, nullable=False, default=10, server_default='10')
    # ▲▲▲▲▲ [핵심 수정] ▲▲▲▲▲
    
    histories = db.relationship('AnalysisHistory', backref='author', lazy=True)
    feedbacks = db.relationship('Feedback', backref='author', lazy=True)

    def __repr__(self):
        return f"User('{self.username}', '{self.email}', '{self.plan}', credits={self.credits})"