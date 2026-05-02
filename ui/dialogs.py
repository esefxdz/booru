import os
import threading
import json
import customtkinter as ctk

import settings
import boorus

class APISettingsDialog:
    @staticmethod
    def show(parent_gui, name):
        pop = ctk.CTkToplevel(parent_gui)
        pop.title(f"{name} Auth")
        pop.geometry("300x320")
        pop.attributes("-topmost", True) # Keep on top
        
        creds = settings.CREDENTIALS.get(name, {"user_id": "", "api_key": ""})
        u_ent = ctk.CTkEntry(pop, placeholder_text="User ID")
        u_ent.pack(pady=10)
        u_ent.insert(0, creds['user_id'])
        
        a_ent = ctk.CTkEntry(pop, placeholder_text="API Key", show="*")
        a_ent.pack(pady=10)
        a_ent.insert(0, creds['api_key'])

        def save():
            settings.CREDENTIALS[name] = {"api_key": a_ent.get(), "user_id": u_ent.get()}
            parent_gui.downloader.save_credentials(name, u_ent.get(), a_ent.get())
            pop.destroy()
            
        ctk.CTkButton(pop, text="SAVE", command=save).pack(pady=10)

        # Cloudflare Bypass Hook
        def run_cf_bypass():
            url = boorus.REGISTRY[name]["url"]
            parent_gui.status_lbl.configure(text=f"Waiting for {name} bypass...", text_color="yellow")
            pop.destroy()

            def worker():
                import subprocess
                res = subprocess.run(["python", "cf_bypass.py", url], capture_output=True, text=True)
                if res.returncode == 0:
                    try:
                        data = json.loads(res.stdout)
                        settings.save_bypass(name, data['cf_clearance'], data['user_agent'])
                        parent_gui.after(0, lambda: parent_gui.status_lbl.configure(text=f"Bypassed {name}!", text_color="green"))
                        parent_gui.after(500, lambda: parent_gui.trigger_fetch(new=True))
                    except Exception as e:
                        parent_gui.after(0, lambda: parent_gui.status_lbl.configure(text=f"Bypass error: {e}", text_color="red"))
                else:
                    parent_gui.after(0, lambda: parent_gui.status_lbl.configure(text="Bypass cancelled or failed.", text_color="red"))

            threading.Thread(target=worker, daemon=True).start()

        ctk.CTkButton(pop, text="Bypass Cloudflare", fg_color="#8b0000", hover_color="#5a0000", command=run_cf_bypass).pack(pady=(20,0))

        # Delete Custom Booru button (if file exists in boorus/ folder)
        booru_file = os.path.join(os.path.dirname(os.path.dirname(__file__)), "boorus", f"{name}.py")
        if os.path.exists(booru_file):
            def delete_booru():
                pop.destroy()
                parent_gui.remove_booru(name)
            ctk.CTkButton(pop, text="Delete Booru", fg_color="#5a2020", hover_color="#3a1010", command=delete_booru).pack(pady=(20,0))


class BulkDownloadDialog:
    @staticmethod
    def show(parent_gui, current_tags):
        pop = ctk.CTkToplevel(parent_gui)
        pop.geometry("300x200")
        pop.attributes("-topmost", True)
        
        ctk.CTkLabel(pop, text="Download limit:").pack(pady=10)
        e = ctk.CTkEntry(pop)
        e.pack()
        e.insert(0, "20")
        
        def run():
            limit = int(e.get())
            pop.destroy()
            threading.Thread(target=parent_gui._bulk_proc, args=(current_tags, limit), daemon=True).start()
            
        ctk.CTkButton(pop, text="START", command=run).pack(pady=20)


class GlobalSettingsDialog:
    @staticmethod
    def show(parent_gui):
        win = ctk.CTkToplevel(parent_gui)
        win.title("Global Settings")
        win.geometry("400x380")
        win.attributes("-topmost", True)
        
        ctk.CTkLabel(win, text="Blacklist Tags:").pack(pady=10)
        bl_entry = ctk.CTkEntry(win, width=300)
        bl_entry.pack()
        bl_entry.insert(0, settings.BLACKLIST)

        ctk.CTkLabel(win, text="Thumbnail Size:").pack(pady=10)
        sz_entry = ctk.CTkEntry(win, width=300)
        sz_entry.pack()
        sz_entry.insert(0, str(settings.THUMBNAIL_SIZE))

        arrow_var = ctk.BooleanVar(value=settings.USE_ARROWS_FOR_SORTING)
        ctk.CTkCheckBox(win, text="Use Arrow Buttons for Source Sorting (Fallback)", variable=arrow_var).pack(pady=20)

        def save():
            settings.BLACKLIST = bl_entry.get()
            settings.THUMBNAIL_SIZE = int(sz_entry.get())
            settings.USE_ARROWS_FOR_SORTING = arrow_var.get()
            settings.save()
            parent_gui.rebuild_source_list()
            win.destroy()
            
        ctk.CTkButton(win, text="SAVE ALL", command=save).pack(pady=10)


class AddBooruDialog:
    @staticmethod
    def show(parent_gui):
        from adapters import adapter_choices
        choices = adapter_choices()          # [(api_type, label), ...]
        labels   = [lbl for _, lbl in choices]
        api_types = [at  for at,  _  in choices]

        win = ctk.CTkToplevel(parent_gui)
        win.title("Add Custom Booru")
        win.geometry("420x360")
        win.attributes("-topmost", True)

        ctk.CTkLabel(win, text="Name:").pack(pady=(15, 2))
        name_ent = ctk.CTkEntry(win, width=340, placeholder_text="my_booru")
        name_ent.pack()

        ctk.CTkLabel(win, text="URL (no trailing slash):").pack(pady=(10, 2))
        url_ent = ctk.CTkEntry(win, width=340, placeholder_text="https://example.com")
        url_ent.pack()

        ctk.CTkLabel(win, text="API Type:").pack(pady=(10, 2))
        menu = ctk.CTkOptionMenu(win, values=labels, width=340)
        menu.pack()

        status_lbl = ctk.CTkLabel(win, text="", text_color="gray")
        status_lbl.pack(pady=8)

        def add_booru():
            name     = name_ent.get().strip().lower().replace(" ", "_")
            url      = url_ent.get().strip().rstrip("/")
            api_type = api_types[labels.index(menu.get())]

            if not name or not url:
                status_lbl.configure(text="Name and URL are required.", text_color="red")
                return
            if name in boorus.REGISTRY:
                status_lbl.configure(text="A booru with that name already exists.", text_color="red")
                return

            # Write booru config as .py file in boorus/ folder
            booru_file = os.path.join(os.path.dirname(os.path.dirname(__file__)), "boorus", f"{name}.py")
            try:
                with open(booru_file, "w", encoding="utf-8") as f:
                    f.write(f'NAME     = "{name}"\n')
                    f.write(f'URL      = "{url}"\n')
                    f.write(f'API_PATH = "/index.php"\n')
                    f.write(f'POST_KEY = None\n')
                    f.write(f'API_TYPE = "{api_type}"\n')

                # Add to live registry
                boorus.REGISTRY[name] = {
                    "url": url,
                    "api_path": "/index.php",
                    "post_key": None,
                    "api_type": api_type,
                }

                parent_gui.rebuild_source_list()
                win.destroy()
            except Exception as e:
                status_lbl.configure(text=f"Error creating file: {e}", text_color="red")
                print(f"[gui] Error writing booru file: {e}")

        ctk.CTkButton(win, text="ADD", command=add_booru).pack(pady=(15, 0))
