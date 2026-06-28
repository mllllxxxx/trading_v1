## Context
Dự án Trade_V1 tại C:\Users\minhl\Desktop\STARUP\Trade_V1
Dashboard hiện tại: http://localhost:8000/trader

## Skills đã cài
Đọc các skill sau trước khi làm:
1. .claude/skills/design-taste-frontend/SKILL.md — anti-slop UI rules
2. .claude/skills/minimalist-ui/SKILL.md — phong cách tối giản
3. .claude/skills/redesign-skill/SKILL.md — audit + redesign workflow

## Nhiệm vụ
Redesign toàn bộ Vibe-Trading dashboard từ multi-page thành **1 màn hình terminal quản lý duy nhất** — trader thấy tất cả data quan trọng mà ko cần click qua lại.

## Design Concept — "Trading Command Center"

Tưởng tượng Bloomberg Terminal gặp Notion — professional trading data trình bày sạch sẽ, tối giản.

### Layout Architecture

```
┌──────────────────────────────────────────────────────────────────────┐
│  TOP BAR: Live indicator + Market Ticker + Global Stats            │
├────────────┬─────────────────────────────────────┬──────────────────┤
│  LEFT      │  CENTER                              │  RIGHT           │
│  PANEL     │  MAIN CONTENT                        │  SIDE PANEL      │
│            │                                       │                  │
│  📊 STATS  │  📈 OPEN POSITIONS (card grid)        │  🤖 BRAIN LOG   │
│  COLLECTION│                                       │                  │
│            │  Collapsible:                         │  Real-time LLM   │
│  PnL/Cap   │  [positions] [history] [alerts]       │  decisions       │
│  Winrate   │                                       │  scrollable      │
│  Kill sw   │  Active tab hiển thị ở center         │                  │
│  Model     │                                       │  Collapsible:    │
│            │                                       │  [alpha zoo]     │
│  Collapse: │                                       │  [pending feats] │
│  [settings]│                                       │                  │
│            │                                       │                  │
├────────────┴─────────────────────────────────────┴──────────────────┤
│  BOTTOM BAR: mini trade history + quick actions + status            │
└──────────────────────────────────────────────────────────────────────┘
```

### Mỗi section làm gì

**TOP BAR (luôn hiện)**
- Trái: logo + live indicator (chấm xanh nhấp nháy khi refresh)
- Giữa: market ticker — BTC, ETH, SOL, BNB giá realtime chạy ngang
- Phải: capital $10k | PnL hôm nay | kill switch badge (xanh/đỏ)

**LEFT PANEL (fixed width ~220px)**
- PnL card: số lớn, màu theo âm/dương
- Capital + change since start
- Winrate: số + progress bar ngang
- Open: X / max Y — warning nếu gần đầy
- System status: model name, symbols tracked, last update
- Kill switch toggle + confirmation dialog
- [Settings] collapse — ẩn các config ko cần thường xuyên

**CENTER (co giãn, main area)**
- Tab bar: Positions | History | Alerts
- **Positions tab (mặc định):** card grid, mỗi card 1 position
  - Header: symbol + side badge (LONG xanh, SHORT đỏ)
  - Entry, Mark, PnL (số lớn + %), SL/TP
  - R:R progress bar (đầy dần đến TP)
  - Confluence badge (màu theo mức)
  - Close button ×
  - Nếu ko có positions → empty state: "No open positions. LLM đang scan..."
- **History tab:** table — Time | Symbol | Side | Entry | Exit | PnL | Reason | Conf.
  - Sort mới nhất, pagination 20 rows
- **Alerts tab:** notification log — system events, kill switch, errors

**RIGHT PANEL (~300px, collapsible)**
- **Brain Log (default):** scrollable list
  - Mỗi dòng: timestamp + action badge (LONG/SHORT/HOLD) + confidence + reasoning truncate
  - Màu theo action: LONG xanh, SHORT đỏ, HOLD xám
- **Alpha Zoo (collapse):** top factors, IC score
- **Feature Pipeline (collapse):** P1, P2, P3 pending features

**BOTTOM BAR (luôn hiện)**
- Mini trade history: 3 trade gần nhất dạng compact
- Quick actions: [Manual Trade] [Backtest] [Alpha Bench] [Journal]
- Status text: "Last scan: 30s ago | Next: 4m30s"

### Color System (CSS Variables)
```css
:root {
  --bg-primary: #0D1117;      /* nền chính */
  --bg-secondary: #161B22;    /* card/section nền */
  --bg-tertiary: #21262D;     /* hover, input */
  --border: #30363D;          /* border mờ */
  --text-primary: #E6EDF3;    /* chữ chính */
  --text-secondary: #8B949E;  /* chữ phụ */
  --text-muted: #484F58;      /* chữ mờ nhất */
  --green: #3FB950;           /* long / up / profit */
  --red: #F85149;             /* short / down / loss */
  --yellow: #D29922;          /* warning */
  --blue: #58A6FF;            /* info / link */
  --accent: #7C5CFC;          /* điểm nhấn tím */
}
```

### Typography
- Numbers: JetBrains Mono ('JetBrains Mono', 'Cascadia Code', monospace)
- Text: Inter (-apple-system, 'Inter', sans-serif)
- Scale: 24px bold (PnL), 14px (body), 12px (phụ), 11px (label)

### Interaction & Animation
- PnL thay đổi → flash animation 500ms theo màu (xanh nếu tăng, đỏ nếu giảm)
- Card hover → border sáng + glow nhẹ, ko scale
- Tab chuyển → fade transition 200ms
- Brain log new entry → slide in từ dưới
- Toast notification cho trade mới (góc dưới phải, auto dismiss 5s)
- Skeleton loading cho lần fetch đầu — ko màn hình trắng

### Density
- Trading terminal = dense. 4px/8px/12px grid
- Card padding: 12px. Table cell: 6px 8px
- Bottom bar: 32px cao
- Ko có whitespace phí phạm — mỗi pixel đều có data

### Data Flow
- Giữ nguyên API backend endpoints
- Frontend auto-poll API mỗi 5s (hoặc WebSocket nếu có sẵn)
- Ko cần chạy real WebSocket mới — polling từ endpoint hiện tại là đủ

## Output
- File HTML/CSS/JS hoàn chỉnh
- Dùng vanilla JS hoặc lightweight (ko React/Vue nặng)
- Ko placeholder code — mọi thứ chạy được ngay
- CSS variables ở đầu file
- Comment rõ section nào là gì

## Taste-Skill Settings
- DESIGN_VARIANCE: 6 (cấu trúc rõ ràng, ko quá phá cách)
- MOTION_INTENSITY: 4 (trading cần tĩnh, animation chỉ điểm nhấn)
- VISUAL_DENSITY: 8 (trader cần nhiều data)
