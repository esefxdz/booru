import sys, traceback
from PyQt6.QtWidgets import QApplication
try:
    from ui.browser_dialog.cloudflare_browser_dialog import CloudflareBrowserDialog
    app = QApplication(sys.argv)
    dlg = CloudflareBrowserDialog('https://google.com', 'Test')
    dlg.exec()
except Exception as e:
    traceback.print_exc(file=sys.stdout)
