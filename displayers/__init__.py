"""
displayers/ — Media overlay system for viewing posts full-screen.

Architecture:
  MediaOverlay (overlay.py)
    ├── MediaViewer (media_viewer.py)  — images, GIFs, and video playback
    │   └── VideoPlayerWidget (video_player.py)  — multi-engine video (Qt/VLC/MPV)
    └── OverlaySidebar (sidebar.py)
        ├── FileDetails (details.py)   — collapsible post metadata
        ├── ActionButtons (actions.py)  — bookmark, download, share, view-original
        └── TagsDropdown (tags.py)      — categorized tag display
"""
from displayers.overlay import MediaOverlay

__all__ = ["MediaOverlay"]
