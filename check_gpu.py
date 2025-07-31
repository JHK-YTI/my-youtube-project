# check_gpu.py
import torch
import sys

print("="*50)
print(f"파이썬 실행 경로: {sys.executable}")
print(f"PyTorch 라이브러리 버전: {torch.__version__}")
print("="*50)

try:
    is_gpu_available = torch.cuda.is_available()
    print(f"NVIDIA GPU 사용 가능 여부: {is_gpu_available}")

    if is_gpu_available:
        gpu_count = torch.cuda.device_count()
        gpu_name = torch.cuda.get_device_name(0)
        print(f"사용 가능한 GPU 개수: {gpu_count}")
        print(f"GPU 모델명: {gpu_name}")
        print("\n>>> [결론] 성공: PyTorch가 GPU를 성공적으로 인식했습니다.")
        print(">>> 만약 속도가 여전히 느리다면, GPU의 절대적인 성능 또는 다른 프로그램의 GPU 점유가 원인일 수 있습니다.")
    else:
        print("\n>>> [결론] 문제 발견: PyTorch가 NVIDIA GPU를 인식하지 못하고 있습니다.")
        print(">>> 이 상태에서는 device='cuda' 옵션을 주어도 항상 CPU로만 작동합니다.")
        print(">>> 해결책: 현재 설치된 PyTorch를 삭제하고, GPU를 지원하는 버전으로 재설치해야 합니다.")

except Exception as e:
    print(f"\n[오류] 테스트 중 예외가 발생했습니다: {e}")

print("="*50)