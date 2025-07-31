# services/calculator.py

def _format_korean_currency(amount):
    """숫자를 '억', '만' 단위의 한글 문자열로 변환합니다."""
    if amount < 10000:
        return f"{int(amount):,}원"
    man = int(amount / 10000)
    if man < 10000:
        return f"{man:,}만원"
    eok = int(man / 10000)
    man_remainder = man % 10000
    if man_remainder == 0:
        return f"{eok:,}억원"
    else:
        return f"{eok:,}억 {man_remainder:,}만원"

def estimate_monthly_revenue(channel_data):
    """채널 데이터를 기반으로 월간 예상 수익 범위를 계산합니다."""
    def get_int(val):
        """쉼표가 포함된 문자열이나 None을 안전하게 정수형으로 변환"""
        try:
            return int(str(val or '0').replace(',', ''))
        except:
            return 0
            
    total_long_views = get_int(channel_data.get("total_long_form_views_raw", 0))
    total_short_views = get_int(channel_data.get("total_short_form_views_raw", 0))
    
    # 3개월 데이터이므로 월평균 계산
    monthly_avg_long_views = total_long_views / 3
    monthly_avg_short_views = total_short_views / 3

    # 범용적인 채널에 적용 가능한 현실적인 평균 RPM 단가로 상향 조정
    rpm_long_low = 2500
    rpm_long_high = 4500
    rpm_short_low = 70
    rpm_short_high = 110

    # 수익 계산
    estimated_long_low = (monthly_avg_long_views / 1000) * rpm_long_low
    estimated_long_high = (monthly_avg_long_views / 1000) * rpm_long_high
    estimated_short_low = (monthly_avg_short_views / 1000) * rpm_short_low
    estimated_short_high = (monthly_avg_short_views / 1000) * rpm_short_high
    
    total_estimated_low = estimated_long_low + estimated_short_low
    total_estimated_high = estimated_long_high + estimated_short_high

    # 최종 결과 반환
    return {
        "total_low": _format_korean_currency(total_estimated_low),
        "total_high": _format_korean_currency(total_estimated_high),
        "long_form_low": _format_korean_currency(estimated_long_low),
        "long_form_high": _format_korean_currency(estimated_long_high),
        "short_form_low": _format_korean_currency(estimated_short_low),
        "short_form_high": _format_korean_currency(estimated_short_high),
        "message": "최근 3개월 내 모든 롱폼 영상 조회수, 국내 평균 RPM을 기준으로 한 예측입니다."
    }