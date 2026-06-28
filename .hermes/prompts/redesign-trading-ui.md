## Context
Dự án Trade_V1 tại C:\Users\minhl\Desktop\STARUP\Trade_V1
Đã cài taste-skill + minimalist-skill từ https://github.com/Leonxlnx/taste-skill

## Nhiệm vụ
Redesign Vibe-Trading trader dashboard tại http://localhost:8000/trader
Cho nó **ra dáng 1 trading platform thực thụ** — như Bloomberg Terminal, TradingView, hoặc 3Commas.

## Design Direction

### Tổng thể — "Pro Trading Terminal"
- **Dark theme** hoàn toàn (nền #0D1117 hoặc tương tự)
- **Dense information** — trader cần thấy nhiều số liệu cùng lúc, ko spacing phí phạm
- **Color code**: xanh lá cho long/up, đỏ cho short/down, vàng cho warning
- **Monospace font** cho số (JetBrains Mono hoặc Inter)
- **Minimal UI decoration** — ko gradient, ko shadow ko cần thiết

### Layout cụ thể

```
┌─────────────────────────────────────────────────────┐
│  HEADER: Logo | Market Ticker (chạy ngang)          │
├──────────┬──────────────────────────────────────────┤
│ SIDEBAR  │  MAIN CONTENT                            │
│          │                                          │
│ PnL card │  ┌──────────┐ ┌──────────┐ ┌─────────┐  │
│ Capital  │  │ POSITION │ │ POSITION │ │   ...   │  │
│ Winrate  │  │ 1 ETH    │ │ 2 BTC    │ │         │  │
│ Open     │  │ LONG     │ │ LONG     │ │         │  │
│          │  │ +$3.04   │ │ +$3.80   │ │         │  │
│          │  │ R:R 1:2  │ │ R:R 1:1  │ │         │  │
│          │  └──────────┘ └──────────┘ └─────────┘  │
│ SYSTEM   │                                          │
│ Kill sw  │  ┌────────────────────────────────────┐  │
│ Symbols  │  │ RECENT TRADES TABLE                │  │
│ Model    │  │ Time | Symbol | Side | PnL | Exit  │  │
│          │  │ ...                                │  │
│          │  └────────────────────────────────────┘  │
│          │                                          │
│          │  ┌────────────────────────────────────┐  │
│          │  │ LLM DECISIONS LOG                  │  │
│          │  │ Time | Action | Reason             │  │
│          │  └────────────────────────────────────┘  │
└──────────┴──────────────────────────────────────────┘
```

### Chi tiết từng component

**Market Ticker (header bar)**
- Chạy ngang: BTC $64,353 ▲0.2% | ETH $1,732 ▼0.18% | SOL $72.68 ▼2.36%
- Mỗi symbol có: giá hiện tại, change % (màu xanh/đỏ), 24h high/low nhỏ
- Font monospace, size nhỏ, auto-update

**Sidebar cards**
- PnL: số lớn nhất, màu xanh/đỏ theo PnL
- Capital: số nhỏ hơn, phụ
- Winrate: progress bar hoặc pie chart mini (xanh/đỏ tỉ lệ)
- System status: kill switch (armed/disarmed) với badge màu
- Model name: deepseek-v4-flash

**Position cards**
- Dạng card, ko phải table row — mỗi position 1 card riêng
- Header: symbol + side badge (LONG xanh lá, SHORT đỏ)
- Entry price, mark price, PnL (số lớn + %), SL/TP levels
- R:R ratio, Confluence score
- Progress bar cho distance to SL/TP
- Nút close (×) ở góc

**Recent trades table**
- Columns: Time | Symbol | Side (badge) | Entry | Exit | Size | PnL | Reason | Conf.
- PnL âm = đỏ, dương = xanh
- Side: BUY xanh, SELL đỏ
- Sort by time mới nhất

**LLM log**
- Scrollable, compact
- Time | Action (long/short/hold) | Confidence badge | Reasoning (1 dòng truncate)

### Trading-specific UI elements
- **Confluence score** hiển thị dạng badge: +5/8 với màu theo mức (xanh > 5, vàng 3-5, đỏ < 3)
- **R:R ratio** hiển thị luôn: "1:2.07" — nếu > 1:2 thì highlight xanh
- **Kill switch** toggle có confirmation dialog
- **Auto-refresh** indicator: chấm xanh nhấp nháy khi đang update

### Motion & Micro-interactions
- **Số PnL thay đổi**: flash animation (xanh lá khi tăng, đỏ khi giảm) trong 500ms
- **Card hover**: nhẹ, border sáng lên, ko scale
- **Price ticker**: chạy ngang mượt, ko giật
- **Toast notification** khi có trade mới (góc dưới phải)
- **Loading skeleton** khi fetch data — ko để màn hình trắng

### Typography & Spacing
- Font: Inter cho text, JetBrains Mono cho numbers
- Size: số PnL 24px bold, giá symbol 14px, phụ 11px
- Spacing: dense — 4px/8px/12px grid, ko 16px+ phí phạm

## Kỹ thuật
- Chỉ sửa frontend HTML/CSS/JS — ko động vào backend API
- Giữ nguyên API endpoints
- Dùng CSS variables cho theme colors
- Responsive tối thiểu: 1280px+ là chính
- Ko thêm framework nặng — vanilla CSS/JS hoặc lightweight

## Output
- File HTML/CSS/JS hoàn chỉnh
- Ko placeholder, ko "// TODO"
