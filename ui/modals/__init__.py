"""
ui/modals/__init__.py

Re-exports every dialog class so that existing code using:
    from ui.modals import APISettingsDialog
continues to work without any changes after the split into separate files.
"""
from ui.modals.api_settings_dialog import APISettingsDialog
from ui.modals.bulk_download_dialog import BulkDownloadDialog
from ui.modals.add_booru_dialog import AddBooruDialog, AutoDetectThread

__all__ = [
    "APISettingsDialog",
    "BulkDownloadDialog",
    "AddBooruDialog",
    "AutoDetectThread",
]
