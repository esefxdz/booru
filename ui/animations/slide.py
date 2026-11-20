from PyQt6.QtCore import QPropertyAnimation, QEasingCurve, QParallelAnimationGroup, QRect
from PyQt6.QtWidgets import QGraphicsOpacityEffect, QWidget
from core import settings

def animate_slide_up_fade(widget: QWidget, duration: int = 300, offset: int = 20):
    if settings.manager.reduced_motion:
        return

    effect = QGraphicsOpacityEffect(widget)
    widget.setGraphicsEffect(effect)
    
    fade_anim = QPropertyAnimation(effect, b"opacity")
    fade_anim.setStartValue(0.0)
    fade_anim.setEndValue(1.0)
    fade_anim.setDuration(duration)
    fade_anim.setEasingCurve(QEasingCurve.Type.OutCubic)

    geom = widget.geometry()
    slide_anim = QPropertyAnimation(widget, b"geometry")
    slide_anim.setStartValue(QRect(geom.x(), geom.y() + offset, geom.width(), geom.height()))
    slide_anim.setEndValue(geom)
    slide_anim.setDuration(duration)
    slide_anim.setEasingCurve(QEasingCurve.Type.OutBack)

    group = QParallelAnimationGroup(widget)
    group.addAnimation(fade_anim)
    group.addAnimation(slide_anim)
    group.start(QPropertyAnimation.DeletionPolicy.DeleteWhenStopped)
    
    widget._slide_fade_group = group
    widget._slide_fade_effect = effect
