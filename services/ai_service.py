# services/ai_service.py

import openai
import os
import config
import prompt_templates as pt
import sys
from datetime import datetime
import re
import json
import time

_openai_api_initialized = False

def _setup_openai_api():
    global _openai_api_initialized
    if _openai_api_initialized:
        return True
    
    try:
        api_key = os.getenv("OPENAI_API_KEY")
        if not api_key:
            print("[ERROR] OpenAI API 키를 찾을 수 없습니다. .env 파일을 확인해주세요.")
            return False
        openai.api_key = api_key
        _openai_api_initialized = True
        return True
    except Exception as e:
        print(f"[ERROR] OpenAI API 설정 중 오류 발생: {e}")
        return False

def _safe_generate_openai(user_prompt, system_prompt=None, model_name="gpt-3.5-turbo", temperature=0.7):
    if not _setup_openai_api():
        return "⚠️ OpenAI API 키가 설정되지 않았습니다."

    max_retries = 3
    retry_delay = 2

    for attempt in range(max_retries):
        try:
            messages = []
            if system_prompt:
                messages.append({"role": "system", "content": system_prompt})
            messages.append({"role": "user", "content": user_prompt})
            
            response = openai.chat.completions.create(
                model=model_name,
                messages=messages,
                temperature=temperature
            )
            if response and response.choices and len(response.choices) > 0 and response.choices[0].message and response.choices[0].message.content:
                return response.choices[0].message.content.strip()
            else:
                print(f"[ERROR] OpenAI API가 비어있거나 예상치 못한 형태의 응답을 반환했습니다: {response}", file=sys.stderr)
                return "⚠️ AI가 응답을 생성했지만, 내용이 비어있습니다. 다시 시도해주세요."
        except (openai.RateLimitError, openai.APIConnectionError, openai.APITimeoutError) as e:
            print(f"[WARN] OpenAI API 호출 실패 (시도 {attempt + 1}/{max_retries}): {type(e).__name__}. {retry_delay}초 후 재시도합니다.")
            if attempt < max_retries - 1:
                time.sleep(retry_delay)
                continue
            else:
                error_message = f"API 서버가 불안정합니다. ({type(e).__name__}) 잠시 후 다시 시도해주세요."
                print(f"[ERROR] 최종 재시도 실패: {e}", file=sys.stderr)
                return f"⚠️ {error_message}"
        except openai.AuthenticationError as e:
            error_message = "OpenAI API 키가 유효하지 않습니다. 관리자에게 문의하여 확인해주세요."
            print(f"[ERROR] AuthenticationError: {e}", file=sys.stderr)
            return f"⚠️ {error_message}"
        except openai.InvalidRequestError as e:
            if "context_length_exceeded" in str(e):
                error_message = "입력된 대본의 양이 너무 많아 AI가 처리할 수 없습니다. 내용을 조금 줄여서 다시 시도해주세요."
                print(f"[ERROR] InvalidRequestError (Context Length): {e}", file=sys.stderr)
                return f"⚠️ {error_message}"
            else:
                error_message = f"AI에 대한 요청이 잘못되었습니다: {e}"
                print(f"[ERROR] InvalidRequestError: {e}", file=sys.stderr)
                return f"⚠️ {error_message}"
        except Exception as e:
            error_message = f"GPT API를 호출하는 중 예측하지 못한 오류가 발생했습니다: {type(e).__name__}"
            print(f"[ERROR] {error_message}: {e}", file=sys.stderr)
            return f"⚠️ {error_message}"
    
    return "⚠️ 알 수 없는 오류로 AI 응답 생성에 최종 실패했습니다."


def postprocess_script(text):
    processed_text = re.sub(r'(\n\s*){2,}', '\n\n', text).strip()
    lines = processed_text.split('\n')
    unique_lines = []
    for line in lines:
        if line.strip() and line.strip() not in [ul.strip() for ul in unique_lines]:
            unique_lines.append(line)
    return "\n".join(unique_lines)

def extract_narration_for_tts(full_script):
    if not full_script:
        return ""
    lines = full_script.split('\n')
    narration_lines = []
    for line in lines:
        if line.strip().startswith('[') and line.strip().endswith(']'):
            continue
        if line.strip().startswith('---') and line.strip().endswith('---'):
            continue
        cleaned_line = re.sub(r'\([^)]*\)', '', line)
        cleaned_line = re.sub(r'^\s*[\w\s]+:\s*', '', cleaned_line)
        if cleaned_line.strip():
            narration_lines.append(cleaned_line.strip())
    return '\n'.join(narration_lines)

def clean_script_for_tts(script_text):
    if not script_text:
        return ""
    cleaned = re.sub(r'\[[^\]]*\]', '', script_text)
    cleaned = re.sub(r'\([^)]*\)', '', cleaned)
    cleaned = cleaned.replace('"', '').replace("'", "")
    cleaned = re.sub(r'^\s*[\w\s]+:\s*', '', cleaned, flags=re.MULTILINE)
    lines = cleaned.strip().split('\n')
    non_empty_lines = [line.strip() for line in lines if line.strip()]
    return '\n'.join(non_empty_lines)

def parse_planned_script_response(ai_response):
    results = {}
    delimiters = {
        'production_script': (r'\[PRODUCTION_SCRIPT_START\](.*?)\[PRODUCTION_SCRIPT_END\]', "제작용 대본 생성에 실패했습니다."),
        'storyboard': (r'\[STORYBOARD_START\](.*?)\[STORYBOARD_END\]', "콘티 추천 생성에 실패했습니다."),
        'followup_topics': (r'\[FOLLOWUP_TOPICS_START\](.*?)\[FOLLOWUP_TOPICS_END\]', "후속 주제 추천 생성에 실패했습니다.")
    }
    for key, (pattern, default_text) in delimiters.items():
        match = re.search(pattern, ai_response, re.DOTALL)
        if match:
            results[key] = match.group(1).strip()
        else:
            results[key] = default_text
    return results

def generate_planned_script(options):
    category = options.get('category')
    
    prompt_config = pt.PLANNER_PROMPTS.get(category)
    if not prompt_config or "system_message" not in prompt_config or "user_message_template" not in prompt_config:
        error_msg = f"'{category}'는 유효하지 않거나 구조가 잘못된 V4 카테고리입니다."
        print(f"[ERROR] {error_msg}")
        return { "error": error_msg, "tts_script": "생성 실패", "production_script": "생성 실패", "storyboard": "생성 실패", "followup_topics": "생성 실패" }

    system_prompt_base = prompt_config.get("system_message")
    user_message_template = prompt_config.get("user_message_template")
    
    if not options.get('target_audience'):
        options['target_audience'] = '모든 연령대의 일반 시청자'
        
    options['category_specific_guide'] = pt.CATEGORY_GUIDES.get(category, "")
    user_prompt = user_message_template.format(**options)

    tone_instruction = f"\n\n[최우선 특별 명령]\n- 이 대본은 반드시 '{options['tone']}' 어조로 서술되어야 합니다. 문체, 단어 선택, 분위기 등 모든 면에서 이 톤앤매너를 최우선으로 고려하여 작성해주세요."
    final_system_prompt = system_prompt_base + tone_instruction

    raw_response = _safe_generate_openai(
        user_prompt=user_prompt,
        system_prompt=final_system_prompt,
        model_name=config.PREMIUM_MODEL, 
        temperature=0.8
    )
    
    if raw_response.startswith("⚠️"):
        return { "error": raw_response, "tts_script": "생성 실패", "production_script": "생성 실패", "storyboard": "생성 실패", "followup_topics": "생성 실패" }
        
    parsed_results = parse_planned_script_response(raw_response)

    production_script = parsed_results.get('production_script', '')
    tts_script = extract_narration_for_tts(production_script)
    parsed_results['tts_script'] = tts_script if tts_script else "TTS용 대본을 추출하지 못했습니다."
        
    return parsed_results


def generate_trend_ideas():
    current_date_str = datetime.now().strftime("%Y년 %m월 %d일")
    category_prompt = pt.TREND_CATEGORY_PROMPT.format(current_date=current_date_str)
    raw_categories = _safe_generate_openai(user_prompt=category_prompt, model_name=config.STANDARD_MODEL, temperature=0.9)
    
    if raw_categories.startswith("⚠️"):
        return raw_categories 

    try:
        if raw_categories.strip().startswith("```json"):
            raw_categories = raw_categories.strip()[7:-3].strip()
        
        parsed_json = json.loads(raw_categories)
        categories = [item['category_name'] for item in parsed_json.get('categories', [])]
    except (json.JSONDecodeError, KeyError) as e:
        print(f"[ERROR] 트렌드 카테고리 JSON 파싱 실패: {e}\n원본 AI 응답: {raw_categories}")
        return "⚠️ AI가 트렌드 카테고리를 생성했지만, 응답 형식이 잘못되었습니다."

    if not categories:
        return "⚠️ AI가 트렌드 카테고리를 생성하는 데 실패했습니다."

    all_topics = []
    import random
    selected_categories = random.sample(categories, min(len(categories), 3))

    for category in selected_categories:
        topic_prompt = pt.TOPIC_WITHIN_CATEGORY_PROMPT.format(category=category)
        raw_topics = _safe_generate_openai(user_prompt=topic_prompt, model_name=config.STANDARD_MODEL, temperature=0.8)
        
        if raw_topics.startswith("⚠️"):
            print(f"[WARN] 카테고리 '{category}'의 주제 생성 실패: {raw_topics}")
            continue
        
        topics = [line.replace('-', '').strip() for line in raw_topics.strip().split('\n') if line.strip()]
        all_topics.extend(topics)

    if not all_topics:
        return "⚠️ AI가 최종 주제를 생성하는 데 실패했습니다."

    final_selection = random.sample(all_topics, min(len(all_topics), 5))
    return "\n".join(final_selection)

def rewrite_script_v12(original_script, category='ssultoon'):
    if not original_script or not original_script.strip():
        return "⚠️ 각색할 원본 대본이 없습니다."
    
    prompt_config = pt.REWRITE_PROMPTS.get(category)
    if not prompt_config:
        raise ValueError(f"'{category}'는 유효하지 않은 V12 각색 카테고리입니다.")

    final_prompt = prompt_config['prompt'].format(script=original_script)

    rewritten_script = _safe_generate_openai(
        user_prompt=final_prompt, 
        model_name=prompt_config['model'], 
        temperature=prompt_config['temperature']
    )
    if rewritten_script.startswith("⚠️"):
        return f"V12 엔진 각색 실패: {rewritten_script}"
        
    final_script = postprocess_script(rewritten_script)
    
    return final_script

def rewrite_script_v13_safe(original_script, category='ssultoon'):
    if not original_script or not original_script.strip():
        return {"error": "각색할 원본 대본이 없습니다."}

    correction_user_prompt = pt.V13_CORRECTION_PROMPT.format(script=original_script)
    
    corrected_script = _safe_generate_openai(
        user_prompt=correction_user_prompt,
        model_name=config.STANDARD_MODEL,
        temperature=0.1
    )
    
    if corrected_script.startswith("⚠️"):
        print(f"[WARN] V13 각색 1단계(교정) 실패: {corrected_script}. 원본 스크립트로 각색을 계속합니다.")
        corrected_script = original_script

    prompt_config = pt.REWRITE_V13_SAFE_PROMPTS.get(category)
    if not prompt_config:
        return {"error": f"'{category}'는 지원하지 않는 V13 각색 카테고리입니다."}

    final_user_prompt = prompt_config['prompt'].format(corrected_script=corrected_script)
    
    rewritten_script = _safe_generate_openai(
        user_prompt=final_user_prompt, 
        model_name=prompt_config['model'], 
        temperature=prompt_config['temperature']
    )
    
    if rewritten_script.startswith("⚠️"):
        return {"error": f"V13 엔진 각색 실패: {rewritten_script}"}
        
    final_script = clean_script_for_tts(rewritten_script)
    
    return {
        'final_script': final_script,
        'corrected_script': corrected_script,
        'original_script': original_script
    }

def analyze_transcript(transcript_text):
    prompt = pt.ANALYSIS_PROMPT.format(transcript_text=transcript_text)
    return _safe_generate_openai(user_prompt=prompt, model_name=config.PREMIUM_MODEL, temperature=0.5)

def correct_transcript(transcript_text):
    prompt = pt.CORRECTION_PROMPT.format(transcript_text=transcript_text)
    result = _safe_generate_openai(user_prompt=prompt, model_name=config.STANDARD_MODEL, temperature=0.2)
    if result.startswith("⚠️"):
        return transcript_text
    return result

def summarize_script(script_text):
    if not script_text or not script_text.strip():
        return ""
    if len(script_text) <= 6000:
        prompt = f"주어진 [원본]의 핵심 내용을 유지하면서, 3~4 문장의 간결한 요약본으로 만들어주세요.\n\n[원본]\n{script_text}\n\n[요약본]"
        summary = _safe_generate_openai(user_prompt=prompt, model_name=config.FAST_MODEL, temperature=0.3)
        return summary if not summary.startswith("⚠️") else script_text[:500]
    chunk_size = 6000
    chunks = [script_text[i:i+chunk_size] for i in range(0, len(script_text), chunk_size)][:5]
    chunk_summaries = []
    for i, chunk in enumerate(chunks):
        prompt = f"당신은 긴 글의 일부를 읽고 핵심만 요약하는 AI입니다. 다음 [부분 원본]을 2~3문장으로 요약해주세요.\n\n[부분 원본]\n{chunk}\n\n[부분 요약본]"
        chunk_summary = _safe_generate_openai(user_prompt=prompt, model_name=config.FAST_MODEL, temperature=0.3)
        if not chunk_summary.startswith("⚠️"):
            chunk_summaries.append(chunk_summary)
    if not chunk_summaries:
        return script_text[:500]
    final_combined_summary = "\n".join(chunk_summaries)
    return final_combined_summary

def create_content_pillars(main_topic):
    prompt = pt.CREATE_CONTENT_PILLARS_PROMPT.format(main_topic=main_topic)
    return _safe_generate_openai(user_prompt=prompt, model_name=config.PREMIUM_MODEL, temperature=0.8)

def expand_pillar_topics(pillar_topic, existing_topics):
    prompt = pt.EXPAND_PILLAR_TOPICS_PROMPT.format(pillar_topic=pillar_topic, existing_topics=existing_topics)
    return _safe_generate_openai(user_prompt=prompt, model_name=config.STANDARD_MODEL, temperature=0.9)

def predict_script_performance(script):
    prompt = pt.PERFORMANCE_PREDICTION_PROMPT.format(script_text=script)
    return _safe_generate_openai(user_prompt=prompt, model_name=config.PREMIUM_MODEL, temperature=0.6)

def generate_benchmark_report(channel_stats, top_video_titles, top_video_transcripts):
    prompt = pt.BENCHMARKING_REPORT_PROMPT.format(
        channel_stats=channel_stats,
        top_video_titles=top_video_titles,
        top_video_transcripts=top_video_transcripts
    )
    return _safe_generate_openai(user_prompt=prompt, model_name=config.PREMIUM_MODEL, temperature=0.5)

def analyze_single_video(video_id):
    from services.youtube_extractor import YouTubeDataExtractor
    try:
        video_url = f"[https://www.youtube.com/watch?v=](https://www.youtube.com/watch?v=){video_id}"
        extractor = YouTubeDataExtractor()
        _, transcript_text = extractor.extract_video_info_and_transcript(video_url)

        if transcript_text.startswith("⚠️"):
            return {"error": transcript_text}

        analysis_summary = analyze_transcript(transcript_text)
        if analysis_summary.startswith("⚠️"):
            return {"error": analysis_summary}
            
        return {"analysis": analysis_summary}
    except Exception as e:
        print(f"[ERROR] 단일 영상 분석 중 오류: {e}", file=sys.stderr)
        return {"error": "영상을 분석하는 중 서버에서 오류가 발생했습니다."}

def get_absorption_strategy(competitor_video_id, my_channel_title, my_channel_description, whisper_model_loader=None):
    from services.youtube_extractor import YouTubeDataExtractor
    try:
        video_url = f"[https://www.youtube.com/watch?v=](https://www.youtube.com/watch?v=){competitor_video_id}"
        
        extractor = YouTubeDataExtractor(whisper_model_loader=whisper_model_loader)
        
        _, transcript_text = extractor.extract_video_info_and_transcript(video_url)

        if transcript_text.startswith("⚠️"):
            return {"error": transcript_text, "original_script": ""}

        prompt = pt.ABSORPTION_STRATEGY_PROMPT.format(
            competitor_script=transcript_text,
            my_channel_title=my_channel_title,
            my_channel_description=my_channel_description
        )
        
        strategy = _safe_generate_openai(prompt, model_name=config.PREMIUM_MODEL, temperature=0.6)
        
        if strategy.startswith("⚠️"):
            return {"error": strategy, "original_script": transcript_text}

        return {"strategy": strategy, "original_script": transcript_text}
    except Exception as e:
        print(f"[ERROR] 흡수 전략 생성 중 오류: {e}", file=sys.stderr)
        return {"error": "전략을 생성하는 중 서버에서 오류가 발생했습니다.", "original_script": ""}

def run_v4_engine(topic):
    try:
        analysis_prompt = pt.REWRITE_V4_STEP1_ANALYZE.format(original_script=topic)
        analysis_report = _safe_generate_openai(user_prompt=analysis_prompt, model_name=config.PREMIUM_MODEL, temperature=0.3)
        if analysis_report.startswith("⚠️"):
            return {"error": f"1단계 주제 분석 실패: {analysis_report}"}

        draft_prompt = pt.REWRITE_V4_STEP2_DRAFT.format(analysis_report=analysis_report, original_script=topic)
        draft_script = _safe_generate_openai(user_prompt=draft_prompt, model_name=config.PREMIUM_MODEL, temperature=0.7)
        if draft_script.startswith("⚠️"):
            return {"error": f"2단계 초안 작성 실패: {draft_script}"}

        revise_prompt = pt.REWRITE_V4_STEP3_REVISE.format(draft_script=draft_script, analysis_report=analysis_report)
        final_script = _safe_generate_openai(user_prompt=revise_prompt, model_name=config.PREMIUM_MODEL, temperature=0.8)
        if final_script.startswith("⚠️"):
            return {"error": f"3단계 대본 수정 실패: {final_script}"}
        
        guide_prompt = pt.REWRITE_V4_STEP4_GUIDE.format(final_script=final_script)
        production_guide = _safe_generate_openai(user_prompt=guide_prompt, model_name=config.STANDARD_MODEL, temperature=0.5)
        if production_guide.startswith("⚠️"):
            production_guide = "AI 제작 가이드를 생성하는 데 실패했습니다."
            
        tts_script = extract_narration_for_tts(final_script)
        
        return {
            "topic": topic, "analysis_report": analysis_report, "final_script": final_script,
            "tts_script": tts_script, "production_guide": production_guide, "error": None
        }
    except Exception as e:
        print(f"[ERROR] V4 엔진 실행 중 심각한 오류 발생: {e}", file=sys.stderr)
        return {"error": f"V4 엔진 실행 중 예측하지 못한 오류가 발생했습니다: {str(e)}"}