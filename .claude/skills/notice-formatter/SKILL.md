---
name: notice-formatter
description: 이번 주 당번표를 카카오톡 공지문으로 만든다. rotation-generator 실행 직후, 그리고 운영자가 "공지 완료"라고 입력했을 때 사용한다.
---

# notice-formatter

`rotation-generator`가 계산한 이번 주 당번표를 카카오톡에 바로 붙여넣을 수 있는
공지문으로 변환한다. 지난주 마감 처리에서 디파짓 차감이 발생했으면 그 안내를
자동으로 포함한다.

## 언제 사용하는가
- `rotation-generator`의 `run` 실행 직후 (공지문 생성)
- 운영자가 "공지 완료"라고 입력했을 때 (발송완료 확인)

## 사용법

```bash
# 공지문 생성 (rotation-generator 실행 직후)
python3 scripts/format_notice.py generate

# 운영자가 카톡에 붙여넣고 "공지 완료"라고 말했을 때
python3 scripts/format_notice.py confirm
```

`generate`는 `output/weekly_notice_YYYYMMDD.md` 파일을 만들고 화면에도 그대로
출력한다 — 운영자가 그 텍스트를 그대로 복사해 카카오톡에 붙여넣으면 된다.

## 발송완료 확인 반복 정책

운영자가 지난주 "공지 완료" 확인을 입력하지 않은 채 다음 주가 되면, `generate`
실행 시 화면(stderr)에 "지난주 발송 미확인" 안내가 뜬다. 이 안내는 **최대 3회까지만**
반복되고, 4회째부터는 안내를 멈추고 자동으로 `발송완료`로 간주한다 (무한 반복 방지 —
강제 차단이 아니라 그냥 더 이상 캐묻지 않는 것).

이 미확인 안내는 카카오톡에 올라가는 공지문 본문에는 절대 포함하지 않는다 —
운영자에게만 보이는 콘솔 메시지다.

## 공지문에 절대 포함하지 않는 것

- 규칙 자체에 대한 긴 설명(왜 이 규칙이 생겼는지 등)은 최초 1회 공지로 이미
  안내되었다고 보고, 매주 반복하지 않는다 (`state["rule_notice_shown"]`가 True가
  되면 다시 나가지 않음). 매주는 "미제출 시 2회차부터 디파짓 차감" 같은 짧은
  사실 고지만 반복한다.
- 디파짓 차감 블록은 실제로 차감이 발생한 주에만 자동 삽입되고, 그 외 주에는
  아예 표시되지 않는다 (`state["deposit"]["pending_events"]`가 비어있으면 생략).

## 디파짓 안내 블록

`checklist-tracker close-week`가 차감을 기록하면 `state["deposit"]["pending_events"]`에
쌓인다. `generate`는 이걸 "💰 디파짓 안내" 블록으로 한 번 포함시키고 나면
바로 비운다 — 같은 내역이 다음 주에 또 나오지 않는다.
