from PyQt6.QtCore import QPropertyAnimation
from PyQt6.QtWidgets import QGraphicsOpacityEffect, QWidget
from ui import settings_view as settings

# ╔══════════════════════════════════════════════════════════════════════╗
# ║                      ANIMATE_BUTTON_PRESS                           ║
# ╚══════════════════════════════════════════════════════════════════════╝
def animate_button_press(widget: QWidget):
    """Quick pop animation when a button is clicked."""
    if settings.manager.reduced_motion:
        return
    
    # Animate opacity quickly down and up to simulate a click flash
    effect = QGraphicsOpacityEffect(widget)
    widget.setGraphicsEffect(effect)
    
    anim = QPropertyAnimation(effect, b"opacity")
    anim.setStartValue(1.0)
    anim.setKeyValueAt(0.5, 0.5)
    anim.setEndValue(1.0)
    anim.setDuration(150)
    anim.start(QPropertyAnimation.DeletionPolicy.DeleteWhenStopped)
    
    widget._click_anim = anim
    widget._click_effect = effect
