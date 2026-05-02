import settings
import boorus
from gui import BooruGui

def main():
    # Load user settings from JSON
    settings.load()
    settings.load_bookmarks()
    
    # Booros are auto-discovered from booros/ folder
    # (both preset and user-added .py files)
    
    # Launch GUI
    app = BooruGui()
    app.mainloop()

if __name__ == "__main__":
    main()