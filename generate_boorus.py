import os

boorus_data = {
    # Gelbooru Engine
    'gelbooru': ('https://gelbooru.com', 'gelbooru', '/index.php'),
    'safebooru': ('https://safebooru.org', 'gelbooru', '/index.php'),
    'xbooru': ('https://xbooru.com', 'gelbooru', '/index.php'),
    'tbib': ('https://tbib.org', 'gelbooru', '/index.php'),
    'hypnohub': ('https://hypnohub.net', 'gelbooru', '/index.php'),

    # Danbooru Engine
    'danbooru': ('https://danbooru.donmai.us', 'danbooru', ''),
    'safebooru_donmai': ('https://safebooru.donmai.us', 'danbooru', ''),
    'atfbooru': ('https://booru.allthefallen.moe', 'danbooru', ''),
    'behoimi': ('http://behoimi.org', 'danbooru', ''),

    # Moebooru Engine
    'yandere': ('https://yande.re', 'moebooru', ''),
    'konachan': ('https://konachan.com', 'moebooru', ''),
    'konachan_safe': ('https://konachan.net', 'moebooru', ''),
    'lolibooru': ('https://lolibooru.moe', 'moebooru', ''),
    'sakugabooru': ('https://www.sakugabooru.com', 'moebooru', ''),

    # e621 Engine
    'e621': ('https://e621.net', 'e621', ''),
    'e926': ('https://e926.net', 'e621', '')
}

os.makedirs('boorus', exist_ok=True)
for name, (url, api_type, api_path) in boorus_data.items():
    path = f'boorus/{name}.py'
    if not os.path.exists(path):
        with open(path, 'w') as f:
            f.write(f'NAME     = "{name}"\n')
            f.write(f'URL      = "{url}"\n')
            f.write(f'API_PATH = "{api_path}"\n')
            f.write(f'POST_KEY = None\n')
            f.write(f'API_TYPE = "{api_type}"\n')
        print(f'Created {name}.py')
