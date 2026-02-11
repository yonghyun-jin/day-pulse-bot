## 0) MVP 기능 범위 (고정)

1. **Telegram** : 아침에 “기분/걱정/오늘 1개 Must-do” 질문 → 응답 받기
2. **GitHub** : 응답을 `/daily/YYYY-MM-DD.md`에 append(또는 생성)
3. **Google Calendar** : 오늘 이벤트 목록 조회 + “대략 spare time” 계산해 텔레그램으로 요약 ([events.list](https://developers.google.com/workspace/calendar/api/v3/reference/events/list?utm_source=chatgpt.com))
4. **Google Calendar** : 사용자가 텔레그램에 “3pm 2h Lombard” 같은 계획을 보내면 → 승인 후 캘린더 이벤트 생성 ([events.insert](https://developers.google.com/workspace/calendar/api/v3/reference/events/insert?utm_source=chatgpt.com))
5. **9PM** : 텔레그램 “오늘 어땠어?” 한 질문 → 답을 같은 md에 append

---

# 1) 개발 스펙 (공통)

## 1.1 데이터/파일 스키마

* 저장 경로: `/daily/YYYY-MM-DD.md`
* 포맷(최소):

<pre class="overflow-visible! px-0!" data-start="856" data-end="1024"><div class="contain-inline-size rounded-2xl corner-superellipse/1.1 relative bg-token-sidebar-surface-primary"><div class="sticky top-[calc(var(--sticky-padding-top)+9*var(--spacing))]"><div class="absolute end-0 bottom-0 flex h-9 items-center pe-2"><div class="bg-token-bg-elevated-secondary text-token-text-secondary flex items-center gap-4 rounded-sm px-2 font-sans text-xs"></div></div></div><div class="overflow-y-auto p-4" dir="ltr"><code class="whitespace-pre! language-md"><span><span># YYYY-MM-DD</span><span>

</span><span>## Morning</span><span>
</span><span>-</span><span> Mood: __/10
- Worry: "..."
- Must-do: "..."

## Plan (optional)
- Planned Blocks:
  - ...

## 21:00 Check-in
- How was today: "..."
</span></span></code></div></div></pre>

## 1.2 Telegram 업데이트 수신 방식

* **옵션 A: getUpdates(폴링)** — 서버 없어도 가능, 단 “항상 돌아가는 프로세스” 필요
* **옵션 B: webhook(푸시)** — HTTPS 엔드포인트 필요 (Telegram이 POST로 쏴줌)

## 1.3 GitHub 기록 방식

* GitHub repo에 파일 생성/업데이트: `PUT /repos/{owner}/{repo}/contents/{path}` (“Create or update file contents”)

## 1.4 Google Calendar 연동 방식

* 오늘 일정 조회: `events.list`
* 계획 블록 생성: `events.insert` (start/end 필수)

## 1.5 보안 요구사항 (최소)

* Telegram bot token, GitHub token, Google OAuth 토큰은 **절대 md에 기록 금지**
* 캘린더 “쓰기(insert)”는 **사용자 승인(Yes) 후에만 실행**

---

# 2) 구현 옵션 (최대한 무료 우선)

## 옵션 1) **Google Apps Script 단독 (가성비/무료 끝판왕)**

**구성**

* Google Apps Script(GAS) 웹앱: Telegram webhook 받기 + 로직 실행
* GAS의 Calendar 서비스로 캘린더 읽기/쓰기 (CalendarApp)
* 시간 기반 트리거로 “매일 아침/밤 9시” 메시지 발송
* GitHub는 REST API로 md 파일 PUT

**장점**

* 서버 운영 0원, 배포/HTTPS 자동
* 스케줄 트리거가 “진짜 쉬움”
* Google Calendar는 GAS에서 네 계정 권한으로 자연스럽게 접근

**단점**

* 코드/디버깅 경험이 웹서버보다 불편할 수 있음

➡️  **“하루 안에 만들기” 목표면 1순위** .

---

## 옵션 2) **Cloudflare Workers (무료 플랜) + Cron Triggers**

**구성**

* Workers가 Telegram webhook 엔드포인트 역할
* Workers Cron으로 매일 아침/9PM 실행
* Google Calendar API(OAuth) + GitHub API 호출
* Cloudflare Workers Free는 일일 요청/CPU 제한이 있으나 소규모 봇은 보통 충분

**장점**

* 무료 플랜으로 운영 가능, 성능 좋음
* 서버리스라 관리 부담 적음

**단점**

* Google OAuth 세팅이 GAS보다 번거로울 수 있음(특히 토큰 갱신)

---

## 옵션 3) **n8n Community Edition Self-host (무료)**

**구성**

* n8n(자체 호스팅)에서:
  * Telegram 트리거
  * Google Calendar 노드
  * GitHub(HTTP Request 노드로 contents API)
  * 스케줄 트리거(아침/9PM)
* n8n Cloud는 유료 플랜 위주라 “최대한 무료”면 self-host가 핵심

**장점**

* 너 이미 n8n 관심/경험 있음 → 만들기 빠름
* UI로 흐름 확인 쉬움

**단점**

* “어딘가에” n8n을 띄워야 함(집 PC/서버/무료 호스팅 등)

---

## 옵션 4) **Pipedream (무료 티어)**

**구성**

* Telegram webhook → workflow 실행
* 스케줄 workflow(아침/9PM)
* GitHub/Google Calendar API 호출
* Free tier 존재

**장점**

* 서버리스 + 개발자 친화
* 빠르게 “작동”시키기 좋음

**단점**

* 무료 티어 한도 존재(장기 운영 시 제한될 수 있음)

---

# 3) Todoist는?

너가 “투두 앱에도 만들까?” 했잖아.

* Todoist는 **공식 REST API v2**가 있고, 개인 API 토큰으로 task 생성 가능.
* “무료로?” → API 자체는 사용할 수 있고, 플랜에 따라 일부 기능 제한 가능성은 있음(하지만 태스크 생성 같은 기본은 보통 가능).

 **초미니 MVP에서는 Todoist는 빼는 걸 추천** (하루안에 성공 확률 올리기). 캘린더에 timeblock만 들어가도 충분히 “오늘 뭐해야 하지” 문제가 해결돼.

---

# 4) 내 추천 (너 기준, “최대한 무료 + 하루 완성”)

1. **옵션 1: Google Apps Script** (가장 빠르고 공짜로 끝까지 감)
2. 그다음 확장: Workers 또는 n8n self-host

---

원하면, 다음 메시지에서 **옵션 1(GAS)** 기준으로:

* 필요한 환경 변수(토큰) 목록
* Telegram 명령어/상태 머신(아침 질문 → 저장 → 오늘 일정 → 계획 입력 → 승인)
* GitHub md 업데이트 로직(“파일 있으면 append, 없으면 생성”)

까지 “구현 직전” 수준으로 아주 짧게 정리해줄게.
