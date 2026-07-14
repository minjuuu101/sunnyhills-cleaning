#!/usr/bin/env python3
"""
notice-formatter: rotation-generator의 결과를 카카오톡 공지문으로 변환한다.

사용법:
  python3 format_notice.py generate [--date YYYY-MM-DD] [--state PATH] [--output-dir PATH]
  python3 format_notice.py confirm [--state PATH]

설계서 3장 '주간 공지문 템플릿' 참조. 지난주 마감 처리(checklist-tracker close-week)에서
디파짓 차감이 발생했으면 그 내역이 이번 공지에 자동으로 한 번 포함된다.
'공지 완료' 확인이 없으면 다음 generate 호출 시 최대 3회까지 미확인 안내가 누적되고
4회째부터는 자동으로 '발송완료'로 간주한다.
"""
import argparse
import sys
from datetime import date, datetime
from pathlib import Path
import json

ROOT = Path(__file__).resolve().parents[4]
DEFAULT_STATE = ROOT / "output" / "state.json"
DEFAULT_OUTPUT_DIR = ROOT / "output"

ZONE_EMOJI = {
    "화장실": "🚿",
    "주방": "🍳",
    "공용공간": "🛋️",
    "분리수거": "♻️",
}

# 공지문에 표시되는 순서(고정). rotation-generator가 순환 계산에 쓰는
# state["zones"] 순서와는 별개다 — 순환 방향이 바뀌어도 공지문 표시 순서는
# 항상 이 순서를 따른다.
DISPLAY_ORDER = ["화장실", "주방", "공용공간", "분리수거"]

# 페널티 규칙을 처음으로 실제 적용하는 시점에 딱 한 번만 내보내는 안내문.
# (state["rule_notice_shown"]가 True가 되면 이후로는 다시 나가지 않는다.)
RULE_INTRO_TEXT = """안녕하세요 🙂

최근 몇 주간 청소 인증사진이 잘 안 올라오고 있어서, 이번 주부터 규칙을 다시 한번 명확히 정리하려고 해요.

📌 청소 당일 자정까지 인증사진 미제출 시
→ 다음 주 담당 구역에 '공용공간(가장 손 많이 가는 곳)' 추가

지금까지는 말만 하고 실제로 적용을 안 했는데, 이번 주부터는 예외 없이 적용할게요. 다 같이 사는 공간이라 한 명이라도 계속 빠지면 결국 누군가 두 배로 하게 되더라고요. 서로 피곤해지지 않게 이번 기회에 확실히 자리 잡았으면 합니다."""


def load_json(path: Path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def save_json(path: Path, data):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def build_notice_text(state, cw) -> str:
    lines = []
    if not state.get("rule_notice_shown"):
        lines += [RULE_INTRO_TEXT, "", "─────────────", ""]

    lines += [f"📋 이번 주 청소 당번 ({cw['week_range']})", ""]
    zone_details = state.get("zone_details", {})
    for zone in DISPLAY_ORDER:
        emoji = ZONE_EMOJI.get(zone, "•")
        person = cw["assignment"].get(zone)
        lines.append(f"{emoji} {zone}: {person if person else '(공석 — 운영자 확인 필요)'}")
        detail = zone_details.get(zone)
        if detail:
            lines.append(f"    └ {detail}")

    lines += [
        "",
        "📌 마감: 청소 당일 자정까지 인증사진 제출",
        "📌 미제출 시 디파짓에서 차감됩니다 (1회차는 넘어가고, 2회차부터 매회 $10)",
    ]

    deposit_events = state.get("deposit", {}).get("pending_events") or []
    if deposit_events:
        lines += ["", "💰 디파짓 안내"]
        lines += [f"- {e}" for e in deposit_events]

    if cw.get("notes"):
        lines += ["", "📎 참고사항"]
        lines += [f"- {n}" for n in cw["notes"]]

    return "\n".join(lines) + "\n"


def generate(state_path: Path, output_dir: Path, run_date: date):
    state = load_json(state_path)
    cw = state.get("current_week")
    if not cw:
        print("이번 주 당번표가 없습니다. rotation-generator를 먼저 실행하세요.", file=sys.stderr)
        sys.exit(1)

    notice = state.get("notice") or {}
    pending_msg = None
    streak = notice.get("unconfirmed_reminder_count", 0)
    is_same_week_regenerate = notice.get("iso_week") == cw["iso_week"]

    if notice.get("status") == "생성됨" and not is_same_week_regenerate:
        streak += 1
        if streak >= 4:
            pending_msg = (
                f"[운영자 안내] 지난주 공지 '발송완료' 확인이 {streak - 1}회 반복 누락되어 "
                f"자동으로 발송완료 처리합니다."
            )
            streak = 0
        else:
            pending_msg = (
                f"[운영자 안내] 지난주 공지 '발송완료' 확인이 아직 안 되었습니다. "
                f"카톡에 올리셨다면 '공지 완료'라고 입력해 주세요. ({streak}/3)"
            )
    elif is_same_week_regenerate:
        streak = notice.get("unconfirmed_reminder_count", 0)

    rule_notice_included = not state.get("rule_notice_shown")
    text = build_notice_text(state, cw)
    output_dir.mkdir(parents=True, exist_ok=True)
    fname = f"weekly_notice_{run_date.strftime('%Y%m%d')}.md"
    (output_dir / fname).write_text(text, encoding="utf-8")

    if rule_notice_included:
        state["rule_notice_shown"] = True

    if state.get("deposit", {}).get("pending_events"):
        state["deposit"]["pending_events"] = []  # 이번 공지에 실었으니 소비

    state["notice"] = {
        "status": "생성됨",
        "iso_week": cw["iso_week"],
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "confirmed_at": None,
        "unconfirmed_reminder_count": streak,
    }
    save_json(state_path, state)

    if pending_msg:
        print(pending_msg, file=sys.stderr)
        print("", file=sys.stderr)
    print(f"공지문이 생성되었습니다: {output_dir / fname}", file=sys.stderr)
    print(text)


def confirm(state_path: Path):
    state = load_json(state_path)
    notice = state.get("notice")
    if not notice or notice.get("status") != "생성됨":
        print("확인할 미발송 공지가 없습니다.")
        return
    notice["status"] = "발송완료"
    notice["confirmed_at"] = datetime.now().isoformat(timespec="seconds")
    notice["unconfirmed_reminder_count"] = 0
    state["notice"] = notice
    save_json(state_path, state)
    print("공지 상태를 '발송완료'로 기록했습니다.")


def main():
    parser = argparse.ArgumentParser(description="notice-formatter")
    parser.add_argument("--state", type=Path, default=DEFAULT_STATE)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--date", type=str, default=None, help="YYYY-MM-DD (기본값: 오늘)")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("generate", help="이번 주 공지문 생성")
    sub.add_parser("confirm", help="'공지 완료' 확인 입력 처리")

    args = parser.parse_args()
    run_date = datetime.strptime(args.date, "%Y-%m-%d").date() if args.date else date.today()

    if args.command == "generate":
        generate(args.state, args.output_dir, run_date)
    elif args.command == "confirm":
        confirm(args.state)


if __name__ == "__main__":
    main()
