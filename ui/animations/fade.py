from PyQt6.QtCore import QPropertyAnimation, QEasingCurve
from PyQt6.QtWidgets import QGraphicsOpacityEffect, QWidget
from ui import settings_view as settings

# ╔══════════════════════════════════════════════════════════════════════╗
# ║                        ANIMATE_FADE_IN                              ║
# ╚══════════════════════════════════════════════════════════════════════╝
def animate_fade_in(widget: QWidget, duration: int = 300):
    """Smoothly fades a widget in from 0 to 1 opacity."""
    if settings.manager.reduced_motion:
        return

    effect = QGraphicsOpacityEffect(widget)
    widget.setGraphicsEffect(effect)
    
    anim = QPropertyAnimation(effect, b"opacity")
    anim.setStartValue(0.0)
    anim.setEndValue(1.0)
    anim.setDuration(duration)
    anim.setEasingCurve(QEasingCurve.Type.InOutSine)

    def on_finished():
        widget.setGraphicsEffect(None)
        if hasattr(widget, '_fade_anim'):
            del widget._fade_anim
        if hasattr(widget, '_fade_effect'):
            del widget._fade_effect

    anim.finished.connect(on_finished)
    anim.start(QPropertyAnimation.DeletionPolicy.DeleteWhenStopped)
    
    # Store reference so the garbage collector doesn't destroy the animation
    widget._fade_anim = anim
    widget._fade_effect = effect
