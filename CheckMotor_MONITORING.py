#!/usr/bin/env python3
import time
from lerobot.motors.feetech import FeetechMotorsBus
from lerobot.motors.motors_bus import Motor, MotorNormMode

PORT = "COM7"        # 환경에 맞게 수정
MODEL = "sts3215"               # 대소문자 주의
ID_LIST = [1, 2, 3, 4, 5, 6]    # 6축

def motor_name(mid: int) -> str:
    return f"joint_{mid}"

def build_bus():
    motors = {
        motor_name(mid): Motor(
            id=mid,
            model=MODEL,
            norm_mode=MotorNormMode.RANGE_0_100  # 본 예제는 normalize=False로 스텝 직접 사용
        )
        for mid in ID_LIST
    }
    bus = FeetechMotorsBus(port=PORT, motors=motors)
    bus.connect()
    return bus


def _set_torque(bus, name, val: int):
    """Torque_Enable 안전 쓰기 (잠금 해제/복구 포함 시도)"""
    try:
        bus.write("Torque_Enable", name, val, normalize=False)
        return
    except Exception:
        pass
    try:
        bus.write("Lock", name, 0, normalize=False)
        bus.write("Torque_Enable", name, val, normalize=False)
    except Exception:
        pass
    finally:
        try:
            bus.write("Lock", name, 1, normalize=False)
        except Exception:
            pass


def option_stream_all_positions(bus, hz=10.0):
    """
    6개 ID 모두를 실시간으로 읽기.
    - 진입 시: 전 축 Torque OFF → 손으로 돌릴 수 있음
    - 종료 시: 전 축의 '기존 토크 상태'로 복구
    """
    names = [motor_name(mid) for mid in ID_LIST]

    # 기존 토크 상태 저장
    prev_torque = {}
    for name in names:
        try:
            prev_torque[name] = int(bus.read("Torque_Enable", name, normalize=False))
        except Exception:
            prev_torque[name] = 1  # 읽기 실패 시 ON 가정

    # 전 축 Freewheel: 토크 OFF
    for name in names:
        _set_torque(bus, name, 0)

    print("실시간 각도 읽기 시작 (6축, 자유이동). 손으로 모터를 돌릴 수 있습니다. 종료: Ctrl+C")
    interval = 0.1 / hz
    try:
        while True:
            vals = []
            for mid, name in zip(ID_LIST, names):
                try:
                    pos = bus.read("Present_Position", name, normalize=False)
                    vals.append(f"{mid}:{pos:4d}")
                except Exception:
                    vals.append(f"{mid}:----")
            # 한 줄 갱신
            line = "  ".join(vals)
            print(f"\r{line}  ", end="", flush=True)
            time.sleep(interval)
    except KeyboardInterrupt:
        print("\n실시간 읽기 종료, 토크 상태 복구 중...")
    finally:
        # 이전 토크 상태로 복구
        for name in names:
            _set_torque(bus, name, prev_torque[name])
        restored = " ".join([f"{mid}:{'ON' if prev_torque[motor_name(mid)]==1 else 'OFF'}" for mid in ID_LIST])
        print(f"토크 상태 복구 완료 → {restored}")

def main():
    bus = build_bus()
    print("모터 모니터링 프로그램 시작")
    print("=" * 50)

    try:
        while True:
            print("\n=== 모터 모니터링 메뉴 ===")
            print("1) 실시간 모터 각도 읽기 (6축 동시)")
            print("0) 종료")
            choice = input("선택: ").strip()

            if choice == "1":
                option_stream_all_positions(bus, hz=10.0)
            elif choice == "0":
                print("종료합니다.")
                break
            else:
                print("올바른 번호를 선택하세요.")
    finally:
        # 종료 시 전체 축 토크 OFF 권장
        print("종료 전 모든 모터 토크 OFF...")
        for mid in ID_LIST:
            name = motor_name(mid)
            try:
                bus.write("Torque_Enable", name, 0, normalize=False)
            except Exception:
                pass
        bus.disconnect()

if __name__ == "__main__":
    main()
