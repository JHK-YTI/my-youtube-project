# app.py

from flask import Flask, render_template, request, Response, send_file, json, jsonify, flash, redirect, url_for
from flask_login import LoginManager, current_user, login_user, logout_user, login_required
import os
from dotenv import load_dotenv
import functools
import torch
import re
from dateutil.parser import isoparse
import sys
import time
from datetime import datetime
import io
import uuid
import whisper
import google.generativeai as genai
import logging
from logging.handlers import RotatingFileHandler
import redis
from flask_migrate import Migrate
import click

# Celery 관련 모듈 추가
from celery_worker import celery_app
from celery.result import AsyncResult

# 서비스 및 설정 파일 임포트
from services.youtube_extractor import YouTubeDataExtractor, clean_transcript, resource_path
from services import ai_service, calculator, content_analyzer, tts_service
import config

# models.py와 forms.py에서 필요한 것들을 가져옵니다.
from models import db, bcrypt, User, AnalysisHistory, Feedback
from forms import RegistrationForm, LoginForm, ChangePasswordForm, FeedbackForm


# 애플리케이션 팩토리 함수
def create_app():
    load_dotenv()
    
    app = Flask(__name__)
    
    log_formatter = logging.Formatter('%(asctime)s %(levelname)s: %(message)s [in %(pathname)s:%(lineno)d]')
    
    log_handler = RotatingFileHandler('app.log', maxBytes=1024 * 1024 * 10, backupCount=5, encoding='utf-8')
    log_handler.setFormatter(log_formatter)
    
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(log_formatter)

    app.logger.addHandler(log_handler)
    app.logger.addHandler(console_handler)
    
    werkzeug_logger = logging.getLogger('werkzeug')
    werkzeug_logger.addHandler(log_handler)
    werkzeug_logger.addHandler(console_handler)
    
    app.logger.setLevel(logging.INFO)
    werkzeug_logger.setLevel(logging.INFO)
    app.logger.info("Flask 애플리케이션 시작 (파일 및 콘솔 로깅 활성화)")
    
    app.config['SECRET_KEY'] = os.urandom(24) 
    app.config['SQLALCHEMY_DATABASE_URI'] = os.getenv('DATABASE_URL', 'sqlite:///youtube_app.db')
    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

    db.init_app(app)
    bcrypt.init_app(app)

    migrate = Migrate(app, db)

    login_manager = LoginManager()
    login_manager.init_app(app)
    login_manager.login_view = 'login'
    login_manager.login_message = "이 페이지에 접근하려면 로그인이 필요합니다."
    login_manager.login_message_category = 'info'

    @login_manager.user_loader
    def load_user(user_id):
        return db.session.get(User, int(user_id))

    @functools.lru_cache(maxsize=1)
    def get_whisper_model():
        device = "cuda" if torch.cuda.is_available() else "cpu"
        model = whisper.load_model("medium", device=device)
        return model

    def parse_ai_topic_response(text_response):
        structured_ideas = []
        category_blocks = text_response.strip().split('###')
        for block in category_blocks:
            if not block.strip(): continue
            lines = block.strip().split('\n')
            category_title = lines[0].strip().replace('[','').replace(']','')
            topics = []
            for topic_line in lines[1:]:
                if topic_line.strip().startswith('-'):
                    try:
                        topic_text = topic_line.split(':', 1)[1].strip()
                        topics.append(topic_text)
                    except IndexError:
                        topic_text = topic_line.replace('-', '').strip()
                        if topic_text:
                            topics.append(topic_text)
            if category_title and topics:
                structured_ideas.append({'category': category_title, 'topics': topics})
        return structured_ideas
    
    def parse_prompt_response(text_response):
        pattern = re.compile(r"###\s*(.*?)\s*```\s*\n?(.*?)\n?\s*```", re.DOTALL)
        matches = pattern.findall(text_response)
        
        structured_prompts = []
        for match in matches:
            title = match[0].strip()
            prompt = match[1].strip()
            
            prompt = re.split(r'\s*###\s*SCENE', prompt)[0].strip()

            if title and prompt:
                structured_prompts.append({'title': title, 'prompt': prompt})
        return structured_prompts

    def _parse_prediction_report(raw_prediction):
        prediction_data = {
            'score': '0', 'score_reason': '분석 실패',
            'strengths_html': '<p>강점 분석에 실패했습니다.</p>',
            'weaknesses_html': '<p>약점 분석에 실패했습니다.</p>',
            'tip_html': '<p>꿀팁 분석에 실패했습니다.</p>'
        }

        def _format_text_to_html(text_block):
            if not text_block or not text_block.strip():
                return ""
            lines = [f'<p>{line.strip().lstrip("- ")}</p>' for line in text_block.strip().split('\n') if line.strip()]
            return "".join(lines)

        try:
            score_match = re.search(r"종합 잠재력 점수[:\s*]*(\d+)", raw_prediction)
            if score_match:
                prediction_data['score'] = score_match.group(1)

            reason_match = re.search(r"점수 산정 근거:\s*(.*)", raw_prediction)
            if reason_match:
                prediction_data['score_reason'] = reason_match.group(1).strip()

            strengths_match = re.search(r"### 👍 강점 \(Good Points\)(.*?)(?=###|$)", raw_prediction, re.DOTALL)
            if strengths_match:
                prediction_data['strengths_html'] = _format_text_to_html(strengths_match.group(1))

            weaknesses_match = re.search(r"### 👎 보완점 \(Areas for Improvement\)(.*?)(?=###|$)", raw_prediction, re.DOTALL)
            if weaknesses_match:
                prediction_data['weaknesses_html'] = _format_text_to_html(weaknesses_match.group(1))
            
            tip_match = re.search(r"### 🚀 조회수 2배 올리는 꿀팁(.*?)(?=###|$)", raw_prediction, re.DOTALL)
            if tip_match:
                prediction_data['tip_html'] = _format_text_to_html(tip_match.group(1))

        except Exception as e:
            app.logger.error(f"성과 예측 리포트 파싱 중 오류 발생: {e}")

        return prediction_data
    
    @app.route('/error')
    @login_required
    def error_page():
        error_message = request.args.get('message', '알 수 없는 오류가 발생했습니다.')
        return render_template('error.html', error_message=error_message)

    @app.route('/')
    def index():
        if current_user.is_authenticated:
            return redirect(url_for('start'))
        return render_template('landing_page.html')
    
    @app.route('/login', methods=['GET', 'POST'])
    def login():
        if current_user.is_authenticated:
            return redirect(url_for('start'))
        form = LoginForm()
        if form.validate_on_submit():
            user = User.query.filter_by(email=form.email.data).first()
            if user and bcrypt.check_password_hash(user.password_hash, form.password.data):
                login_user(user, remember=form.remember.data)
                next_page = request.args.get('next')
                flash('성공적으로 로그인되었습니다!', 'success')
                return redirect(next_page) if next_page else redirect(url_for('start'))
            else:
                flash('로그인에 실패했습니다. 이메일과 비밀번호를 확인해주세요.', 'danger')
        return render_template('login.html', title='로그인', form=form)

    @app.route("/logout")
    @login_required
    def logout():
        logout_user()
        return redirect(url_for('login'))

    @app.route('/signup', methods=['GET', 'POST'])
    def signup():
        if current_user.is_authenticated:
            return redirect(url_for('start'))
        form = RegistrationForm()
        if form.validate_on_submit():
            hashed_password = bcrypt.generate_password_hash(form.password.data).decode('utf-8')
            user = User(username=form.username.data, email=form.email.data, password_hash=hashed_password, created_at=datetime.utcnow())
            db.session.add(user)
            db.session.commit()
            flash('계정이 성공적으로 생성되었습니다! 이제 로그인할 수 있습니다.', 'success')
            return redirect(url_for('login'))
        return render_template('signup.html', title='회원가입', form=form)
        
    @app.route("/account", methods=['GET', 'POST'])
    @login_required
    def account():
        password_form = ChangePasswordForm(prefix='password')
        feedback_form = FeedbackForm(prefix='feedback')

        if password_form.validate_on_submit() and password_form.submit.data:
            if bcrypt.check_password_hash(current_user.password_hash, password_form.current_password.data):
                hashed_password = bcrypt.generate_password_hash(password_form.new_password.data).decode('utf-8')
                current_user.password_hash = hashed_password
                db.session.commit()
                flash('비밀번호가 성공적으로 변경되었습니다.', 'success')
                return redirect(url_for('account'))
            else:
                flash('현재 비밀번호가 일치하지 않습니다.', 'danger')

        if feedback_form.validate_on_submit() and feedback_form.submit.data:
            feedback = Feedback(subject=feedback_form.subject.data, content=feedback_form.content.data, author=current_user)
            db.session.add(feedback)
            db.session.commit()
            flash('소중한 의견 감사합니다!', 'success')
            return redirect(url_for('account'))

        recent_history = AnalysisHistory.query.filter_by(author=current_user).order_by(AnalysisHistory.created_at.desc()).limit(5).all()
        return render_template('account.html', title='마이페이지', password_form=password_form, feedback_form=feedback_form, history=recent_history)
    
    @app.route('/admin/feedback')
    @login_required
    def admin_feedback():
        if not getattr(current_user, 'is_admin', False):
            flash('접근 권한이 없습니다.', 'danger')
            return redirect(url_for('dashboard'))
        all_feedback = Feedback.query.order_by(Feedback.created_at.desc()).all()
        return render_template('admin_feedback.html', feedbacks=all_feedback, title="사용자 건의사항")

    @app.route('/start')
    @login_required
    def start():
        return render_template('index.html')

    @app.route('/dashboard')
    @login_required
    def dashboard():
        return render_template('start_dashboard.html')

    @app.route('/navigator')
    @login_required
    def navigator():
        return render_template('navigator_start.html')

    @app.route('/navigator_pillars', methods=['POST'])
    @login_required
    def navigator_pillars():
        main_topic = request.form.get('main_topic')
        if not main_topic:
            flash("메인 주제를 입력해주세요.", "error")
            return redirect(url_for('navigator'))
        try:
            raw_response = ai_service.create_content_pillars(main_topic)
            if "⚠️" in raw_response:
                return render_template('navigator_pillars.html', error=raw_response, main_topic=main_topic)
            
            structured_pillars = parse_ai_topic_response(raw_response)
            if not structured_pillars:
                 raise ValueError("AI 응답에서 유효한 콘텐츠 기둥을 파싱하지 못했습니다.")

            return render_template('navigator_pillars.html', pillars=structured_pillars, main_topic=main_topic)
        except Exception as e:
            app.logger.error(f"콘텐츠 기둥 생성 중 오류 발생: {e}")
            error_message = f"콘텐츠 기둥을 생성하는 동안 오류가 발생했습니다."
            return render_template('navigator_pillars.html', error=error_message, main_topic=main_topic)
    
    @app.route('/content_planner', methods=['GET', 'POST'])
    @login_required
    def content_planner():
        topic = ''
        if request.method == 'POST':
            topic = request.form.get('topic', '')
        
        return render_template('content_planner.html', topic=topic)

    @app.route('/generate_planned_script', methods=['POST'])
    @login_required
    def generate_planned_script():
        if not current_user.is_admin:
            credit_cost = 2
            if current_user.credits < credit_cost:
                message = f"V4 대본 생성을 위해서는 {credit_cost} 크레딧이 필요합니다. (현재 보유 크레딧: {current_user.credits})"
                return redirect(url_for('error_page', message=message))

        form_data = {
            'category': request.form.get('category'),
            'tone': request.form.get('tone'),
            'format': request.form.get('format'),
            'target_audience': request.form.get('target_audience'),
            'topic': request.form.get('topic')
        }
        
        if not all([form_data['category'], form_data['tone'], form_data['format'], form_data['topic']]):
            flash('필수 입력값을 모두 채워주세요.', 'danger')
            return redirect(url_for('content_planner'))

        task = celery_app.send_task('celery_worker.generate_planned_script_task', args=[form_data], kwargs={'user_id': current_user.id})
        
        return redirect(url_for('loading_page', task_id=task.id, result_view='planned_script_result'))

    @app.route('/planned_script_result/<task_id>')
    @login_required
    def planned_script_result(task_id):
        task = AsyncResult(task_id, app=celery_app)

        if task.state == 'FAILURE':
            error_info = str(task.info)
            app.logger.error(f"Planned Script Task {task_id} failed with error: {error_info}")
            return render_template('planned_script_result.html', error=f"대본 생성 실패: {error_info}")

        if task.state != 'SUCCESS':
            return redirect(url_for('loading_page', task_id=task.id, result_view='planned_script_result'))

        result = task.result
        if not result or 'result' not in result:
            app.logger.error(f"Planned Script Task {task_id} succeeded but result format is invalid: {result}")
            return render_template('planned_script_result.html', error="결과 형식이 올바르지 않습니다.")
        
        result_data = result.get('result', {})
        return render_template('planned_script_result.html', **result_data)

    @app.route('/get_trend_categories', methods=['POST'])
    @login_required
    def get_trend_categories():
        try:
            raw_response = ai_service.generate_trend_ideas()
            
            if raw_response.startswith("⚠️"):
                return jsonify({'error': raw_response})
            
            categories = []
            for line in raw_response.strip().split('\n'):
                cleaned_line = line.strip()
                if cleaned_line:
                    if ':' in cleaned_line:
                        topic_text = cleaned_line.split(':', 1)[1].strip()
                    elif cleaned_line.startswith('-'):
                        topic_text = cleaned_line[1:].strip()
                    else:
                        topic_text = cleaned_line
                    
                    if topic_text:
                        categories.append(topic_text)

            if not categories:
                app.logger.error(f"트렌드 추천 파싱 최종 실패. AI 원본 응답: {raw_response}")
                return jsonify({'error': 'AI가 추천한 트렌드를 해석하는 데 실패했습니다.'}), 500

            return jsonify({'categories': categories})
        except Exception as e:
            app.logger.error(f'트렌드 분석 중 심각한 서버 오류 발생: {e}', exc_info=True)
            return jsonify({'error': f'트렌드 분석 중 심각한 서버 오류가 발생했습니다. 잠시 후 다시 시도해주세요.'}), 500

    @app.route('/expand_pillar', methods=['POST'])
    @login_required
    def expand_pillar():
        try:
            pillar_topic = request.form.get('pillar_topic')
            existing_topics_str = request.form.get('existing_topics', '')
            raw_response = ai_service.expand_pillar_topics(pillar_topic, existing_topics_str)
            if raw_response.startswith("⚠️"):
                return jsonify({'error': raw_response})
            new_topics = []
            for line in raw_response.strip().split('\n'):
                cleaned_line = line.strip()
                if cleaned_line.startswith(('-', '*')):
                    try:
                        if ':' in cleaned_line:
                            topic_text = cleaned_line.split(':', 1)[1].strip()
                        else:
                            topic_text = cleaned_line[1:].strip()
                        new_topics.append(topic_text)
                    except IndexError:
                       app.logger.error(f"주제 확장 파싱 오류: {line}")
            return jsonify({'new_topics': new_topics})
        except Exception as e:
            app.logger.error(f'주제 확장 중 서버 오류: {str(e)}')
            return jsonify({'error': f'주제 확장 중 서버 오류'}), 500
    
    @app.route('/loading/<task_id>')
    @login_required
    def loading_page(task_id):
        result_view = request.args.get('result_view', 'analysis_result')
        task_type = request.args.get('task_type', 'celery') 
        return render_template('loading.html', task_id=task_id, is_restored=False, result_view=result_view, task_type=task_type)

    @app.route('/task_status/<task_id>')
    @login_required
    def task_status(task_id):
        task = AsyncResult(task_id, app=celery_app)
        response_data = {'state': task.state}
        if task.state == 'PROGRESS':
            response_data['status'] = task.info.get('status', '진행 중...')
        elif task.state == 'SUCCESS':
            result_view = request.args.get('result_view', 'analysis_result') 
            response_data['result_url'] = url_for(result_view, task_id=task.id)
            
            try:
                task_result = task.result
                task_name = task_result.get('name')
                user_id = task_result.get('kwargs', {}).get('user_id') if task_result.get('kwargs') else None

                if user_id:
                    user = db.session.get(User, user_id)
                    if user and not user.is_admin:
                        credit_cost = 0
                        if 'rewrite_script_task' in task_name: credit_cost = 3
                        elif 'rewrite_script_v13_task' in task_name: credit_cost = 5
                        elif 'extract_and_analyze_task' in task_name: credit_cost = 2
                        elif 'analyze_text_task' in task_name: credit_cost = 2
                        elif 'analyze_channel_task' in task_name: credit_cost = 10
                        elif 'generate_planned_script_task' in task_name: credit_cost = 2

                        if credit_cost > 0:
                            if user.credits >= credit_cost:
                                user.credits -= credit_cost
                                db.session.commit()
                                app.logger.info(f"'{user.username}' 사용자의 크레딧 {credit_cost} 차감 완료. 남은 크레딧: {user.credits}")
                            else:
                                flash(f"작업(ID:{task_id[:8]}...)은 완료되었지만, 크레딧이 부족하여 차감되지 않았습니다. (필요: {credit_cost}, 보유: {user.credits})", "warning")
                                app.logger.warning(f"'{user.username}' 사용자의 크레딧이 부족하여 {credit_cost} 크레딧 차감에 실패했습니다. (보유: {user.credits})")
            except Exception as e:
                app.logger.error(f"크레딧 차감 중 심각한 오류 발생: {e}")

        elif task.state == 'FAILURE':
            response_data['status'] = str(task.info)
        return jsonify(response_data)
    
    @app.route('/generate_tts', methods=['POST'])
    @login_required
    def generate_tts():
        script = request.form.get('script')
        if not script:
            flash("음성으로 변환할 대본이 없습니다.", "danger")
            return redirect(request.referrer or url_for('dashboard'))

        try:
            audio_buffer = tts_service.text_to_speech_file(script)
            if audio_buffer:
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                filename = f"generated_speech_{timestamp}.mp3"
                
                return send_file(
                    audio_buffer,
                    as_attachment=True,
                    download_name=filename,
                    mimetype='audio/mpeg'
                )
            else:
                raise Exception("오디오 버퍼 생성 실패")
        except Exception as e:
            app.logger.error(f"TTS 생성 중 오류 발생: {e}")
            flash(f"음성 파일을 생성하는 중 오류가 발생했습니다: {e}", "danger")
            return redirect(request.referrer or url_for('dashboard'))
    
    @app.route('/generate_sseoltoon_prompt', methods=['POST'])
    @login_required
    def generate_sseoltoon_prompt():
        script = request.form.get('script')
        title = request.form.get('title', '웹툰 프롬프트')
        if not script:
            return "오류: 프롬프트를 생성할 대본이 없습니다.", 400
        
        prompt = ai_service.pt.SSEOLTOON_PROMPT.format(script=script)
        result = ai_service._safe_generate_openai(prompt, model_name=ai_service.config.PREMIUM_MODEL, temperature=0.5)

        print(f"--- [Webtoon Prompt] AI Raw Response ---\n{result}\n------------------------------------")

        if result.startswith("⚠️"):
            return f"오류: AI 프롬프트 생성에 실패했습니다. ({result})", 500
        
        parsed_prompts = parse_prompt_response(result)

        return render_template("webtoon_prompt.html", webtoon_prompts=parsed_prompts, original_script=script, title=title)

    @app.route('/generate_imagefx_prompt', methods=['POST'])
    @login_required
    def generate_imagefx_prompt():
        script = request.form.get('script')
        title = request.form.get('title', 'ImageFX 프롬프트')
        if not script:
            return "오류: 프롬프트를 생성할 대본이 없습니다.", 400
            
        prompt = ai_service.pt.IMAGEFX_PROMPT.format(script=script)
        result = ai_service._safe_generate_openai(prompt, model_name=ai_service.config.PREMIUM_MODEL, temperature=0.5)
        
        print(f"--- [ImageFX Prompt] AI Raw Response ---\n{result}\n------------------------------------")

        if result.startswith("⚠️"):
            return f"오류: AI 프롬프트 생성에 실패했습니다. ({result})", 500
        
        parsed_prompts = parse_prompt_response(result)
        
        return render_template("image_prompt.html", imagefx_prompts=parsed_prompts, original_script=script, title=title)

    @app.route('/v12_rewrite', methods=['POST'])
    @login_required
    def v12_rewrite():
        if not current_user.is_admin:
            credit_cost = 3
            if current_user.credits < credit_cost:
                message = f"V12 각색을 위해서는 {credit_cost} 크레딧이 필요합니다. (현재 보유 크레딧: {current_user.credits})"
                return redirect(url_for('error_page', message=message))

        original_script = request.form.get('original_script')
        category = request.form.get('category')
        title = request.form.get('title', '제목 없음')
        original_task_id = request.form.get('original_task_id')
        
        task = celery_app.send_task('celery_worker.rewrite_script_task', args=[original_script, category, title, original_task_id], kwargs={'user_id': current_user.id})
        return redirect(url_for('loading_page', task_id=task.id, result_view='v12_result_page'))

    @app.route('/v12_result_page/<task_id>')
    @login_required
    def v12_result_page(task_id):
        task = AsyncResult(task_id, app=celery_app)
        if task.state == 'FAILURE':
            error_info = str(task.info)
            task_info = task.backend.get(task.id)
            original_script = task_info.get('args', [''])[0] if task_info else ''
            return render_template('v12_result.html', error=error_info, original_script=original_script)
        if task.state != 'SUCCESS':
            return redirect(url_for('loading_page', task_id=task.id, result_view='v12_result_page'))
        result = task.result.get('result', {})
        return render_template('v12_result.html', **result)

    @app.route('/v13_rewrite', methods=['POST'])
    @login_required
    def v13_rewrite():
        if not current_user.is_admin:
            credit_cost = 5
            if current_user.credits < credit_cost:
                message = f"V13 안전 각색을 위해서는 {credit_cost} 크레딧이 필요합니다. (현재 보유 크레딧: {current_user.credits})"
                return redirect(url_for('error_page', message=message))

        original_script = request.form.get('original_script')
        category = request.form.get('category')
        title = request.form.get('title', '제목 없음')
        original_task_id = request.form.get('original_task_id')
        
        task = celery_app.send_task('celery_worker.rewrite_script_v13_task', args=[original_script, category, title, original_task_id], kwargs={'user_id': current_user.id})
        return redirect(url_for('loading_page', task_id=task.id, result_view='v13_result_page'))

    @app.route('/v13_result_page/<task_id>')
    @login_required
    def v13_result_page(task_id):
        task = AsyncResult(task_id, app=celery_app)
        if task.state == 'FAILURE':
            error_info = str(task.info)
            task_info = task.backend.get(task.id)
            original_script = task_info.get('args', [''])[0] if task_info else ''
            return render_template('v13_result.html', error=error_info, original_script=original_script)
        if task.state != 'SUCCESS':
            return redirect(url_for('loading_page', task_id=task.id, result_view='v13_result_page'))
        
        result = task.result.get('result', {})
        return render_template('v13_result.html', **result)

    @app.route('/content_analysis')
    @login_required
    def content_analysis():
        return render_template('analysis_entry.html')

    @app.route('/extract_script', methods=['POST'])
    @login_required
    def extract_script():
        if not current_user.is_admin:
            credit_cost = 2
            if current_user.credits < credit_cost:
                message = f"콘텐츠 분석을 위해서는 {credit_cost} 크레딧이 필요합니다. (현재 보유 크레딧: {current_user.credits})"
                return redirect(url_for('error_page', message=message))
        
        youtube_link = request.form.get('youtube_link')
        if not youtube_link:
            flash("유튜브 영상 URL을 입력해주세요.", "danger")
            return redirect(url_for('content_analysis'))
        
        task = celery_app.send_task('celery_worker.extract_and_analyze_task', args=[youtube_link], kwargs={'user_id': current_user.id})
        return redirect(url_for('loading_page', task_id=task.id, result_view='analysis_result'))

    @app.route('/upload_script', methods=['POST'])
    @login_required
    def upload_script():
        if not current_user.is_admin:
            credit_cost = 2
            if current_user.credits < credit_cost:
                message = f"콘텐츠 분석을 위해서는 {credit_cost} 크레딧이 필요합니다. (현재 보유 크레딧: {current_user.credits})"
                return redirect(url_for('error_page', message=message))

        script_content = request.form.get('script_content')
        filename = request.form.get('filename', '사용자 입력 대본')
        if not script_content:
            flash("분석할 대본 내용을 입력해주세요.", "danger")
            return redirect(url_for('content_analysis'))

        task = celery_app.send_task('celery_worker.analyze_text_task', args=[script_content, filename], kwargs={'user_id': current_user.id})
        return redirect(url_for('loading_page', task_id=task.id, result_view='analysis_result'))
    
    @app.route('/analysis_result/<task_id>')
    @login_required
    def analysis_result(task_id):
        task = AsyncResult(task_id, app=celery_app)
        
        if task.state == 'FAILURE':
            error_info = str(task.info)
            return redirect(url_for('error_page', message=f"분석 중 오류가 발생했습니다: {error_info}"))

        if task.state != 'SUCCESS':
            return redirect(url_for('loading_page', task_id=task.id, result_view='analysis_result'))
            
        result = task.result.get('result', {})
        
        return render_template('loading.html', 
                               is_restored=True, 
                               initial_data_json=json.dumps(result),
                               task_id=task_id,
                               result_view='analysis_result')

    @app.route('/performance_predictor', methods=['GET', 'POST'])
    @login_required
    def performance_predictor():
        if request.method == 'POST':
            if not current_user.is_admin:
                credit_cost = 1
                if current_user.credits < credit_cost:
                    message = f"성과 예측을 위해서는 {credit_cost} 크레딧이 필요합니다. (현재 보유 크레딧: {current_user.credits})"
                    return redirect(url_for('error_page', message=message))
            
            script = request.form.get('script')
            if not script or not script.strip():
                return render_template('performance_prediction.html', error="분석할 대본을 입력해주세요.")

            raw_prediction = ai_service.predict_script_performance(script)
            
            if raw_prediction.startswith("⚠️"):
                return render_template('performance_prediction.html', error=raw_prediction, original_script=script)
            
            if not current_user.is_admin:
                user = db.session.get(User, current_user.id)
                user.credits -= 1
                db.session.commit()
                flash(f"성과 예측 완료! 1 크레딧이 차감되었습니다.", "success")
            
            prediction_data = _parse_prediction_report(raw_prediction)
            
            return render_template('performance_prediction.html', prediction_data=prediction_data, original_script=script)
        
        return render_template('performance_prediction.html')

    @app.route('/single_channel_analysis')
    @login_required
    def single_channel_analysis():
        return render_template('single_channel_form.html')

    @app.route('/analyze_channel', methods=['POST'])
    @login_required
    def analyze_channel():
        if not current_user.is_admin:
            credit_cost = 10
            if current_user.credits < credit_cost:
                message = f"채널 분석을 위해서는 {credit_cost} 크레딧이 필요합니다. (현재 보유 크레딧: {current_user.credits})"
                return redirect(url_for('error_page', message=message))

        channel_url = request.form.get('channel_url_or_id')
        if not channel_url:
            flash("채널 URL을 입력해주세요.", "danger")
            return redirect(url_for('single_channel_analysis'))
        
        task = celery_app.send_task('celery_worker.analyze_channel_task', args=[channel_url], kwargs={'user_id': current_user.id})
        return redirect(url_for('loading_page', task_id=task.id, result_view='channel_analysis_result'))

    @app.route('/channel_analysis_result/<task_id>')
    @login_required
    def channel_analysis_result(task_id):
        task = AsyncResult(task_id, app=celery_app)
        if task.state == 'FAILURE':
            error_info = str(task.info)
            app.logger.error(f"Channel Analysis Task {task_id} failed: {error_info}")
            return redirect(url_for('error_page', message=f"채널 분석 중 오류가 발생했습니다: {error_info}"))
        
        if task.state != 'SUCCESS':
            return redirect(url_for('loading_page', task_id=task.id, result_view='channel_analysis_result'))
        
        result_data = task.result.get('result', {})
        
        channel_info = result_data.get('channel_info', {})
        revenue_info = result_data.get('revenue_info', {})
        content_info = result_data.get('content_info', {})
        report_html = result_data.get('report_html', {})

        return render_template(
            'channel_analysis_result.html',
            channel_title=channel_info.get('channel_title', 'N/A'),
            subscriber_count=channel_info.get('subscriber_count', 'N/A'),
            recent_3_month_views=channel_info.get('recent_3_month_views', 'N/A'),
            avg_long_form_views=channel_info.get('avg_long_form_views', 'N/A'),
            avg_short_form_views=channel_info.get('avg_short_form_views', 'N/A'),
            revenue_info=revenue_info,
            report_html=report_html,
            content_strategy_analysis=content_info,
            popular_videos=channel_info.get('popular_videos', [])
        )
    
    @app.route('/analyze_single_video', methods=['POST'])
    @login_required
    def analyze_single_video():
        data = request.get_json()
        video_id = data.get('video_id')
        if not video_id:
            return jsonify({'error': '영상 ID가 필요합니다.'}), 400
        
        result = ai_service.analyze_single_video(video_id)
        if result.get('error'):
            return jsonify({'error': result['error']}), 500
        
        return jsonify(result)

    @app.route('/get_absorption_strategy', methods=['POST'])
    @login_required
    def get_absorption_strategy():
        data = request.get_json()
        competitor_video_id = data.get('competitor_video_id')
        my_channel_title = data.get('my_channel_title')
        my_channel_description = data.get('my_channel_description')

        if not competitor_video_id:
            return jsonify({'error': '경쟁 영상 ID가 필요합니다.'}), 400

        result = ai_service.get_absorption_strategy(
            competitor_video_id, 
            my_channel_title, 
            my_channel_description, 
            whisper_model_loader=get_whisper_model
        )
        
        if result.get('error'):
            return jsonify({'error': result['error']}), 500
        
        return jsonify(result)

    @app.route('/compare_form')
    @login_required
    def compare_form():
        return render_template('compare_form.html')

    @app.route('/compare_channels', methods=['POST'])
    @login_required
    def compare_channels():
        my_channel_url = request.form.get('my_channel_url')
        competitor_urls = request.form.getlist('competitor_urls')
        
        all_urls = [my_channel_url] + [url for url in competitor_urls if url]
        if len(all_urls) < 2:
            flash("비교를 위해 최소 2개 이상의 채널 URL을 입력해주세요.", "danger")
            return redirect(url_for('compare_form'))
            
        if not current_user.is_admin:
            credit_cost = len(all_urls)
            if current_user.credits < credit_cost:
                message = f"채널 비교 분석에는 채널당 1크레딧, 총 {credit_cost} 크레딧이 필요합니다. (현재 보유 크레딧: {current_user.credits})"
                return redirect(url_for('error_page', message=message))

        results = []
        extractor = YouTubeDataExtractor(whisper_model_loader=get_whisper_model)
        
        for url in all_urls:
            channel_info = extractor.extract_channel_info(url)
            if 'error' in channel_info:
                results.append({'error': channel_info['error'], 'channel_title': url})
                continue

            revenue_info = calculator.estimate_monthly_revenue(channel_info)
            content_info = content_analyzer.analyze_content_strategy(channel_info.get('videos_data', []))
            
            channel_id = extractor._get_channel_id(url)
            popular_videos = extractor.get_popular_videos(channel_id, max_results=1) if channel_id else []
            
            combined_result = {**channel_info, 'revenue_info': revenue_info, **content_info, 'top_video': popular_videos[0] if popular_videos else None}
            results.append(combined_result)
        
        if not current_user.is_admin:
            user = db.session.get(User, current_user.id)
            user.credits -= credit_cost
            db.session.commit()
            flash(f"채널 비교 분석이 완료되었습니다. {credit_cost} 크레딧이 차감되었습니다.", "info")

        return render_template('compare_results.html', results=results)

    @app.route('/admin')
    @login_required
    def admin_redirect():
        if not current_user.is_admin:
            flash("관리자만 접근 가능합니다.", "danger")
            return redirect(url_for('start'))
        return redirect(url_for('admin_dashboard'))

    @app.route('/admin/dashboard')
    @login_required
    def admin_dashboard():
        if not current_user.is_admin:
            flash("관리자만 접근 가능합니다.", "danger")
            return redirect(url_for('start'))
        
        user_count = db.session.query(User).count()
        users = User.query.order_by(User.id.asc()).all()
        analysis_count = AnalysisHistory.query.count()
        feedback_count = Feedback.query.count()
        
        stats = {
            'user_count': user_count,
            'analysis_count': analysis_count,
            'feedback_count': feedback_count
        }
        
        return render_template('admin_dashboard.html', stats=stats, users=users)

    @app.route('/admin/user/<int:user_id>/update_credits', methods=['POST'])
    @login_required
    def update_credits(user_id):
        if not current_user.is_admin:
            return jsonify({'error': '권한 없음'}), 403
        
        user = db.session.get(User, user_id)
        if not user:
            return jsonify({'error': '사용자를 찾을 수 없음'}), 404
            
        try:
            amount = int(request.form.get('amount'))
            user.credits += amount
            db.session.commit()
            flash(f"'{user.username}'님의 크레딧이 {amount}만큼 변경되었습니다. (현재: {user.credits})", "success")
            return redirect(url_for('admin_dashboard'))
        except (ValueError, TypeError):
            flash("유효한 숫자를 입력해주세요.", "danger")
            return redirect(url_for('admin_dashboard'))

    @app.route('/admin/user/<int:user_id>/toggle_admin', methods=['POST'])
    @login_required
    def toggle_admin(user_id):
        if not current_user.is_admin:
            return jsonify({'error': '권한 없음'}), 403

        user_to_modify = db.session.get(User, user_id)
        if not user_to_modify:
            return jsonify({'error': '사용자를 찾을 수 없음'}), 404
        
        if user_to_modify.id == current_user.id and user_to_modify.is_admin:
            flash("자기 자신의 관리자 권한은 해제할 수 없습니다.", "warning")
            return redirect(url_for('admin_dashboard'))

        user_to_modify.is_admin = not user_to_modify.is_admin
        db.session.commit()
        status = "관리자로 임명" if user_to_modify.is_admin else "관리자 권한 해제"
        flash(f"'{user_to_modify.username}'님을 {status}했습니다.", "success")
        return redirect(url_for('admin_dashboard'))

    @app.cli.command("set-admin")
    @click.argument("email")
    def set_admin(email):
        """지정된 이메일의 사용자를 관리자로 설정합니다."""
        user = User.query.filter_by(email=email).first()
        if user:
            user.is_admin = True
            db.session.add(user)
            db.session.commit()
            print(f"성공: 사용자 '{user.username}' ({email}) 님이 이제 관리자입니다.")
        else:
            print(f"오류: 이메일 '{email}'을(를) 가진 사용자를 찾을 수 없습니다.")

    @app.cli.command("check-user")
    @click.argument("email")
    def check_user(email):
        """지정된 이메일의 사용자 상태를 확인합니다."""
        user = User.query.filter_by(email=email).first()
        if user:
            print(f"--- 사용자 정보: {email} ---")
            print(f"사용자 이름: {user.username}")
            print(f"관리자 여부 (is_admin): {user.is_admin}")
            print(f"--------------------------")
        else:
            print(f"오류: 사용자를 찾을 수 없습니다.")

    return app

if __name__ == '__main__':
    app = create_app()
    with app.app_context():
        db.create_all()
    
    app.run(debug=True, use_reloader=True)