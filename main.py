import asyncio
import httpx
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

    # Start Download Engine
    semaphore = asyncio.Semaphore(config.MAX_CONNECTIONS)
    
    async def limited_task(client, post):
        async with semaphore:
            await bot.download_task(client, post, final_folder)

    async with httpx.AsyncClient(headers=bot.headers, timeout=config.TIMEOUT) as client:
        tasks = [limited_task(client, post) for post in posts]
        await asyncio.gather(*tasks)
    
    print("\n--- Download Task Complete ---")

if __name__ == "__main__":
    asyncio.run(run_workflow())