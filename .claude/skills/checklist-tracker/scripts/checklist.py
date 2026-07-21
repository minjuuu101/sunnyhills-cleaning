#!/usr/bin/env python3
"""
checklist-tracker: 마감 처리, 완료 입력 반영, 연속 미제출 카운터, 디파짓 차감, 이력 관리.

사용법:
  python3 checklist.py close-week [--date YYYY-MM-DD] [--state PATH] [--history PATH]
  python3 checklist.py complete NAME [--state PATH] [--history PATH]
  python3 checklist.py summary [--weeks N] [--history PATH]
  python3 checklist.py trim [--months N] [--date YYYY-MM-DD] [--history PATH]
  python3 checklist.py deposit-status [--state PATH]

마감시각 자정+10분 유예, 연속 미제출 카운터, 이름 정확 일치, 디파짓 차감 규칙 참조.

디파짓 규칙: 연속 미제출 1회차는 그냥 넘어가고, 2회차부터(그 연속 스트릭이
끝날 때까지 매회) $10씩 개인 차감 + 공동 풀에 적립. 공동 풀이 $100에 도달하면
회식비로 쓰고 초과분만 남긴 채 리셋. 실제 돈 수금·보관은 운영자가 수동으로
하고, 이 스크립트는 장부(누가 얼마 차감됐는지)만 관리한다.
"""
import argparse
import json
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


def close_week(state_path: Path, history_path: Path, today: date):
    """지난주(state['current_week'])에 아직 '확인대기'인 사람을 '미제출'로 전환하고
    연속 미제출 카운터를 갱신한 뒤 이력에 확정 기록한다.
    (자정+10분 유예는 마감시각 자체에 이미 반영되어 있다고 가정 — 이 커맨드는
    다음 주 실행 시점, 즉 유예시간이 이미 지난 뒤에 호출된다.)

    안전장치: current_week가 아직 '이번 주'(오늘과 같은 ISO 주차)이면 절대
    마감 처리하지 않는다 — 주중에 실수로(또는 자동화 세션이 판단을 잘못해서)
    호출되어도 아직 청소 안 한 사람들이 부당하게 '미제출' 처리되는 사고를 막는다.
    """
    state = load_json(state_path)
    history = load_json(history_path) if history_path.exists() else {}

    cw = state.get("current_week")
    if not cw:
        print("마감 처리할 이전 주 데이터가 없습니다.")
        return
    if cw.get("closed"):
        print(f"{cw['iso_week']}는 이미 마감 처리되었습니다.")
        return

    today_iso_week = f"{today.isocalendar()[0]}-W{today.isocalendar()[1]:02d}"
    if cw["iso_week"] == today_iso_week:
        print(
            f"{cw['iso_week']}는 아직 진행 중인 이번 주입니다 — 마감 처리를 "
            f"거부합니다 (다음 주가 시작된 뒤에만 지난주를 마감할 수 있습니다)."
        )
        return

    deposit = state.setdefault("deposit", {
        "ledger": {r: 0 for r in state["residents"]},
        "shared_pool": 0,
        "threshold": 100,
        "pending_events": [],
    })
    charge_events = []

    for person, status in cw["status"].items():
        if status == "확인대기":
            cw["status"][person] = "미제출"
            state["penalty_counters"][person] = state["penalty_counters"].get(person, 0) + 1
            streak = state["penalty_counters"][person]
            if streak >= 2:
                deposit["ledger"][person] = deposit["ledger"].get(person, 0) + 10
                deposit["shared_pool"] += 10
                charge_events.append(
                    f"💰 {person}님 연속 {streak}회 미제출로 디파짓 $10 차감 "
                    f"(개인 누적 차감 ${deposit['ledger'][person]})"
                )
        elif status == "완료":
            state["penalty_counters"][person] = 0

    if deposit["shared_pool"] >= deposit["threshold"]:
        deposit["shared_pool"] -= deposit["threshold"]
        charge_events.append(
            f"🎉 공동 풀이 ${deposit['threshold']}에 도달했습니다! 회식비로 사용해 주세요. "
            f"(남은 풀: ${deposit['shared_pool']})"
        )

    deposit["pending_events"] = charge_events
    state["deposit"] = deposit

    cw["closed"] = True
    history[cw["iso_week"]] = {
        "assignment": cw["assignment"],
        "status": cw["status"],
        "closed": True,
    }
    state["current_week"] = cw

    save_json(state_path, state)
    save_json(history_path, history)

    print(f"{cw['iso_week']} 마감 처리 완료:")
    for person, status in cw["status"].items():
        print(f"  - {person}: {status} (연속 미제출 {state['penalty_counters'].get(person, 0)}회)")
    for e in charge_events:
        print(f"  {e}")


def complete(state_path: Path, history_path: Path, name: str):
    state = load_json(state_path)
    history = load_json(history_path) if history_path.exists() else {}

    cw = state.get("current_week")
    if not cw:
        print("이번 주 당번표가 아직 생성되지 않았습니다. rotation-generator를 먼저 실행하세요.")
        return

    if name not in state["residents"]:
        print(f"오류: '{name}'은(는) 등록된 거주자 이름과 정확히 일치하지 않습니다. "
              f"({', '.join(state['residents'])}) 정확한 이름으로 다시 입력해 주세요.")
        return

    if name not in cw["status"]:
        print(f"오류: '{name}'님은 이번 주({cw['iso_week']}) 당번 명단에 없습니다.")
        return

    cw["status"][name] = "완료"
    state["penalty_counters"][name] = 0
    state["current_week"] = cw

    if cw["iso_week"] in history:
        history[cw["iso_week"]]["status"][name] = "완료"

    save_json(state_path, state)
    save_json(history_path, history)
    print(f"{name}님 완료 처리되었습니다. ({cw['iso_week']})")


def deposit_status(state_path: Path):
    state = load_json(state_path)
    deposit = state.get("deposit", {})
    ledger = deposit.get("ledger", {})
    print(f"공동 풀: ${deposit.get('shared_pool', 0)} / ${deposit.get('threshold', 100)}")
    for name, amount in ledger.items():
        print(f"  - {name}: 누적 차감 ${amount}")


def summary(history_path: Path, weeks: int):
    history = load_json(history_path) if history_path.exists() else {}
    weeks_sorted = sorted(history.keys())[-weeks:]
    if not weeks_sorted:
        print("이력이 없습니다.")
        return
    for wk in weeks_sorted:
        entry = history[wk]
        if entry.get("summary"):
            print(f"{wk}: [요약만 보관] 미제출 {entry.get('miss_count', 0)}회 / 완료 {entry.get('complete_count', 0)}회")
            continue
        line = ", ".join(f"{p}:{s}" for p, s in entry.get("status", {}).items())
        print(f"{wk}: {line}")


def trim(history_path: Path, months: int, today: date):
    """오래된 이력(months개월 이전)을 상세 삭제하고 요약만 남긴다."""
    history = load_json(history_path) if history_path.exists() else {}
    cutoff = today - timedelta(days=months * 30)

    for wk, entry in list(history.items()):
        if entry.get("summary"):
            continue
        try:
            year, week = wk.split("-W")
            wk_monday = date.fromisocalendar(int(year), int(week), 1)
        except ValueError:
            continue
        if wk_monday < cutoff:
            status = entry.get("status", {})
            history[wk] = {
                "summary": True,
                "miss_count": sum(1 for s in status.values() if s == "미제출"),
                "complete_count": sum(1 for s in status.values() if s == "완료"),
            }

    save_json(history_path, history)
    print(f"{cutoff.isoformat()} 이전 이력을 요약본으로 정리했습니다.")


def main():
    parser = argparse.ArgumentParser(description="checklist-tracker")
    parser.add_argument("--state", type=Path, default=DEFAULT_STATE)
    parser.add_argument("--history", type=Path, default=DEFAULT_HISTORY)
    parser.add_argument("--date", type=str, default=None, help="YYYY-MM-DD (기본값: 오늘)")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("close-week", help="지난주 체크리스트 마감 처리")

    comp = sub.add_parser("complete", help="특정 인원 완료 처리 (이름 정확 일치)")
    comp.add_argument("name")

    summ = sub.add_parser("summary", help="최근 이력 요약 출력")
    summ.add_argument("--weeks", type=int, default=8)

    tr = sub.add_parser("trim", help="오래된 이력 요약화 (기본 3개월)")
    tr.add_argument("--months", type=int, default=3)

    sub.add_parser("deposit-status", help="디파짓 차감 장부 및 공동 풀 현황 조회")

    args = parser.parse_args()
    run_date = datetime.strptime(args.date, "%Y-%m-%d").date() if args.date else date.today()

    if args.command == "close-week":
        close_week(args.state, args.history, run_date)
    elif args.command == "complete":
        complete(args.state, args.history, args.name)
    elif args.command == "summary":
        summary(args.history, args.weeks)
    elif args.command == "trim":
        trim(args.history, args.months, run_date)
    elif args.command == "deposit-status":
        deposit_status(args.state)


if __name__ == "__main__":
    main()
