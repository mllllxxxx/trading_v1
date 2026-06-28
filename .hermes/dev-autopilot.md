---
name: dev-autopilot
description: "Autonomous development loop for Trade_V1 — scans codebase, identifies feature gaps, designs, delegates to Minimax M3 (OpenCode) for implementation, tests, and iterates."
version: 1.0.0
---

# Dev Autopilot — Self-Improving Development Loop

## 🎯 Mục Đích

Hệ thống tự động loop phát triển tính năng mới cho Trade_V1 — Minimax M3 làm code, Hermes cron làm orchestrator.

```
Hermes cron (mỗi 30 phút)   ──►   Kiểm tra feature pipeline
                                      │
                              File-based state (.hermes/features/)
                                      │
                                      ▼
                              Minimax M3 (OpenCode CLI)
                                      │
                                      ▼
                              Code changes + pytest
```

---

## 📁 Feature Pipeline

```
.hermes/features/
├── pending.md          # Features chờ (sorted by priority)
├── in_progress.md      # Feature đang làm (1 cái duy nhất)
├── done.md             # Feature đã hoàn thành
└── {feature-name}/
    ├── brief.md        # M3 input — ngắn gọn, đủ context
    ├── design.md       # Design doc (M3 viết)
    ├── status          # designing | implementing | testing | done | blocked
    ├── READY_TO_DESIGN      # Flag: cần M3 design
    ├── READY_TO_IMPLEMENT   # Flag: cần M3 implement
    └── APPROVED             # Flag: user đã approve design
```

### pending.md format
```markdown
## [P1] Tên feature
- **Phát hiện:** ngày
- **Lý do:** ...
- **Files ảnh hưởng:** ...
- **Mô tả:** ...
```

Priority: P1=urgent, P2=important, P3=nice-to-have

---

## 🔄 Workflow (từng bước cụ thể)

### Bước 1: Worker cron pick feature

Hermes chạy mỗi 30 phút:
```
in_progress rỗng → lấy P1 cao nhất từ pending.md
                 → tạo thư mục .hermes/features/{name}/
                 → viết brief.md
                 → ghi flag READY_TO_DESIGN
                 → notification
```

### Bước 2: Fen chạy M3 design

Khi thấy flag `READY_TO_DESIGN`:

```bash
opencode --model minimax-m3 --prompt "
Đọc docs/ARCHITECTURE_V2.md
Đọc .hermes/features/{name}/brief.md

Nhiệm vụ: Design feature '{name}'
Output: .hermes/features/{name}/design.md

Format design.md:
## Mục tiêu
...
## Files ảnh hưởng
| File | Thay đổi |
## Data Flow
...
## Implementation Steps
1. ...
## Test Plan
- ...
"
```

### Bước 3: Fen approve

```bash
echo "APPROVED" > .hermes/features/{name}/APPROVED
```

Worker cron chạy tiếp → thấy APPROVED → chuyển `implementing` → ghi `READY_TO_IMPLEMENT`

### Bước 4: Fen chạy M3 implement

```bash
opencode --model minimax-m3 --prompt "
Đọc .hermes/features/{name}/design.md

Nhiệm vụ: Implement feature theo design doc
Rules:
- Test before commit: chạy pytest -x sau mỗi thay đổi
- 1 feature = 1 branch: dev-autopilot/{name}
- Ko sửa file ko liên quan
- Backward compatible JSON format
"
```

### Bước 5: Worker cron test + commit

```
Worker chạy → pytest -x
  PASS → git add + commit + push
       → append vào done.md
       → xóa in_progress
       → pick feature tiếp theo!
  FAIL → ghi log lỗi
       → nếu retry < 3: quay lại step 4
       → nếu retry >= 3: status = blocked + notification
```

---

## 📋 brief.md Template (Hermes tự viết)

```markdown
# Feature: {name}
Priority: P1
Target branch: dev-autopilot/{name}

## Context
{2-3 câu, link tới ARCHITECTURE_V2.md}

## Yêu cầu
- {req 1}
- {req 2}

## Files chính
- {file 1}
- {file 2}

## Done khi
- [ ] Code changes done
- [ ] pytest pass
- [ ] Ko break existing JSON format
```

---

## ⚙️ Cron Jobs

```bash
# Scanner — phát hiện feature gaps mới
hermes cron create "every 12h" \
  --name dev-autopilot-scanner \
  --skills dev-autopilot,trading-rules \
  --workdir /c/Users/minhl/Desktop/STARUP/Trade_V1 \
  --prompt "Scan codebase vs ARCHITECTURE_V2.md. Nếu có gap mới → thêm vào pending.md"

# Worker — implement feature từ pipeline
hermes cron create "every 30m" \
  --name dev-autopilot-worker \
  --skills dev-autopilot,trading-rules \
  --workdir /c/Users/minhl/Desktop/STARUP/Trade_V1 \
  --prompt "Check in_progress.md → advance feature 1 step (design→implement→test→done)"
```

---

## 🚦 Safety Rules

1. **1 feature at a time** — ko overlap
2. **Max 3 retry** — nếu test fail 3 lần → blocked
3. **Git branch riêng** — ko ảnh hưởng main
4. **Approve gate** — design xong phải có APPROVED flag
5. **Backward compatible** — ko xóa field cũ trong JSON

---

## 📊 Trạng thái hiện tại

Xem nhanh:
```bash
echo "=== PENDING ===" && cat .hermes/features/pending.md
echo "=== IN PROGRESS ===" && cat .hermes/features/in_progress.md
echo "=== DONE ===" && cat .hermes/features/done.md
```
