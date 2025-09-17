# ui/widgets.py
from PySide6.QtWidgets import QWidget, QFrame, QLabel, QGridLayout
from PySide6.QtGui import QPainter, QPen, QColor, QGuiApplication
from PySide6.QtCore import Qt, QRect, Signal

from core.models import (
    AnalysisResult, SidePlan,
)

# ----------- 擷取工具 -----------

class SnippingTool(QWidget):
    snipping_finished = Signal(dict)

    def __init__(self):
        super().__init__()
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
        )
        self.setWindowState(Qt.WindowState.WindowFullScreen)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.begin = None
        self.end = None
        self.is_snipping = False

    def paintEvent(self, event):
        if not self.isVisible():
            return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = QRect(self.begin or self.rect().center(), self.end or self.rect().center()).normalized()
        painter.fillRect(self.rect(), QColor(0, 0, 0, 80))
        if rect.width() > 0 and rect.height() > 0:
            painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_Clear)
            painter.fillRect(rect, Qt.GlobalColor.transparent)
            painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceOver)
            painter.setPen(QPen(QColor(0, 120, 215), 2))
            painter.drawRect(rect)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.begin = event.pos()
            self.end = self.begin
            self.is_snipping = True
            self.update()
        elif event.button() == Qt.MouseButton.RightButton:
            self.close()

    def mouseMoveEvent(self, event):
        if self.is_snipping:
            self.end = event.pos()
            self.update()

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton and self.is_snipping:
            self.is_snipping = False
            rect = QRect(self.begin, self.end).normalized()
            if rect.width() > 10 and rect.height() > 10:
                virtual_origin = QGuiApplication.primaryScreen().virtualGeometry().topLeft()
                monitor_dict = {
                    'left': virtual_origin.x() + rect.left(),
                    'top': virtual_origin.y() + rect.top(),
                    'width': rect.width(),
                    'height': rect.height()
                }
                self.hide()
                self.snipping_finished.emit(monitor_dict)
            self.close()

    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_Escape:
            self.close()

# ----------- 結果卡片 -----------

class AnalysisCard(QFrame):
    def __init__(self, result: AnalysisResult, parent=None):
        super().__init__(parent)
        self.setObjectName("ResultCard")
        self.setFrameShape(QFrame.Shape.StyledPanel)
        self.setup_ui(result)

    def setup_ui(self, result: AnalysisResult):
        layout = QGridLayout(self)

        # --- 小工具 ---
        def fmt_num(x):
            try:
                return f"{float(x):.2f}"
            except Exception:
                return "N/A"

        def fmt_pct(x):
            try:
                return f"{float(x)*100:.1f}%"
            except Exception:
                return "—"

        def get(obj, key, default=None):
            if isinstance(obj, dict):
                return obj.get(key, default)
            return getattr(obj, key, default)

        conf_pct = int(round(((result.confidence or 0.0) * 100)))
        risk_txt = f"{getattr(result, 'risk_score', 0)}/5"

        # 標的（代號 / 名稱） + 標題
        subject = ""
        if getattr(result, "symbol", None) or getattr(result, "name", None):
            subject = f"標的：{result.symbol or '-'} / {result.name or '-'}  |  "
        title = QLabel(f"{subject}交易建議 (信心: {conf_pct}%, 風險: {risk_txt})")
        title.setObjectName("CardTitle")
        layout.addWidget(title, 0, 0, 1, 4)

        # 方向 / 入場 / 停損 / 留倉
        bias_label = QLabel("建議方向:")
        bias_value = QLabel(result.bias)
        bias_value.setObjectName("CardBias")
        layout.addWidget(bias_label, 1, 0)
        layout.addWidget(bias_value, 1, 1)

        entry_label = QLabel("建議入場:")
        entry_value = QLabel(fmt_num(result.entry_price) if result.entry_price is not None else "N/A")
        layout.addWidget(entry_label, 2, 0)
        layout.addWidget(entry_value, 2, 1)

        sl_label = QLabel("建議停損:")
        sl_value = QLabel(fmt_num(result.stop_loss) if result.stop_loss is not None else "N/A")
        layout.addWidget(sl_label, 3, 0)
        layout.addWidget(sl_value, 3, 1)

        hold_label = QLabel("留倉短波:")
        hold_text = "是" if result.hold_overnight else ("否" if result.hold_overnight is False else "依條件")
        hold_value = QLabel(hold_text)
        layout.addWidget(hold_label, 1, 2)
        layout.addWidget(hold_value, 1, 3)

        row = 4

        def add_block(title_text: str, value_text: str):
            nonlocal row
            lbl = QLabel(title_text)
            val = QLabel(value_text or "—")
            val.setWordWrap(True)
            layout.addWidget(lbl, row, 0)
            layout.addWidget(val, row, 1, 1, 3)
            row += 1

        add_block("結構：", result.structure)
        add_block("動能：", result.momentum)
        add_block("關鍵價位：", result.key_levels)

        # --- BBand 專區 ---
        bb = getattr(result, "bband", None)
        if bb:
            lbl = QLabel("BBand（布林）：")
            layout.addWidget(lbl, row, 0)
            lines = []
            if get(bb, "period", None) or get(bb, "dev", None):
                lines.append(f"參數：{get(bb,'period','?')}/{get(bb,'dev','?')}")
            ma = get(bb, "ma", None)
            up = get(bb, "upper", None)
            lo = get(bb, "lower", None)
            if ma or up or lo:
                parts = []
                if ma is not None: parts.append(f"中軌≈{fmt_num(ma)}")
                if up is not None: parts.append(f"上軌≈{fmt_num(up)}")
                if lo is not None: parts.append(f"下軌≈{fmt_num(lo)}")
                if parts: lines.append("、".join(parts))
            width = get(bb, "width", None)
            if width is not None:
                lines.append(f"帶寬：{fmt_pct(width)}")
            pb = get(bb, "percent_b", None) or get(bb, "%b", None)
            if pb is not None:
                try:
                    pbv = float(pb)
                    lines.append(f"%B：{pbv:.2f}（0=下軌, 0.5=中軌, 1=上軌）")
                except Exception:
                    pass
            sq = get(bb, "squeeze", None)
            if sq is not None:
                sqtxt = "狹縮" if sq else "非狹縮"
                r = get(bb, "squeeze_rank_1y", None)
                if r is not None:
                    sqtxt += f"（近1年分位≈{fmt_pct(r)}）"
                lines.append(sqtxt)
            note = (get(bb, "note", "") or "").strip()
            if note:
                lines.append(note)
            val = QLabel("；".join(lines) if lines else "—")
            val.setWordWrap(True)
            layout.addWidget(val, row, 1, 1, 3); row += 1

        add_block("交易計畫（總結）：", result.trade_plan)
        add_block("加分訊號：", result.bonus_signals)
        
        # --- 籌碼分析 ---
        chips = getattr(result, "chips", [])
        if chips:
            score_txt = f" (綜合評分: {result.chip_score}/5)" if getattr(result, 'chip_score', None) is not None else ""
            lbl = QLabel(f"籌碼分析：{score_txt}")
            
            lines = []
            for chip in chips:
                line = (f"<b>{getattr(chip, 'period', '?')}</b>: "
                        f"{getattr(chip, 'pattern', 'N/A')} "
                        f"(評分: {getattr(chip, 'score', '?')}/5). "
                        f"<i>{getattr(chip, 'comment', '')}</i>")
                lines.append(line)
            
            val = QLabel("<br>".join(lines))
            val.setWordWrap(True)
            
            layout.addWidget(lbl, row, 0)
            layout.addWidget(val, row, 1, 1, 3)
            row += 1

        # 交易計畫（條列）
        if result.plan_breakdown:
            lbl = QLabel("交易計畫（條列）：")
            layout.addWidget(lbl, row, 0)
            pb = result.plan_breakdown
            lines = []
            if pb.entry: lines.append(f"1) 進場：{pb.entry}")
            if pb.stop: lines.append(f"2) 停損：{pb.stop}")
            if pb.take_profit: lines.append(f"3) 停利：{pb.take_profit}")
            val = QLabel("\n".join(lines) if lines else "—"); val.setWordWrap(True)
            layout.addWidget(val, row, 1, 1, 3); row += 1

        # 位階判斷 / 操作週期
        pos = getattr(result, "position", None)
        if pos:
            lbl = QLabel("位階判斷：")
            layout.addWidget(lbl, row, 0)
            parts = [f"{getattr(pos, 'level', '—')}"]
            try:
                parts.append(f"距52W高 {fmt_pct(getattr(pos, 'pct_from_52w_high', None))}")
                parts.append(f"距52W低 {fmt_pct(getattr(pos, 'pct_from_52w_low', None))}")
                parts.append(f"距MA200 {fmt_pct(getattr(pos, 'pct_from_ma200', None))}")
                parts.append(f"距MA60 {fmt_pct(getattr(pos, 'pct_from_ma60', None))}")
                parts.append(f"AVWAP距離 {fmt_pct(getattr(pos, 'avwap_from_pivot', None))}")
            except Exception:
                pass
            val = QLabel("；".join(parts))
            val.setWordWrap(True)
            layout.addWidget(val, row, 1, 1, 3); row += 1

        if result.operation_cycle:
            oc = result.operation_cycle
            lbl = QLabel("操作週期：")
            layout.addWidget(lbl, row, 0)
            lines = []
            if oc.momentum: lines.append(f"1) 動能：{oc.momentum}")
            if oc.volume: lines.append(f"2) 成交量：{oc.volume}")
            if oc.institutions: lines.append(f"3) 法人籌碼：{oc.institutions}")
            if oc.concentration: lines.append(f"4) 籌碼集中度：{oc.concentration}")
            val = QLabel("\n".join(lines) if lines else "—"); val.setWordWrap(True)
            layout.addWidget(val, row, 1, 1, 3); row += 1

        # 多／空方案
        def add_side_block(side_name: str, plan: SidePlan | None):
            nonlocal row
            if not plan:
                return
            lbl = QLabel(f"{side_name}方案："); layout.addWidget(lbl, row, 0)
            v = []
            v.append(f"入場：{fmt_num(plan.entry_price)}" if plan.entry_price is not None else "入場：N/A")
            v.append(f"停損：{fmt_num(plan.stop_loss)}" if plan.stop_loss is not None else "停損：N/A")
            if plan.targets:
                try:
                    tg = ", ".join([fmt_num(t) for t in plan.targets])
                except Exception:
                    tg = ""
                if tg:
                    v.append(f"停利目標：{tg}")
            detail = "；".join(v)
            detail = detail + (f"\n{plan.plan}" if getattr(plan, "plan", "") else "")
            val = QLabel(detail); val.setWordWrap(True)
            layout.addWidget(val, row, 1, 1, 3); row += 1

        add_side_block("多方", result.long)
        add_side_block("空方", result.short)

        lbl_r = QLabel("分析理由："); layout.addWidget(lbl_r, row, 0, 1, 4); row += 1
        txt_r = QLabel(result.rationale); txt_r.setWordWrap(True)
        layout.addWidget(txt_r, row, 0, 1, 4); row += 1

        if result.notes:
            lbl_n = QLabel("備註："); layout.addWidget(lbl_n, row, 0, 1, 4); row += 1
            txt_n = QLabel(result.notes); txt_n.setWordWrap(True); txt_n.setObjectName("CardNotes")
            layout.addWidget(txt_n, row, 0, 1, 4); row += 1

        if result.model_used and result.response_time is not None:
            meta = QLabel(f"Model: {result.model_used} | Time: {result.response_time:.2f}s")
            meta.setObjectName("CardMeta")
            layout.addWidget(meta, row, 0, 1, 4, Qt.AlignmentFlag.AlignRight)