#!/usr/bin/env python3
"""
rotation-generator: 고정 명단/구역을 규칙에 따라 순환시켜 이번 주 매핑을 산출한다.

사용법:
  python3 rotation.py run [--date YYYY-MM-DD] [--state PATH] [--history PATH]
  python3 rotation.py report-vacancy NAME [--date YYYY-MM-DD] [--state PATH]

설계서(써리힐즈 청소당번 자동화 설계서) 2장/3장 참조.
"""
import argparse
import json
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

DEFAULT_STATE = Path(__file__).resolve().parents[4] / "output" / "state.json"
DEFAULT_HISTORY = Path(__file__).resolve().parents[4] / "output" / "checklist_history.json"


def load_json(path: Path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def save_json(path: Path, data):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def iso_week_str(d: date) -> str:
    y, w, _ = d.isocalendar()
    return f"{y}-W{w:02d}"


def week_range_label(d: date) -> str:
    monday = d - timedelta(days=d.weekday())
    sunday = monday + timedelta(days=6)
    return f"{monday.month}/{monday.day} ~ {sunday.month}/{sunday.day}"


def compute_base_assignment(state):
    zones = state["zones"]
    residents = state["residents"]
    idx = state["rotation_index"]
    n = len(residents)
    return {zone: residents[(i + idx) % n] for i, zone in enumerate(zones)}


def archive_open_week_if_needed(state, history):
    """직전에 계산됐던 주(현재 last_run_iso_week)가 아직 이력에 기록 안 됐으면 기록해둔다.
    (checklist-tracker가 다음 주 실행 시 이 기록을 찾아 마감 처리한다.)"""
    cw = state.get("current_week")
    if not cw:
        return
    wk = cw["iso_week"]
    if wk not in history:
        history[wk] = {
            "assignment": cw["assignment"],
            "status": cw["status"],
            "closed": False,
        }


def apply_carryover(state, assignment, notes):
    carryover = state.get("carryover")
    if carryover and carryover.get("weeks_remaining", 0) > 0:
        zone = carryover["zone"]
        assignment[zone] = carryover["person"]
        notes.append(
            f"{zone}: 지난 결원으로 {carryover['person']}님이 2주 연속 담당 중입니다."
        )
        carryover["weeks_remaining"] -= 1
        state["carryover"] = carryover if carryover["weeks_remaining"] > 0 else None


def apply_vacancy(state, iso_week, assignment, notes):
    vacancy = state.get("vacancy")
    if not vacancy or vacancy.get("week") != iso_week:
        return
    absent = vacancy["name"]
    absent_zone = next((z for z, p in assignment.items() if p == absent), None)
    if absent_zone:
        assignment[absent_zone] = None
        notes.append(f"{absent_zone}: {absent}님 결원으로 이번 주 스킵.")
        n = len(state["residents"])
        zi = state["zones"].index(absent_zone)
        # 다음 순번자(현재 인덱스+1 기준 해당 구역 담당 예정자)가 2주 연속 담당
        next_person = state["residents"][(zi + state["rotation_index"] + 1) % n]
        state["carryover"] = {"zone": absent_zone, "person": next_person, "weeks_remaining": 2}
    state["vacancy"] = None  # 신고 소비


def run(state_path: Path, history_path: Path, run_date: date):
    state = load_json(state_path)
    history = load_json(history_path) if history_path.exists() else {}

    iso_week = iso_week_str(run_date)

    if state.get("last_run_iso_week") == iso_week and state.get("current_week"):
        print(f"[중복 실행 방지] 이번 주({iso_week})는 이미 계산되었습니다. 기존 결과를 표시합니다.")
        print(json.dumps(state["current_week"], ensure_ascii=False, indent=2))
        return

    archive_open_week_if_needed(state, history)

    assignment = compute_base_assignment(state)
    notes = []
    apply_carryover(state, assignment, notes)
    apply_vacancy(state, iso_week, assignment, notes)

    status = {p: "확인대기" for p in assignment.values() if p}

    current_week = {
        "iso_week": iso_week,
        "week_range": week_range_label(run_date),
        "assignment": assignment,
        "status": status,
        "notes": notes,
    }

    state["current_week"] = current_week
    state["last_run_iso_week"] = iso_week
    state["rotation_index"] = (state["rotation_index"] + 1) % len(state["residents"])
    # 주의: state["notice"]는 여기서 건드리지 않는다. notice-formatter가 지난주
    # 공지의 '발송완료' 확인 여부를 먼저 판단한 뒤 이번 주 notice로 갱신해야 하므로,
    # 그 판단 전에 rotation-generator가 값을 지우면 안 된다.

    save_json(state_path, state)
    save_json(history_path, history)

    print(json.dumps(current_week, ensure_ascii=False, indent=2))
    for n in notes:
        print(f"- {n}", file=sys.stderr)


def report_vacancy(state_path: Path, name: str, run_date: date):
    state = load_json(state_path)
    if name not in state["residents"]:
        print(f"오류: '{name}'은(는) 등록된 거주자가 아닙니다. ({', '.join(state['residents'])})", file=sys.stderr)
        sys.exit(1)
    state["vacancy"] = {"name": name, "week": iso_week_str(run_date)}
    save_json(state_path, state)
    print(f"{name}님 결원 신고 완료. 이번 주({iso_week_str(run_date)}) 로테이션 계산 시 반영됩니다.")


def main():
    parser = argparse.ArgumentParser(description="rotation-generator")
    parser.add_argument("--state", type=Path, default=DEFAULT_STATE)
    parser.add_argument("--history", type=Path, default=DEFAULT_HISTORY)
    parser.add_argument("--date", type=str, default=None, help="YYYY-MM-DD (기본값: 오늘)")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("run", help="이번 주 로테이션 계산")

    vac = sub.add_parser("report-vacancy", help="이번 주 결원 신고")
    vac.add_argument("name")

    args = parser.parse_args()
    run_date = datetime.strptime(args.date, "%Y-%m-%d").date() if args.date else date.today()

    if args.command == "run":
        run(args.state, args.history, run_date)
    elif args.command == "report-vacancy":
        report_vacancy(args.state, args.name, run_date)


if __name__ == "__main__":
    main()
