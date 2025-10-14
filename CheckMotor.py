#!/usr/bin/env python3
import time
from lerobot.motors.feetech import FeetechMotorsBus
from lerobot.motors.motors_bus import Motor, MotorNormMode

PORT = "COM3"           # 환경에 맞게 수정
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

def setup_motor_runtime(bus, name, max_pos_guess=4095):
    """
    런타임(전원 인가 후) 기본 설정.
    - 안전 순서: 토크 OFF → 잠금 해제 → 설정 → 잠금 → 토크 ON
    - 영구 레지스터(리밋 등) 잦은 쓰기는 피하고 싶다면 최초 1회만 수행하세요.
    """
    try:
        bus.write("Torque_Enable", name, 0, normalize=False)
        bus.write("Lock",          name, 0, normalize=False)
    except Exception:
        pass

    # 모델 해상도 가져오기 (없으면 추정값)
    try:
        model = bus.motors[name].model
        max_pos = bus.model_resolution_table.get(model, max_pos_guess) - 1
    except Exception:
        max_pos = max_pos_guess

    # 포지션 모드로 설정
    bus.write("Operating_Mode",       name, 0,          normalize=False)  # 0 = POSITION
    # 필요시 첫 세팅에서만 아래 3개를 쓰세요 (EEPROM/Flash 수명 고려)
    bus.write("Min_Position_Limit",   name, 0,          normalize=False)
    bus.write("Max_Position_Limit",   name, max_pos,    normalize=False)
    bus.write("Max_Torque_Limit",     name, 1023,       normalize=False)
    bus.write("Minimum_Startup_Force",name, 50,         normalize=False)

    # 프로파일(미지원 모델은 예외 무시)
    try:
        bus.write("Profile_Velocity",     name, 300, normalize=False)
        bus.write("Profile_Acceleration", name, 50,  normalize=False)
    except Exception:
        pass

    try:
        bus.write("Lock", name, 1, normalize=False)
    except Exception:
        pass
    bus.write("Torque_Enable", name, 1, normalize=False)
    return max_pos

def choose_id(prompt="모터 ID 선택 (1~6): "):
    raw = input(prompt).strip()
    if not raw.isdigit():
        print("숫자를 입력하세요.")
        return None
    mid = int(raw)
    if mid not in ID_LIST:
        print(f"ID {mid} 는 유효하지 않습니다. {ID_LIST} 중에서 선택하세요.")
        return None
    return mid

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

def option_move(bus):
    mid = choose_id()
    if mid is None:
        return
    name = motor_name(mid)
    max_pos = setup_motor_runtime(bus, name)  # 필요 시 최소 설정 보증

    # 각도 입력
    try:
        raw = input(" 모터 각도 : ").strip()
        if raw == "":
            print("입력이 없어 메뉴로 돌아갑니다.")
            return
        target = int(raw)
    except ValueError:
        print("정수 값을 입력하세요. 예) 2000")
        return

    # 클램프
    target = max(0, min(target, max_pos))

    # 이동 전 토크 ON 보장
    _set_torque(bus, name, 1)
    bus.write("Operating_Mode", name, 0, normalize=False)  # POSITION
    bus.write("Goal_Position",  name, target, normalize=False)
    print(f"[ID {mid}] → Goal_Position = {target} 로 이동 명령 보냄")

def option_move_all(bus):
    """
    6개 모터 모두에게 동일한 각도를 설정
    """
    # 각도 입력
    try:
        raw = input(" 모터 각도 (모든 모터에 적용): ").strip()
        if raw == "":
            print("입력이 없어 메뉴로 돌아갑니다.")
            return
        target = int(raw)
    except ValueError:
        print("정수 값을 입력하세요. 예) 2000")
        return

    # 각 모터에 대해 설정 및 이동 명령
    for mid in ID_LIST:
        name = motor_name(mid)
        max_pos = setup_motor_runtime(bus, name)  # 필요 시 최소 설정 보증
        
        # 클램프
        clamped_target = max(0, min(target, max_pos))
        
        # 이동 전 토크 ON 보장
        _set_torque(bus, name, 1)
        bus.write("Operating_Mode", name, 0, normalize=False)  # POSITION
        bus.write("Goal_Position",  name, clamped_target, normalize=False)
        print(f"[ID {mid}] → Goal_Position = {clamped_target} 로 이동 명령 보냄")

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
    try:
        # 필요 시 최초 1회 전체 축 세팅하려면 주석 해제
        # for mid in ID_LIST:
        #     setup_motor_runtime(bus, motor_name(mid))

        while True:
            print("\n=== 메뉴 ===")
            print("1) 모터 회전제어(각도 명령) - ID 지정")
            print("2) 실시간 모터 각도 읽기(6축 동시, Freewheel)")
            print("3) 모든 모터 회전제어(각도 명령) - 각도 지정")
            print("0) 종료")
            choice = input("선택: ").strip()

            if choice == "1":
                option_move(bus)
            elif choice == "2":
                option_stream_all_positions(bus, hz=10.0)
            elif choice == "3":
                option_move_all(bus)
            elif choice == "0":
                print("종료합니다.")
                break
            else:
                print("올바른 번호를 선택하세요.")
    finally:
        # 종료 시 전체 축 토크 OFF 권장
        for mid in ID_LIST:
            name = motor_name(mid)
            try:
                bus.write("Torque_Enable", name, 0, normalize=False)
            except Exception:
                pass
        bus.disconnect()

if __name__ == "__main__":
    main()
