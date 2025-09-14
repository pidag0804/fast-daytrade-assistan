# 股票當沖詢問工具 (Fast Daytrade Assistant)

這是一個使用 PySide6、asyncio (qasync)、mss 和 OpenAI API 構建的高效能桌面應用程式，旨在以最短延遲完成「截圖 →（可選編輯）→ 上傳至 GPT 模型 → 產出交易建議」的流程。

## 主要功能

- **非同步架構**：使用 `asyncio` 和 `qasync` 處理網路請求，確保 GUI 流暢不阻塞。
- **多執行緒影像處理**：使用 `QThreadPool` 進行影像壓縮 (WebP) 和儲存，效能最佳化。
- **高效截圖**：F2 (當前視窗)、F3 (截取並編輯)、F4 (框選範圍)。Windows 平台使用 DWM API 精確捕捉視窗。
- **全功能影像編輯器 (F3)**：基於 QGraphicsScene，支援文字、矩形、圓形、直線/箭頭，並具備完整的 Undo/Redo 功能。
- **智慧 GPT 整合**：自動選擇回答速度策略（快速/深度），具備逾時降級重試機制，嚴格 JSON 輸出。
- **使用者體驗**：待上傳區支援拖拉排序、多選、縮圖預覽；結果以清晰的卡片呈現。
- **安全設定**：API Key 使用系統 Keyring 安全儲存。

## 安裝與執行

### 環境需求

- Python 3.10+

### 安裝步驟

1. **複製專案**：
   確保所有提供的程式碼檔案都已儲存到對應的資料夾結構中。

2. **建立並啟動虛擬環境** (建議)：

   ```bash
   cd fast-daytrade-assistant
   python -m venv venv
   # Windows
   .\venv\Scripts\activate
   # macOS/Linux
   source venv/bin/activate