"""
ui/animations/__init__.py

Re-exports all animation functions so existing code using:
    import ui.animations as anims
    anims.animate_fade_in(...)
continues to work without any changes.
"""
from ui.animations.fade import animate_fade_in
from ui.animations.slide import animate_slide_up_fade
from ui.animations.button import animate_button_press

__all__ = ["animate_fade_in", "animate_slide_up_fade", "animate_button_press"]
