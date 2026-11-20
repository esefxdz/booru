from PyQt6.QtCore import QPropertyAnimation
from PyQt6.QtWidgets import QGraphicsOpacityEffect, QWidget
from core import settings

def animate_button_press(widget: QWidget):
    if settings.manager.reduced_motion:
        return
    
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
