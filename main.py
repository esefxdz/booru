import asyncio
import config
from downloader import BooruDownloader

def get_valid_folder_name(tags):
    folder_name = tags.replace(" ", "_")
    illegal_chars = r'<>:"/\|?*'
    for char in illegal_chars:
        folder_name = folder_name.replace(char, "")
    return folder_name[:150]

async def run_workflow():
    bot = BooruDownloader()
    
    posts = await bot.get_image_urls(config.SEARCH_TAGS, config.SEARCH_LIMIT)
    
    if not posts:
        print(f"No results found for '{config.SEARCH_TAGS}'")
        return

    # Prepare the folder using our cleaning function
    clean_tag_dir = get_valid_folder_name(config.SEARCH_TAGS)
    final_folder = config.DOWNLOAD_DIR / config.ACTIVE_BOORU / clean_tag_dir
    
    final_folder.mkdir(parents=True, exist_ok=True)
    print(f"Downloading to: {final_folder}")

    # Start Download Engine using built-in httpx connection pooling
    tasks = [bot.download_task(None, post, final_folder) for post in posts]
    await asyncio.gather(*tasks)
    
    print("\n--- Download Task Complete ---")

if __name__ == "__main__":
    asyncio.run(run_workflow())